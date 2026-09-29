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

기관별 연구 심의 지침을 채팅에서 안내하는 선택 기능이다. 지침 번들은 기관이 별도로 제공하며,
`SKILL_BUNDLE_DIR` 로 번들 디렉터리를 지정하면 켜진다. 미설정이면 기능이 꺼지고 나머지는 그대로 동작한다.
로더·연동 코드는 `backend/src/skills/`, 스위치 설명은 [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) §7.
