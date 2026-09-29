# ADR-0001 · LangGraph 엔진 탈피 → FastAPI + LangChain SDK

- **상태**: 제안(Proposed) — 점진 마이그레이션, 미구현
- **일자**: 2026-06-18
- **결정자**: 오너
- **관련**: `docs/spec/03_ARCHITECTURE.md`(현 LangGraph 구조, v0.x), `CLAUDE.md`(운영 주의 §1·§2)

---

## 1. 배경 (Context)

현재 medi-back은 **LangGraph 그래프엔진 + `langgraph dev` 서버** 위에서 돌고, `src/api.py`(FastAPI)가 거기에 `http.app`으로 마운트돼 있다. 그러나:

1. **오케스트레이션이 단순하다.** 자율 에이전트는 채팅 supervisor 1개(`build_graph`, `subagents=[]`), 보고서는 결정형 파이프라인 1개(`report_pipeline`). 복잡한 그래프 토폴로지를 쓰지 않아 **LangGraph 엔진의 이득을 거의 활용하지 않는다.**
2. **운영 고통이 크다.** `CLAUDE.md §2`에 명시된 `.langgraph_api` stale 상태, watchfiles loop, blockbuster 500 등 langgraph dev/platform 결합 비용.
3. **앞으로 원하는 구조**(빠른 채팅 + 백그라운드 보고서 + 대화기반 보고서 + **법률 네트워크 인터랙티브 선택**)는 평범한 HTTP + DB + SSE 에 더 깔끔하게 매핑된다. 특히 인터랙티브 그래프 선택은 LangGraph `interrupt` 없이 **비차단 2-요청**으로 충분하다.

**프레임워크는 답변 품질을 올리지 않는다** — 품질은 retrieval/grounding의 문제다. 본 결정은 **개발속도·운영 단순성·통제**를 위한 것이지 챗봇 정확도 향상을 위한 것이 아니다. (정확도는 별도 트랙: retrieval 강화 + grounding 게이트 + eval 하니스.)

## 2. 결정 (Decision)

**LangGraph(그래프엔진 + `langgraph dev` 서버 + checkpointer)를 걷어내고, FastAPI + LangChain SDK(only) + 자체 Postgres 상태 + SSE 스택으로 이전한다.**

- **버린다**: `langgraph`, `deepagents`, `langgraph dev/platform`, `.langgraph_api`, LangGraph checkpointer/StateGraph/interrupt.
- **지킨다**: `langchain`/`langchain-anthropic`(LLM 호출·`bind_tools` tool use), retrieval 클라이언트(Qdrant/Neo4j/Mongo — 프레임워크 무관), 프롬프트(`src/prompts/`), persistence repo(`src/persistence/`), 스트림 이벤트 스키마(`tool_progress`/`steps`/citations).

## 3. 목표 아키텍처

```
FastAPI (단일 ASGI 앱 — API + SSE)
  ├─ POST /chat  (SSE 스트리밍)
  │     LangChain bind_tools + 수동 tool-loop (while: model → tool 실행 → 반복)
  │     tool: qdrant_search 코어, tavily, ask_clarify
  │     스트림: 토큰 + tool_progress + steps + (신규) law_graph
  │     thread 상태 = Postgres 테이블 (messages/steps/selected_law_keys)
  ├─ POST /reports  (백그라운드 잡 enqueue)
  │     잡 러너(asyncio task 또는 arq) + report_runs_repo(멱등락 재사용)
  │     parent thread 대화 + 큐레이션된 법률 선택집합 상속 → 5섹션 보고서 → blob + 알림
  ├─ GET  /law-graph  (서브그래프 조회)
  │     Qdrant seed → Neo4j CITES 1~2홉 확장 → {nodes, edges}
  └─ 기존 라우트 (reports/articles/feedback/admin) — 이미 FastAPI, 그대로
```

## 4. 컴포넌트 매핑 (LangGraph 기능 → 대체)

| LangGraph 제공 | 대체 | 재사용 자산 |
|---|---|---|
| Checkpointer (thread 상태·resume) | 자체 Postgres thread-state 테이블 | `persistence/*_repo.py` 패턴 |
| 스트리밍 (stream_mode, custom 채널) | FastAPI `StreamingResponse`(SSE) + 직접 이벤트 | `tool_progress`/`steps` 스키마 |
| 에이전트 루프 + 미들웨어 | LangChain `bind_tools` + 수동 while 루프 | 프롬프트·도구·쿼터/토큰로깅 미들웨어 로직 |
| 백그라운드 run (`parent_thread_id`) | asyncio task / arq 잡 + 잡 테이블 | `report_runs_repo`(멱등락) |
| interrupt (human-in-loop) | **현재 `ask_clarify`(`tools/clarify.py:81`)가 사용 중** → SSE + `/resume` 엔드포인트로 재구현 필요. 단 #4 그래프선택 자체는 interrupt 불필요(비차단 2-요청) | — |

## 5. 제품 요구사항 매핑

1. **챗봇 + 보고서** → `/chat`(SSE) + `/reports`(잡).
2. **보고서 백그라운드** → 잡 러너 + `report_runs_repo`. 완료 시 알림.
3. **빠른 채팅 → 대화기반 보고서** → `/reports`가 parent thread 상태(대화 + 선택 법률)를 상속.
4. **법률 네트워크 인터랙티브 선택** → `/law-graph`로 서브그래프 반환(비차단) → 사용자가 노드 선택 → 다음 `/chat` 요청에 `selected_law_keys` 동봉 → grounding 제약. 선택집합은 thread 상태 영속 → 보고서로 흐름.
   - **선행 검증 필요**: Neo4j `(Article)-[:CITES]->(Article)` 엣지 커버리지. 희소하면 네트워크가 빈약 → ETL 보강 선결.

## 6. 결과 (Consequences)

**장점**
- `.langgraph_api` stale·watchfiles·blockbuster 운영 고통 제거.
- 흐름이 평범한 async 함수 → 디버깅·통제 용이, 버전 결합 해제.
- 원하는 tiering·병렬 팬아웃·그래프선택을 프레임워크와 안 싸우고 구현.

**비용·위험**
- 스트리밍·thread 상태·잡러너 **plumbing 재구축**(중간 규모). 체크포인터/스트리밍의 durability를 직접 책임짐.
- deepagents/langgraph 생태계 이탈. 추후 그래프가 복잡해지면 일부 재발명 가능.
- **마이그레이션 리스크** → 점진·병행으로 완화(아래).

## 7. 마이그레이션 계획 (점진·되돌리기 쉬움)

1. **`/chat` SSE PoC 병행 구축** — 기존 langgraph 안 건드리고 새 엔드포인트. LangChain tool-loop + SSE + Postgres thread 상태. 기존과 **답변 동등성 검증**(`bench` 비교).
2. **스트림 채널 재현** — `tool_progress`/`steps` 동등, 프런트 무변경 목표.
3. **보고서 잡러너 이전** — `report_runs_repo` 재사용, 백그라운드 + 알림.
4. **`/law-graph` + 선택집합 grounding** — (CITES 커버리지 검증 후) 서브그래프 + 비차단 선택.
5. **검증 완료 후 langgraph 서버 은퇴** — `langgraph.json`/deepagents 의존 제거.

## 8. 미결 사항 (Open Questions)

- thread 상태 스키마 최종형(messages/steps/selected_law_keys 외 토큰·turn 컨텍스트).
- 잡 러너 선택: 단순 asyncio task vs arq(Redis) — 다중 워커·재시작 내구성 요구에 따라.
- LLM tool-loop를 LangChain `bind_tools`로 갈지 Anthropic SDK 직접 tool-use로 갈지(의존 최소화 관점).
- 프런트(medi-front) 영향: SSE 이벤트 포맷 호환 유지 범위.
- **선결 검증**: Neo4j CITES 엣지 커버리지(요구사항 4 토대).

## 9. 비고

본 ADR은 **방향 합의용**이며 구현은 미시작. 코드·프롬프트는 별도 승인 후 착수한다(오너 정책: 지시받은 변경만).

---

## 10. 스카우팅 결과 (2026-06-18, 읽기전용 3-agent 조사)

### 10.1 LangGraph 의존 표면 — 재구현 난이도

| 기능 | 난이도 | 비고 |
|---|---|---|
| Checkpointer (Memory/PostgresSaver) | **하** | `langgraph-checkpoint*` 패키지는 분리 사용 가능 — 그대로 재사용해도 됨 |
| 토큰로깅(`TokenLoggerMiddleware`)·LLM RPS(`LLMRateLimitMiddleware`) | **하** | LangChain 표준 `BaseCallbackHandler`/`InMemoryRateLimiter` → 거의 그대로 |
| 에이전트 루프(`create_deep_agent`) | **중** | 수동 ReAct(while: model→tool parse→exec) |
| 미들웨어(`StepsMiddleware`/`ReportContextMiddleware`) | **중** | `Annotated[list, reducer]` + 모델호출 wrap 훅 |
| `InjectedState`/`InjectedToolCallId` | **하** | 도구 시그니처에서 제거 → state 명시 전달 |
| StateGraph 보고서 파이프라인 | **상** | 수동 async 오케스트레이션으로 교체 |
| 백그라운드 run(`parent_thread_id`) | **상** | 잡 큐 필요 |
| `interrupt`(ask_clarify) | **중** | SSE + `/resume` 재구현 |

- **정정**: 당초 ADR은 interrupt "불필요"라 했으나 **`ask_clarify`가 이미 사용 중**(§4 수정됨). 단순화하려면 clarify도 비차단 방식으로 재설계 검토.
- 개략 규모: 15~20일(병렬 가능). 대부분 `app.py`/`api.py`/`middleware`/`tools` 수정.

### 10.2 재현해야 할 FE 계약 (무변경 목표)

- **이벤트**: `tool_progress`(type/tool/phase/message + result 시 index/title/subtitle/url), `step_lifecycle`(start step), `values`(messages/steps/files), `messages-tuple`(토큰 — `report_writer_internal` 태그는 채팅 렌더 제외).
- **상태**: `messages`(add_messages) + `steps`(merge_steps_by_id 리듀서). Step dict: id/ts/label/status/tool_name/(+source_message_id/turn_idx).
- **citation 번호**: turn 전역 단조, id 기준 dedup, 같은 id=같은 번호.
- **마커**: `<next_steps>` 닫힘까지 파싱. **쿼터 헤더** `X-Quota-*` + 429 스키마.
- 근거: `src/steps.py`, `src/state.py`, `src/tools/search.py`(emit), `docs/contracts/API.md`.

### 10.3 요구사항 ④ 법률그래프 — 실현가능성

- ✅ **토대 충분**: `Article` 노드 + `(Law)-[:CONTAINS]->(Article)` 실사용(`/law/{lawId}/articles`).
- ⚠️ **정정(2026-06-18 라이브 검증)**: 스카우트가 "`article_key`==`Article.id` 일치"라 했으나 **실제로는 포맷이 다름**. Neo4j `Article.id`=`{lawId}_{jo4}{gaji2}`(6자리 suffix, 예 `009514_000600`), PG/Qdrant `article_key`=7자리(끝 1자리 더, 예 `009514_0006001`). **prefix 매칭으로 1:1 해소**(`article_key LIKE '{Article.id}%'`, 8/8 정확). 구현: `pg_client.resolve_article_keys`(이미 `feat/law-graph-poc` 에 반영, 양방향 포맷 안전). seed 측(채팅 citation 7자리 → 그래프 6자리)도 동일 역해소 필요 — 후속.
- ✅ **CITES 커버리지 측정 완료(2026-06-18, 라이브 Neo4j)**: Article **1,230,827** / CITES 엣지 **2,076,819** / **커버리지 75.4%**(with_cites 928,104) / max out-degree 588. **≥70% "즉시 진행" 기준 충족 → ETL 보강 불필요, 1~2홉 서브그래프 가능.**
- ✅ **그래프가 문서보다 풍부**: `CITES` 외 `CITES_HISTORICAL`(123,693)·`DELEGATES_TO`(63,969, 위임)·`CORRESPONDS_TO`(27,356)·`REGULATES_VIA`(20,245) 관계 존재 → 법률 네트워크를 다중 엣지타입으로 풍성하게 구성 가능. 노드도 `DeletedArticle`/`RepealedLaw`/`Document` 등 버전·이력 포함.
- 보완책(불필요해짐): 커버리지 충분하므로 `REFERS_TO_ATTACHMENT` 보조·ETL 보강 선결 없음.

```cypher
// CITES 커버리지 측정 (Neo4j Browser)
MATCH (a:Article) OPTIONAL MATCH (a)-[:CITES]->(b:Article)
WITH a, count(b) AS deg
RETURN count(a) AS total,
       count(CASE WHEN deg>0 THEN 1 END) AS with_cites,
       round(100.0*count(CASE WHEN deg>0 THEN 1 END)/count(a),1) AS pct;
```

### 10.4 미결 질문에 대한 권고 (단순화 우선)

- **LLM 루프**: LangChain `bind_tools` 유지(중·검증된 의존). Anthropic SDK 직접은 의존 더 줄지만 재작업 큼 → 후순위.
- **잡 러너**: 처음엔 **asyncio task + `report_runs_repo`**(단일 프로세스, 단순). 다중 워커·재시작 내구성 필요해지면 arq(Redis)로 승격.
- **다음 선결 액션(완료됨)**: ~~CITES 커버리지 측정~~ → 75.4%로 측정 완료, ④ 그린라이트. 다음은 **`/law-graph` 서브그래프 빌더 PoC**(읽기전용 Cypher: seed `article_key` + `CITES` 1~2홉 → {nodes, edges}) 또는 **`/chat` SSE PoC** 중 택일.
