# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 저장소 개요

MEDIREG AI — 한국어 의료 규제 상담 서비스. 모노레포 (저장소명 `regnavigator`).

- `backend/` — FastAPI + 자체 tool-loop (Python 3.11+, 패키지명 `medi-back`). 채팅 SSE·보고서 잡·가드레일·영속.
- `frontend/` — Next.js 15 App Router + NextAuth + Prisma(Postgres) (패키지명 `medi-front`).
- `docs/` — `OPERATIONS.md`(운영·배포·장애 대응), `CHANGELOG.md`(양쪽 변경 이력 단일 타임라인).

코드 주석·문서·커밋 메시지는 전부 한국어. 과거 사고와 날짜를 주석에 남기는 관행이 있다(“2026-08-02 실측 사고” 식). 기존 스타일을 따른다.

## 자주 쓰는 명령

### backend (`cd backend`)

```bash
pip install -e ".[dev]"                       # ruff·pytest 포함
cp .env.example .env                          # REPORTS_BACKEND=sqlite 가 dev 기본
PYTHONUTF8=1 python -c "from dotenv import load_dotenv; load_dotenv(); import uvicorn; uvicorn.run('src.api:app', port=2024)"

pytest tests/ -q                              # 전체 (~1150 테스트)
pytest tests/test_chat_loop.py -q             # 파일 하나
pytest tests/test_chat_loop.py -k "grounding" -q   # 이름으로 선택
ruff check src tests                          # line-length 100, py311

python scripts/check_config.py                # prod 필수 env 누락 점검(배포 전)
python scripts/gen_env_docker_example.py --write   # .env.docker.example 재생성(손편집 금지)
python scripts/bench_chatloop.py "<질문>"      # fast 1턴 벤치(TTFT·steps·citations)
```

- `PYTHONUTF8=1` 은 `.env` 의 한글 주석 때문에 Windows 에서 필수. Linux 는 없어도 된다.
- pytest 설정 파일은 없다. async 테스트는 `@pytest.mark.asyncio` 를 명시한다.
- `tests/conftest.py` 가 모든 테스트에 tmp SQLite 를 강제하고 `REPORTS_PG_DSN`·Tavily·Qdrant 키를 지운다. 실 서비스 없이 돌아가야 정상이며, 외부 서비스가 필요한 테스트는 새로 만들지 않는다.
- Swagger: `http://127.0.0.1:2024/docs`. 헬스: `/healthz`, `/readyz`(의존성), `/load`.

### frontend (`cd frontend`)

```bash
npm install                                   # postinstall 이 prisma generate
cp .env.example .env.local                    # NEXTAUTH_SECRET 은 backend 와 같은 값
npx prisma migrate dev                        # 인증 DB(Postgres `medi_auth`) — SQLite 아님
npm run dev                                   # http://localhost:3000
npm run dev:mock                              # 백엔드·DB 없이 public/mocks 로 UI 확인

npm run lint && npx tsc --noEmit && npm run build   # 배포 전 게이트(이 셋을 다 통과해야 한다)
```

- 프런트에는 테스트 스위트가 없다. 위 세 명령이 유일한 자동 검증이다.
- `NEXT_PUBLIC_*` 는 빌드 시 번들에 인라인된다. 값을 바꾸면 재빌드.

## 아키텍처 핵심

### 두 흐름, 완전 분리

- **fast** — `POST /chat` SSE. `src/chat_loop.py`(수동 tool-loop: bind_tools + while). 순서: PII 게이트 ∥ 의도 판정(병렬) → 규제 질의면 `qdrant_search` 강제 → 답변 스트리밍(`[n]` 인용) → `done` → grounding 검증은 done *후* trailing steps 로. 
- **deep** — `POST /reports` + 폴링. `src/report_runner.py`(asyncio 잡러너, 멱등키 `^rpt_`) → `src/report_pipeline.py`(분해 → 수집 → 근거 충분성 게이트 → vLLM writer → critique/revise → grounding).
- 보고서는 채팅 대화록에 아무것도 append 하지 않는다(2026-07-25). 전달은 사이드바·우측 패널·이메일만. 이 분리를 깨는 변경은 하지 않는다.
- `src/grounding.py` 는 chat·report 가 공유한다.

### thin-client 원칙

무거운 ML(검색 랭킹·PII NER·의도 분류·보고서 writer)은 전부 외부 GPU 서버(DGX) 서비스다. 백엔드에 로컬 ML 을 넣지 않는다.

- 검색: `src/retrieval/search_api_client.py` → 외부 `/search` API. pg/neo4j/mongo 클라이언트는 `/article`·`/law-graph`·pinned 전용(RAG 검색 경로가 아니다).
- 가드레일: `src/guardrail/` — `ner_client.py`·`intent_client.py` 가 DGX 호출, `pii.py` 는 regex 1차. 서빙 코드 원본은 `backend/guardrail-server/`(배포 미러는 별도 저장소).
- LLM 스택은 `langchain-core` + `langchain-anthropic` 만. langgraph·deepagents 는 ADR-0001(2026-07-14)로 은퇴 — 다시 들이지 않는다. vLLM writer 는 `[writer-vllm]` extra 의 `langchain-openai` lazy import.

### 단일 워커 전제

uvicorn 은 **workers 1 고정**. 검색 백프레셔·보고서 큐·턴 락·LLM RPS 캡이 전부 프로세스 로컬이다(`src/single_instance.py` 가 PG 어드바이저리 락으로 강제).
그래서 라우트 규약이 있다(`tests/test_async_route_convention.py` 가 잠근다):
- `async def` 라우트는 반드시 `await` 가 있어야 한다. 없으면 `def` 로 써서 스레드풀에서 돌린다.
- SMTP·webhook·동기 repo 호출 등 블로킹 호출은 async 안에서 `asyncio.to_thread` 로 넘긴다.

### 설정 단일 진실원

`backend/src/config.py` 의 `ENV_REGISTRY` 가 모든 env 노브의 정본이다. 노브를 추가할 때 세 곳을 같이 고친다:
1. `ENV_REGISTRY` 에 `Setting` 추가.
2. `docker-compose.yml` 의 `environment:` 매핑 추가 — 운영은 `env_file` 을 안 쓰므로 매핑 없으면 컨테이너에 전달되지 않는다(`tests/test_compose_env_mapping.py`).
3. `python scripts/gen_env_docker_example.py --write` 로 `.env.docker.example` 재생성.

숫자 노브는 `os.getenv(K) or "기본값"` 패턴을 쓴다. 빈 문자열이 기본값을 잡아먹은 사고가 있었다(`tests/test_env_empty_string.py`).

### 영속

`src/persistence/*_repo.py` — SQLite(dev) / Postgres(운영) 양쪽 구현. `REPORTS_BACKEND` 로 선택. dev 프로세스가 원격 PG 에 붙으려 하면 부팅 가드가 막는다. 운영 DB 를 읽어야 하는 스크립트만 `ALLOW_REMOTE_PG=1 REPORTS_BACKEND=postgres REPORTS_PG_DSN=...` 를 그 실행에 명시한다. DDL 은 `backend/db/migrations/`.

프런트 인증 DB 는 별도: Prisma → 같은 Postgres 인스턴스의 `medi_auth` DB. 백엔드와 프런트는 `NEXTAUTH_SECRET` 을 공유하고, 백엔드 `src/middleware/auth.py` 가 프런트 발급 JWT 를 검증한다. 권한의 권위 경계는 백엔드다.

### doc_kinds 단일 진실원

검색 종별(법령·행정규칙·판례·해석례·별표 등)을 추가하면 `src/chat_loop.py` 의 `TOOL_SPECS` enum, `src/tools/search.py` 의 `ALLOWED_DOC_KINDS`, `src/coverage.py` 의 `ALLOWED_KINDS` 를 함께 갱신한다(`tests/test_doc_kinds_sot.py`).

### 기관 지침 스킬 (선택 기능)

`src/skills/` — `SKILL_BUNDLE_DIR` 미설정이면 카탈로그·도구·강제 전부 미부착(기존 채팅과 동일). 번들 `src/skills/medireg_irb_drb/` 는 제휴 기관 내부 지침이라 외부 재배포 금지.

### 프런트 구조

- `src/lib/client/chatApi.ts` — SSE 직접 파싱. 이벤트: `meta`·`pii_notice`·`token`·`tool_progress`·`step_lifecycle`·`steps`·`clarify`·`error`·`done`.
- `src/lib/api/client.ts` — REST 단일 wrapper `apiFetch`(Bearer 주입, DUMMY 모드 `mockFetch` 인터셉트). 새 엔드포인트는 이걸 재사용한다.
- `src/lib/store/` — `useChatState`(send/stop/retry·폴링) → `turns.ts`(chunk 디스패처) → `derive.ts`(Turn 증분 파생).
- 라우트 그룹: `(chat)` 메인 셸, `(auth)` 로그인·가입, `admin/*`, `landing`, `terms`·`privacy`·`maintenance`.

프런트 규율(코드 리뷰에서 강제):
- 단일 에이전트 멘탈 모델 — supervisor/sub-agent/tool 노드 이름을 UI 에 노출하지 않는다.
- 디자인 토큰만 — `globals.css` 밖 raw hex 금지. 아이콘은 Material Symbols 단일 셋(lucide 미사용).
- 백엔드 payload 의 snake_case 를 camelCase 로 바꾸지 않는다.
- References·다음 단계는 본문 텍스트가 아니라 전용 UI(`<next_steps>` 블록 파싱) — 채널 분리.

## 문서 위치와 갱신 규칙

| 바뀐 것 | 고칠 문서 |
|---|---|
| 아키텍처·흐름 | `backend/docs/guide/architecture.md`(정본) |
| 기능 동작·env | `backend/docs/guide/features.md` |
| API·SSE 계약 | `backend/docs/contracts/API.md`, `frontend_chat_v2.md`(프런트 계약 정본) |
| 설계 결정 | `backend/docs/spec/ADR-*.md` |
| 프런트 구현 현황 | `frontend/docs/ARCHITECTURE.md`(코드가 진실) |
| 운영·배포·장애 | `docs/OPERATIONS.md` |
| 날짜별 변경 | `docs/CHANGELOG.md` 한 곳에만 |

처음 왔다면 `backend/docs/guide/onboarding.md`. 운영진 대상 기능 설명은 `backend/docs/product/ops_feature_manual.md`.

`backend/README.md`·`frontend/README.md`·`backend/docs/guide/*.md` 일부는 모노레포 통합 전 경로를 가리킨다(`../medi-back/...`, `docs/ops/runbook.md`, `docs/PATCHNOTE.md`, `backend/CLAUDE.md` 등 — 현재 없음). 해당 내용은 `docs/OPERATIONS.md`·`docs/CHANGELOG.md` 로 흡수됐다.

## 작업 시 주의

- 비밀값은 `.env`·`.env.local`·`.env.docker`(전부 gitignore)에만. `.env.docker` 는 배포 rsync 에서도 제외되어 VM 에서만 관리한다.
- 운영 compose: `backend/docker-compose.yml`(backend :6000→8000, postgres :6001, medi-cron, medi-backup) + `frontend/docker-compose.yml`(migrator 성공 후 :3000 기동, 외부 네트워크 `medi-net` 공유).
- `STRICT_CONFIG=1` 이면 prod 필수 env 누락 시 부팅 차단. 테스트에서 lifespan 을 돌릴 땐 `NEXTAUTH_SECRET`·`ANTHROPIC_API_KEY` 를 monkeypatch 로 채운다(`tests/test_boot_config.py` 참조).
- 평가 데이터 `backend/data/eval_queries*.json`·`pii_eval_ko.jsonl` 은 `scripts/eval_retrieval.py`·`scripts/eval_pii.py`·`scripts/quality_regression.py`(야간 회귀) 입력이다.
- 프런트 목 데이터 원본은 `backend/mocks/` (프런트 `public/mocks` 와 정합 유지).
