# medi-front — 페이지·기능 인벤토리

> 사용자가 말로 수정 요청할 때 영역 식별 빨리 하려고 정리한 문서. 코드 구조와 1:1 매핑 안 함.
>
> ⚠️ **deep(보고서) 관련 옛 표현 주의** — `deep_progress`·`deep_dispatched_at`·
> `DeepProgressPanel`·`agent_deep`/`agent_report`·`deep_stream.jsonl` 은 전부 은퇴한
> 모델이다(assistant 디스패치는 2026-07-14 ADR-0001, 채팅 결합은 2026-07-25 분리).
> **현행**: 보고서는 `POST /reports` + `idempotency_key(^rpt_…)` 로 트리거되고 **채팅과
> 완전히 분리·병렬**로 돌며, 대화록에 아무것도 append 하지 않는다(사이드바·우측 패널·
> 이메일 첨부로만 전달). 구조는 [`ARCHITECTURE.md`](./ARCHITECTURE.md) §7, 계약은
> medi-back `docs/contracts/frontend_chat_v2.md` §4, 최신 변경은 [`PATCHNOTE.md`](./PATCHNOTE.md).

---

## 1. 라우팅

| URL | 화면 | 비고 |
|---|---|---|
| `/` | redirect | middleware가 `?threadId` 없으면 `/new`로 이동 |
| `/new` | 빈 채팅 (EmptyHero) | thread 생성 X — 첫 메시지 송신 시 lazy 생성 |
| `/?threadId=xxx` | 활성 thread 채팅 | (chat) layout이 PageShell 유지 |
| `/landing/basic` `/landing/medra` `/landing/regia` | 테마별 랜딩 | URL이 theme 고정 |
| `/login` `/signup` `/auth/verify` `/auth/set-password` `/auth/email-preview` | auth 동선 | NextAuth + EmailProvider + Credentials |
| `/admin/users` `/admin/feedback` | admin 전용 | is_admin 가드 |

**(chat) route group**:
```
app/(chat)/layout.tsx   ← PageShell 호스팅
app/(chat)/page.tsx     ← / 마커
app/(chat)/new/page.tsx ← /new 마커
```
두 라우트 간 전환 시 PageShell 유지 (Suspense 분리로 children suspend가 PageShell unmount 안 시킴).

---

## 2. 좌측 사이드바 (ThreadList)

### 상단
- **로고 (ThemeLogo)** + Beta 라벨 — 클릭 시 `/new`
- **사이드바 접기 토글** (`onCollapse`)
- **+ 새 대화** 버튼 — `router.push('/new')`, thread 생성 X

### 중단 — 심층 보고서 칸 (h-[200px] 고정)
- 보고서 done ≥1건 → 카드 리스트 (final kind만 노출)
- 카드 클릭 → ReportPreviewDialog 모달
- 0건 → "아직 생성된 보고서가 없어요"

### 중단 — 대화 목록
- "대화" 서브타이틀
- 시간별 그룹: 오늘 / 어제 / 지난 7일 / 지난 30일 / 이전
- 활성 thread 좌측 2px primary 보더
- hover 시 inline rename / delete 버튼
- 인터럽트 있으면 우측 빨강 점

### 하단 footer
- 사용자 아바타 + 이메일 + UsageBadge (일/월 사용량)
- admin 전용 — 🛡️ (사용자 관리) / 📋 (피드백 조회) 아이콘
- ⚙️ 설정 버튼 (SettingsDialog)
- 로그아웃 / 로그인

---

## 3. 채팅 영역 (ChatColumn)

### 3.1 ThreadTitleHeader (sticky 상단, turns ≥ 1일 때만)
- 좌: 사이드바 닫혀있으면 ≡ 펼침 토글
- 중: 현재 thread 제목 + ✏️ inline edit (Enter commit / Esc 취소)
- 우: **📋 보고서** 버튼 (보고서 done ≥1건일 때) + 우측 패널 토글 아이콘

### 3.2 EmptyHero (turns === 0일 때)
- 인삿말 (theme-grad-text)
- 4개 sample 카드 — 클릭 시 ChatInput prefill
- 안내문 (의료규제 전문 AI 에이전트)

### 3.3 Turn (한 turn 단위)
1. **UserMessage** — 사용자 입력 말풍선
2. **답변 대기 indicator** — running + 첫 chunk 전: 회전 스피너 + shimmer "답변을 기다리는 중입니다..."
3. **StepCarousel** — running step 자동 펼침, done step 자동 접힘
   - 헤더: 상태 아이콘 + label + (running 시) 라이브 progress_message + 소요시간 + nav 버튼
   - 본문 펼침: 도구 / 쿼리 / 진행 / 결과 / 발견한 출처 (citation 클릭 → 우측 패널)
4. **처리 과정 토글** (`<details>` 접힘 기본) — 직전 AI preamble 보존
5. **TurnAnswer** (turn.status === "done"일 때만 노출):
   - ConfidenceBadge ("신뢰도 높음 · 3/3")
   - MarkdownContent — citation chip [n] 클릭형, GFM 표/번호목록 렌더
   - CitationFootnotes — references 한-칸 carousel (선택)
   - ArtifactCard — 생성 파일 카드
   - FeedbackButtons — 👍/👎 + 코멘트 popover
6. **NextStepsCard** — 답변 본문의 `<next_steps>` 마커 파싱 → title + prompt 카드, 클릭 시 ChatInput prefill

### 3.4 ChatInput (sticky 하단)
- textarea 자동 grow 1~12줄
- Enter 전송 / Shift+Enter 줄바꿈 / Esc(running) 정지
- 좌측 toolbar:
  - 첨부 (disabled, 자리만)
  - **`@피드백` 토글 버튼** — 클릭 시 `@feedback ` prefix 박힘, 활성 시 primary-fixed 배경
- 우측: 전송 버튼 (running 시 stop 버튼)
- placeholder: "Medra에 메시지 보내기"

---

## 4. 우측 패널 (RightPanel)

### 모드 우선순위
1. **citation_split / reports_split** — citation/docPath URL + (deep 진행 또는 reports 강제) 동시 → 위/아래 분할
2. **deep_progress** — `state.deep_dispatched_at` set + `current_stage !== "done"` → DeepProgressPanel
3. **citation** — `?citation=<id>` → CitationInspector
4. **artifact** — `?docPath=<path>` → ArtifactViewer
5. **reports (강제)** — `panelOverride === "reports"` → ReportCardGroup
6. **none** — null (패널 unmount)

### 자동 노출
- citation/artifact 클릭 → panel open
- deep dispatch 시작 → panel 강제 open (DeepProgressPanel)
- deep 완료 → 패널 자동 닫힘 (현재 동작 — 변경 검토 중)

### 수동 토글
- ThreadTitleHeader의 우측 패널 토글 아이콘
- ThreadTitleHeader의 **📋 보고서** 버튼 (보고서 done 1건 이상 시 노출)
- citation chip 다시 클릭 → 같은 chip이면 토글 닫기

### 컴포넌트별 디자인
- **CitationInspector**: 제목 / 발행·일자·조항·페이지·문서ID 메타 / 본문 발췌 (whitespace-pre-wrap, 한글 word-break) / 원문 새 탭 링크 (본문 안)
- **ArtifactViewer**: 생성 파일 .md 미리보기 + 다운로드
- **DeepProgressPanel**: 헤더(스피너+shimmer "심층 보고서 생성 중"+(N/3)+진행 percent bar) / 3 stage 카드 (웹/법령/writer) / 검색 결과 + phase_message 라이브 / 슬라이드 진행바
- **ReportCardGroup**: final 보고서 카드 / 클릭 → ReportPreviewDialog / 다운로드 + 피드백

---

## 5. 입력 인터셉트

### `@feedback ...` / `@피드백 ...`
- 채팅 send 안 함
- POST `/feedback/general` (mock 모드면 fixture)
- 빈 코멘트 / 2000자 초과 → 에러 토스트
- 성공 → "피드백이 전송되었습니다. 감사합니다!" 토스트
- 토스트 위치: chat input 바로 위 + 좌우 input 중앙 정렬 (ResizeObserver)
- 토스트 디자인: theme `--md-surface` 배경 + `--md-primary` 보더, 좌측 색 스트립 X, 아이콘 X

---

## 6. 모달

| 모달 | 트리거 | 내용 |
|---|---|---|
| **SettingsDialog** | 사이드바 ⚙️ 클릭 | deployment_url / assistant_id / langsmith_key / user_jwt 입력 |
| **ReportPreviewDialog** | 보고서 카드 클릭 | .md 본문 마크다운 렌더 + 다운로드 버튼 |
| **DeleteConfirmDialog** | 사이드바 thread delete 클릭 | rounded-full 버튼, error 아이콘 중앙 |

---

## 7. 테마 (3종)

**우상단 ThemeToggle** — landing path에선 자동 숨김:
- **basic**: 흰 배경 + 그린 #00965E + Pretendard
- **medra**: 아이보리 #F4F2ED + 포레스트 #1D4D3A + Sora 폰트
- **regia**: 흰 배경 + 인디고/블루/시안 그라데이션
- 순환 토글 + localStorage `medi-front-theme` 영속 + body[data-theme] 박힘

**ThemeLogo** — `/logo.png` (basic) / `/logo-medra.png` / `/logo-regia.png` 자동 swap. 파일 없으면 hue-rotate filter fallback.

토큰 var() cascading — 토스트·CTA·카드·로고·토글 모두 자동 매칭.

---

## 8. 인증·미들웨어

- NextAuth v4 + EmailProvider (매직링크) + CredentialsProvider + PrismaAdapter
- middleware 흐름: 미인증 → `/login`, hasPassword=false → `/auth/set-password`
- `/` (no threadId) → `/new` redirect
- `NEXT_PUBLIC_AUTH_BYPASS=true` 또는 `NEXT_PUBLIC_DUMMY_MODE=true` → 인증 우회 (production 강제 OFF)
- JWT: jose HS256, backend가 NEXTAUTH_SECRET으로 verify

---

## 9. Admin 페이지

### `/admin/users`
- mock 또는 실 backend의 사용자 리스트 (페이지네이션)
- 각 사용자: 이메일·권한·일/월 한도·사용량
- 상세 → UserUsageDialog (period card + 입력/출력/비용 breakdown)
- 편집 → EditUserDialog (한도 override + admin 부여)

### `/admin/feedback`
- kind 토글: 자유 피드백 (`user_feedback`) / 평가 (`feedback`)
- 카드 리스트: 시간 / user_id / 코멘트 본문 / thread·msg id / rating(평가 모드)
- 페이지네이션 (50건씩)

---

## 10. State 관리

### useChatState (per thread)
- ChatState — `messages` / `files` / `steps` / `turns` / `reports` / `deep_progress` / `deep_dispatched_at` / `error`
- runs.stream 소비 (`values` / `messages-tuple` / `custom` 채널)
- 5 reducer — `applyValues` / `applyMessageChunk` / `applyToolProgress` / `applyDeepStep` / `applyDeepToolProgress`
- pollReports — Reports API 폴링 (3s 간격), final done / error / 5분 timeout 시 정지
- `dispatchedDeepStepIds` ref — 무한 deep 발화 차단

### RightPanelProvider (Context, 메모리만)
- `open`: boolean (패널 열림/닫힘)
- `panelOverride`: `"reports"` | `null` (강제 모드)

---

## 11. Mock 모드

`npm run dev:mock` (= `NEXT_PUBLIC_DUMMY_MODE=true` + `NEXT_PUBLIC_AUTH_BYPASS=true`):
- LangGraph SDK → `dummy.ts` fake client (메모리 thread store + jsonl 시나리오)
- runs.stream → `public/mocks/fast_stream.jsonl` / `deep_stream.jsonl` (150ms 간격 yield)
- REST 호출 → `mockFetch` 인터셉트 → `public/mocks/*.json` fixture
- 매 stream session마다 unique 접미사 — id 충돌 방지

### Fixture 파일
| 파일 | 매핑 |
|---|---|
| `fast_stream.jsonl` | runs.stream (assistantId가 일반) |
| `deep_stream.jsonl` | runs.stream (assistantId가 agent_deep 또는 deep trigger msg id) |
| `me_usage.json` | GET `/me/usage` |
| `reports_list.json` | GET `/threads/{tid}/reports` |
| `report_detail.json` | GET `/reports/{rid}`, GET `/reports/{rid}/download` |
| `feedback_general_response.json` | POST `/feedback/general`, 메시지·보고서 feedback |
| `admin_feedback.json` | GET `/admin/feedback` |
| `admin_users.json` | GET `/admin/users` |
| `suggestions.json` | GET `/suggestions` |
| `auto_title_response.json` | POST `/threads/{tid}/auto-title` |

---

## 11-a. 기능 카탈로그 — 20개 · 4단계 (2026-10-06)

진실원 `lib/features/catalog.ts`. 카테고리는 업무 흐름 4단계로 고정(`Stage`, 번호가 순서)이고 첫 화면
타일·패널 1열·연계 목록이 같은 라벨을 쓴다. 기능별 `icon`, 연계용 `io {needs, yields}`(슬롯 어휘 12개).

| 단계 | 기능 (id) |
|---|---|
| 1 파악 | 사실관계·타임라인 `facts_timeline` · 확인 질문 `question_list` · 사건 파일 검토 `case_issues` · 문서 검토(관점: 적합성/내규 갭/규제 추출/위험 조항) `doc_review` |
| 2 조사 | 판례 `prec_issues` · 유권해석 `interpretation` · 조문 변동(과거/시행 예정) `article_diff` · 조례 비교 `ordinance_compare` |
| 3 분석 | 법리 검토 `legal_memo` · 판례 적용 비교 `precedent_compare` · 증거 계획 `evidence_map` · 상대 주장 분석 `counter_argument` · 의무 매트릭스 `duty_matrix` · 인허가 경로 `pathway` · 제재 수위 `sanction_level` · 인용 검증 `cite_verify` |
| 4 산출 | 기한 일정표 `deadline_calendar` · 서식 `form_find` · 서면 초안(의견서·검토 보고·내용증명·답변서·질의서) `brief` · 의뢰인용 설명 `client_brief` |

- 합병·이동된 id(`pending_watch`·`rule_gap`·`mon_extract`→`LEGACY_FN`, `impact_graph`→모니터링)는 저장된
  직무에서 조용히 승격된다. `brief` 는 연계의 **마지막 단계만** 될 수 있고(패널이 막는다) 종합 뒤 모달로
  열린다(`OPEN_BRIEF_EVENT` detail `{kind}` → `POST /documents/from-brief {kind}`). `form_find` 가 마지막이면
  서식 목록이 펼쳐진다(`OPEN_FORM_LIST_EVENT`).
- 추천 직무 3(`presetTasks.ts`): 사건 초기 검토(7) · 인허가·컴플라이언스 자문(4) · 상대 서면 대응(6).
  저장분이 없을 때 첫 화면에, 패널에선 "내 직무" 아래 항상. 셋 다 `findGaps` 공백 0(테스트).
- 범위 고지 2건 추가(`legal.FEATURE_CAVEATS`): `deadline`(기한 계산 참고용) · `client`(변호사 검토 후 전달).

## 11-b. 기능 조합(composition) — 전문가 모드 전용

> **2026-10-06 — 실행 모델 재정의.** 종전 "단계는 숨은 턴, 마지막에 종합 1건"은 **폐지**. 사용자 지적: 단계
> 답변이 종합보다 훨씬 풍부한데 다 사라지고, 프롬프트 전문이 말풍선에 그대로 떠서 보기 싫다. 지금은:
> - 단계마다 **보이는 턴**. 턴에 `feature` 메타(기능·입력값·`run` 위치)가 실린다(모델 입력 아님).
> - 프런트가 같은 `run.id` 의 연속 턴을 **`RunReport` 한 편**으로 그린다 — 헤더(직무명·n/N·날짜·목차) ·
>   절(`n. 기능 제목` 중제목 + 입력 한 줄 + 접힌 프롬프트 + 답변·인용) · 하단(마지막이 서면이면 "서면 초안
>   열기", 서식이면 "서식 목록 열기", 그리고 "보고서로 저장 .md"). 종합 턴 없음. 절 안엔 next_steps 카드 없음.
> - 단일 실행은 `FeatureMessage` 카드 말풍선(제목 + 입력값, "프롬프트 보기" 접기).
> - 단계 사이에 사용자가 일반 질문을 끼우면 run 이 끊긴다(그 질문은 그 자리에 보인다).
> - 옛 스레드의 `hidden` 턴은 "과정 보기" 토글 그대로. 코드: `groupRuns.ts`·`RunReport.tsx`·
>   `FeatureMessage.tsx`·`export/runReport.ts`, 백엔드 `ChatFeatureMeta`.

> **2026-10-05 — "기능연계" 패널로 통합(2차 재설계).** 사용자 지침: 첫 화면 타일(단순 실행)은
> 유지하고, 세션 중간에도 기능을 골라 쓰거나 여러 기능을 연계할 수 있어야 하며, 세션이 시작되면
> 그 화면이 우측에 고정된다. 입력창 팝오버 피커와 조합 패널을 한 패널로 합쳤다
> (`CompositionPanel.tsx`, `FeaturePicker.tsx` 삭제).
> - **배치**: 근거(인용) 패널과 **별도 4번째 pane**(`PageShell` `id="features"`, 기본 18%·근거 패널의
>   절반). 둘이 동시에 열린다 — 종전엔 조합이 근거 탭을 덮어 인용을 누르면 안 열렸다.
>   위 2/3 = 기능 찾기 + **1열** 타일, 아래 1/3 = 고른 기능의 입력.
> - **자동 채움**: 대화가 있으면 타일을 누르는 순간 `/workflow/suggest` 로 입력을 대화 내용으로
>   먼저 채운다(사용자가 고칠 수 있음). 서식 작성(`form_find`)은 파일 업로드 대신 **대화에
>   나온 서식 목록**을 보여 주고 "다른 서식 찾기"로 폼을 연다.
> - **무입력 연계**: 빈 칸은 `(앞 단계에서 정리한 ○○)` / `(앞 대화에서 정리한 ○○)` 로 치환해
>   보내므로 따로 적지 않아도 이어진다. 첫 단계 + 대화 없음일 때만 빈 칸이 실행을 막는다.
> - **가시성**: 연계가 도는 동안 단계 턴이 **보인다**(끝나면 "과정 숨기기"). 단계 턴이 답 없이
>   실패하면 그 단계에서 멈추고 토스트로 알린다(종전엔 403·429 로 전부 실패해도 done + 빈 종합).
> - 끝난 연계에 단계를 더하면 새 연계(cursor·status 리셋), 끝난 연계는 "다시 실행".

여러 기능을 순서대로 묶어 돌린다. **일반 상담에는 두지 않는다** — 일반인 모드는
"그냥 물어보면 답한다"가 전부여야 하고, 기능과 조합이 전문가 모드의 차별점이다.

| 모드 | 기능 피커 | 조합 |
|---|---|---|
| 일반인 | ✗ (첫 화면 상황 카드만) | ✗ |
| 전문가 | ✓ 단일 기능 | ✓ |
| 모니터링 | ✓ 모니터링 도구 | ✗ (관찰·보고서·발송이 그 모드의 흐름) |

### 조각

| 역할 | 파일 |
|---|---|
| 타입 · 왕복 · 단계 메시지 · 종합 프롬프트 | `lib/features/composition.ts` |
| 조립 화면(선택·순서·입력·파일·기밀·실행) | `components/panel/CompositionPanel.tsx` |
| 우측 패널 탭 | `components/panel/RightPanel.tsx` (`composer` 모드) · `lib/store/rightPanel.tsx` |
| 실행기(순차 전송 → 제안 → 종합) | `components/shell/PageShell.tsx` |

### 실행 모델 — 단계는 보이지 않는다

```
step1 → 숨은 턴 ┐
step2 → 숨은 턴 ├ 채팅에 렌더 안 함(과정 보기로 펼침)
step3 → 숨은 턴 ┘
종합  → 보이는 턴 1건   ← 사용자가 읽는 것
```

단계마다 답을 쏟으면 읽을 수 없는 대화가 된다. 숨김은 **렌더 계층의 일**이고
모델 컨텍스트에는 그대로 들어간다 — 그래야 마지막에 종합할 수 있다.

두 모드의 차이는 **단계 사이에만** 있다.

| | 단계별 | 한번에 |
|---|---|---|
| 단계 N 완료 후 | 다음 입력을 채워 놓고 **멈춘다** | 채우고 바로 진행 |
| 사람의 개입 | 값을 고치거나 정보를 더 넣는다 | 없음 |
| 결과 | 종합 1건 | 종합 1건 |

입력 제안은 `POST /chat/{tid}/workflow/suggest` 한 번. 실패해도 조합은 멈추지
않는다(빈 칸으로 둔다).

### 단계별 기밀 — 메시지 단위 격리가 전제

단계마다 기밀을 다르게 줄 수 있다. 이게 성립하려면 **비기밀 턴이 기밀 메시지를
보지 못해야** 한다 — 요청 컨텍스트는 스레드 전체 이력이라, 필터가 없으면 앞 기밀
단계 내용이 다음 단계에서 상용 모델로 나간다. 백엔드 `chat_messages.sensitive` +
`_drop_sensitive` 가 그 일을 하고, `tests/test_sensitive_isolation.py` 가 고정한다.

종합도 기밀 단계가 하나라도 있었으면 원내에서 돈다 — 종합은 그 내용을 읽는다.

기밀 토글은 **스레드 단위**다(2026-10-03, `regnav_confidential:<threadId>`). 종전 전역
키 하나는 보호 단위(스레드)와 어긋나 다른 스레드까지 원내로 저하되거나, 그쪽에서 끄면
돌아와서 기밀 내용이 통째로 드롭됐다. `/new` 에서 켠 값은 첫 전송 때 `adoptConfidential`
이 새 스레드로 옮긴다. 해제 경고문도 사실대로 바꿨다 — 끄면 "외부로 전송"되는 게 아니라
**모델이 그 내용을 더 이상 보지 않는다**(`_drop_sensitive`).

백엔드 쪽 보장은 `docs/OPERATIONS.md` 불변식 11 — 같은 턴의 보조 LLM 호출 전부가
`aux_model` 을 지나 기밀이면 원내로 가거나 건너뛴다. 심층 보고서는 기밀 스레드에서 422.

### 파일

단계 첨부는 **스레드에 보관**한다(암호화). 채팅 첨부는 무상태지만 조합은 짜 놓고
나중에 돌리거나 새로고침 뒤 이어서 하기 때문이다. 전송 시 id 만 보내고 서버가
본문을 꺼내 합친다 — 사건 파일이 브라우저로 되돌아오지 않는다.

`triggers:"attach"` 인 기능은 **파일이 없으면 실행 비활성**이다.

### 직무(task) 템플릿 — 구현 (2026-10-06)

조합의 저장 구조가 그대로 **직무(task)** 의 저장 구조다. 연계 목록의 **"직무로 저장"** 으로
이름을 붙이면 사용자 단위로 저장되고(`POST /task-templates`), 첫 화면 타일 맨 앞과 패널 타일
위 "내 직무"에 선다. 누르면 새 스레드(또는 현재 스레드)에 `cursor 0 · draft` 로 복원되고, 대화가
있으면 기존 자동 채움이 1단계 입력을 채운다. 이름 변경·삭제는 패널 "내 직무"에서.

- **저장하는 것은 `fn`·`confidential` 뿐** — 값(사실관계·쟁점)은 사건마다 다르고 저장하면 다음
  사건에 지난 사실관계가 섞인다(기밀 격리). 파일은 스레드 소속이라 못 옮긴다.
- 복원 시 레지스트리에 없는 `fn` 은 버리고 토스트로 알린다(`fromTemplate`, 문서의 "끊어진 노드" 검증).
- 서버 스레드는 첫 `POST /chat` 에서 생기므로, `PATCH /chat/{tid}/workflow` 는 **아직 없는
  스레드를 호출자 소유로 만들어 받는다** — 첫 화면에서 직무를 고르는 흐름이 그 전에 저장한다.
- 상한 사용자당 50개 · 이름 80자 · 8단계. 코드: `lib/client/taskTemplates.ts`, `composition.ts`
  의 `toTemplateSteps/fromTemplate`, 백엔드 `persistence/task_templates_repo.py` · `routes/task_templates.py`.

### 연계 공백 채움 — 구현 (2026-10-06)

같은 문서의 "자가치유 라우팅"을 사용자 정정대로 읽은 것: **짠 연계에 빠진 단계가 있으면 채워
제안**. 기능마다 `io: { needs, yields }`(`catalog.ts`, 슬롯 어휘 `Slot` 9개 — facts·issue·subject·
article·precedent·duty·form·sanction·doc)를 두고, `lib/features/gaps.ts` 의 `findGaps` 가
**결정적으로** 판정한다(LLM·판단 모델 없음). 단계 i 의 `needs` 가 앞 단계 `yields` ∪ 대화(있으면
facts·issue·subject) ∪ 서식 인용(form) ∪ 첨부(doc) 에 없으면 그 단계 앞에 "빠진 단계 — ○○: △△
넣기" 행이 선다. **제안일 뿐 자동 삽입하지 않는다**(실행 전 사용자 승인). 그 슬롯을 내는 기능이
없는 공백(subject·doc 은 사용자 입력)은 제안하지 않는다 — 그건 폼 빈 칸이다. `brief`(의견서)는
`io.needs` 가 있지만 패널에서 턴으로 보낼 수 없어(모달) 연계 단계가 되지 않는다.

### 판단 모델 계층 — 적재만 (2026-10-06)

`backend/src/judgment.py`: `judge(state, {key: Question}) -> {key: 확률}`. 백엔드 ① 원내
`JUDGE_LOCAL_BASE_URL`(Ollama ≥0.35 `/v1/systemone`, Kev-4B) → ② 상용 `JUDGE_API_URL`(TypeSafe
Jev) → ③ `aux_model()` LLM 폴백. 기밀 턴은 ①만. 지금은 `/workflow/suggest` 가 "앞 내용에 채울
정보가 있나"를 함께 묻고 **events(`judgment`)에 적재만** 한다 — 임계값은 이 적재와 실제 채움
결과를 대조한 오탐률이 나온 뒤에 켠다(감사 M3). dev 실측: 백엔드 `llm`, `fillable` 0.95/0.15.

출처: `docs/Vibe_Coding_Agent_Master_Prompt.docx` 선별 적용(대조표 `docs/CHANGELOG.md` 2026-10).
채택하지 않은 것: 분기 DAG · 실패 시 자동 우회 실행 · 비용·실패확률 사전 시뮬레이션 · Redis.

## 12. 알려진 한계 / TODO

- mock 모드에서 답변 본문은 fixture 정적 — 어떤 질문에도 같은 답변
- Deep stream의 LLM 토큰 라이브 표시(messages-tuple) 미구현 (v1)
- 페이지 재진입 시 deep stream 재구독 X (폴링이 결과 fallback)
- `tool_progress phase=="result"`의 `index/title/subtitle/url` 필드는 backend가 emit해야 search_results 카드에 채워짐
