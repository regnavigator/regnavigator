# 온보딩 — 이 시스템을 기술적으로 설명하기 위한 한 장

> 대상: 새로 합류했거나, 이 시스템을 남에게 **설명해야** 하는 사람.
> 여기 있는 건 요약이다. 각 절 끝의 링크가 정본이다. 최종 갱신 2026-08-10.

---

## 1. 서비스 정의

**MEDIREG AI** — 의사·RA/QA·인허가 컨설턴트가 의료기기·의약품 규제를 질문하면,
법령·행정규칙(고시)·자치법규(조례)·판례·법령해석례를 검색해 **출처(`[n]` 인용)가 박힌
한국어 답변**을 돌려주는 서비스. 현재 **v0.2.0 클로즈 베타**.

| | **fast (즉답)** | **deep (심층 보고서)** |
|---|---|---|
| 진입 | `POST /chat` (SSE) | `POST /reports` + `idempotency_key(^rpt_…)` → 폴링 |
| 소요 | 15~20초 (실측 TTFT ~17s / 총 ~26s) | 백그라운드 ~5–40분 (서빙 writer 모델 의존) |
| 엔진 | `src/chat_loop.py` 수동 tool-loop | `src/report_runner.py` asyncio 잡 |
| 출력 | 본문 + `[n]` 인용 + 신뢰도 배지 + 추천질문 | 컨설팅형 5섹션(개요·핵심결론·근거·실무액션·리스크/후속) |
| 전달 | SSE 스트리밍 | 사이드바·우측 패널 + 이메일(Word 첨부). **대화록엔 남지 않음** |

경쟁 서비스와 갈리는 지점은 세 가지다 — **검색 강제**, **grounding 검증**, **인용 현행성**
(폐지·개정예정 배지). 셋 다 "그럴듯한 답"이 아니라 "근거를 댈 수 있는 답"을 만들기 위한 장치다.

---

## 2. 토폴로지 — 네 덩어리

```
medi-front (Next.js)  ── NextAuth 로그인 / JWT 발급 (NEXTAUTH_SECRET 공유)
        │                 인증 DB: Postgres medi_auth (같은 PG 인스턴스)
        ▼ Authorization: Bearer <jwt>
medi-back (FastAPI · uvicorn --workers 1 · thin-client)
   미들웨어: CORS → Auth(JWT+베타 게이트) → RateLimit → Quota → SecurityHeaders
        ├── DGX (Tailscale 192.0.2.10) ── 무거운 AI 전부
        │      :8080 검색 API(KURE+BM25+RRF+fp16 리랭커) · :8090 PII NER
        │      :8091 의도분류(Qwen3.5-0.8B) · :8000 보고서 writer(vLLM) · :8001 임베딩
        ├── openlaw DB (GCP 192.0.2.20) ── ETL 소유, **읽기만**
        │      PG:5401 조문메타·전문 · Mongo:5402 본문 · Neo4j:5403 인용그래프 · Qdrant:5405 벡터
        └── 운영 Postgres + Blob(GCS) ── medi-back 소유(RW)
               users·events·feedback·reports·report_runs·whitelist·settings
               + chat thread 상태(threads_repo) / 보고서 .md
외부: Anthropic Haiku-4-5(Sonnet 폴백) · Tavily · SMTP
```

**배포**: medi-back·medi-front 가 **같은 GCP VM** 의 docker compose(`medi-net` 공유),
`main` push → GHA self-hosted runner 자동배포. DGX 는 Tailscale, 법령 DB 는 공인 IP.

정본: [`architecture.md`](./architecture.md) §1·§6 · 프런트는 medi-front `docs/ARCHITECTURE.md`.

---

## 3. fast 파이프라인 (한 턴에 실제로 일어나는 일)

1. **미들웨어** — JWT 검증 → 베타 화이트리스트(매 요청) → rate limit → 토큰 quota
2. **입력 게이트(병렬)** — `asyncio.gather` 로 두 DGX 호출을 겹친다
   - **PII**: regex(주민번호·전화·카드…) + NER(:8090, 이름·주소). 적용 지점 2곳 —
     **egress**(Anthropic·Tavily 전송 직전) + **at-rest**(threads_repo 저장 전)
   - **의도**: Qwen3.5-0.8B(:8091) 이진 분류 + 인사/재촉 휴리스틱
3. **검색 강제** — 규제 질의면 `tool_choice="qdrant_search"` **forced 바인딩**
4. **검색** — `/search` 1콜(dense KURE + BM25 → RRF → cross-encoder 리랭킹 → 법률종
   부스팅 → 조문 GROUP BY), `top_k=12`. 결과로 잠정 citation 빌드
5. **답변 스트리밍** — Haiku-4-5 가 `[n]` 마커를 붙여 토큰 emit. `done` 을 먼저 쏴서 체감 랙 제거
6. **grounding** — `done` 이후 trailing step 으로, 각 `[n]` 의 근거 문장을
   `/articles/bodies` 원문과 **substring 대조** → `verified` 부착 → 신뢰도 배지

정본: [`architecture.md`](./architecture.md) §2·§3 · [`features.md`](./features.md) §1.1·§1.5·§1.6

## 3-b. deep 파이프라인

멱등락(`report_runs`) → **decompose**(≤5 서브쿼리) → **gather**(RAG×N ‖ Tavily×N,
`top_k=20`, rag=T1/web=T3 tier 태깅) → **근거 충분성 게이트**(`REPORT_MIN_CITATIONS`=6
미달 시 1회 재수집, 그래도 미달이면 **run 실패**) → **로컬 vLLM writer 초안** →
**결정적 선행 검사**(초안 grounding + (법령명, 조번호) 페어 대조) → **critique(교차 모델
haiku) → revise** → **발행 게이트**(깨진 마커 정리·무인용 수치 로깅·기준일 stamp) →
최종 grounding → Blob(.md) + 운영 PG 메타 + 이메일(DOCX 첨부).

정본: [`architecture.md`](./architecture.md) §5 · [`features.md`](./features.md) §1.2

---

## 4. 설계 결정 5개와 그 근거 (설명할 때 제일 많이 물어보는 것)

| 결정 | 왜 |
|---|---|
| **thin-client** — 로컬 ML 0 | 검색 랭킹·NER·의도·writer 를 전부 DGX HTTP 로 밀어냄. medi-back 은 오케스트레이션·인용검증·채널분리만 소유 → 모델 교체가 배포와 분리된다 |
| **검색 강제** | 소형·고속 모델(Haiku)에게 "검색할지"를 맡기면 캐주얼·후속 어투에서 검색을 건너뛰고 **인용을 날조**한다(실측). 근거 확보를 모델 판단에서 분리 |
| **채널 분리** | References·다음 단계를 본문에 박지 않고 `<next_steps>` 마커 계약 + 전용 UI 로. 본문은 답변만, 부가정보는 구조화된 채널로 |
| **워커 1개 고정** | 검색 백프레셔(2)·보고서 큐(1)·per-thread 턴 락·전역 LLM RPS 캡이 **전부 프로세스 로컬**. 2026-08-04 부터 PG 어드바이저리 락으로 런타임 강제(2번째 인스턴스는 부팅 거부) |
| **소유권 경계** | 법령 DB 는 openlaw-etl 소유(medi-back 읽기 전용), 앱 데이터는 medi-back 소유. RAG 는 반드시 검색 API 경유 — Qdrant 직접 접속 없음 |

추가 근거: `spec/ADR-0001-*`(langgraph 은퇴), 검색 강제 근거는 `architecture.md` 「왜 검색을 강제하나」.

---

## 5. 자주 틀리는 6가지

1. **Postgres 가 두 개** — openlaw PG(법령, 읽기 전용, `PG_*`) ≠ 운영 PG(`REPORTS_PG_DSN`, 앱 데이터+대화상태)
2. **Qdrant 에 직접 붙지 않는다** — 검색 API(:8080) 뒤에 숨어 있음. 임베딩·리랭커도 마찬가지
3. **writer 모델은 고정이 아니다** — `/v1/models` 자동 감지(Qwen3.5-27B·Gemma-4-31B 등 교체 실험 중). 보고서 소요시간이 5~40분으로 흔들리는 이유
4. **보고서 트리거는 자유 텍스트가 아니다** — `POST /reports` + `^rpt_…` 멱등키. 채팅으로 "보고서 써줘"는 트리거가 아님
5. **보고서는 대화록에 안 남는다**(2026-07-25 분리) — 구 계약(`kind:"report_overview"` append)은 폐지
6. **`/readyz` 의 postgres down(degraded)** — dev 에선 정상(SQLite 폴백). 채팅·RAG·조문 조회 전부 동작

---

## 6. 알아야 하는 개념 (모르면 코드가 안 읽힌다)

**도메인** — 법 → 시행령 → 시행규칙 → 고시/공고 → 조례 위계 / 코퍼스 5종 코드
`law`·`admrul`·`ordin`·`prec`·`expc` / 개정상태(`amend_status`)가 왜 치명적인지
(폐지 조문 근거로 인허가 진행 = 사고) / 해석례가 RA 실무에서 갖는 무게

**검색** — dense(임베딩) vs sparse(BM25) / **RRF** 융합 / **cross-encoder 리랭커**(bi-encoder
와 뭐가 다른지) / `article_key`(PG 7자리 ↔ Neo4j 6자리 prefix 매칭) / 평가 지표
recall@k·hit@1·MRR (베이스라인 hit@1 0.65·MRR 0.75) / `top_k=12` 인 이유(8이면 법령이
상위를 독식해 판례·해석례가 밀림)

**LLM 엔지니어링** — tool-loop(`bind_tools` + while) / `tool_choice` 강제 바인딩 /
**grounding**(생성문 ↔ 원문 대조) / `[n]` 인용 계약 / 프롬프트 캐싱 / 대화 압축 /
교차 모델 critique→revise(자기검수와 다른 이유)

**인프라** — SSE 이벤트 8종(`meta`·`pii_notice`·`token`·`tool_progress`·`step_lifecycle`·
`steps`·`clarify`·`error`·`done`) / 멱등키 / 세마포어 백프레셔 / NextAuth JWT 공유 /
SQLite·PG dual repo / Tailscale

**규제·개인정보** — PIPA 국외 이전 별도 동의(§28의8) / 파기(§36) → 소프트 탈퇴 vs 하드 삭제 /
PII 2지점 마스킹 / 클로즈 베타 화이트리스트 / 유지보수 모드

---

## 7. 읽는 순서

| 시간 | 경로 |
|---|---|
| 5분 | 본 문서 §1~§2 |
| 30분 | 본 문서 전체 → [`architecture.md`](./architecture.md) → [`features.md`](./features.md) §0~§1 |
| 개발 합류 | 위 + [`../CLAUDE.md`](../../CLAUDE.md)(주의 10개조) → `src/chat_loop.py` 정독 → [`frontend_chat_v2.md`](../contracts/frontend_chat_v2.md) |
| 운영 인수 | [`startup.md`](./startup.md) → [`runbook.md`](../ops/runbook.md) → [`audit_2026-08-04.md`](../reports/audit_2026-08-04.md) |
| 프런트 | medi-front [`docs/ARCHITECTURE.md`](../../../medi-front/docs/ARCHITECTURE.md) → `docs/PATCHNOTE.md` |

## 8. 30초 요약 (그대로 말해도 되는 문장)

> "의료 규제 질문을 받으면 법령·고시·판례·해석례 코퍼스를 하이브리드 검색(임베딩+BM25+
> 리랭커)해서, 근거를 먼저 확보한 뒤 답을 생성하는 RAG 백엔드입니다. 모델이 검색을
> 건너뛰지 못하도록 tool 호출을 강제하고, 생성된 답의 인용은 법령 원문과 대조해
> 검증 표시를 붙입니다. 무거운 추론(검색 랭킹·PII NER·의도분류·보고서 생성)은 전부
> 로컬 GPU 서버(DGX)로 위임하고, API 서버는 오케스트레이션과 근거 검증만 합니다.
> 심층 질의는 백그라운드 잡으로 분해→수집→작성→교차검수를 거쳐 보고서로 나갑니다."
