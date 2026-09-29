# medi-back 시스템 기능 상세 (개발자용)

각 기능의 **목적 · 진입점 · 동작 · 핵심코드 · 설정(env) · 주의**를 정리한 레퍼런스.
흐름도는 [`architecture.md`](./architecture.md), API 계약은 [`API.md`](../contracts/API.md) ·
[`frontend_chat_v2.md`](../contracts/frontend_chat_v2.md), 운영은 [`runbook.md`](../ops/runbook.md),
변경 이력은 [`CHANGELOG.md`](../CHANGELOG.md).

> **아키텍처 전제** (ADR-0001, 2026-07-14 컷오버 완료): langgraph·deepagents·
> langchain(메타)은 은퇴. LLM 스택은 `langchain-core` + `langchain-anthropic` 만.
> 채팅은 자체 tool-loop(`chat_loop.py`), 보고서는 asyncio 잡러너(`report_runner.py`),
> thread 상태는 `threads_repo`(dev SQLite / prod PG) 영속. **무거운 ML(검색 랭킹·
> PII NER·의도분류·보고서 생성)은 전부 DGX 서비스로 위임** — 로컬 ML 없음.

설정 노브 전체는 `src/config.py`(`ENV_REGISTRY`) — `python scripts/check_config.py` 로 한눈에.

---

## 0. 두 갈래 흐름 (오리엔테이션)

| | **fast** (즉답) | **deep** (심층 보고서) |
|---|---|---|
| 진입 | `POST /chat` (SSE, ~15–20s) | `POST /reports` + 폴링 (백그라운드, 모델 의존 ~5–40분) |
| 엔진 | `src/chat_loop.py` 수동 tool-loop | `src/report_runner.py` asyncio 잡 |
| 파이프라인 | PII 게이트 → 의도판정 → **검색 강제** → 답변 스트리밍 → grounding 검증 | 멱등락 → 분해 → 수집(+근거 충분성 게이트) → **로컬 vLLM writer** → 5섹션 종합 |
| writer 모델 | Anthropic Haiku-4-5 (Sonnet 폴백) | 로컬 vLLM — **고정 아님**: `/v1/models` 자동 감지(Qwen3.5-27B·Gemma-4-31B-w4a16 등 교체 실험). `REPORT_WRITER_BASE_URL` 미설정 시 Sonnet 폴백 |
| 트리거 | 자유 텍스트 | `idempotency_key`(`^rpt_…`) 멱등락 — 자유 텍스트 아님 |
| 출력 | 본문 + `[n]` 인용 + 신뢰도 배지 | **채팅에 아무것도 남기지 않음**(2026-07-25 분리) — 사이드바·우측 패널·이메일 DOCX 첨부로만 |

---

## 1. 사용자 기능

### 1.1 Fast 채팅 (자체 tool-loop, SSE)

- **목적**: 규제 질의에 근거(법령 인용) 기반 즉답을 스트리밍.
- **진입**: `POST /chat` (SSE). 이벤트: `meta`·`token`·`tool_progress`·`steps`·`clarify`·`done`.
- **동작**: `ChatAnthropic.bind_tools` + while 루프. 훅 순서 — ① PII 스크럽(입력) →
  ② 의도판정 → ③ **검색 강제**(규제 질의면 `tool_choice=qdrant_search` forced 바인딩)
  → ④ 검색·답변 스트리밍 → ⑤ grounding 검증 → ⑥ 대화 압축 → per-thread 턴 락.
- **지연 최적화(임계 경로)**: ① PII 스크럽·의도판정은 독립 DGX 호출이라 `asyncio.gather`
  로 **병렬**(왕복 하나 겹침), 의도는 턴당 1회만 판정(`_intent_force_search`). ② 시스템
  (supervisor+도구) 프리픽스에 프롬프트 **캐싱**(`_system_blocks`) — 단, Haiku 4.5는 캐시
  최소 임계가 높아 현 프리픽스(~4.3k토큰)로는 turn-1 무효과(Sonnet·프롬프트 성장 시 유효).
- **코드**: `src/chat_loop.py`(`run_chat_turn`·`build_models`·훅) · `src/routes/chat.py`.
- **설정**: `CHAT_MAX_TOKENS`(4096) · `CHAT_MODEL_OVERRIDE_ALLOW` · `CHAT_LOOP_DISABLE`
  · `CHAT_PROMPT_CACHE_DISABLE`.
- **주의**: 검색은 **모델 선택이 아니라 강제**다 — 캐주얼 어투에서 모델에 맡기면
  인용을 날조함(실측). 근거 확보를 모델 판단에서 분리(CLAUDE.md §5).

### 1.2 Deep 심층 보고서 (asyncio 잡러너)

- **목적**: 컨설팅형 5섹션 종합 보고서를 백그라운드 생성(수분~십수분 허용).
- **진입**: `POST /reports` + `idempotency_key`(`^rpt_…`) → `GET /reports/runs/{idem}` 폴링
  (`queue_ahead` 로 대기 순번 표시). 계약: `docs/contracts/frontend_chat_v2.md` §4.
- **동작**: 멱등락 → 질문 분해(decompose) → 수집(gather, 검색 동시성 큐) → **근거
  충분성 게이트**(`REPORT_MIN_CITATIONS`=6 미달 시 1회 재수집 → 그래도 미달이면 run
  실패, 얇은 보고서를 완성품으로 내보내지 않음) → 로컬 vLLM writer **초안 → 비평
  (교차 모델) → 개정** → 전문 blob 저장 + 완료 이메일(전문 DOCX 첨부).
- **채팅과 완전 분리·병렬**(2026-07-25): 대화록에 개요를 append 하지 않고, 진행
  step 도 채팅 턴에 바인딩하지 않으며, 대화 모델은 보고서 진행을 모른다. 완료는
  폴링 → 토스트·브라우저 알림·사이드바로 알린다.
- **품질(지연 허용)**: ① **비평·개정 패스**(`_critique_and_revise`) — 비평(기본 haiku 교차
  모델, `REPORT_CRITIQUE_MODEL`)이 각 `[N]` 을 citation 원문과 대조해 근거 없는 주장·관계
  주장(벌칙 연결·양벌 금액) 오단정·판례 형식 미비·요약 확신도 역전을 지적하고 개정이 반영.
  실패·공백 시 초안 유지(개악 방지). ② **결정적 선행 검사** — 초안 grounding 선검증
  (`verified=False` 인용)과 (법령명, 조번호) 페어 대조(`_unbacked_articles` — 법령 귀속
  오류 검출 포함)를 개정 지적으로 주입. ③ **수집 깊이·tier** — top_k 20(채팅 12보다
  깊게, rerank_pool=25 이내) + rag=T1·web=T3 태깅과 **T1 승격**(웹이 언급한 조문의 원문
  표적 재검색, `REPORT_TIER_UPGRADE_MAX`=3) — writer 는 법적 주장에 T1 우선.
  ④ **발행 직전 결정적 게이트** — 깨진 마커 정리·무인용 수치 주장 로깅(`_verify_rendered`)
  + 작성 기준일 stamp(`_stamp_as_of`) + 최종 grounding 으로 인용 verified 부착.
  근거·설계: `reference/재설계보고서_반영기록.md`.
- **코드**: `src/report_runner.py`(`spawn_report_job`·`queue_ahead`) · `src/report_pipeline.py`
  (분해·수집·비평·개정·writer — writer 지시는 `_RECONCILE_INSTRUCTIONS`) · `src/routes/reports.py`.
- **설정**: `REPORT_MAX_CONCURRENCY`(1) · `REPORT_DEADLINE_S` · `REPORT_WRITER_BASE_URL/MODEL`
  · `REPORT_ATTACH_FORMAT`(docx|md) · `REPORT_REVISE_ENABLE`(1) · `REPORT_CRITIQUE_MODEL`
  · `REPORT_TIER_UPGRADE_MAX`(3) · `REPORT_QDRANT_TOP_K`(20).
- **주의**: 채널 분리 — 본문에 References·다음 단계 안내를 박지 않는다(`<next_steps>`
  마커 계약 + suggest UI). 드물게 실행되는 이메일 분기는 e2e 로 검증(과거 미발송 사고).

### 1.3 Tier-0 조문 즉답

- **목적**: "법령명 제N조" 류 *명시적 조문 지정* 질의를 **LLM 없이** 즉답(0.x초·무비용).
- **진입**: `GET /article/lookup?q=의료기기법 제25조`. 식별 실패 시 404 → FE 가 일반 채팅 폴백.
- **코드**: `src/routes/articles.py:lookup_article` · `src/text/article_query.py:parse_article_query`
  · `src/retrieval/pg_client.py:resolve_article_by_name`.

### 1.4 법률 네트워크 + 선택 grounding

- **목적**: 전문가가 답변 인용을 시작점으로 **조문 인용 네트워크**를 탐색하고, grounding 에
  쓸 법령을 직접 골라 근거를 통제(LLM 추측 아님).
- **진입**: `GET /law-graph?keys=&depth=&rels=` → 선택 조문은 채팅 요청에 `selected_law_keys`
  로 동봉 → 다음 검색이 **선택 조문으로 grounding 고정**(벡터검색 대신 "이 법으로만").
- **코드**: `src/routes/law_graph.py` · `src/retrieval/neo4j_client.py:fetch_law_subgraph`
  · `src/tools/search.py:run_qdrant_pinned`. 선택 상태는 `threads_repo` 영속.
- **주의**: Neo4j Article.id(6자리) ↔ article_key(7자리)는 prefix 매칭으로 해소. 허용 rel
  화이트리스트(`ALLOWED_GRAPH_REL_TYPES`). Neo4j 미연결 시 503. pinned 검색은 판례·해석례·
  헌재결정례·행정심판례(prec/expc/decc/detc)까지 종별 명시 포함.

### 1.5 인용 검증(grounding) + 신뢰도 배지

- **목적**: 답변의 각 `[n]` 인용이 **실제 법령 원문에 근거**하는지 자동 검증 → 환각 표시.
- **동작**: 답변 완료 후 haiku 가 claim ↔ source 근거 문장(`supporting_quote`)을 뽑고,
  그 문장이 원문에 **substring 으로 존재**하는지 확인해 인용에 `verified`(bool)·
  `supporting_quote` 부착. `text` 없는 인용(웹 등)은 원본 보존. 답변 속도 무영향(뒤따라 부착).
- **신뢰도 배지**(프런트 `ConfidenceBadge.tsx`): `verified / 전체 인용` 비율 →
  **≥80% 🟢High · 30–79% 🟡Medium · <30% 🔴Low**. 인용 0건·verified 미사용 응답엔 미렌더.
- **코드**: `src/grounding.py`(`ground_citations`, chat+report 공유). **설정**: 게이트 비활성 env.

### 1.6 검색 (openlaw-etl `/search` thin-client)

- **목적**: 랭킹·인용메타·grounding 원문을 서버가 전담(로컬 임베딩/Qdrant 없음). medi-back 은
  계약만 안다.
- **동작**: `search_articles(query, top_k, target_types)` 1콜 → dense(KURE)+BM25+RRF+
  **fp16 리랭커**+법률종 부스팅+조문 GROUP BY 결과 수신 → 잠정 citation 빌드. 인용 원문
  (full_text)은 grounding·보고서가 필요할 때만 `/articles/bodies` 로 별도 조회.
- **기본 종별**: 미설정 시 `law,admrul,ordin,prec,expc`(법령+판례+법령해석례). openlaw-etl
  코퍼스가 5종 전부 인덱싱(`citations.py`) — 해석례는 "의료기기 해당 여부" 유권해석 질의에
  핵심(RA/QA). `RAG_SEARCH_TARGET_TYPES` 로 재정의(조문만 원하면 `law,admrul,ordin`).
- **종별 보충(2026-07-16)**: 혼합 랭킹은 법령이 상위 독식(리랭커 score 법령 ~2.x
  vs 판례 ~-0.02, 실측) — 2중 보완. ① **LLM 주도**: `qdrant_search` tool 에
  `doc_kinds`(law/admrul/ordin/prec/expc) 파라미터 — 논점상 판례·해석례가 유용하면
  LLM 이 종별 지정 검색을 스스로 추가 호출(supervisor 프롬프트 지침). ② **단서
  자동 보충**: 질의에 "판례/해석례/행정규칙·고시/조례" 단서가 있는데 그 종별이
  3건 미만이면 4건 보충 병합(`_supplement_cued_types`). 일반 질의 랭킹 불변.
- **top_k**: 기본 **12**(`QDRANT_TOP_K`). 8이면 리랭킹 상위 8칸을 법령이 차지해 판례·해석례가
  밀려 누락(실측). **GPU 무관** — 서버 리랭커 후보 풀은 `rerank_pool=25` 고정, `top_k` 는
  리랭킹 '후' 슬라이스(engine.py). 비용은 Anthropic 입력 토큰뿐(Haiku, 미미).
- **캐시 + keepalive**: 질의 정규화(공백·대소문자, 조사·어순 보존) 캐시 키로 적중 시 검색
  통째 스킵. lifespan 배경 태스크가 `SEARCH_KEEPALIVE_S`(240s) 주기로 리랭커 웜 유지
  (idle 후 콜드 지연 방지, fp16 웜 ~0.79s).
- **코드**: `src/retrieval/search_api_client.py` · `src/tools/search.py`(`run_qdrant`).
- **설정**: `RAG_SEARCH_API_URL/KEY` · `RAG_SEARCH_TIMEOUT_S` · `RAG_SEARCH_TARGET_TYPES`
  · `QDRANT_TOP_K`(12) · `SEARCH_CACHE_SIZE/TTL_S` · `SEARCH_KEEPALIVE_S` · `SEARCH_MAX_CONCURRENCY`(2).

### 1.7 대화 메모리 압축

- **목적**: 긴 대화의 토큰 폭증·컨텍스트 초과 방지.
- **동작**: 누적 추정 토큰이 임계를 넘으면 오래된 메시지를 요약 압축, 최근 N턴은 원문 유지.
  요약 상태도 `threads_repo` 영속(재시작 생존).
- **코드**: `src/chat_loop.py:_maybe_compact`. **설정**: `CHAT_SUMMARY_TRIGGER_TOKENS`(24000,
  0=끔) · `CHAT_SUMMARY_KEEP_TURNS`(2) · `CHAT_SUMMARY_MODEL`(미설정=SUBAGENT_MODEL→haiku).

### 1.8 인용 신고 (검색 품질 라벨)

- **목적**: 사용자가 부적절한 인용을 신고 → 검색 품질 개선 신호 수집.
- **진입**: `POST /feedback/citation` (thread_id·message_id·citation_id·번호·제목·사유).
- **코드**: `src/routes/feedback.py`. feedback repo + events(`citation_report`) 이중 기록 →
  admin 통계에 집계.

### 1.9 조문·별표 조회

- **진입**: `GET /article`(단건 원문) · `GET /annex`(별표·서식). openlaw PG 직접(읽기).
- **주의**: `/readyz` 의 postgres down(=degraded)은 **운영 PG DSN 미설정**(dev SQLite 폴백)
  때문 — 채팅·RAG·조문 조회는 정상(CLAUDE.md §3).

### 1.10 기관 내부 지침 스킬 — IRB/DRB 심의 상담 (2026-08-10, 조건부)

- **목적**: 병원 IRB(생명윤리)·DRB(의료정보데이터) SOP 기반 심의 판정(면제/신속/
  정규)·절차·서식 작성 — 국가 법령 검색이 못 덮는 "우리 병원 기준" 답변.
- **동작**: IRB/DRB 질의 감지(키워드 프리게이트) → `load_skill` 1회차 강제(지침
  우선) → 문진(슬롯 채우기, 멀티턴 스티키) → 판정 + `<verdict>` 구조화 로그.
  판정 원칙은 지침에 내장: 애매하면 HOLD, 심의대상→면제 오판 절대 금지, 매번
  예비판단 고지. 답변 말미 판정은 SSE `skill_verdict` + events 로 적재(골든셋).
- **스위치 3단**: `SKILL_BUNDLE_DIR`(미설정=기능 없음) · `SKILL_WHITELIST_EMAILS`
  (기관 잠금) · 스레드 프리게이트+스티키. off 면 기존 채팅과 완전 동일.
- **코드**: `src/skills/`(loader·chat_integration — 격리, chat_loop 은 가드 훅만).
  지식 자산 `src/skills/medireg_irb_drb/`(스킬 7종 .md — 코드에서 파싱 금지).
  manifest 갱신 `scripts/build_skill_manifest.py`. FE 계약 frontend_chat_v2.md §2-4.

### 1.11 서식 작성 — 별표·서식 원문 기입 (2026-08-25~, 정리 2026-09-18)

- **진입**: 답변 아래 관련 서식 카드·출처의 별표/서식 [이 서식으로 작성] →
  `POST /documents/from-form`(LLM 없이 서식 항목 추출, 몇 초) → `reports` 행
  `kind="doc"` + `report_runs(purpose=document_draft)`. 작성 모달 = 좌 항목 행·우 도우미 챗.
- **채우기 3경로**: 도우미 대화(`POST /documents/{id}/chat`, 온프레미스 모델 직행 —
  명시 값만·추론 금지) · 행 인라인 직접 입력(`POST /documents/{id}/fill`) · 서류 첨부
  (같은 chat 라우트에 `attachment_text`). 채팅 턴 대조 기입(`doc_fill.run_turn_fill`)은
  현재 스레드 최신 초안이 있을 때만.
- **내보내기**: `GET /documents/{id}/original-form` — 원문 HWP/HWPX 에 kordoc `patch` 로
  값만 기입(바이트 보존, 확장자는 원본 따름). 미기입 칸은 화면에 `[확인 필요]`, 파일은 빈 칸.
  원문 없는 서식(IRB 등)은 초안 본문 `.docx` 폴백.
- **다시 보기·삭제**(2026-09-18): `GET /documents`(본인 서식, 최신순 — `report_runs.user_id`
  로 잇는다) → 사이드바 "작성한 서식" 섹션에서 열기·삭제. 삭제는 `DELETE /reports/{id}`
  (소유자만, 404 fail-closed) + `report_runs.detach_report` 로 지운 서류를 run 이 가리키지
  않게 → pill·턴 대조가 이전 초안으로 자연 복귀.
- **수명 규칙**(2026-09-18, `src/form_docs.py`): 서식은 만든 대화에 딸린다 — 대화 삭제(`DELETE /chat/{tid}`)·
  90일 보존 정리(`prune_threads.py`) 때 그 대화의 서식도 함께 삭제(blob·행·run 분리). 예외는 **보관**
  (`reports.kept`, `POST /documents/{id}/keep`) — 보관한 서식은 독립 목록으로 남고, 대화가 없어도 소유자는
  `report_runs.owner_of_report` 로 계속 연다. reports↔threads 는 저장소가 달라 DB FK 가 아니라 삭제 경로 2곳이
  같은 함수를 부른다. 관리 모달(medi-front `DocumentsDialog`): 표(제목·작성일·작성 상태·보기·대화·다운로드·
  보관·삭제) + [전체]/[보관함] 탭, 진입은 사이드바 "작성한 서식" 섹션 [관리]. 작성 상태는 본문 마커 수 대비
  채운 수(empty/partial/done).
- **저장 암호화**(2026-09-18): `reports.filled_values`(성명·연락처 등 개인정보 그 자체)는
  `src/persistence/field_crypto.py` 가 Fernet 으로 감싸 `enc1:` 암호문으로 저장. 키는
  `FILLED_VALUES_ENC_KEY`(쉼표=회전), 미설정 시 `NEXTAUTH_SECRET` 파생 — 배포 즉시 켜짐.
  레거시 평문 행은 읽기 호환·다음 병합 때 승격. 복호 실패는 예외(조용한 빈 값 금지).
  완성 파일은 저장하지 않는다(요청 시 생성). 테스트 `tests/test_filled_values_crypto.py`.

---

## 2. 가드레일 · 보안 · 인증

### 2.1 PII 마스킹 게이트

- **목적**: 주민번호·전화·카드·이메일·여권·사업자·계좌·이름·주소 등을 외부 전송·저장 전 마스킹.
- **동작**: **두 지점** — ① egress(국외 LLM·Tavily 전송 전) ② at-rest(DB·대화기록 저장 전).
  구조적 PII 는 regex 결정적 마스킹, 문맥 PII(이름·주소 등)는 DGX NER 서비스. NER 다운 시
  regex-only 폴백(안전 — 구조적 PII 는 계속 마스킹).
- **코드**: `src/guardrail/{pii,gate,ner_client}.py`. **설정**: `PII_GATE_DISABLE` ·
  `PII_NER_API_URL/KEY/TIMEOUT_S`. 계약: `docs/contracts/guardrail_ner_service.md`.

### 2.1b 마스킹 전수 수집·라벨링 + 오탐 신고 루프 (2026-08-13)

- **목적**: NER 오탐(`[이름]` 오마스킹)을 **재배포 없이** 해소하고, 마스킹 판정
  전체를 라벨셋으로 축적(임계값 튜닝·가드 개선의 실측 데이터).
- **동작**: ① **전수 수집** — 채팅에서 NER 마스킹된 모든 단어를 자동 등재
  (`observe_many`, 구조적 PII 는 스킵·마스킹 동작 불변). ② **신고(선보고
  후조치)** — `pii_notice` SSE(`masked_text`)로 프런트가 치환 단어를 짚어
  토스트+[오류 신고] → `POST /feedback/pii` → 즉시 마스킹 제외(TTL 10s).
  ③ **라벨링(후조치)** — admin 이 correct(정탐, 마스킹 유지·복귀)/wrong(오탐,
  영구 제외) 라벨(`/admin/pii-terms`, 다이제스트에 신고 현황 포함). 구조적
  PII(주민번호·전화 등)는 어느 경로로도 등재·허용 불가 — 진짜 개인정보 절대 필터.
- **코드**: `src/guardrail/pii_terms.py` + `gate._stoplisted`/`_apply_spans(collect)` ·
  chat_loop 배선 · 라우트 `feedback.py(/feedback/pii)`·`admin.py(/admin/pii-terms)`.

### 2.1c 패치노트 팝업 (2026-08-13)

- **목적**: 개선 사항을 사용자에게 가시화("매일 개선한다") — 로그인 후 최초 접속
  시 안 본 노트만 팝업 1회.
- **동작**: admin 발행(`POST /admin/announcements`, DB 최근 20건) →
  `GET /announcements/latest` id 를 프런트 localStorage 와 비교. 서버 read 상태 없음.
- **코드**: `src/announcements.py` · `src/routes/announcements.py`.

### 2.2 의도 판정 + 검색 강제

- **목적**: 규제 질의엔 법령 검색을 강제해 답변 모델 환각 차단, 인사·재촉엔 검색 스킵.
- **동작**: DGX 의도 분류기(Qwen3.5-0.8B) → 규제면 forced 바인딩. 분류기 다운 시 인사말
  휴리스틱 폴백(규제면 검색강제 = 안전 기본값). 정확 인사말(`_OFFTOPIC`)·물음 없는
  재촉/필러(`_NO_QUESTION`: "대답해"·"빨리"·"계속")는 분류기 호출 없이 검색 스킵 —
  강제 검색을 풀어야 모델이 맥락에 진짜 질문이 있을 때만 스스로 검색하고, 없으면
  되묻는다(주제 날조 차단). "ㅎㅇ"은 말미 웃음만 정규화해 인사로 인식.
- **응답 라우팅(supervisor v7)**: A 인사·자기소개 / B 규제 무관 실제 질문(범위 안내·
  인사문 재사용 금지) / C 물음 없는 재촉(되묻기·★주제 날조 금지) / D 규제 질문 /
  모호 단독어→`ask_clarify` / 유해 요청→안전 거절. → `src/prompts/supervisor.py`.
- **코드**: `src/guardrail/{intent,intent_client}.py`. **설정**: `INTENT_SEARCH_DISABLE` ·
  `INTENT_API_URL/KEY/TIMEOUT_S`. 계약: `docs/contracts/guardrail_intent_service.md`.

### 2.3 인증 (NextAuth JWT)

- **목적**: medi-front 가 발급한 JWT 를 검증(`NEXTAUTH_SECRET` 양쪽 공유).
- **동작**: `AuthMiddleware` — HS256 서명·만료 검증 → user upsert(ADMIN_EMAILS 면 is_admin 자동)
  → `request.state.user_*`. 공개 라우트(`PUBLIC_PATH_PREFIXES`: healthz·readyz·load·legal·
  beta·suggestions·docs)는 검증 스킵. dev: `NEXTAUTH_SECRET` 미설정 시 통과, `AUTH_DEV_BYPASS_USER`
  로 자동 로그인.
- **코드**: `src/middleware/auth.py`. **dependency**: `get_current_user_id` · `require_admin`.

### 2.4 클로즈 베타 화이트리스트

- **목적**: 목록 밖 사용자는 유효 JWT 여도 차단(가입·API 우회 불가).
- **동작**: 게이트 = env(`BETA_WHITELIST_EMAILS`) ∪ DB(`beta_whitelist`, admin 관리) 합집합.
  항목: 이메일 또는 `@도메인`. 둘 다 비면 게이트 OFF(전면 허용=정식 오픈). **매 요청 검사** —
  목록에서 빼면 기발급 JWT 도 즉시 차단. ADMIN_EMAILS 항상 허용(운영자 잠금 방지). 짧은 TTL
  캐시, admin 변경 시 즉시 무효화.
- **진입**: 공개 `POST /beta/check`(가입 전 boolean 확인, 목록 미노출) · admin `GET/POST/DELETE
  /admin/whitelist`.
- **코드**: `src/middleware/auth.py`(`_beta_allowed`·`invalidate_whitelist_cache`) ·
  `src/persistence/whitelist_repo.py` · `src/routes/{beta,admin}.py`. 프런트 `src/lib/betaGate.ts`.

### 2.5 토큰 한도 (quota)

- **목적**: 사용자별 일/월 토큰 상한 → 비용 폭주 방지.
- **동작**: `QuotaMiddleware` 가 요청 전 잔여 확인, 초과 시 차단(events 에 `quota_blocked` 기록).
  시스템 기본값 + admin 사용자별 override(`-1` = 기본값 리셋).
- **집계 대상**: `events.llm_call` 의 in+out 토큰. **모든** LLM 호출이 잡힌다 —
  로거는 `build_chat_model()` 이 모델마다 붙이고(호출부가 잊을 수 없다), 사용자
  귀속은 진입점에서 심는 ambient 컨텍스트(`src/observability/usage_context.py`)가
  맡는다. 같은 run 이 두 번 계상되지 않도록 `run_id` dedupe(2026-08-05).
- **"하루"의 경계**: 사용자 자정 기준(`USAGE_DAY_UTC_OFFSET_HOURS`=9 → KST).
  종전 UTC 자정은 KST 오전 9시에 리셋돼 사용자가 하루를 어긋나게 봤다.
- **코드**: `src/middleware/quota.py` · admin `PATCH /admin/users/{id}`. **설정**:
  `DEFAULT_DAILY_TOKEN_LIMIT` · `DEFAULT_MONTHLY_TOKEN_LIMIT` ·
  `USAGE_DAY_UTC_OFFSET_HOURS`.

### 2.6 Rate limit + 보안 헤더

- **Rate limit**: IP·사용자별 분/시 상한(프로세스 로컬 슬라이딩 윈도). `src/middleware/rate_limit.py`.
  **설정**: `RATE_LIMIT_DISABLE` · `RATE_LIMIT_PER_IP_PER_MIN`(60) · `_PER_USER_PER_MIN`(30) ·
  `_PER_USER_PER_HOUR`(600). `/readyz` 등 LB 폴링 경로는 제외.
- **보안 헤더**: HSTS·X-Content-Type-Options·프레임 차단 등. `src/middleware/security_headers.py`.
- **CORS**: `API_CORS_ORIGINS` 화이트리스트. AuthMiddleware 가 OPTIONS preflight 를 통과시켜
  CORSMiddleware 가 응답 헤더를 붙이도록 함(순서 주의).

---

## 3. 계정 · 개인정보

### 3.1 회원 탈퇴(소프트 삭제) ↔ 완전 삭제(하드)

- **목적**: 탈퇴(즉시 접근 차단, 보유기간 후 파기)와 완전 삭제(지체 없이 파기, 법 제36조)를 분리.
- **동작**: `POST /me/withdraw` → `users.deleted_at` 마킹(행 보존, 소프트). 이후 접근은 403
  (upsert 가 되살리지 않음). `POST /me/erase` → 대화·보고서·이력 지체 없이 파기(하드, 되돌릴 수
  없음, 동의·삭제요구 기록만 증빙 보존). 관리자 `POST /admin/users/{id}/restore` 로 소프트 복구.
- **코드**: `src/persistence/users_repo.py`(`soft_delete`·`restore`·`deleted_at`) ·
  `src/routes/privacy.py` · `src/middleware/auth.py`(deleted_at 403). 정본 방침: `docs/legal/privacy.md`.

### 3.2 법적 고지 정본 서빙

- **동작**: 약관·개인정보처리방침의 **단일 진실원**은 `docs/legal/{terms,privacy}.md` — `GET /legal`
  (요약·버전) · `GET /legal/{doc}`(markdown 본문)로 서빙, 프런트가 렌더. 버전이 오르면 재동의.
- **주의**: 프런트에 본문을 하드코딩하면 두 벌이 되어 실제 동작과 어긋난다(과거 §3·§5 불일치 사고).

---

## 4. 운영 · 관리자

### 4.1 서버 점검(유지보수) 모드 ★신규

- **목적**: 매일 04:00 데이터 갱신 등 정비 중 **일반 사용자만 차단**(관리자는 접근 유지).
- **동작**: 켜지면 `AuthMiddleware` 가 비관리자 API 를 **503**(`{detail, maintenance:true}` +
  `Retry-After`), 관리자는 통과. 공개 라우트(health·load·legal·beta)는 계속 열려 프런트가
  점검 화면 표시. 상태는 `app_settings` DB(`maintenance` 키) — **재기동 생존**. 짧은 TTL(5s)
  캐시(외부 프로세스 변경도 반영), admin 변경 시 즉시 무효화.
- **두 트리거**(효과 = 둘 중 하나라도 참):
  - **수동**: 즉시 on/off.
  - **예약(매일 반복 시간대)**: `04:00~04:20`(KST) 식 설정 → 서버가 매 요청 시각 평가해 **매일
    자동 on/off**(크론 불필요). 자정 넘김 지원, 경계 반열림 `[start,end)`. 예약 평가는 비캐시
    (즉시 반영). tzdata 미설치 시 KST +9 폴백(DST 없어 정확).
- **진입**: 관리자 화면 *설정 > 서버 점검*(토글 + 예약) · `GET/POST /admin/maintenance` ·
  공개 `/load` 의 `maintenance` 필드 · CLI `scripts/maintenance.py on|off|status|schedule`.
- **코드**: `src/maintenance.py` · `src/persistence/settings_repo.py` · `src/routes/admin.py` ·
  `src/middleware/auth.py:_maintenance_block_or_none` · 프런트 `MaintenanceGate.tsx`.
- **주의**: env `MAINTENANCE_MODE`(프런트 middleware 리다이렉트, 재배포 필요)와 **별개·공존**.
  시간대 예약은 창을 고정 차단(갱신이 길어질 위험 있으면 여유 있게 잡거나 CLI 잡 래핑 병행).
  운영 절차: `runbook.md` §10-b.

### 4.2 관리자 API

- **사용자·한도**: `GET /admin/users`(목록+사용량) · `PATCH /admin/users/{id}`(일/월 한도·is_admin,
  `-1`=기본값 리셋) · `GET /admin/users/{id}/usage` · `POST /admin/users/{id}/restore`(탈퇴 복구).
- **화이트리스트**: `GET/POST/DELETE /admin/whitelist`(§2.4).
- **설정 뷰**: `GET /admin/config` — `ENV_REGISTRY` 읽기전용 뷰(시크릿은 설정 여부만, 값 미노출).
  변경은 `.env(.docker)` + 재기동.
- **통계**: `GET /admin/stats?days=N` — events 일별 집계(한국시간 날짜, llm_calls·active_users·in/out tokens·
  cost_usd·quota_blocked·citation_reports) + totals + 같은 기간 **실사용·내부·전체 비교**(`breakdown`).
  `events_repo.daily_stats` · `usage_weekly.compute_range`.
- **주간 이용**(2026-09-21): `GET /admin/stats/weekly` — 월~일(KST) 주 단위, 끝난 주는 스냅샷 저장
  (app_settings `usage_weekly:v1:*`, lifespan 이 6h 주기로 직전 2주 보장). 화면은 지난주 vs 그 전주
  타일·주별 누적 막대(실사용+내부)·표·CSV. 이벤트는 90일 뒤 정리되므로 **장기 추이의 원본은 스냅샷**.
  `src/usage_weekly.py` · `src/routes/admin_usage.py`.
- **주간 보고서 메일**(2026-09-21): 매주 월 09:00(KST) 이후 첫 점검(15분 주기)에 직전 주 보고서를
  `WEEKLY_REPORT_TO`(기본 admin@example.com)로 1회 발송 — HTML 본문(핵심 지표·전주 대비·8주 추이·
  **이번 주 업데이트**(관리자 전용 보고 노트 중 그 주·'포함' — 관리자 › 보고 노트, `src/report_notes.py`)·실사용자 **자유 의견** 원문·내부 트래픽 비중) + 첨부 `.html`·주간 지표 `.csv`·자유 의견 `.csv`. 실사용 기준, LLM 없음,
  **개인 단위 활동 명단은 싣지 않음**. 보낸 주는 app_settings `weekly_report_sent:*`(중복 방지, 전부 실패면 미기록→재시도).
  관리자 › 통계에 상태·[설정](켜기/끄기·요일·시각·수신자 — 저장값이 env 보다 우선, 재시작 불필요)·[미리보기]·[지금 보내기].
  스케줄은 **서버 안 주기 작업**(lifespan) — 별도 cron·스크립트 없음. `src/weekly_report.py`.
- **계정 구분**(2026-09-21): 사용자 관리 › 구분 — 운영진·테스트·실사용자 라벨(미지정=자동: 관리자 →
  운영진, 베타 오픈 전 가입 + 초대 명단에 없음 → 테스트). 운영진·테스트는 모든 관리자 화면의 "실사용"에서 빠진다.
  정본 `src/account_class.py`(스레드 단위 내부 판정 `is_internal_thread` 도 여기).
- **코드**: `src/routes/{admin,admin_usage}.py`. 프런트 `src/app/admin/{users,settings,stats,feedback}/` · `components/admin/usage/`.
- **주의**: FE 라우트 하드블록은 env 이중관리 락아웃 리스크로 제거 — 권위 경계는 백엔드
  `require_admin`(서버 JWT 검증). 메뉴 비노출은 UX 레벨(`session.user.isAdmin`).

### 4.3 관측 · 통계 수집

- **토큰 로거**: 전역 LLM 호출을 events(`llm_call`, in/out tokens·cost)로 캡처 →
  quota·admin 통계 원천. `src/observability/token_logger.py`. `DISABLE_TOKEN_LOGGER=1` 로 끔.
  채팅·보고서·grounding·auto-title·커버리지 판정 **전 경로** 포함(2026-08-05 —
  종전엔 셋이 미배선이라 이벤트가 아예 없었고, grounding 은 user_id 가 NULL 이었다).
  캡처 건전성은 `GET /admin/stats` 의 `usage_capture`(miss_ratio)로 본다.
- **보고서 품질 메트릭**: 보고서 1건당 events(`report_quality`) — writer/critique 모델·
  verified 비율·미검증/무근거 건수·무인용 수치 건수·소요시간. 모델 교체(gemma vs qwen)·
  게이트 개선의 효과 비교 원천. `report_pipeline._emit_report_quality`.
- **검색 진행 emit**: 검색 단계·혼잡을 SSE `tool_progress` 로. `src/observability/search_progress.py`.

---

### 4.4 답변 검수 — 정답성 사람 채점 (2026-09-17)

- **목적**: grounding·claim audit 은 "쓴 문장이 출처와 일치하나"까지만 잰다. **답이 맞는가**
  (조문 오적용·핵심 누락·시점 오류)를 사람이 채점해 정답률·개선 우선순위를 얻는다.
- **검수 큐**(`GET /admin/review-queue`): 두 갈래 표본. ① 위험 신호 점수순 — 인용 오류 신고·👎·
  서식번호 불일치·출처와 모순·강제검색인데 인용 없음·검색 0건·인용 검증률 <0.7·미검증 사실·잘림.
  ② 무작위 표본 — `message_id` 해시 고정 10%, **신호와 독립**. 정답률은 ②의 채점만으로 계산한다
  (①은 편향). IRB/DRB 스킬 턴은 `lane=skill` 로 분리 — 설계상 [n] 인용이 없어 인용 축 미적용.
- **채점**(`POST /admin/reviews`): 정확/부분정확/오답/판단불가 + 오류 유형(검색 실패·오적용·
  날조·시점·누락·기타) + 메모. 답변×검수자 upsert. **집계**(`/admin/reviews/stats`): 무작위 표본
  정답률(strict/lenient) + Wilson 95% CI, 오류 유형 분포.
- **채점 내용 보존**(2026-09-18): 채점 저장 시 그 턴의 질문·답변을 `answer_reviews.question_snapshot`·
  `answer_snapshot` 에 복사(대화 저장본=마스킹본, ≤20,000자, user_id 미포함). 대화는 90일 뒤 지워지지만
  채점한 턴은 근거가 남는다 — `GET /admin/reviews/archive`(`thread_alive`) · 검수 화면 "채점 내역".
  재채점 upsert 는 COALESCE 라 원 대화가 없어도 기존 스냅샷을 지우지 않는다. 미채점 턴은 종전대로
  90일 뒤 검수 불가. 방침 §3 보유기간 표에 "답변 품질 검수 표본" 행 추가(버전 미변경).
- **식별자 대조 감사**(`src/identifier_audit.py`): 답변의 `별지 제N호서식`·`별표 N` 이 이번 턴
  근거에 실재하는지 결정적 대조(LLM 무호출, done 뒤 비차단) → events `identifier_audit` → 큐 신호.
  사용자 비노출. 조문 번호는 범위 밖(실측 오탐만 늘어남). 짝: supervisor v30 서식번호 규율.
- **화면**: medi-front `/admin/reviews`. **코드**: `src/review_queue.py`(순수 선정 규칙) ·
  `src/routes/admin_reviews.py` · `src/persistence/answer_reviews_repo.py`.
  **설정**: `IDENT_AUDIT_DISABLE=1`.

## 5. 안정성 · 헬스 · 보존

### 5.1 `/readyz` readiness 헬스체크

- **동작**: `/healthz`(항상 200)와 달리 PG·검색API·Neo4j·PII NER·의도·writer 를 병렬 probe.
  critical(PG·검색API) 다운 시 **503**, 나머지는 non-critical(graceful degradation 이지만 **보이게**
  → 운영자 복구). critical/가드레일 다운 시 ops 알림 발화(dedup).
- **코드**: `src/routes/health.py`. **설정**: `READYZ_PROBE_TIMEOUT_S`(4). rate limit 제외.

### 5.2 장애 알림

- **동작**: critical 의존성 다운·가드레일 저하를 Slack 등 웹훅으로. dedup 으로 폴링 스팸 방지.
- **코드**: `src/observability/alerts.py:send_ops_alert`. **설정**: `OPS_ALERT_WEBHOOK_URL` ·
  `OPS_ALERT_DEDUP_S`(600).

### 5.3 동시성 제어 + 서버 부하 표시

- **목적**: 단일 GPU 공유로 동시 요청 thrash 방지(제어) + 느려도 사용자가 이해(표시).
- **동작**: 검색 백프레셔(`BoundedSemaphore`, `SEARCH_MAX_CONCURRENCY`=2, 캐시 히트 제외) +
  보고서 큐(`asyncio.Semaphore`, `REPORT_MAX_CONCURRENCY`=1) + per-thread 턴 락 + 전역 LLM RPS 캡.
  **전부 프로세스 로컬 → uvicorn `--workers 1` 고정**(멀티 워커 금지, CLAUDE.md §7).
- **표시**: `GET /load`(인증 X) → 프런트 '원활/혼잡' 배지 + 채팅 중 혼잡 진행 emit.
- **코드**: `src/retrieval/search_api_client.py` · `src/report_pipeline.py` · `src/llm_limits.py`
  · `src/observability/load.py`.

### 5.4 보존 정리 (개인정보 §3 이행)

- **대화(thread)**: 마지막 활동 90일 경과 → 메시지·steps 포함 완전 삭제(구 prune_checkpoints
  대체). `scripts/prune_threads.py`. **설정**: `CHAT_RETENTION_DAYS`(90) · `PRUNE_APPLY=1`.
- **보고서**: `created_at` 30일 경과 → blob 과 메타 행(목록·제목·요약·인용) **모두 삭제**(2026-09-23 —
  종전엔 메타를 남겨 열리지 않는 보고서가 사이드바에 떴다). 작성한 서식(`kind=doc`)은 제외(대화 cascade·보관이
  수명 결정). `report_runs` 이력은 남김. orphan blob 도 삭제. `scripts/prune_blobs.py`. **설정**:
  `BLOB_RETENTION_DAYS`(30) · `PRUNE_MAX`. `medi-cron` 이 일 1회 실행(기본 DRY_RUN).

### 5.5 Eval 하니스 (검색 품질 측정)

- **동작**: 라벨 질문셋으로 recall@k·precision@k·hit@k·MRR. 실버 라벨은 seed → LLM-judge 생성.
  리랭커 A/B(오프라인, 모델별 독립 프로세스 필수 — CUDA assert 연쇄 방지).
- **코드**: `src/eval/metrics.py` · `scripts/{eval_retrieval,build_eval_labels,ab_reranker}.py`.
- **베이스라인**(2026-07-09, 실버 20질의, fp16): hit@1 0.65·hit@3 0.85·hit@5 0.90·MRR 0.75.
  현행 리랭커 `bge-reranker-v2-m3` 최고(hit@1 0.80). ⚠️ 라벨이 top-15 유래라 recall 낙관 편향
  (회귀 비교엔 유효, 절대 정확도엔 gold 필요).

---

## 6. 개발 인프라

### 6.1 영속 (SQLite/PG dual)

- **동작**: 동일 인터페이스로 dev SQLite / prod Postgres 스위치(env 한 줄). repos: users·events·
  feedback·reports·report_runs·threads·whitelist·**settings**·blobs. thread 상태·보고서 메타·
  사용자·이벤트·화이트리스트·앱설정 전부 영속(재시작 생존).
- **코드**: `src/persistence/{...}_repo.py` · `_common.py`(SqliteRepoBase) · `_pg.py`(DDL·init_schema).
- **설정**: `REPORTS_BACKEND`(sqlite|postgres) · `REPORTS_SQLITE_PATH` · `REPORTS_PG_DSN` ·
  `BLOB_BACKEND`(local|gcs) · `BLOB_GCS_BUCKET`.
- **주의**: PG/GCS 는 prod stub 아닌 실 구현(`[prod]` extras). dev venv 에 psycopg 설치됨.

### 6.2 이메일 알림 + 보고서 DOCX 변환

- **동작**: 보고서 완료 시 사용자 이메일로 **전문 DOCX 첨부**(범용 SMTP, 미설정 시 stub·graceful,
  best-effort). `.md` 가 원본, DOCX 는 요청 시 pandoc(`pypandoc-binary`, 시스템 설치 불요) 변환 —
  헤더·굵게·중첩 번호목록·`[n]` 보존, 실패 시 `.md` 폴백. `GET /reports/{id}/download?format=md|docx`.
- **코드**: `src/reports_convert.py` · `src/observability/notifications.py` · `src/report_runner.py`.
- **설정**: `EMAIL_SERVER`(medi-front NextAuth 와 같은 URL 재사용, 권장) 또는 `SMTP_*` ·
  `SMTP_FROM` · `REPORT_ATTACH_FORMAT`(docx|md).

### 6.3 타입드 스키마 · 중앙 Config · 부팅 검증

- **스키마**: `Citation`/`Step` 을 `src/schemas.py` TypedDict 로 명시(런타임 dict 보존 + 타입 안전망).
  step 헬퍼·reducers 는 `src/steps.py`.
- **Config**: `src/config.py`(`ENV_REGISTRY` 단일 진실원 + 타입 접근자 + prod 검증). `scripts/
  check_config.py`(노브 한눈·시크릿 마스킹·prod 필수 누락). 부팅 lifespan 이 prod 필수 누락 시
  경고, `STRICT_CONFIG=1` 이면 부팅 차단.

### 6.4 모델 생성 · 한도

- **동작**: `build_chat_model(spec)` provider 직접 생성(init_chat_model 대체) + 폴백. 전역 LLM RPS
  캡(`src/llm_limits.py`). writer 는 로컬 vLLM(옵션, ImportError 가드).
- **코드**: `src/models.py` · `src/llm_limits.py`. **설정**: `LLM_MODEL` · `LLM_FALLBACK` ·
  `SUBAGENT_MODEL` · `MODEL_RETRY_MAX` · `RESILIENCE_DISABLE`.

---

## 부록 — 외부 의존 (DGX 서빙, Tailscale `192.0.2.10`)

| 서비스 | 포트 | 상시화 |
|---|---|---|
| 검색 API `/search`·`/articles/bodies` (KURE+BM25+RRF+fp16 리랭커) | 8080 | systemd `openlaw-search` |
| PII NER (KoELECTRA modu-ner) | 8090 | systemd `guardrail-ner` |
| 의도 분류 (Qwen3.5-0.8B) | 8091 | systemd `guardrail-intent` |
| 보고서 writer (vLLM — **모델 고정 아님**, /v1/models 자동 감지) | 8000 | docker |
| KURE 임베딩 (vLLM, 검색서버 내부용) | 8001 | docker |

**데이터 스토어**: openlaw PG/Mongo/Neo4j(ETL 소유, 읽기) · 운영 Postgres(users·events·feedback·
reports·threads·whitelist·settings, dev SQLite 폴백) · Blob(GCS/로컬, 보고서 `.md`).
**외부 서비스**: Anthropic Haiku-4-5(Sonnet 폴백) · Tavily · SMTP · NextAuth.


---

## 부록 — 2026-07-15~16 추가 기능 (UX 스프린트 1·2)

**근거 신뢰**: 답변 상단 근거 요약 바(구성·검증 X/Y·폐지/개정 경고) · 인용 현행성
배지(law.go.kr 개정상태 연동) · 별표/서식 칩+HWP 다운로드 · 검증 의미 명시.
**실무 산출물**: 인용 포함 복사 · Word(docx) 내보내기 · 인허가 절차 타임라인(단계 체크).
**근거 라이브러리**: 인용 북마크(폴더 정리) · 개정 알림(폐지/개정예정/시행일 변경) ·
헤더 벨 알림 센터.
**탐색·효율**: 대화 본문 전문검색 · 대화 고정(핀) · Ctrl+K 커맨드 팔레트(+최근 열람 조문).
**입력·개인화**: 설명 수준 토글(전문가/쉬움) · 구조화 질문 폼 · 보고서 목적 템플릿 ·
온보딩 투어 · 다크모드 · 사용량 상세 · PWA.
**엔진**: 별표/서식·판례 검색(ETL dense 필터 완화) · 웹 검색 강제 게이트 ·
LLM A/B 하네스(CHAT_MODEL_AB) · lawdangle 개정상태 enrich 소비.
상세: CHANGELOG 2026-07-15~16 · medi-front PATCHNOTE.
