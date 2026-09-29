# medi-back 아키텍처 & 파이프라인 (종합)

시스템 전체 구조·데이터 흐름·서비스 인벤토리. 최종 갱신 2026-07-26(§0 참조). 코드 위치는 [`../CLAUDE.md`](../../CLAUDE.md), API 계약은
[`API.md`](../contracts/API.md), 운영은 [`runbook.md`](../ops/runbook.md).

**설계 원칙 — thin-client**: medi-back 은 **오케스트레이션 + 인용/grounding + 채널
분리** 레이어. 무거운 것(검색 랭킹·PII NER·의도 분류·보고서 생성)은 전부 **DGX
서비스**로, 데이터(法令 DB)는 **GCP**로 밀어냈다. medi-back 코드베이스엔 로컬 ML 없음.

- **fast** (`POST /chat` SSE, ~십수 초): 즉답. 가드레일(PII·의도) → 검색강제 → Haiku
  답변. 엔진: `src/chat_loop.py` 수동 tool-loop(bind_tools + while).
- **deep** (`POST /reports` + 폴링, 백그라운드 — 소요시간은 서빙 모델 의존 ~5–40분):
  채팅 맥락 상속 → 수집 → 로컬 vLLM writer(**모델 고정 아님**, `/v1/models` 자동
  감지) → 컨설팅형 5섹션 보고서. 엔진: `src/report_runner.py` asyncio 잡.
  **채팅과 완전 분리·병렬**(2026-07-25) — 대화록에 보고서 흔적이 남지 않는다.

> **✅ 컷오버 완료 (2026-07-14, ADR-0001 Phase 5)** — langgraph·deepagents·
> langchain(메타) **은퇴**. LLM 스택은 langchain-core + langchain-anthropic 만.
> 서버는 uvicorn `src.api:app` 단일(FastAPI) — `langgraph dev`·`.langgraph_api`·
> checkpointer·`langgraph.json` 삭제. thread 영속은
> `src/persistence/threads_repo.py`(dev SQLite / prod 운영 PG).
> 결정·검증 로그: [`spec/ADR-0001-migration-plan.md`](../spec/ADR-0001-migration-plan.md),
> 현행 FE 계약: [`frontend_chat_v2.md`](../contracts/frontend_chat_v2.md).

---


## 0. 최근 변경 반영

이 문서의 각 절에 아래 변경이 전제된다. 상세는 [`CHANGELOG.md`](../CHANGELOG.md).

### 2026-07-25~26

- **채팅↔보고서 완전 분리·병렬**: 완료 개요를 채팅에 append 하지 않고(구
  `kind:"report_overview"` 계약 폐지), 진행 step 을 채팅 턴에 바인딩하지 않으며,
  채팅 프롬프트에 보고서 컨텍스트를 주입하지 않는다. 개요 append 를 위해 잡던
  per-thread 턴 락이 사라져 **실제로 병렬**. 계약: `frontend_chat_v2.md` §4.
- **보고서 근거 충분성 게이트**: `REPORT_MIN_CITATIONS`(6) 미달 시 1회 재수집 →
  그래도 미달이면 run 실패(얇은 보고서를 완성품으로 배달하지 않음).
- **웹 레인 프리페치**: tavily 를 턴 시작과 동시에 병렬 실행해 LLM 왕복 1회 제거.
  실패 시 그 턴 웹 스킵(폴백 재시도 없음 — 어차피 또 실패).
- **검색 응답 무결성 가드**: 200+비정상(비-list / `article_key` 없는 항목) 차단,
  불량 섞인 응답은 캐시 금지. ETL 측 원인(혼합 target_types dict 응답)은 수정 완료.
- **writer 모델은 고정 아님**: `/v1/models` 자동 감지. 소요시간도 모델 의존(5~40분).
- **답변 포맷**: 병렬 구조 정보는 표 우선(supervisor v17 · writer rp_v8), 분야 혼합
  근거는 공통 원칙 + 분야별 비교표로 분리 서술.
- **정체성·시각**: 서비스명 MEDIREG AI · `[현재 시각]`(KST) 주입.
- **알림 배관 수정**: SMTP 465 암묵 TLS 판정 + `EMAIL_FROM` 발신자 —
  보고서 완료 메일이 **전혀 발송되지 않던 상태**를 고침(실발송 검증).

### 2026-07-15~16

**Fast 파이프라인(§2)**:
- 입력 게이트(PII 스크럽 ‖ 의도판정) **병렬화**(asyncio.gather) + 시스템 프리픽스 prompt caching.
- **웹 강제 게이트**: qdrant 강제 회차 뒤 tavily 1회 강제(`CHAT_FORCE_WEB=1`) — 웹 인용 확보를 모델 재량에서 분리.
- **done-before-grounding**: 텍스트 완료 즉시 `done` emit → grounding 은 done *후* trailing steps 로 verified 갱신(체감 랙 제거). FE 는 done 에서 턴 settle.
- **LLM A/B 하네스**: `CHAT_MODEL_AB="a|b"` — user 해시 안정 배정 + events(model_ab) 태깅.
- 답변 `style`("expert"/"simple") — 시스템 프롬프트 가변부 분기.

**검색(§3)**:
- openlaw-etl dense arm 의 `chunk_type="article"` 하드필터 제거 → **별표/서식(attachment)** 이 의미검색에 포함(+snippet 1200자). 판례(prec)·해석례(expc)는 기본 target_types.
- **개정상태 체인**: law.go.kr(lawdangle-kr) → ETL 배치 enrich(`law_amendment_status`) → `/search` payload `amend_status` → citation.status(폐지→revoked·개명→amended_pending). 나이틀리 롤링 sweep(~6일 풀커버).

**Deep 보고서(§5)**:
- writer 후 **critique(교차 모델, 기본 haiku·`REPORT_CRITIQUE_MODEL`)→revise** 패스
  (`REPORT_REVISE_ENABLE=1`) + **결정적 선행 검사**(초안 grounding 선검증·(법령명, 조번호)
  페어 대조 → 개정 지적 주입) + **발행 직전 게이트**(깨진 마커 정리·무인용 수치 로깅·작성
  기준일 stamp) + 수집 `REPORT_QDRANT_TOP_K=20` · **source tier**(rag=T1·web=T3, 웹 언급
  조문 T1 승격 `REPORT_TIER_UPGRADE_MAX=3`). 설계 근거: `reference/재설계보고서_반영기록.md`.
- **gather 원자성**: 데드라인 초과 시 완료 소스 보존(미완만 cancel — 구현은 asyncio.wait).
- 목적 템플릿 `purpose`(license_strategy/reg_summary/change_response) → writer 지시 분기.

**영속(§9)**:
- **인증 DB**: medi-front Prisma 가 SQLite → **Postgres `medi_auth`**(medi-postgres 동일 인스턴스, medi-backup 이 함께 pg_dump). 컷오버 런북: medi-front `docs/auth_db_postgres_migration.md`.
- `chat_threads.pinned`(대화 고정) · `bookmarks`(개인 근거 라이브러리: citation JSONB·folder·UNIQUE user+citation) 테이블 추가.
- users upsert email-유니크 충돌 시 id 정렬(front/back id 불일치 흡수).

**신규 API**: `/chat/search`(본문 검색) · `/chat/{tid}/pin` · `/bookmarks*`(+`/amendments`) · `/answers/export`(docx). → [`API.md`](../contracts/API.md) 부록.

## 1. 시스템 토폴로지 — "무엇이 어디서 도나"

```
┌──────────────────────────────────────────────────────────────────────────┐
│  medi-front (Next.js · medi-back 과 **같은 GCP VM** docker compose)        │
│    NextAuth 로그인 / JWT 발급 · 인증 DB = 같은 PG 인스턴스의 medi_auth      │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │  JWT (NEXTAUTH_SECRET 공유)
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  medi-back (FastAPI · uvicorn --workers 1 단일 프로세스 · thin-client)     │
│   HTTP 미들웨어: CORS→Auth(JWT)→RateLimit→Quota→SecurityHeaders             │
│   채팅 루프 훅(chat_loop): PII게이트→의도검색강제→Steps→Grounding→압축      │
│   경로: POST /chat(fast) · POST /reports(deep)  라우트: /article /law-graph…│
└───┬────────────────────────────┬─────────────────────────────┬────────────┘
    │ 소유 스토어(RW)            │ AI 서빙 = DGX(Tailscale)     │ DB = GCP(공인IP)
    ▼                            ▼ 192.0.2.10                 ▼ 192.0.2.20
 ┌──────────────────┐   ┌──────────────────────────┐   ┌──────────────────────┐
 │ 운영 Postgres    │   │ :8080 검색 API           │   │ PG   :5401 조문메타·전문│
 │  users·events·   │   │   KURE+BM25+RRF+리랭커   │   │ Mongo:5402 본문        │
 │  feedback·reports│   │ :8090 PII NER(KoELECTRA) │   │ Neo4j:5403 인용그래프  │
 │  +thread상태(chat)  │ │ :8091 의도분류(Qwen0.8B) │   │ (Qdrant:5405 — 검색API │
 │ Blob(GCS/로컬).md │   │ :8000 보고서 writer vLLM │   │   내부용, medi-back 직접X)│
 └──────────────────┘   │ :8001 KURE 임베딩(vLLM)  │   └──────────────────────┘
                        └──────────────────────────┘
   외부: Anthropic Claude (Haiku=chat·보조 / Sonnet=폴백) · Tavily 웹
```

**Postgres 두 개(혼동 주의)**
- **openlaw PG**(`PG_*`, GCP 192.0.2.20:5401): 法令 조문 메타·전문. ETL 소유,
  medi-back 읽기만. **RAG 검색엔 직접 안 씀**(검색 API 경유) — `/article`·pinned 만.
- **운영 PG**(`REPORTS_PG_DSN`): 앱데이터 + chat thread 상태(`threads_repo`). medi-back 소유.

---

## 2. Fast 채팅 파이프라인 (~십수 초)

엔진 = `src/chat_loop.py` — 수동 tool-loop(`bind_tools` + while) + 훅. 진입은
`POST /chat`(SSE), 같은 thread 동시 요청은 턴 락으로 직렬화.

```
사용자 질문 (POST /chat)
   │
   ▼ [HTTP 미들웨어] Auth→RateLimit→Quota
   │
   ▼ ① PII 게이트 (2중)  ── regex(주민번호·전화·카드…) + DGX NER(:8090, 이름·주소)
   │     ★egress: 모델엔 스크럽본만(Anthropic·Tavily 원문 유출 차단, 모델 호출 직전 훅)
   │     ★at-rest: human 원문을 스크럽본으로 교체 → threads_repo 저장분 원문 PII 제거
   │
   ▼ ② 의도 검색강제  ── should_search(질문, 직전맥락)
   │     • 인사말("고마워")·물음없는 재촉("대답해"·"빨리") → 스킵
   │     • 규제 → forced 바인딩(tool_choice=qdrant_search)
   │       판정: 인사/재촉 휴리스틱(_OFFTOPIC·_NO_QUESTION) + Qwen0.8B 분류기(:8091, 맥락)
   │       응답 라우팅은 supervisor v7 taxonomy(A인사/B범위밖/C재촉·날조금지/D규제)
   │
   ▼ ③ supervisor (Haiku-4-5)  ── 강제된 검색을 수행(쿼리는 맥락 반영해 작성)
   │     tools: qdrant_search · tavily_search · ask_clarify
   │     채널: <next_steps> 마커(추천질문) · 보고서는 POST /reports 별도 트리거
   │     └► qdrant_search ─► [RAG §3] ─► citations[] (번호 [n])
   │
   ▼ ④ 답변 스트리밍 (SSE token 이벤트, [n] 마커) + References(시스템 자동 부착)
   │
   ▼ ⑤ grounding gate  ── 답변의 [n] ─ 원문 대조(haiku + /articles/bodies) ─► verified✓/✗
   │
   ▼ threads_repo 저장 (사용자별 격리·영속 — dev SQLite / prod 운영 PG)
```

> **왜 검색을 강제하나**: 답변 모델이 "검색할지" 판단하면 소형·고속 모델(Haiku)이
> 캐주얼·후속 어투에서 검색을 건너뛰고 인용을 날조(환각)한다. 근거 확보를 모델
> 선택에서 분리 → 빠른 모델도 근거 보장. 역사: CHANGELOG + `git log -- docs/archive`(2026-09-29 삭제).

---

## 3. RAG 검색 내부 (`qdrant_search` → thin-client)

```
질의 텍스트
   │
   ▼  run_qdrant → search_api_client.search_articles
   │
   ▼  POST DGX :8080 /search   { query, top_k, target_types }
   │     target_types: 기본 5종(law·admrul·ordin·prec·expc) — LLM 이 doc_kinds 로
   │     종별 지정 시 그 종별만, 질의에 판례/조례 단서 있으면 자동 보충(2026-07-16)
   │     서버가 전부 처리: dense(KURE) + BM25 + RRF + cross-encoder 리랭커
   │                        + 법률종 부스팅 + 조문 GROUP BY            [캐시 TTL 1h]
   │  ← 랭킹된 조문 + 메타(제목·부처·시행일·정본URL·별표링크·시행상태)
   │
   ▼  build_citation_from_api_hit → citations[] (Citation)
   │
   └─ selected_law_keys 있으면? → run_qdrant_pinned (선택 조문만, PG 직접) [§4]
```

> 로컬 임베딩·Qdrant·리랭커 스택은 **없음**(2026-07 thin-client 전환). 원문(grounding·
> 보고서)은 필요할 때만 `POST /articles/bodies`. 계약: [`search_api_citation_enrichment.md`](../etl_requests/search_api_citation_enrichment.md).

---

## 4. 법률 네트워크 선택 → pinned grounding (요구사항 ④)

```
채팅 인용(article_key[]) → GET /law-graph?keys=…  ─► Neo4j(:5403) 인용 서브그래프
   │  [전문가 화면] 네트워크+원문, 노드클릭→/article, 더블클릭→hop 확장
   ▼  선택/해제 → selected_law_keys (state, 영속)
   ▼  다음 턴 → run_qdrant_pinned: 벡터검색 대신 "이 법으로만" grounding(replace, PG 직접)
```
> pinned·`/article`·`/law-graph` 는 openlaw PG/Neo4j 직접 조회(RAG 경로 아님). Neo4j
> 6자리 ↔ PG 7자리 키는 prefix 매칭(`resolve_article_keys`).

---

## 5. Deep 보고서 파이프라인 (~5–10분, 백그라운드)

```
POST /reports {thread_id, idempotency_key(rpt_…)}   ← 프런트 트리거 (202 수락)
   │  ★게이트: 인증(uid) + thread 소유권(불일치 404) + report_runs 멱등락 + 큐 용량(429)
   ▼
report_runner (asyncio 잡)  ── thread 맥락 상속: threads_repo 에서 질문·fast답변·인용 읽음
   ├─ decompose (haiku)  ── ≤5 서브쿼리 (질문+fast답변 반영)
   ├─ gather (병렬)      ── RAG(/search)×N + Web(Tavily)×N  + selected_law_keys grounding
   │                        └ 근거 충분성 게이트: REPORT_MIN_CITATIONS(기본 6) 미달이면
   │                          1회 재수집 → 그래도 미달이면 **run 실패**(얇은 보고서 배달 금지)
   ▼
synthesize_and_persist  ── writer = 로컬 vLLM (DGX :8000, **모델 고정 아님** —
   │                        REPORT_WRITER_MODEL 미설정 시 /v1/models 자동 감지)
   │   깊이 우선 프롬프트 → 5섹션(개요·핵심결론·근거·실무액션·리스크/후속) ~18KB
   ├─ 선행 검사(haiku grounding + 산문 조문번호 대조) → critique(교차 모델)→revise
   ▼  발행 게이트(마커 정리·무인용 수치 로깅·기준일 stamp) → grounding(haiku) 인용검증
      → 저장: Blob(.md) + 운영 PG(reports 메타)
   ▼  완료: reports 레코드(summary=`## 개요`) + 이메일 DOCX 첨부
      **채팅에는 아무것도 append 하지 않는다**(2026-07-25 분리 — 구 계약은
      `kind:"report_overview"` AI 메시지를 붙였고, 그 append 순서 보존을 위해
      per-thread 턴 락을 잡아 보고서가 채팅을 기다렸다. 지금은 결합 없음).
      진행/완료는 GET /reports/runs/{idempotency_key} 폴링 → FE 토스트·브라우저
      알림·사이드바. 진행 step(report_*)은 채팅 턴에 바인딩되지 않는다.
```
> deep 는 fast 의 확장 — [n] 인용 번호 유지, 모순 시 '보완·정정' 섹션. 채팅 맥락
> 상속은 같은 thread 의 threads_repo 상태에서 읽음(실서버 검증됨). 트리거 계약:
> [`frontend_chat_v2.md`](../contracts/frontend_chat_v2.md) §4 (~~assistant_id="agent_report" 디스패치~~ 는 2026-07-14 은퇴).

---

## 6. 서비스 인벤토리

| 서비스 | 위치 | 역할 | 상시화 |
|---|---|---|---|
| 검색 API `/search`·`/articles/bodies` | DGX 8080 | RAG 랭킹·인용·grounding 원문 | systemd (openlaw-etl) |
| PII NER (KoELECTRA modu-ner) | DGX 8090 | 이름·주소 2차 마스킹 | systemd `guardrail-ner` |
| 의도 분류 (Qwen3.5-0.8B) | DGX 8091 | 검색 필요 판정(이진+맥락) | systemd `guardrail-intent` |
| 보고서 writer (vLLM — **모델 고정 아님**, /v1/models 자동 감지) | DGX 8000 | deep 보고서 writer | docker |
| KURE 임베딩 (vLLM) | DGX 8001 | 검색 API 내부용 | docker |
| PG·Mongo·Neo4j | GCP 5401/2/3 | 조문·본문·인용그래프 | GCP |
| Claude Haiku / Sonnet | Anthropic | chat·보조 / 폴백 | SaaS |

**게이트 모델 서빙**: NER=transformers(토큰분류, vLLM 불가) · 의도=transformers 별도
프로세스(부하 격리, 스케일 시 vLLM+guided_choice). 두 서비스 다 systemd 상시(부팅·크래시
자동복구), **재현 배포 `guardrail-server/deploy.sh`**(핀 의존·모델 사전다운로드·헬스체크).
writer/임베딩만 vLLM/docker. 코드·배포: [`../guardrail-server/`](../../guardrail-server/) · 계약:
[`guardrail_ner_service.md`](../contracts/guardrail_ner_service.md) · [`guardrail_intent_service.md`](../contracts/guardrail_intent_service.md).

> **왜 transformers 서비스는 상시인가**: 모델 로드가 수 초~수십 초인데 지연 예산은
> 50~165ms — 요청마다 로드는 불가. GPU 상주(NER ~3GB · 의도 ~3.2GB, GB10 128GB 통합
> 메모리라 무시할 수준). **죽어도 서비스는 안 멈춤**: NER 다운→regex-only, 의도 다운→
> 인사·재촉 휴리스틱 폴백(규제면 검색강제=안전 기본값).

---

## 6-b. 구성요소 상세

### 모델 (역할별)

| 역할 | 모델 | 실행 위치 | 비고 |
|---|---|---|---|
| chat supervisor | `claude-haiku-4-5` | Anthropic API | 폴백 `openai:gpt-5.4` |
| 보조(질의분해·요약·grounding 검증) | `claude-haiku-4-5` | Anthropic API | 폴백 `gpt-5.4-mini` |
| 보고서 writer | **고정 아님** — 그때 서빙 중인 모델을 `/v1/models` 로 자동 감지(Qwen3.5-27B·gemma-4-31B-w4a16 등 교체 실험). 소요시간도 모델 의존(5~40분) | DGX vLLM :8000 | 백그라운드·비용 0. `REPORT_WRITER_MODEL` 명시 시 고정 |
| 보고서 비평(검수) | `claude-haiku-4-5` (기본) | Anthropic API | 교차 모델 감사 — `REPORT_CRITIQUE_MODEL`(self=writer 자기검수) |
| PII NER | `Leo97/KoELECTRA-small-v3-modu-ner` (2026-08-14 OpenMed 에서 교체 — 한국어 오탐 6/10→0/10) | DGX transformers :8090 | 토큰분류(vLLM 불가) |
| 의도 분류 | `Qwen/Qwen3.5-0.8B` | DGX transformers :8091 | 이진+맥락 few-shot |
| 임베딩(dense) | `KURE` | DGX vLLM :8001 | **검색 API 내부** — medi-back 모름 |
| 리랭커 | `BAAI/bge-reranker-v2-m3` (fp16·512) | DGX 검색서버 | **검색 API 내부**. `engine.py` 에 **하드코딩**(dtype 만 env `RERANKER_DTYPE`) — 교체하려면 ETL 코드 수정 + **평가셋 재측정 필수** |

> medi-back 이 **직접 호출하는 건 Anthropic 2종 + DGX 3종**(검색API·NER·의도).
> 임베딩·리랭커는 검색 API 뒤에 감춰져 있다(thin-client).

### 데이터 저장소 (소유권 2갈래)

| 저장소 | 내용 | 소유 | medi-back |
|---|---|---|---|
| openlaw **PostgreSQL** | 조문 메타·전문 | ETL | 읽기 — `/article`·pinned 만 |
| **MongoDB** | 본문 보강 | ETL | 읽기 — `/article` 보조 |
| **Neo4j** | 법령 인용 그래프 | ETL | 읽기 — `/law-graph` |
| **Qdrant** (`articles_kure_v1`) | 벡터 | ETL | ❌ **직접 접속 안 함**(검색 API 뒤) |
| 운영 **PostgreSQL** | users·events·feedback·reports·report_runs + **chat thread 상태(threads_repo)** | medi-back | 읽기쓰기 (dev=SQLite 폴백) |
| **Blob** | 보고서 `.md` 원본 | medi-back | 읽기쓰기 |

**Blob 경로**: dev `./reports_blobs/{thread_id}/{report_id}.md`(`BLOB_BACKEND=local`) ·
prod `gs://{bucket}/{thread_id}/{report_id}.md`(`gcs`).
> blob 보존정리: `scripts/prune_blobs.py`(기본 DRY_RUN, `PRUNE_APPLY=1` 실삭제 — cron).
> thread 상태는 threads_repo 정규 테이블이라 체크포인트식 무한 누적 문제 없음.

### 기능 → 구현

| 기능 | 구현 |
|---|---|
| 대화 오케스트레이션 | `src/chat_loop.py` 수동 tool-loop(`bind_tools` + while) + threads_repo 영속 (~~LangGraph+deepagents~~ 2026-07-14 은퇴) |
| 훅(구 그래프 미들웨어) | chat_loop 내장 훅 — PII·의도검색강제·grounding·이력 압축·턴 락 |
| PII 마스킹 | regex(`guardrail/pii.py`) + NER HTTP → chat_loop PII 훅(egress+at-rest) |
| 검색 강제 | `chat_loop._should_force_search` → forced 바인딩(`tool_choice="qdrant_search"`) |
| 의도 판정 | 인사·재촉 휴리스틱 + Qwen0.8B HTTP 분류기 |
| RAG 검색 | `httpx` → `/search` REST + `TTLCache` + `threading.BoundedSemaphore`(백프레셔) |
| 인용/grounding | `grounding.py` — `[n]` 을 `/articles/bodies` 원문과 haiku 로 대조 |
| 보고서 | `report_runner.py`(잡·멱등락) + `report_pipeline.py` — 분해→병렬수집(RAG+Tavily)→writer `astream` + `asyncio.Semaphore`(큐) |
| 보고서 DOCX | `reports_convert.py` — pandoc(`pypandoc-binary`), `.md` 원본 유지·요청 시 변환 |
| 이메일 | stdlib `smtplib`+`EmailMessage`(첨부) — SMTP 공급자 무관 |
| API | FastAPI 단일(uvicorn) — `/chat`(SSE)·`/reports`·조회 REST (~~langgraph 네이티브 `/threads`·`/runs`~~ 은퇴) |
| 인증 | JWT(NextAuth 시크릿 공유) — `AuthMiddleware` 단일 + `BETA_WHITELIST_EMAILS` 게이트. thread 소유권은 서버 검사(불일치 404) |
| 부하 표시 | `observability/load.py` 카운터 → `GET /load` |
| 관측 | `/readyz` 프로브 · ops webhook 알림 · 토큰 로거(자체) |
| 평가 | `eval/metrics.py`(recall@k·MRR) + LLM-judge 실버 라벨 파이프라인 |
| 스키마 | pydantic (`Citation`·`Step`) |

---

## 7. 소유권 경계

- **medi-back 소유**: 대화 오케스트레이션(chat_loop·report_runner·훅), 인용/grounding,
  채널 분리, 운영 데이터(users·reports·thread 상태).
- **DGX 위임**: 검색 랭킹, PII NER, 의도 분류, 보고서 생성(모델). HTTP 계약만 앎.
- **GCP(ETL 소유) 위임**: 法令 DB(PG·Mongo·Neo4j·Qdrant). RAG 는 검색 API 경유,
  `/article`·`/law-graph`·pinned 만 PG/Neo4j 직접(읽기).
- **Anthropic**: chat supervisor(Haiku) + 보조(haiku: 분해·grounding·요약).

---

## 8. 동시성·부하 (한 자릿수 동시 사용자)

단일 DGX GPU 가 검색 리랭커·게이트·writer 를 공유 → 동시 요청 시 thrash. 검색 단건은
리랭커 fp16 최적화(openlaw-etl `7f6be70`)로 2.84s→**0.79s**(품질 동일). writer 바쁠 땐
공유 GPU 경합으로 순간 스파이크(~3.4s). 대응(medi-back 인프로세스):

```
검색:  threading.BoundedSemaphore(SEARCH_MAX_CONCURRENCY=2)  ── 동시 /search 상한(thrash↓)
보고서: asyncio.Semaphore(REPORT_MAX_CONCURRENCY=1)          ── writer 동시 실행 제한(채팅 우선)
표시:  src/observability/load.py → GET /load                ── '원활/혼잡' + 인라인 "혼잡" 안내
```

- 검색은 동기 툴(스레드풀) → threading 세마포어(캐시 히트는 슬롯 미점유). 보고서는
  별도 thread async → asyncio 세마포어. 둘 다 초과분 대기 + 진행 이벤트로 사용자 안내.
- `GET /load`(인증 X): `{status:ok|busy, search:{active,waiting,limit}, reports:{active}}`.
  프런트 폴링 배지 + 혼잡 시 검색 도구가 "서버 혼잡 · 느릴 수 있어요" emit → **느려도 이해**.
- 배칭·GPU 증설은 보류(한 자릿수엔 오버). 리랭커 배칭은 openlaw-etl 과제.

## 9. 인증 & 영속 (정석 운영)

- **인증 단일 계층**: FastAPI `AuthMiddleware`(NextAuth JWT, `NEXTAUTH_SECRET`
  medi-front 공유) + `BETA_WHITELIST_EMAILS` 클로즈베타 게이트. thread 소유권은
  서버가 검사(불일치 404 — 존재 비노출). dev(secret 미설정)=dev identity.
  (~~langgraph `@auth.on.threads` 2계층~~ 은 2026-07-14 은퇴.)
- **대화 영속**: `threads_repo`(chat_threads·chat_messages·chat_steps) — dev SQLite
  `./medi_reports.db`, prod 운영 PG(`REPORTS_PG_DSN`) → 재시작·세션 보존.
  (~~`CHECKPOINT_BACKEND`·`medi_langgraph_state` 볼륨~~ 은퇴.)
- **부팅 검증**: lifespan 이 prod 필수 env 점검(`STRICT_CONFIG=1` fail-fast).
- **관측**: `/readyz`(PG·검색API·Neo4j probe, critical 다운 503) + ops 알림 webhook.

배포: medi-back·medi-front **같은 GCP VM 의 docker compose**(공유 `medi-net`, `main`
push → GHA self-hosted runner 자동배포). 프런트 인증 DB(`medi_auth`)는 같은 PG 인스턴스
안 별도 DB 로, medi-backup 이 함께 pg_dump. DGX 서빙·GCP DB 도달
필요(Tailscale/공인IP). 배포 전: `.env.docker` 에 `RAG_SEARCH_*`·`PII_NER_*`·`INTENT_*`·
`REPORT_WRITER_*`·`LLM_MODEL=haiku` 필요.
