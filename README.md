# MEDIREG AI

의사·RA/QA·인허가 컨설턴트를 위한 **한국어 의료 규제 상담 서비스**. 법령·행정규칙·판례를 근거로
즉답(채팅)하고, 백그라운드에서 컨설팅형 심층 보고서를 만든다.

백엔드와 프런트엔드를 한 저장소에 둔다. 변경 이력은 [`docs/CHANGELOG.md`](./docs/CHANGELOG.md).

## 구성

```
backend/    FastAPI + 자체 tool-loop (Python 3.11+) — 채팅 SSE·보고서 잡·가드레일·영속
frontend/   Next.js 15 (App Router) + NextAuth + Prisma — 채팅 UI·인증·관리자 화면
docs/       OPERATIONS.md(운영 요약) · CHANGELOG.md(변경 요약)
```

```
브라우저 ──▶ frontend (Next.js) ──JWT──▶ backend (FastAPI, 단일 워커)
                                          ├─▶ 검색 API /search (KURE+BM25+RRF+리랭커)   ┐
                                          ├─▶ PII NER · 의도 분류 (transformers)         ├ GPU 서버(온프레미스)
                                          ├─▶ 보고서 writer (vLLM, 모델 자동 감지)        ┘
                                          ├─▶ LLM API (Anthropic, 폴백 OpenAI) · 웹 검색(Tavily)
                                          └─▶ Postgres(운영) / SQLite(dev) · 보고서 blob
```

- **fast**(`POST /chat`, SSE ~15–20s): PII 게이트 → 의도 판정 → **규제 질의면 검색 강제** → 답변 스트리밍 → 인용 검증(grounding).
- **deep**(`POST /reports` + 폴링, 5–40분): 멱등키 → 분해·수집 → 로컬 vLLM writer → 5섹션 보고서. 채팅과 완전 분리·병렬.
- 무거운 ML(검색 랭킹·NER·의도 분류·보고서 생성)은 전부 별도 서비스로 위임한다 — 백엔드는 thin-client.

설계 근거는 `backend/docs/guide/architecture.md`·`backend/docs/guide/onboarding.md`,
결정 기록은 `backend/docs/spec/ADR-*`, 프런트 계약은 `backend/docs/contracts/frontend_chat_v2.md`.

## 빠른 시작 (dev)

**backend**
```bash
cd backend
python -m venv venv && . venv/Scripts/activate   # macOS/Linux: . venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                              # 키·서비스 주소 채우기
PYTHONUTF8=1 python -c "from dotenv import load_dotenv; load_dotenv(); import uvicorn; uvicorn.run('src.api:app', port=2024)"
pytest tests/ -q
```
dev 는 SQLite 로 돈다(`REPORTS_BACKEND=sqlite`). 검색·NER·의도 분류 서비스 주소가 없으면 해당 기능이 폴백/비활성으로 동작한다.

**frontend**
```bash
cd frontend
npm install
cp .env.example .env.local                        # NEXTAUTH_SECRET 은 backend 와 같은 값
npm run dev          # 또는 npm run dev:mock — 백엔드 없이 목 데이터로 UI 확인
```

운영 배포(docker compose)·장애 대응·운영 불변식은 [`docs/OPERATIONS.md`](./docs/OPERATIONS.md).

## 미설정 외부 연동 — 지금 무엇이 막혀 있나

아래가 없어도 서비스는 뜬다. 해당 기능만 **비활성 또는 폴백**으로 동작한다.
전부 `backend/.env` 에 주석으로 들어 있으니 `#` 만 풀고 값을 채우면 된다.
상태 점검은 `python scripts/check_config.py`.

> 설계 원칙: 외부 연동이 없을 때 **조용히 성공하지 않는다.** 예컨대 법령 DB가
> 죽어 있으면 "변경 없음"이 아니라 "확인하지 못했습니다"로 답한다 —
> 거짓 음성이 모니터링 도구가 낼 수 있는 가장 나쁜 출력이기 때문이다.

### ① openlaw Postgres — 막는 기능이 가장 많다

```
PG_HOST=        PG_PORT=5432      PG_NAME=openlaw
PG_USER=        PG_PASS=
```
**읽기 전용 계정으로 충분하다**(ETL 소유, backend 는 조회만).

| 없을 때 | 증상 |
|---|---|
| 조문 전문 열람 | "조문 전문을 불러오지 못해 **발췌만** 보여 드립니다" |
| 서식 작성 패널 | `[이 서식으로 작성]` 이 열리지 않음(404) |
| 규제 변경 감지 | 알람이 생성되지 않음 — "확인하지 못했습니다" |
| 모니터링 정기 리포트 | "일부 확인 불가"로 발송 |
| 별표 목록 | `/annex/list` 가 `count: 0` |

### ② SMTP — 메일 발송

```
SMTP_HOST=      SMTP_PORT=587     SMTP_USER=
SMTP_PASS=      SMTP_FROM=
```
`EMAIL_SERVER`(`smtps://user:pass@host:465`) 한 줄로 대체 가능하며, 있으면 그쪽이 우선.
없으면 보고서 발송이 `ok:false` 로 **명시적으로 실패**한다(보낸 척하지 않는다).

### ③ 원내(온프레미스) 모델 — 엔드포인트 **두 개**

```
# 채팅 기밀 모드
SKILL_LOCAL_MODEL=1
SKILL_LOCAL_BASE_URL=http://<host>:<port>/v1
REPORT_WRITER_API_KEY=

# 문서 작업 — 서식 도우미 · 의견서 다듬기 · AI 문단 수정
DOC_FILL_BASE_URL=http://<다른 host>:<port>/v1
DOC_FILL_MODEL=                 # 비우면 /v1/models 자동 감지
DOC_FILL_API_KEY=
```

- 둘은 **다른 호스트**여야 한다 — 보고서 writer 와 같은 GPU 를 쓰면 경합한다.
- vLLM 이 **tool-calling 을 지원해야** 한다(`--enable-auto-tool-choice --tool-call-parser hermes`).
  지원 없이 띄우면 첫 턴이 400 으로 죽고 probe 가 '다운'으로 간주한다.
- 없으면 기밀 모드 질문은 **상용 모델로 우회하지 않고 거부**한다(fail-closed).

### ④ 검색 API 키 권한 — ①의 일부를 대신한다

현재 키 권한(`GET /search/access` 실측):

```
scope: search   →  /search, /search/health, /search/access
```

`/articles/bodies` 와 `/articles/{key}/body` 가 **401**이다. ETL 쪽에서 이 둘을 키
권한에 추가하면 **조문 전문·서식 작성이 PG 없이 풀린다**. 단 개정 감지는 PG 가 따로 필요하다.

### ⑤ Neo4j — 조문 인용 네트워크

```
NEO4J_URI=bolt://    NEO4J_USER=    NEO4J_PASS=
```
`frontend/.env.local` 의 `NEXT_PUBLIC_LAW_GRAPH=1` 도 함께 켜고 **재빌드**해야 한다
(`NEXT_PUBLIC_*` 는 빌드 시 번들에 인라인된다). 이 기능은 2026-08-03 "임시 구현"
판정으로 진입점을 꺼 둔 상태이므로, 켠 뒤 품질을 먼저 확인한다.

### ⑥ 입법예고 · 국회 의안 코퍼스 — **아직 없다**

규제 대응 실무의 핵심은 "공포 후 대응"이 아니라 **입법예고 단계 대응**이다. 공포
전에는 적용 범위·유예기간·차등적용을 다툴 수 있지만, 공포된 뒤에는 준수냐 위반이냐만
남는다. 지금 코퍼스는 **공포된 것만** 담고 있다.

| 구간 | 보유 |
|---|---|
| 입법예고 (법제처 · 부처) | ✗ |
| 국회 계류 의안 | ✗ |
| 공포 후 시행 전(개정예정본) | ✓ `include_pending` |
| 현행 | ✓ |
| 구법(과거 시점 조문) | ✗ |

막는 기능: `pending_watch`(개정 추적)가 공포 전 구간을 "확인 불가 — 입법예고 단계
미수집"으로만 답한다. `article_diff`(조문 변동 대조)의 **과거 조문 전문 비교**도
구법 부재로 불가하다(개정 시점 열거까지만).

필요한 것은 env 가 아니라 **ETL 수집 범위 확장**이다 — 법제처 입법예고 목록·
국회 의안정보시스템, 그리고 조문의 시점별 스냅숏.

### ⑦ 조문 전문 — ④와 같은 문제, 영향 받는 기능이 늘었다

기능을 추가하면서 `/articles/bodies` 401 이 막는 범위가 커졌다.

| 기능 | 401 일 때 동작 |
|---|---|
| `article_diff` 조문 변동 대조 | 발췌 200자로만 대조(그렇게 밝힘) |
| `sanction_level` 제재 가늠 | **별표의 부과 기준 표**를 못 읽어 법정 상한만 |
| `rule_gap` 사내 규정 갭 점검 | 조항 대조가 발췌 수준 |
| `impact_graph` 영향 범위 | 인용·준용 문구를 본문에서 못 캐 검색 추정에 의존 |

### 우선순위

| 연동 | 푸는 기능 수 | 비고 |
|---|---|---|
| ④ 검색 API 권한(`/articles/bodies`) | **4** | env 변경 없음 — ETL 쪽 키 권한만. **가장 싸고 효과 큼** |
| ① openlaw PG | 5 | 개정 감지는 이것만 가능 |
| ③ 원내 모델(DOC_FILL·SKILL_LOCAL) | 4 | 기밀 모드 전체가 여기 달림 |
| ② SMTP | 2 | |
| ⑤ Neo4j | 1 | `impact_graph` 정확도 |
| ⑥ 입법예고·구법 코퍼스 | 2 | ETL 신규 과제 — 가장 큼 |

## 배포별 설정

도메인·문의 메일·루트 관리자는 코드에 두지 않고 env 로 준다.

| 대상 | backend (`.env` / `.env.docker`) | frontend (빌드 시 인라인) |
|---|---|---|
| 서비스 URL | `APP_URL` | `NEXT_PUBLIC_APP_URL` |
| 문의 메일 | `SUPPORT_EMAIL` | `NEXT_PUBLIC_SUPPORT_EMAIL` |
| 루트 관리자 | `ROOT_ADMIN_EMAILS` | `NEXT_PUBLIC_ROOT_ADMIN_EMAIL` |
| 메일 발신자 | `SMTP_FROM` | `EMAIL_FROM` / `NEXT_PUBLIC_MAIL_FROM` |

모든 백엔드 노브의 단일 진실원은 `backend/src/config.py` 의 `ENV_REGISTRY`(`python scripts/check_config.py` 로 점검).

## 기관 IRB/DRB 지침 스킬

기관 연구 심의(IRB·DRB) 지침을 채팅에서 안내하는 선택 기능이다. 지침 번들은
`backend/src/skills/medireg_irb_drb/`(제휴 기관 내부 지침 — 관련자 외 재배포 금지)이며,
`SKILL_BUNDLE_DIR` 로 번들 디렉터리를 지정하면 켜진다. 미설정이면 기능이 꺼지고 나머지는 그대로 동작한다.
로더·연동 코드는 `backend/src/skills/`, 스위치 설명은 [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) §7.
