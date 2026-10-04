# MEDIREG AI

의사·RA/QA·인허가 컨설턴트를 위한 **한국어 의료 규제 상담 서비스**. 법령·행정규칙·판례를 근거로
즉답(채팅)하고, 백그라운드에서 컨설팅형 심층 보고서를 만든다.

백엔드와 프런트엔드를 한 저장소(`regnavigator`)에 둔다. 현재 버전 **0.8.0**(프런트·백 동기), 클로즈 베타 운영 중.
변경 이력은 [`docs/CHANGELOG.md`](./docs/CHANGELOG.md).

## 구성

```
backend/            FastAPI + 자체 tool-loop (Python 3.11+, 패키지명 medi-back)
  src/              api(진입)·chat_loop(fast)·report_runner/report_pipeline(deep)·grounding·
                    routes/·persistence/·retrieval/·guardrail/·tools/·skills/·middleware/
  tests/            pytest (~1,150개, 외부 서비스 없이 tmp SQLite 로 격리)
  scripts/          check_config·gen_env_docker_example·bench_chatloop·eval_*·quality_regression 등
  guardrail-server/ GPU 서버용 PII NER·의도 분류 서빙 코드 원본(배포 미러는 별도 저장소)
  mocks/            프런트 dummy 모드용 응답·SSE 픽스처 원본
  db/migrations/    운영 Postgres DDL
  docs/             guide(architecture·features·onboarding·startup) · contracts(API·frontend_chat_v2) ·
                    spec(ADR-*) · product(운영진 기능 설명서) · legal(약관·방침)
frontend/           Next.js 15 (App Router) + NextAuth + Prisma/Postgres (패키지명 medi-front)
  src/app/          (chat)·(auth)·admin·landing·terms·privacy·maintenance·api/auth
  src/lib/          client(SSE·토큰)·api(REST wrapper)·store(채팅 상태)·parse(인용·next_steps)
  src/components/   shell·chat·panel·thread·admin·legal·settings
  prisma/           인증 DB 스키마·마이그레이션
  docs/             ARCHITECTURE(구현 정본)·FEATURES·USER_GUIDE·MAINTENANCE·설계문 00~05
docs/               OPERATIONS.md(운영·배포·장애 대응) · CHANGELOG.md(변경 이력)
```

```
브라우저 ──▶ frontend (Next.js) ──JWT──▶ backend (FastAPI, 단일 워커)
                                          ├─▶ 검색 API /search (KURE+BM25+RRF+리랭커)   ┐
                                          ├─▶ PII NER · 의도 분류                        ├ GPU 서버(온프레미스)
                                          ├─▶ 보고서 writer (vLLM, 서빙 모델 자동 감지)   ┘
                                          ├─▶ LLM API (Anthropic, 폴백 OpenAI) · 웹 검색(Tavily)
                                          └─▶ Postgres(운영) / SQLite(dev) · 보고서 blob
```

- **fast**(`POST /chat`, SSE ~15–20s): PII 게이트 ∥ 의도 판정 → **규제 질의면 검색 강제** → 답변 스트리밍 → 인용 검증(grounding).
- **deep**(`POST /reports` + 폴링, 5–40분): 멱등키 → 분해·수집 → 근거 충분성 게이트 → 로컬 vLLM writer → 비평·개정 → 보고서.
  채팅과 완전 분리·병렬 — 대화록에 보고서 흔적을 남기지 않고 사이드바·우측 패널·이메일로만 전달.
- 무거운 ML(검색 랭킹·NER·의도 분류·보고서 생성)은 전부 별도 서비스로 위임한다 — 백엔드는 thin-client.
- LLM 스택은 `langchain-core` + `langchain-anthropic` 만. langgraph 는 2026-07-14 ADR-0001 로 은퇴.

## 빠른 시작 (dev)

**backend**
```bash
cd backend
python -m venv venv && . venv/bin/activate        # Windows: .\venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env                              # 키·서비스 주소 채우기
PYTHONUTF8=1 python -c "from dotenv import load_dotenv; load_dotenv(); import uvicorn; uvicorn.run('src.api:app', port=2024)"
pytest tests/ -q
```
- dev 는 SQLite 로 돈다(`.env.example` 기본 `REPORTS_BACKEND=sqlite`). 원격 운영 PG 접속은 부팅 가드가 막는다.
- 검색·NER·의도 분류 서비스 주소가 없으면 해당 기능이 폴백/비활성으로 동작한다. `/readyz` 로 의존성 상태 확인.
- `PYTHONUTF8=1` 은 Windows 에서 필수(`.env` 한글 주석). Swagger: `http://127.0.0.1:2024/docs`.

**frontend**
```bash
cd frontend
npm install
cp .env.example .env.local                        # NEXT_PUBLIC_DEPLOYMENT_URL(백엔드)·NEXTAUTH_SECRET(backend 와 같은 값)·DATABASE_URL
npx prisma migrate dev                            # 인증 DB — Postgres `medi_auth` (SQLite 미지원)
npm run dev                                       # http://localhost:3000
npm run dev:mock                                  # 백엔드·DB 없이 목 데이터로 UI 확인

npm run lint && npx tsc --noEmit && npm run build # 배포 전 게이트
```
`NEXT_PUBLIC_*` 는 빌드 시 번들에 인라인된다 — 값을 바꾸면 재빌드.

운영 배포(docker compose)·장애 대응·운영 불변식은 [`docs/OPERATIONS.md`](./docs/OPERATIONS.md).

## 배포별 설정

도메인·문의 메일·루트 관리자는 코드에 두지 않고 env 로 준다.

| 대상 | backend (`.env` / `.env.docker`) | frontend (빌드 시 인라인) |
|---|---|---|
| 서비스 URL | `APP_URL` | `NEXT_PUBLIC_APP_URL` |
| 문의 메일 | `SUPPORT_EMAIL` | `NEXT_PUBLIC_SUPPORT_EMAIL` |
| 루트 관리자 | `ROOT_ADMIN_EMAILS` | `NEXT_PUBLIC_ROOT_ADMIN_EMAIL` |
| 메일 발신자 | `SMTP_FROM` | `EMAIL_FROM` / `NEXT_PUBLIC_MAIL_FROM` |

모든 백엔드 노브의 단일 진실원은 `backend/src/config.py` 의 `ENV_REGISTRY`(`python scripts/check_config.py` 로 점검).
노브를 추가하면 `backend/docker-compose.yml` 의 `environment:` 매핑도 함께 추가하고
`python scripts/gen_env_docker_example.py --write` 로 예시 파일을 재생성한다(운영은 `env_file` 을 쓰지 않는다).

## 기관 IRB/DRB 지침 스킬

기관 연구 심의(IRB·DRB) 지침을 채팅에서 안내하는 선택 기능이다. 지침 번들은
`backend/src/skills/medireg_irb_drb/`(제휴 기관 내부 지침 — 관련자 외 재배포 금지)이며,
`SKILL_BUNDLE_DIR` 로 번들 디렉터리를 지정하면 켜진다. 미설정이면 기능이 꺼지고 나머지는 그대로 동작한다.
로더·연동 코드는 `backend/src/skills/`, 스위치 설명은 [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) §7.

## 문서 지도

| 나는 ... | 문서 |
|---|---|
| 처음 왔다 / 남에게 설명해야 한다 | [`backend/docs/guide/onboarding.md`](./backend/docs/guide/onboarding.md) |
| 시스템 전체 그림 | [`backend/docs/guide/architecture.md`](./backend/docs/guide/architecture.md) |
| 백엔드 기능별 동작·env | [`backend/docs/guide/features.md`](./backend/docs/guide/features.md) |
| API·SSE 계약 | [`backend/docs/contracts/API.md`](./backend/docs/contracts/API.md) · [`frontend_chat_v2.md`](./backend/docs/contracts/frontend_chat_v2.md) |
| 설계 결정 | [`backend/docs/spec/`](./backend/docs/spec) (ADR-0001 FastAPI 이전 · ADR-0002 검색 int8 양자화) |
| 프런트 구현 현황 | [`frontend/docs/ARCHITECTURE.md`](./frontend/docs/ARCHITECTURE.md) · [`FEATURES.md`](./frontend/docs/FEATURES.md) |
| 앱을 사용한다 | [`frontend/docs/USER_GUIDE.md`](./frontend/docs/USER_GUIDE.md) · [`backend/docs/product/ops_feature_manual.md`](./backend/docs/product/ops_feature_manual.md) |
| 운영·배포·장애 | [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) |
| 재부팅 후 기동 | [`backend/docs/guide/startup.md`](./backend/docs/guide/startup.md) · `docs/OPERATIONS.md` §2-3 |
| 변경 이력 | [`docs/CHANGELOG.md`](./docs/CHANGELOG.md) |

> `backend/README.md`·`frontend/README.md` 와 일부 가이드 문서는 저장소 통합 전 경로(`../medi-back/...`,
> `docs/ops/runbook.md`, `docs/PATCHNOTE.md` 등)를 가리키는 곳이 있다. 해당 내용은 위 `docs/OPERATIONS.md`·`docs/CHANGELOG.md` 로 흡수됐다.
