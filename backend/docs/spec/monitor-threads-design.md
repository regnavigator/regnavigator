# 규제 모니터링 — 스레드 재구성 설계

작성 2026-10-02 · 상태: **설계(미구현)**

## 왜 바꾸나

지금 모니터링은 **북마크 폴더**가 관찰 단위다. 답변을 읽다가 조문을 북마크하고
폴더를 지정해야 관찰이 시작된다. 두 가지가 안 된다.

1. **대화로 대상을 정의할 수 없다.** "아크로제약의 의료기기 수입 규제를 보고
   싶다"에서 출발해 관련 규제를 찾아 묶는 흐름이 없다. 조문을 이미 알고 있어야
   한다 — 그걸 찾는 게 이 도구의 본업인데.
2. **자료를 넣을 수 없다.** 내부 규정·계약서·인허가 서류를 올려 "여기 걸리는
   규제를 뽑아 줘"가 안 된다.

그리고 관찰 목록이 폴더 문자열이라 **대상 자체에 맥락이 없다**. 왜 이 조문을
보고 있는지, 무엇을 논의했는지가 남지 않는다.

→ 관찰 단위를 **스레드**로 바꾼다. 대상 하나 = 스레드 하나. 그 안에서 대화하고,
자료를 올리고, 관찰 목록을 고치고, 알람을 받고, 보고서를 뽑는다.

## 핵심 결정 — 채팅 스레드를 그대로 쓴다

모니터링 스레드를 **별도 테이블로 만들지 않는다.** `chat_threads` 에 종류를
더하고, 관찰 목록만 옆에 붙인다.

```
모니터링 스레드 = chat_thread(kind='monitor') + monitor_watch[]
```

별도 테이블로 가면 대화·첨부·검색·인용·기밀 모드를 **전부 다시 배선**해야 한다.
그런데 "대화로 규제를 추출한다"는 요구 자체가 채팅 엔진을 그대로 요구한다 —
복제할 이유가 없다. 사이드바도 이미 `chat_threads` 를 나열하므로 섹션만 가른다.

## 데이터 모델

### 기존 변경

```sql
ALTER TABLE chat_threads ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat';
-- 'chat' | 'monitor'
```

`monitor_targets` 는 **배송 설정 전용**으로 좁힌다. 관찰 대상은 더 이상 폴더가
아니다.

```sql
ALTER TABLE monitor_targets ADD COLUMN thread_id TEXT;
-- folder 는 당분간 남긴다(구 데이터 호환). 신규는 thread_id 만 채운다.
```

### 신규 — `monitor_watch` (관찰 조문)

```sql
CREATE TABLE monitor_watch (
  id            TEXT PRIMARY KEY,
  thread_id     TEXT NOT NULL,
  article_key   TEXT NOT NULL,
  citation_json TEXT NOT NULL,   -- 제목·법령명·URL. amendments.detect 가 그대로 먹는다
  added_by      TEXT NOT NULL,   -- 'ai'(대화에서 제안) | 'user'(직접 추가) | 'file'(자료에서)
  reason        TEXT,            -- 왜 넣었나 (제안 근거 한 줄)
  added_at      TEXT NOT NULL,
  removed_at    TEXT,            -- soft delete — 뺀 이유도 기록으로 남는다
  UNIQUE(thread_id, article_key)
);
```

`citation_json` 을 통째로 들고 있는 이유: `amendments.detect_with_status()` 가
북마크 객체를 받는데, 그 인터페이스를 그대로 재사용하려면 같은 모양이어야 한다.
조문 메타를 다시 조회하지 않아도 된다.

### 신규 — `monitor_alert` (감지된 변경)

```sql
CREATE TABLE monitor_alert (
  id           TEXT PRIMARY KEY,
  thread_id    TEXT NOT NULL,
  article_key  TEXT NOT NULL,
  kind         TEXT NOT NULL,   -- 'repealed' | 'pending' | 'amended' | 'effective_date'
  summary      TEXT NOT NULL,   -- 한 줄 ("2026-11-01 시행 예정으로 변경")
  payload_json TEXT NOT NULL,   -- before/after
  detected_at  TEXT NOT NULL,
  read_at      TEXT,
  dismissed_at TEXT,
  UNIQUE(thread_id, article_key, kind, detected_at)
);
```

지금 개정 감지는 **조회형**이라 화면을 떠나면 사라진다. 적재해야 "알람만 모아
보기"가 가능하고, 같은 변경을 두 번 알리지 않을 수 있다.

### 신규 — `contacts` (수신자 주소록)

```sql
CREATE TABLE contacts (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL,
  email        TEXT NOT NULL,
  name         TEXT,
  org          TEXT,
  last_used_at TEXT,
  created_at   TEXT NOT NULL,
  UNIQUE(user_id, email)
);
```

지금 수신자는 쉼표 문자열이다. 발송할 때마다 주소를 다시 타이핑하면 오타가
그대로 외부로 나간다.

## 흐름

### ① 대상 정의 — 대화

```
[+ 모니터링 대상] → chat_thread(kind='monitor') 생성
  → "아크로제약의 의료기기 수입 규제를 모니터링하고 싶습니다"
  → 평소대로 검색·답변 (엔진 그대로)
  → 답변 아래 [관찰 목록에 추가] 카드
       이번 턴 인용 중 법령·행정규칙·자치법규만, 체크박스
       이미 관찰 중인 것은 ✓ 표시
```

**자동 추가하지 않는다.** 검색 인용은 노이즈를 포함한다(출처 적합성 필터를
거쳐도 남는다). 관찰 목록이 오염되면 알람이 쓰레기가 되고, 그러면 알람을 안
보게 된다. 제안까지만 하고 **승인은 사람이** 한다.

### ② 자료로 추출

첨부 문서 → 기존 `file_extract` 로 텍스트화 → 본문에서 법령명·조문 참조를 뽑아
(`/article/lookup` 의 Tier-0 파서 재사용) `article_key` 로 해소 → 같은 제안 카드.

해소 안 되는 참조는 버리지 않고 "확인 필요"로 보여 준다 — 조용히 빠뜨리면
사용자는 그 규제가 검토된 줄 안다.

### ③ 목록 수정 — 추가 논의

관찰 목록은 우측 패널에 상주한다. 행마다 [빼기], 하단에 [조문 직접 추가].
대화로도 된다 — "제조업 허가는 빼고 수입업만 보자" → 모델이 해당 조문을
제안 카드로 다시 올린다(빼기 제안도 같은 카드).

### ④ 알람

```
_monitor_alert_loop (asyncio, 프로세스 로컬 — 단일 워커 전제)
  → kind='monitor' 스레드의 monitor_watch 를 모아
  → amendments.detect_with_status() 재사용
  → status.complete=False 면 **알람을 만들지 않는다**
       (법령 DB 다운 중에 "변경 없음"이라 단언하지 않는 기존 규율과 같다)
  → 새 변경만 monitor_alert 에 적재
```

주기는 기존 `MONITOR_REPORT_CHECK_INTERVAL_S` 와 별개 노브로 둔다 — 감지는 자주,
발송은 드물게가 맞다.

### ⑤ 알람 모아보기

- 사이드바 모니터링 섹션 헤더에 **미읽음 배지**
- 스레드 행에도 개별 배지
- `/alerts` — 전 스레드 통합, 종별 필터(폐지/개정예정/시행일), 읽음·보관

### ⑥ 짧은 보고서 — 필요할 때

```
POST /monitor/threads/{tid}/report   {since?: "2026-09-01"}
  → 그 기간 알람만 모아 렌더
  → 변경 조문당 2~3줄 + 인용 + 원문 링크
  → 문서로 저장(의견서와 같은 blob 경로) → 패널에서 열람·수정·내보내기
```

정기 발송(`monitor_report.py`)과 **별개 경로**다. 정기는 "일정대로", 이건
"지금 필요해서". 렌더러는 공유한다.

### ⑦ 이메일 발송 — 주소록에서 선택

```
[보고서 보내기] → 수신자 모달
   검색창(이름·이메일·소속 부분일치) + 체크박스 다중 선택
   최근 사용 순 정렬
   새 주소 입력 시 contacts 에 자동 등록
```

## API

| 엔드포인트 | 용도 |
|---|---|
| `POST /monitor/threads` | 모니터링 스레드 생성 |
| `GET /monitor/threads` | 목록 (+ 미읽음 알람 수) |
| `GET/POST/DELETE /monitor/threads/{tid}/watch` | 관찰 목록 조회·추가·제거 |
| `POST /monitor/threads/{tid}/watch/suggest` | 이번 턴 인용 → 제안 목록 |
| `GET /monitor/alerts` | 전 스레드 알람 (`?unread=1&kind=`) |
| `POST /monitor/alerts/{id}/read` · `/dismiss` | 읽음·보관 |
| `POST /monitor/threads/{tid}/report` | 짧은 보고서 생성 |
| `GET /contacts?q=` · `POST /contacts` | 주소록 검색·등록 |
| `POST /monitor/threads/{tid}/send` | 선택 수신자에게 발송 |

라우트는 **async 규약**을 지킨다 — 동기 DB·SMTP 는 `def` 로 선언해 스레드풀에.

## 재사용 — 새로 만드는 게 적다

| 필요한 것 | 이미 있는 것 |
|---|---|
| 대화·검색·인용·첨부 | `chat_loop.py` 전체 |
| 개정 판정 | `amendments.detect_with_status()` |
| 리포트 렌더·발송 | `monitor_report.py` |
| 주기 루프 | `api.py:_monitor_report_loop` 패턴 |
| 문서 저장·패널 | `brief.py` + `BriefPanel.tsx` |
| 사이드바 | `ThreadList.tsx` (섹션만 추가) |
| 조문 참조 파서 | `/article/lookup` Tier-0 |

신규는 **테이블 3개 + 알람 루프 1개 + 제안 카드 UI**가 사실상 전부다.

## 단계

| 단계 | 산출 | 검증 |
|---|---|---|
| 1 | `chat_threads.kind` + `monitor_watch` + 스레드 생성·사이드바 분리 | 모니터링 스레드가 사이드바 별도 섹션에 뜬다 |
| 2 | 인용 → 관찰 목록 제안·추가·제거 | 대화에서 조문을 골라 관찰에 넣는다 |
| 3 | `monitor_alert` + 감지 루프 | 변경을 적재하고 중복 알리지 않는다 |
| 4 | 알람 모아보기 + 배지 | 전 스레드 알람을 한 화면에서 본다 |
| 5 | 짧은 보고서 | 알람을 보고서로 뽑는다 |
| 6 | `contacts` + 선택 발송 | 주소록에서 골라 보낸다 |
| 7 | 구 폴더 기반 정리 | `/monitor` 페이지를 스레드로 흡수 |

1~2 까지 가면 "대화로 대상을 만든다"가 되고, 3~4 에서 비로소 **모니터링**이 된다.
5~6 은 전달 수단이다.

## 자격증명 제약

개정 감지는 openlaw PG (`PG_*`) 가 있어야 **실제로** 동작한다. 없으면 지금처럼
`status.complete=False` 로 "확인 불가"를 표시하고 알람을 만들지 않는다.

즉 1·2·5·6·7 은 지금 자격증명으로 만들고 검증할 수 있고, **3·4 는 구조와 루프를
만들어도 실제 감지 검증은 PG 가 와야 한다.** 그때까지는 알람을 수동 주입해
적재·중복방지·배지·모아보기까지만 검증한다.

## 열어 둔 것

- 한 조문을 여러 스레드가 관찰하면 감지가 중복 실행된다. 스레드 수가 적은 동안은
  그대로 두고, 늘어나면 `article_key` 단위로 모아 한 번만 조회한다.
- 알람 보존 기간. `prune_events` 와 같은 정책이 필요하다(개인정보처리방침 §3).
- 구 `folder` 기반 관찰을 자동 이전할지, 사용자가 다시 묶게 할지.
