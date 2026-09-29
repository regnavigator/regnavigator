# ADR-0001 실행 계획 — langgraph·deepagents 탈피 마이그레이션

- **상태**: 계획 확정(2026-07-13) — Phase 0 착수 대기
- **상위 결정**: [`ADR-0001-fastapi-migration.md`](./ADR-0001-fastapi-migration.md) (Proposed, 2026-06-18)
- **선행 조사**: 2026-07-13 결합도 전수조사 (본 문서 §1·§2 는 그 결과 반영)

---

## 1. 목표 의존 상태 (ADR §2 정정 포함)

| 패키지 | 현재 | 목표 | 비고 |
|---|---|---|---|
| `langgraph`, `langgraph-cli[inmem]`, `langgraph-sdk`, `langgraph-checkpoint-*` | 코어 | **제거** | 서버·체크포인터·interrupt 전부 자체 대체 |
| `deepagents` | 코어 | **제거** | 수동 tool-loop 로 대체 |
| `langchain` (메타) | 코어 | **제거** ← ADR §2 정정 | **langchain 1.x 가 `Requires: langgraph`** — 메타를 남기면 venv 에서 langgraph 가 안 빠짐. `init_chat_model`→직접 생성, `AgentMiddleware`→자체 훅으로 |
| `langchain-core` | 전이 | **유지(직접 의존 승격)** | messages·bind_tools·BaseCallbackHandler·InMemoryRateLimiter. langgraph 미요구(확인됨) |
| `langchain-anthropic` | 전이 | **유지(직접 의존 승격)** | `ChatAnthropic` 직접 생성 (init_chat_model 폐기) |
| `langchain-openai` | 코어 | **extras 격리** (`[writer-vllm]`) | 직접 import 2곳뿐: `src/models.py:52`(REPORT_WRITER_BASE_URL 게이트) + `scripts/ingest.py` |

## 2. 사전 확정 사항 (ADR §8 미결 → 결정)

- **LLM 루프**: `langchain-core` `bind_tools` + 수동 while 루프 (ADR §10.4 권고 유지). raw Anthropic SDK 는 후순위.
- **잡 러너**: asyncio task + `report_runs_repo` 멱등락 재사용 (단일 프로세스 — CLAUDE.md §10 멀티워커 금지와 정합).
- **thread 상태**: 자체 테이블 (`langgraph-checkpoint` 재사용안 폐기 — 의존 제거 목표와 모순). `src/persistence/` dual(SQLite/PG) 패턴으로 `threads_repo` 신설: messages(직렬화 dict)·steps·selected_law_keys·turn 컨텍스트.
- **FE 계약**: **자체 `/chat` SSE 프로토콜 + medi-front 어댑터 전환** (langgraph native `/threads`·`/runs/stream` 호환층 재현안 폐기). 근거: FE 가 native 프로토콜을 쓰는 유일한 이유가 `@langchain/langgraph-sdk` 클라이언트라서, 호환층은 사라질 SDK 를 위해 서버를 흉내내는 낭비. **이벤트 페이로드 스키마는 무변경 재사용** (`tool_progress`/`step_lifecycle`/steps dict/citation 번호 규칙 — ADR §10.2) → FE 수정은 전송층(SDK 호출→fetch+SSE 파서)에 국소화.
- **clarify HITL**: `interrupt()` 폐기 → **턴 종료 재해석**. clarify tool_call 발생 시 `clarify` SSE 이벤트 후 턴 종료, 사용자 답변은 다음 `/chat` 요청 메시지. `/resume` 엔드포인트 불요 (ADR §10.1 "중" → "하"로 하향).
- **대화 압축**: deepagents 내장 `SummarizationMiddleware` 는 암묵 의존이었음 — 자체 구현 필요(토큰 임계 초과 시 선두 구간 Haiku 요약). **신규 작성 항목**.

## 3. 단계별 계획

### Phase 0 — 사전 정리 (무위험, 즉시) ✅ 완료(2026-07-13)
- orphan 삭제: `src/subagents/*` 4파일 + `src/models.py` 의 `subagent_model_or_none`/`subagent_model_spec`(전용 소비자). `SUBAGENT_MODEL` env 는 grounding·분해·auto_title 노브로 유지.
- ~~`src/middleware/deep_context.py` 삭제~~ → **Phase 3 로 연기**: 순수 orphan 아님 — `report_pipeline.py:238` 이 `_loopback_base` lazy import + 단위테스트 존재. 부모 맥락 상속을 threads_repo 직조회로 바꿀 때 함께 제거.
- `langchain-openai` → base 제거, `[writer-vllm]` extras 신설 + prod extras 포함(운영 27B writer 활성이므로 Dockerfile `.[prod]` 무변경 동작). `report_writer_model()` 에 미설치 시 액션 가능한 ImportError 가드.
- 검증: 383 passed (기존 순서오염 2건 제외 — 격리 통과 + 무변경 트리 동일 실패 확인).

### Phase 1 — `/chat` SSE PoC 병행 구축 (기존 langgraph 무접촉) ✅ 완료(2026-07-13)
- **`src/chat_loop.py`** 신설(계획명 agent_loop → 실명 chat_loop): `ChatAnthropic` 직접 생성(init_chat_model 미사용) + `bind_tools`(dict 스펙) + 수동 while 루프. normal/forced 2종 바인딩 — intent 판정 시 forced(`tool_choice=qdrant_search`) 선택으로 **검색 강제 불변식(CLAUDE.md §8) 유지**.
- 도구 코어: **추출 불필요였음** — `run_tavily`/`run_qdrant`/`run_qdrant_pinned` 코어가 이미 분리돼 있어 재사용. 새 루프용 래퍼(`_tool_*`)만 작성(Command → `(ToolMessage, steps, clarify)`).
- 미들웨어 8종 → 훅 이식 완료(파일 docstring 에 이식 맵). TokenUsageLogger 콜백·전역 rate limiter 는 **그대로 공유**(구·신 경로 합산 캡 유지).
- progress emit: `search_progress.py` 를 **sink 추상화**(contextvar) — 새 루프가 sink 설치, 미설치 시 langgraph writer 폴백. 도구 코어 무수정으로 양 경로 이벤트 흐름.
- `src/persistence/threads_repo.py`: SQLite 구현(+merge_steps_by_id 의미론 upsert). **PG 구현 완료**(2026-07-13 후속): `PostgresThreadsRepo` + `_pg.init_schema` DDL(chat_threads/messages/steps). 통합 테스트는 `MEDI_TEST_PG_DSN` gated(`tests/test_pg_repos.py`) — 로컬 docker 부재로 실 PG 검증은 운영 VM/CI 에서 필요.
- `POST /chat`(`src/routes/chat.py`) SSE — 이벤트 meta/token/tool_progress/step_lifecycle/steps/clarify/error/done. 페이로드는 기존 스키마 그대로. QuotaMiddleware 검사 경로에 `/chat` 추가.
- clarify = 턴 종료 재해석 구현(§2 결정대로) — tool_result 짝 유지로 히스토리 유효.
- **검증**: 단위 6종(가짜 모델 주입) + 전체 389 passed. e2e — `scripts/bench_chatloop.py` vs `bench_run.py` 같은 질문(SaMD 임상): 검색 1회·인용 8건·grounding 검증·`<next_steps>` 동등, wall 20.9s vs 22.0s(웜). HTTP 레이어는 uvicorn 단독 기동 + 실 POST 로 SSE 프레이밍 확인.
- 잔여(Phase 2 로): 대화 압축(Summarization 대체) — 긴 thread 는 아직 무압축.

### Phase 2 — 스트림 계약 완성 + 대화 압축 ✅ 완료(2026-07-13)
- citation 번호 규칙·`<next_steps>` 마커: **Phase 1 에서 이미 충족 확인**(기존 헬퍼 재사용 + e2e 실측). `report_writer_internal` 태그 제외는 보고서 스트림 소관 → Phase 3.
- 대화 압축 구현(`chat_loop._maybe_compact`): 추정 토큰 임계(`CHAT_SUMMARY_TRIGGER_TOKENS`, 기본 24k) 초과 시 오래된 턴을 저비용 모델(haiku) 요약으로 대체. **human 경계 컷**(tool 짝 보존·Anthropic 히스토리 규칙 안전), 최근 `CHAT_SUMMARY_KEEP_TURNS`(기본 2) 턴 원문 유지, 요약·컷 지점 thread 영속(`threads_repo.set_summary`), **DB 원본 메시지 보존**(working set 만 압축). 실패 시 무압축 진행.
- 신규 env 6종 `config.py:ENV_REGISTRY` "chatloop" 그룹 등록 + `.env.example` 반영.
- 검증: 압축 단위 테스트(요약 영속·컷 경계·원본 보존) 포함 7종 + 전체 390 passed.

### Phase 3 — 보고서 잡러너 이전 ✅ 완료(2026-07-13, 신경로 PoC)
- **`src/report_runner.py`** 신설: `agent_report` 3노드(entry_check→decompose→gather→synthesize)를 async 함수 체인으로 이식. entry_check 는 라우트로 이동(HTTP 시맨틱: 202 accepted / 200 completed·running / 409 failed / 422). `Command(goto)` → return.
- 트리거: **`POST /reports`** + `report_runs_repo` 멱등락(라우트에서 acquire) + asyncio task. 상태 폴링 **`GET /reports/runs/{idem}`**(소유자 검사). 쿼터 검사 method-aware(`POST /reports` 만).
- parent 맥락 상속: loopback HTTP → **threads_repo 직조회**(자체 /chat 대화 전제). 진행 steps 도 threads_repo 에 merge(라이브 SSE 구독은 Phase 4 FE 계약에서).
- `_persist_report` 에 `ctx=` 명시 config 인자 추가(ensure_config 의존 해소, langgraph 노드 경로 동작 불변). `src/middleware/deep_context.py`+테스트 삭제(연기분) — `report_pipeline` lazy import 는 `auto_title._loopback_base` 로 교체.
- 재사용: decompose/gather/synthesize 코어·writer 세마포어·grounding·이메일(`notify_report_ready`, app.py 사본은 Phase 5 에 일원화).
- **검증**: 단위 4종(성공/수집빈손/writer크래시→락 마감/쿼터경로) + 390 passed. **e2e 실측**(uvicorn + 실 DGX 27B writer): POST 202 → decompose 5쿼리 → gather web 24+법령 33 → writer → **completed ~11분**, 보고서 26 인용·`## 개요` 채팅 메시지 append·download 정상. ~~onbox_verify 6게이트~~ 는 langgraph 경로 계약 스크립트 — 신경로용 동등 검증은 Phase 4(FE 계약 확정) 때 스크립트화.

### Phase 4 — medi-front 전송층 전환 ✅ 완료(2026-07-14) — 브라우저 QA PASS
- medi-front `7f12a5c`: SDK 제거, `chatApi.ts` 신규, `turns.ts` 이벤트 재매핑
  (applyMeta — 로컬 human id→서버 id 치환), `threads.ts` `/chat/*` REST,
  `useChatState` — 리로드/정지(abort)/resume(일반 메시지)/보고서(POST+폴링·409
  새키 재시도). 파서·리듀서·렌더러·fixture 무변경(조사 판정대로 4파일 격리).
- back 지원 보완: `DELETE·PATCH /chat/{tid}`(`2389989`), token `message_id`·
  `POST /reports` prompt(`638afda`).
- 검증: tsc 0에러·next build 통과 + **브라우저 QA(Playwright·실 백엔드·스크린샷
  실측, 2026-07-14) 6흐름 PASS** — ① 첫 질문: 스트리밍·인용칩(법령[3] 등)·출처
  아코디언·auto-title 헤더 ② 후속 턴 맥락·인용 연속 ③ 새로고침 복원(답변·출처·
  next_steps 카드) ④ 정지 후 입력 재활성 ⑤ 모호 질문("규제") 선택지 응답
  ⑥ 보고서 e2e — 트리거 버튼→"근거 수집(3단계)" disclosure→개요 답변+출처 8건+
  신뢰도 배지→완료 토스트→우측 패널·사이드바 카드(≤15분). QA 중 확인된 유일한
  이슈는 테스트 구성(CORS 3077 포트) — 제품 결함 0. → **Phase 5 컷오버 게이트 통과**.

### Phase 5 — 컷오버·은퇴 ✅ 완료(2026-07-14, `b4b24ac`+`5fddf16`)
- 슬라이스①: `init_chat_model` 폐기 — `models.build_chat_model`(provider 직접 생성)로 수렴, transitional 헬퍼 이관(gate.scrub_content·messages.content_text·llm_limits 전역 limiter).
- 슬라이스②: 삭제 — app.py(그래프)·auth.py·langgraph.json·graph 미들웨어 5종·@tool 래퍼 6종·auto_title(loopback)·state.py(reducers→steps.py)·analyst 프롬프트·entrypoint·의존 스크립트 6종. Dockerfile CMD `uvicorn --workers 1`, `.langgraph_api` 볼륨 은퇴. pyproject 5종 제거(**유지 = langchain-core + langchain-anthropic**).
- 테스트 이전: @tool 대상 → `chat_loop._tool_*` 포팅(커버리지 보존), 330 passed.
- **최종 증명**: venv 에서 langgraph·deepagents·langchain 등 11패키지 실제 uninstall → 330 passed·uvicorn 부팅·실 채팅 e2e(verified 인용) 정상. **원 목표(의존 제거) 실현.**
- 문서: CLAUDE.md 전면 개정 + startup/runbook/architecture/API/README 현행화.

## 4. 리스크·롤백

- Phase 1~3 은 **병행 구축**(기존 경로 무손상) — 각 Phase 끝 검증 게이트 실패 시 신규 경로만 폐기하면 됨. 컷오버(Phase 5)는 Phase 4 e2e ALL PASS 후에만.
- best-effort except 은폐 리스크(CLAUDE.md §9): 신규 루프의 훅 배선은 반드시 e2e 로 검증(단위테스트만으로 배선 누락 못 잡음 — 이메일 미발송 사고 전례).
- durability: 체크포인터가 하던 run 중단 복구는 미제공 — fast 채팅(~18s)은 재요청으로 충분, 보고서는 `report_runs_repo` 멱등 재시도로 커버.
- 개략 규모: ADR §10.1 추정 15~20일(병렬 가능). Phase 4 는 medi-front 저장소 작업.

## 5. 검증 총괄

| 게이트 | 도구 |
|---|---|
| 단위 | `pytest tests/ -q` (전 Phase green 유지) |
| fast 동등성 | `scripts/bench_run.py` vs `scripts/bench_chatloop.py` 신구 비교 |
| deep e2e | POST /reports 실측 (langgraph 경로는 `scripts/onbox_verify_report.py`) |
| 설정 | `scripts/check_config.py` |
| FE e2e | 채팅 스트림·clarify·보고서 트리거·cancel (medi-front — Phase 4) |

## 6. 검증 로그 (2026-07-13 실측 — 실 LLM·실 DGX 검색/writer)

**동등성**: 같은 질문(SaMD 임상) 신구 비교 — 검색 1회·인용 8건·grounding·
`<next_steps>` 동등, wall 20.9s(신) vs 22.0s(구, 웜).

**실사용 9시나리오** (HTTP `/chat`·`/reports` 경유):
① 인사 → 검색 미발동·5.2s ② 규제 질문 → 검색 강제·인용 8/8 verified
③ 후속 질문 → 맥락 유지·인용 번호 thread 연속(9~16) ④ PII → DB 저장본
placeholder 치환(원문 무노출) ⑤ 모호 질문 → 검색 후 본문 선택지 제시
(구경로 동일 거동) ⑥ 보고서 e2e → 27B writer 완주 ~11분·26인용·개요 채팅
append·download 정상 ⑦ 멱등 재요청 → 200 completed(재생성 0)·형식오류 422
⑧ **재시작 생존** → 프로세스 kill 후 회상 정확(MemorySaver 대비 개선)
⑨ **대화 압축 라이브** → 3턴째 자동 발동, 요약에 제품·결론·법령 보존,
원본 무손실.

**20인 동시 버스트**: 20/20 성공·에러 0, req p50 32.0s·TTFT p50 25.0s·
/healthz 최대 3.27s(전 구간 200)·토큰 귀속 43행 정상. 대기 지연 = 검색
백프레셔(2)·LLM RPS(8) 큐잉(의도된 graceful degradation).

**검증이 잡아낸 결함(전부 수정·재검증)**:
1. llm_call 이벤트 user/thread NULL 귀속(쿼터 무력화) — TokenUsageLogger
   생성자 컨텍스트 폴백 (`e027e8c`).
2. 같은 thread 동시 요청 히스토리 interleave 가능(langgraph-api 의 run
   직렬화 부재 갭) — per-thread 턴 락 (`55dd243`).
3. 이벤트 루프 동기 I/O 블로킹(부하 시 healthz 7s) — PII NER·SQLite 를
   `asyncio.to_thread` 격리 (`55dd243`).

**잔여 미검증**: PostgresThreadsRepo 실 PG 왕복(`MEDI_TEST_PG_DSN` gated —
운영 VM/CI 1회 필요) · FE 통합(Phase 4) · 압축 요약 출처 언급 프롬프트 손질(사소).
