# medi-back — 의료 규제 상담 AI 백엔드

의사·RA/QA·인허가 컨설턴트가 의료기기·의약품 규제 질문을 던지면,
법령·행정규칙·자치법규·판례·해석례를 검색해 **출처가 박힌 한국어 답변**을 돌려준다.

> 사용자 시점: 질문 → **15~20초** 스트리밍 즉답. 심층이 필요하면 보고서 생성 —
> **서빙 모델에 따라 ~5–40분**(백그라운드, 채팅과 병렬). 완료 시 사이드바 + 이메일(Word 첨부)로 도착.

**thin-client 원칙**: 무거운 것(검색 랭킹·PII NER·의도분류·보고서 writer)은 전부
DGX 서비스로 위임 — 이 서버엔 로컬 ML 없음.
**2026-07-14 컷오버(ADR-0001)**: langgraph 은퇴 — FastAPI + 자체 tool-loop.
**현재 v0.2.0** — 클로즈 베타 운영 중(GCP VM, `main` push → GHA 자동배포).

---

## 어떻게 동작하나요?

```
사용자 질문 "의료기기법 제25조 광고 사전심의 알려줘"
        │
        ▼  POST /chat (SSE)
┌────────────── FAST (~15–20s) — src/chat_loop.py ──────────────┐
│  PII 게이트(NER) ∥ 의도판정(intent)   ← DGX, 병렬              │
│      │                                                        │
│      ▼  규제 질의면 검색 강제(tool_choice=qdrant_search)        │
│  tool-loop: qdrant_search(법령DB, doc_kinds 종별 지정 가능)     │
│             tavily_search(웹) · ask_clarify                    │
│      │        └► DGX /search: KURE+BM25+RRF+fp16 리랭커        │
│      ▼                                                        │
│  답변 스트리밍([n] 인용) → grounding 검증 → <next_steps> 카드    │
└────────────────────────────────────────────────────────────────┘

        ▼  POST /reports + idempotency_key(^rpt_…) → 폴링
┌────────────── DEEP (~5–40분, 백그라운드) — src/report_runner.py ┐
│  분해(decompose) → 수집(gather, 채팅 우선 레인 양보)             │
│  → 근거 충분성 게이트 → 로컬 vLLM writer(모델 고정 아님 —        │
│     /v1/models 자동 감지) → 비평(교차 모델)→개정 → grounding     │
│  새벽 ETL 점검 구간은 pause→자동 재개.                           │
│  ★채팅과 완전 분리(2026-07-25) — 대화록에 아무것도 append 안 함.  │
│   전달은 사이드바·우측 패널 + 이메일(Word 첨부)로만.              │
└────────────────────────────────────────────────────────────────┘

thread 상태(메시지·steps·선택법령)는 threads_repo(dev SQLite / prod PG) 영속.
```

---

## 빠른 시작

### 로컬 dev (port 2024)

```bash
pip install -e .[dev]
cp .env.example .env      # ANTHROPIC·TAVILY·RAG_SEARCH_API_URL/KEY 등 채움

# ⚠️ PYTHONUTF8=1 필수 (.env 한글 주석 — 빠지면 cp949 UnicodeDecodeError)
PYTHONUTF8=1 python -c "from dotenv import load_dotenv; load_dotenv(); import uvicorn; uvicorn.run('src.api:app', port=2024)"
```

→ `http://127.0.0.1:2024/healthz` → `{"status":"ok"}`
재부팅 후 전체 기동은 [`docs/guide/startup.md`](./docs/guide/startup.md) 체크리스트.

### 운영 — docker compose (GCP VM, port 6000)

```bash
cp .env.docker.example .env.docker      # 운영 키 채움 (REQUIRED 16개 필수)
python scripts/check_config.py          # prod 필수 env 누락 점검
docker compose --env-file .env.docker up -d --build
```

상세: [`docs/ops/deployment_docker.md`](./docs/ops/deployment_docker.md) — nginx HTTPS·백업 포함.
- ⚠️ uvicorn **workers 1 고정** — 백프레셔·큐·턴락이 프로세스 로컬.
- ⚠️ `.env.docker`는 **gitignore + 배포 rsync 제외** → VM `/opt/medi-back/.env.docker`에서만 수동 관리.
- ⚠️ 새 env 노브는 `.env.docker`뿐 아니라 `docker-compose.yml`의 `environment:`에도 매핑해야
  앱에 전달된다(medi-back은 `env_file` 미사용). 예시는 손편집 말고 재생성:
  `python scripts/gen_env_docker_example.py --write` (compose+`config.ENV_REGISTRY` 단일 진실원).

---

## 문서

**인덱스: [`docs/README.md`](./docs/README.md)** — 현행 문서만(구문서는 2026-09-29 삭제, `git log -- docs/archive` 로 추적).

| 시작점 | 문서 |
|---|---|
| **처음 왔다 / 남에게 설명해야 한다** | [`docs/guide/onboarding.md`](./docs/guide/onboarding.md) |
| 아키텍처 정본 | [`docs/guide/architecture.md`](./docs/guide/architecture.md) |
| 기능 레퍼런스 | [`docs/guide/features.md`](./docs/guide/features.md) |
| API 명세 | [`docs/contracts/API.md`](./docs/contracts/API.md) · Swagger `http://127.0.0.1:2024/docs` |
| 프런트 계약(현행) | [`docs/contracts/frontend_chat_v2.md`](./docs/contracts/frontend_chat_v2.md) |
| 사고 대응 | [`docs/ops/runbook.md`](./docs/ops/runbook.md) |
| 변경 이력 | [`docs/CHANGELOG.md`](./docs/CHANGELOG.md) |

---

## 폴더 구성

```
medi-back/
├── src/
│   ├── api.py                # FastAPI app + 미들웨어 + lifespan
│   ├── chat_loop.py          # fast 엔진 — 수동 tool-loop(bind_tools+while) + 훅
│   ├── report_runner.py      # deep 잡러너 — 멱등락·pause/resume·이메일
│   ├── report_pipeline.py    # 분해→수집→27B writer + 동시성 큐
│   ├── grounding.py          # 인용 검증 (chat·report 공유)
│   ├── prompts/              # supervisor·writer 프롬프트
│   ├── tools/                # search(run_qdrant/run_tavily)·citations·reports
│   ├── guardrail/            # PII·intent 게이트 (DGX thin-client)
│   ├── retrieval/            # search_api_client(RAG) · pg/neo4j/mongo(조문·그래프 전용)
│   ├── routes/               # chat·reports·articles·admin·law_graph·privacy…
│   ├── persistence/          # users·events·feedback·reports·threads Repos (SQLite/PG)
│   ├── middleware/           # auth(JWT+루트admin)·quota·rate_limit·security_headers
│   └── observability/        # token_logger·notifications·load·alerts
├── scripts/                  # bench_chatloop·check_config·eval_retrieval 등
├── guardrail-server/         # DGX 서빙 코드·배포 (deploy.sh, 멱등)
├── tests/                    # pytest 346+
├── docs/                     # 문서 (현행만)
└── CLAUDE.md                 # AI 어시스턴트 컨텍스트
```

---

## 외부 의존 (요약)

| 무엇 | 어디 | 역할 |
|---|---|---|
| 검색 API `/search` | DGX :8080 (Tailscale) | KURE+BM25+RRF+fp16 리랭커, 5종 코퍼스(법령·행정규칙·조례·판례·해석례) |
| PII NER / 의도분류 | DGX :8090 / :8091 | 가드레일 (systemd 상시) |
| 보고서 writer | DGX :8000 (vLLM 27B) | deep 보고서 본문 생성 |
| openlaw PG/Mongo/Neo4j | GCP (ETL 소유, 읽기만) | `/article`·`/law-graph`·pinned 전용 |
| 운영 Postgres | `REPORTS_PG_DSN` | users·reports·thread 상태 (dev는 SQLite 폴백) |
| Anthropic Haiku-4-5 | API | chat·분해·grounding (Sonnet 폴백) |

전체 토폴로지: [`docs/guide/architecture.md`](./docs/guide/architecture.md).

---

## 자주 묻는 질문

**Q. `.env` 로드에서 UnicodeDecodeError**
→ `PYTHONUTF8=1` 누락. PowerShell: `$env:PYTHONUTF8="1"`.

**Q. `/readyz`에 postgres down(degraded)**
→ dev에서 운영 PG DSN 미설정이면 정상(SQLite 폴백). 채팅·RAG·조문 조회 전부 동작.

**Q. 보고서가 안 만들어집니다**
→ 트리거는 자유 텍스트가 아니라 `POST /reports` + `idempotency_key`(`^rpt_…`).
계약: [`docs/contracts/frontend_chat_v2.md`](./docs/contracts/frontend_chat_v2.md) §4. 새벽 04시대는
ETL 점검으로 일시정지 후 자동 재개(`REPORT_MAINT_WAIT_MAX_S`).

**Q. 401 / 403 / 429**
- 401: `Authorization: Bearer <jwt>` — `NEXTAUTH_SECRET` 프런트와 동일해야
- 403: 클로즈 베타 화이트리스트(`BETA_WHITELIST_EMAILS`) 밖이거나 admin 아님
  (`admin@example.com`은 env 무관 불변 admin)
- 429: 토큰 한도(quota) 또는 rate limit — `Retry-After` 참고

---

## 개발 명령어

```bash
pytest tests/ -q                          # 테스트 (346+)
python scripts/bench_chatloop.py "<질문>"  # fast 1회 벤치 (TTFT·steps·citations)
python scripts/check_config.py            # prod env 점검 (배포 전)
python scripts/build_eval_labels.py       # 검색 평가 실버 라벨 생성
python scripts/eval_retrieval.py          # recall@k·MRR (베이스라인 hit@1 0.65)
guardrail-server/deploy.sh                # DGX 가드레일 재배포 (DGX에서, 멱등)
```

---

## 측정 (2026-07 실측)

| 항목 | 값 |
|---|---|
| fast 답변 | TTFT ~17s · 총 ~26s (검색+grounding 포함) |
| deep 보고서 | 23~26분 (revise 포함, 폴링 타임아웃 70분) |
| 검색 top_k | 12 (판례·해석례 포함률 확보) + 종별 보충(doc_kinds) |
| 검색 품질 | hit@1 0.65 · MRR 0.75 (실버 라벨 베이스라인) |
| 테스트 | 346 pass (+8 skip) |

---

*개발 시작: 2026-04-27 · langgraph → FastAPI 컷오버: 2026-07-14 (ADR-0001) · 문서 정리: 2026-07-16 · **v0.2.0 릴리스: 2026-07-21** (첫 동기 태깅, 프런트·백 동시).*
