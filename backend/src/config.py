"""중앙 설정 — env 노브를 한곳에 문서화 + 타입 접근 + prod 검증.

기존엔 `os.getenv(...)` 가 ~129곳에 흩어져 "어떤 노브가 있나"를 grep 해야 했다.
이 모듈이 **단일 진실원**: 모든 주요 env 를 `ENV_REGISTRY` 로 문서화하고, 타입
접근자(`settings.*`)와 부팅 검증(`missing_prod_required`)을 제공한다.

점진 채택(저위험): 기존 사이트는 그대로, **신규·핵심 경로부터** `settings` 로 읽는다.
env 는 캐시하지 않고 호출 시 읽음(테스트 monkeypatch 안전).

운영 점검: `python scripts/check_config.py`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    key: str
    default: str | None
    group: str
    doc: str
    prod_required: bool = False
    secret: bool = False


# ── 노브 레지스트리 (단일 진실원) ───────────────────────────────────
ENV_REGISTRY: tuple[Setting, ...] = (
    # auth / security
    Setting("NEXTAUTH_SECRET", None, "auth", "NextAuth JWT 검증 시크릿", prod_required=True, secret=True),
    Setting("ADMIN_EMAILS", None, "auth", "admin 자동 부여 이메일(콤마)"),
    Setting("ROOT_ADMIN_EMAILS", "admin@example.com", "auth",
            "루트 관리자(콤마) — ADMIN_EMAILS 와 무관하게 항상 admin, 강등·비활성화 불가. 프런트 NEXT_PUBLIC_ROOT_ADMIN_EMAIL 과 맞출 것"),
    Setting("BETA_WHITELIST_EMAILS", None, "auth",
            "클로즈 베타 화이트리스트(콤마) — 이메일 또는 @도메인. 미설정=전면 허용, ADMIN_EMAILS 항상 허용"),
    Setting("CONSENT_ENFORCE", "1", "auth", "0이면 질문·보고서 요청의 서버측 동의 확인을 끔(긴급 우회용) — 기본 켬, 관리자는 항상 예외"),
    Setting("BETA_GATE", None, "auth", "1이면 화이트리스트 비어도 게이트 강제 활성(전면 차단, ADMIN 제외) — 클로즈 베타 가입 차단"),
    Setting("AUTH_DEV_BYPASS_USER", None, "auth", "dev 자동로그인 이메일"),
    Setting("API_TOKEN", None, "auth", "보고서 라우트 Bearer 토큰(운영)", secret=True),
    # llm
    Setting("ANTHROPIC_API_KEY", None, "llm", "Anthropic 키", prod_required=True, secret=True),
    Setting("OPENAI_API_KEY", None, "llm", "OpenAI 폴백 키", secret=True),
    Setting("LLM_MODEL", "anthropic:claude-sonnet-4-6", "llm", "supervisor 모델"),
    Setting("SUBAGENT_MODEL", None, "llm", "서브에이전트·요약·grounding 모델(기본 haiku)"),
    Setting("LLM_FALLBACK", None, "llm", "1차 모델 오류 시 폴백 스펙"),
    Setting("MAX_MODEL_CALLS_PER_RUN", "250", "llm", "run당 모델 호출 상한"),
    # 자체 /chat 루프 (ADR-0001 Phase 1~2 — langgraph 병행 PoC)
    Setting("CHAT_LOOP_DISABLE", None, "chatloop", "1=POST /chat 자체 루프 비활성(404)"),
    Setting("CHAT_MAX_TOKENS", "4096", "chatloop", "채팅 답변 최대 출력 토큰"),
    Setting("APP_GIT_SHA", "unknown", "ops",
            "배포 식별(2026-09-15) — Dockerfile ARG→ENV 로 박히는 커밋 short sha. "
            "deploy.yml 이 넘김. GET /admin/build 가 노출(관리자 헤더 '최종 배포')"),
    Setting("APP_BUILD_TIME", None, "ops",
            "배포 식별 — 이미지 빌드 UTC 시각(ISO). 미설정=로컬 dev/옛 이미지"),
    Setting("CHAT_AUTO_CONTINUE_MAX", "2", "chatloop",
            "max_tokens 잘림 시 자동 이어쓰기 최대 횟수(0=끔) — 초과 시 FE [이어서 작성] 버튼"),
    Setting("CHAT_MODEL_OVERRIDE_ALLOW", None, "chatloop", "1=요청 body 의 model 오버라이드 허용(dev/벤치)"),
    Setting("CHAT_SUMMARY_TRIGGER_TOKENS", "60000", "chatloop",
            "대화 압축 트리거(추정 토큰, 0=끔). 24,000→60,000(2026-09-14): 첨부 상한 "
            "120,000자(≈4만 토큰 추정) 문서가 후속 턴에서 요약으로 대체되지 않게"),
    Setting("CHAT_MAX_INPUT_CHARS", "32000", "chatloop",
            "채팅 1턴 입력 상한(문자). 서버측 윈도잉 배포 후 상향(12,000→32,000) — "
            "실측 36,754자 7.0초에 이름 3/3 마스킹(2026-08-04)"),
    Setting("CHAT_SUMMARY_KEEP_TURNS", "2", "chatloop", "압축 시 원문 유지할 최근 턴 수"),
    Setting("CHAT_SUMMARY_MODEL", None, "chatloop", "압축 요약 모델(미설정=SUBAGENT_MODEL→haiku)"),
    Setting("CHAT_PROMPT_CACHE_DISABLE", None, "chatloop", "1=시스템 프롬프트 캐싱 끔(기본 ON — Haiku는 프리픽스가 임계 미만이면 무효과)"),
    Setting("CHAT_PROMPT_CACHE_TTL", "1h", "chatloop", "프롬프트 캐시 TTL(1h|5m) — 1h 는 쓰기 2×지만 성긴 트래픽에서 상시 히트(2026-08-14)"),
    Setting("PROMPT_WARM_INTERVAL_S", "2700", "chatloop", "프롬프트 캐시 웜핑 주기 초(0=끔) — 1차 LLM 콜 콜드 프리픽스(6~7s) 방지"),
    Setting("READYZ_NER_SLOW_S", "2.5", "guardrail", "readyz NER 실추론 지연 임계 초 — 초과 시 degraded 보고+운영 알림(GPU 경합 감지)"),
    Setting("CHAT_SSE_HEARTBEAT_S", "15", "chatloop", "SSE 무이벤트 구간 ping 주기(초) — FE 60s 무수신 타임아웃 방지"),
    # 파일 업로드 v1 (2026-08-05) — POST /files/extract + /chat attachments
    Setting("FILE_MAX_UPLOAD_MB", "15", "chatloop", "첨부 파일 업로드 크기 상한(MB)"),
    Setting("FILE_MAX_EXTRACT_CHARS", "120000", "chatloop",
            "첨부 추출 텍스트 상한(문자) — 초과분 truncated=True 로 잘라 반환. "
            "30,000→120,000(2026-09-14): 임상시험계획서 50쪽 안팎(≈10만 자)을 통째로. "
            "NER 교체(8/14 KoELECTRA) 후 실측 120,000자 1.2s 라 PII 병목 해소"),
    Setting("CHAT_MAX_ATTACHMENTS", "3", "chatloop", "채팅 1턴 첨부 개수 상한"),
    Setting("CHAT_MAX_TOTAL_INPUT_CHARS", "150000", "chatloop",
            "본문+첨부 합산 문자 상한. 60,000→150,000(2026-09-14, 계획서+보완공문 동반). "
            "PII NER 실측 150,000자 1.8s·300,000자 3.2s — 남은 제약은 모델 컨텍스트·"
            "턴당 토큰 비용(≈5~8만 토큰/턴)"),
    Setting("CHAT_GUIDE_TOP_K", "4", "chatloop", "채팅 기본 검색에 병렬 합류하는 가이드라인(guide) top_k. 0=끔(cue·모델지목만)"),
    Setting("CHAT_FORCE_WEB", "1", "chatloop", "규제 질의에서 qdrant 검색 뒤 tavily 웹검색 1회 강제(기본 ON). 0=모델 재량(웹 인용 드묾)"),
    Setting("CHAT_MODEL_AB", None, "chatloop", "LLM A/B 테스트 — 'specA|specB'(예: anthropic:claude-haiku-4-5-20251001|anthropic:claude-sonnet-5). user 해시로 변형 배정, events(model_ab)에 태깅. 미설정=단일 모델"),
    Setting("CHAT_URL_ENFORCE_DISABLE", None, "chatloop",
            "1=본문 URL 강제 끔(레지스트리 밖 링크 제거·정본 교정). 끄면 모델이 "
            "쓴 링크가 검증 없이 그대로 나간다 — 실측 오안내 재발 위험"),
    Setting("COVERAGE_JUDGE_MAX_CITES", "35", "chatloop",
            "이 건수 이상 근거를 이미 확보했으면 3층 LLM 커버리지 판정 스킵"
            "(판정 1콜+추가 검색 라운드로 턴당 ~6s — 근거가 충분한 턴엔 낭비)"),
    Setting("APPLICABILITY_JUDGE_DISABLE", "", "chatloop",
            "1=적용가능성 판정(하이쿠 1콜) 끔. 규칙이 못 잡는 '닮았지만 적용 안 되는' "
            "근거가 인용에 남는다"),
    Setting("COVERAGE_JUDGE_ENABLE", "1", "chatloop",
            "1=근거 커버리지 LLM 판정(3층, Haiku 1콜) 활성. 0=규칙(0건 재검색·명시 종별)만"),
    # 기관 내부 지침 스킬 (IRB/DRB — src/skills/, 2026-08-10)
    Setting("SKILL_BUNDLE_DIR", None, "skills",
            "스킬 번들 경로(예: src/skills/medireg_irb_drb). 미설정=기능 자체 비활성 — "
            "카탈로그·도구·강제 전부 미부착, 기존 채팅과 완전 동일"),
    Setting("SKILL_LOCAL_MODEL", None, "skills",
            "1 이면 IRB/DRB 스킬 턴을 온프레미스 vLLM(writer 슬롯)으로 라우팅 — "
            "상용 모델 노출 제거(2026-08-28). 전제: vLLM 이 tool-calling 지원 "
            "(--enable-auto-tool-choice --tool-call-parser hermes). 로컬 다운 시 "
            "상용 폴백 없이 안내 후 턴 종료"),
    Setting("SKILL_LOCAL_BASE_URL", None, "skills",
            "스킬 턴 로컬 모델 base URL. 미설정 시 REPORT_WRITER_BASE_URL 공유"),
    Setting("SKILL_LOCAL_MAX_TOKENS", "8192", "skills",
            "스킬 턴 로컬 모델 최대 출력 토큰. 판정 답변(경로표·IRB+DRB·<verdict> "
            "블록)이 CHAT_MAX_TOKENS(4096)에서 잘리면 말미 verdict 블록이 사라져 "
            "판정 로그·가드가 동작하지 않는다(2026-09-15 e2e 실측)"),
    Setting("REPORT_DYNAMIC_OUTLINE", "1", "reports",
            "1(기본)=보고서 본론 목차를 질문 형태에 맞게 동적 설계(서론·결론 "
            "고정). 실패 시 자동으로 기존 5섹션 폴백. 0=항상 고정 5섹션"),
    Setting("REPORT_YIELD_HOLD_S", "45", "reports",
            "대화형 로컬 호출 후 이 시간(초) 동안 보고서 writer 가 다음 섹션 "
            "시작을 양보(GPU 공유 우선순위)"),
    Setting("REPORT_YIELD_MAX_S", "300", "reports",
            "보고서 양보 상한(초) — 대화형 연속 유입에도 보고서가 무한정 굶지 "
            "않게"),
    Setting("SKILL_WHITELIST_EMAILS", None, "skills",
            "스킬 노출 화이트리스트(콤마) — 이메일 또는 @도메인. 미설정=전면 허용. "
            "단일 기관 번들이므로 운영에선 해당 기관 도메인으로 잠글 것"),
    # RAG 검색 — openlaw-etl /search API (랭킹·인용메타·grounding 원문 서버 담당)
    # 검색 API 는 코어 — 없으면 RAG 가 전면 실패한다. prod 부팅 시 fail-fast.
    # (2026-07-09: docker-compose 에 이 키가 아예 없어 배포 시 검색이 죽는 버그가 있었음.)
    Setting("RAG_SEARCH_API_URL", None, "search", "검색 API 베이스 URL(예 http://host:8080)",
            prod_required=True),
    Setting("RAG_SEARCH_API_KEY", None, "search", "검색 API X-API-Key",
            prod_required=True, secret=True),
    Setting("RAG_SEARCH_TIMEOUT_S", "20", "search", "검색 API 타임아웃(리랭커 콜드 대비)"),
    Setting("RAG_SEARCH_TARGET_TYPES", None, "search",
            "검색 종별 CSV 재정의. **미설정(권장)이면 서버 GET /search/health 로 지금 서빙 중인 종별을 "
            "조회해 쓴다**(10분 캐시, 실패 시 law,admrul,ordin,prec,expc 폴백). 운영자가 일부러 좁힐 때만"),
    Setting("SEARCH_MAX_CONCURRENCY", "2", "search", "동시 /search 호출 상한(백프레셔 — GPU thrash 방지)"),
    Setting("SEARCH_WAIT_TIMEOUT_S", "30", "search",
            "검색 슬롯 대기 상한(초). 초과 시 거절 — 무한 대기가 스레드풀을 고갈시켜 전 요청을 멈추던 것 차단"),
    Setting("PII_GATE_ALLOW_NO_NER", "0", "guardrail",
            "1=NER 미설정을 명시 허용(dev 전용). 0(기본)=미설정이면 strict 게이트가 입력을 차단"),
    Setting("LOG_LEVEL", "INFO", "ops", "앱 로거 레벨(DEBUG/INFO/WARNING). root 핸들러에 적용"),
    Setting("SEARCH_KEEPALIVE_S", "240", "search", "리랭커 웜핑 주기 초(0=끔) — 콜드 검색 방지"),
    Setting("SEARCH_INCLUDE_PENDING", "1", "search",
            "1=같은 조문의 시행예정본을 현행 hit 뒤에 동반 요청(0=현행만). "
            "서버 미배포 시 조용히 생략되므로 켠 채 안전"),
    Setting("SOURCE_FILTER_DISABLE", "", "search",
            "1=출처 적합성 필터 끔 ⚠️ 의미는 닮았으나 적용되지 않는 법령"
            "(타 지자체 조례·타 대상 특별법 등)이 인용에 그대로 섞인다"),
    Setting("SOURCE_FILTER_TAIL_RATIO", "0.12", "search",
            "점수 꼬리 컷 — 최고점 대비 이 비율 미만이면 제외(음수 점수는 항상 제외)"),
    Setting("QDRANT_TOP_K", "12", "search", "검색 top_k(반환 조문 수). 서버 rerank_pool=25 이내 — GPU 무관, 리랭킹 후 슬라이스"),
    # guardrail (입력 게이트)
    Setting("PII_GATE_DISABLE", None, "guardrail", "1=입력 PII 스크럽 게이트 끔"),
    Setting("PII_GATE_STRICT", "1", "guardrail",
            "1(기본)=문맥 PII(이름·주소) 검사가 입력 전 구간을 못 덮으면 **차단**. "
            "0=경고만 남기고 통과(fail-open) — 끄면 미마스킹 PII 가 저장·전송될 수 있다"),
    Setting("PII_NER_API_URL", None, "guardrail", "PII NER 서비스 URL(미설정=regex-only)"),
    Setting("PII_NER_API_KEY", None, "guardrail", "PII NER X-API-Key", secret=True),
    Setting("PII_NER_TIMEOUT_S", "3", "guardrail", "PII NER 타임아웃(입구 저지연)"),
    # 긴 입력 분할 — 서버 파이프라인이 512토큰 상한이라 통째로 보내면 뒷부분이
    # 조용히 미탐된다(문서 붙여넣기 = PII 확률 최고 입력).
    Setting("PII_NER_CHUNK_CHARS", "600", "guardrail",
            "PII NER 청크 크기(문자) — 모델 512토큰 상한을 한국어 최악비율로 환산"),
    Setting("PII_NER_CHUNK_OVERLAP", "100", "guardrail",
            "청크 겹침(문자) — 경계에 걸친 이름·주소가 한쪽엔 온전히 들어가게"),
    Setting("PII_NER_MAX_PARALLEL", "2", "guardrail",
            "청크 동시 요청 수. 동시 요청 = 동시 활성화 메모리 — 8/4 호스트 OOM 후 4→2"),
    Setting("PII_NER_TOTAL_BUDGET_S", "30", "guardrail",
            "긴 입력 전체 스캔 벽시계 예산(초, 0=무제한). 초과분은 포기하고 진행 — "
            "미완료 청크는 경고로 드러난다. 없으면 입구 지연이 무제한(실측 55.8s). "
            "15→30(2026-09-14): 입력 상한 150,000자 상향에 맞춘 GPU 경합 여유"),
    Setting("PII_NER_MIN_SCORE_NAME", None, "guardrail",
            "NER [이름] 마스킹 신뢰도 하한(0~1, 미설정=끔). 일반명사가 이름으로 새는 "
            "오탐 억제용 — 서버 NER_THRESHOLD(0.4) 위 2차 기준. 로그 'ner mask' score 분포 보고 조정"),
    Setting("PII_NER_MIN_SCORE_ADDRESS", None, "guardrail",
            "NER [주소] 마스킹 신뢰도 하한(0~1, 미설정=끔)"),
    Setting("PII_NER_MIN_SCORE", None, "guardrail",
            "위 라벨별 값 미설정 시 공통 하한(0~1, 미설정=끔)"),
    Setting("INTENT_SEARCH_DISABLE", None, "guardrail", "1=규제 의도 검색강제 끔"),
    Setting("INTENT_MAX_INPUT_CHARS", "2000", "guardrail",
            "의도 분류기 입력 상한(문자). 초과 시 앞뒤만 남기고 가운데 생략 — "
            "문서를 통째로 보내면 타임아웃으로 판정이 무력화된다"),
    Setting("INTENT_API_URL", None, "guardrail", "의도 분류 서비스 URL(미설정=휴리스틱)"),
    Setting("INTENT_API_KEY", None, "guardrail", "의도 분류 X-API-Key", secret=True),
    Setting("INTENT_TIMEOUT_S", "1", "guardrail", "의도 분류 타임아웃(입구 저지연)"),
    # 판단 모델(2026-10-06, `src/judgment.py`) — state+타입 질문 → 확률. 측정 전엔 events 적재만.
    Setting("JUDGE_LOCAL_BASE_URL", None, "guardrail",
            "원내 판단 모델(Ollama ≥0.35 /v1/systemone, Kev-4B 등). 기밀 턴은 이것만 쓴다"),
    Setting("JUDGE_API_URL", None, "guardrail", "상용 판단 모델(TypeSafe Jev) base URL"),
    Setting("JUDGE_API_KEY", None, "guardrail", "상용 판단 모델 Bearer 키", secret=True),
    Setting("JUDGE_TIMEOUT_S", "2", "guardrail", "판단 모델 타임아웃"),
    # postgres / neo4j / mongo
    Setting("PG_HOST", None, "datastore", "openlaw PG 호스트(없으면 PG 비활성)"),
    Setting("PG_PORT", "5432", "datastore", "PG 포트"),
    Setting("PG_NAME", "openlaw", "datastore", "PG DB명"),
    Setting("PG_USER", None, "datastore", "PG 사용자", secret=True),
    Setting("PG_PASS", None, "datastore", "PG 비밀번호", secret=True),
    Setting("NEO4J_URI", None, "datastore", "Neo4j bolt URI(법률그래프·별표)"),
    Setting("NEO4J_USER", None, "datastore", "Neo4j 사용자", secret=True),
    Setting("NEO4J_PASS", None, "datastore", "Neo4j 비밀번호", secret=True),
    # 이메일 알림(SMTP — 보고서 완료 등). 미설정 시 stub(로그만).
    # EMAIL_SERVER 가 우선 — medi-front(NextAuth·nodemailer)와 **같은 값 재사용**.
    Setting("EMAIL_SERVER", None, "notify",
            "smtps://user:pass@host:465 (medi-front 와 공유). 있으면 SMTP_* 무시. "
            "포트 465 면 scheme 이 smtp 여도 암묵적 TLS 로 접속", secret=True),
    Setting("EMAIL_FROM", None, "notify",
            "발신 주소(EMAIL_SERVER 와 짝, medi-front 와 공유). SMTP_FROM 다음 우선 — "
            "미설정 시 계정 user 가 이메일 형태일 때만 발신자로 사용"),
    Setting("SMTP_HOST", None, "notify", "SMTP 호스트(EMAIL_SERVER 없을 때). 예 smtp.gmail.com"),
    Setting("SMTP_PORT", "587", "notify", "SMTP 포트(587 STARTTLS / 465 SSL)"),
    Setting("SMTP_USER", None, "notify", "SMTP 사용자", secret=True),
    Setting("SMTP_PASS", None, "notify", "SMTP 비밀번호/앱비번", secret=True),
    Setting("SMTP_FROM", "MEDIREG AI <noreply@example.com>", "notify",
            "발신자(From). EMAIL_FROM 보다 우선. 표시명 형식 허용 — 받은편지함에 "
            "`noreply` 대신 서비스명이 보이게(2026-09-14 운영 결정, 모든 백엔드 메일 공통)"),
    Setting("SMTP_SSL", None, "notify", "1=SSL(465), 미설정=STARTTLS(587)"),
    Setting("APP_URL", "https://app.example.com", "notify", "서비스 공개 URL — 메일 본문 링크(공지·주간 보고서)"),
    Setting("SUPPORT_EMAIL", "admin@example.com", "notify", "사용자 문의 안내 주소(계정 삭제 완료 메일 등)"),
    Setting("EVENT_CONTENT_RETENTION_DAYS", None, "datastore",
            "이벤트 중 **내용**(질문·검색어·코멘트) 보존일 — 미설정 시 CHAT_RETENTION_DAYS(90)"),
    Setting("EVENT_METRIC_RETENTION_DAYS", "90", "datastore",
            "이벤트 중 **지표**(토큰·비용) 비식별화 시점(일). 행은 남기고 식별자만 제거 — 통계 보존"),
    Setting("NOTICE_REPLY_TO", None, "notify",
            "공지·알림 메일 회신 주소(Reply-To). From 은 발송 도메인(noreply@…)이라 "
            "미설정 시 답장이 아무에게도 안 간다 — 문의 안내가 있는 메일엔 필수"),
    Setting("NOTICE_SCHEDULER_INTERVAL_S", "60", "notify",
            "예약 공지 발송 루프 주기(초). 0=비활성(예약이 영영 안 나감). 워커 1개 전제"),
    # 검색 캐시
    Setting("SEARCH_CACHE_SIZE", "512", "cache", "검색 결과 캐시 크기"),
    Setting("SEARCH_CACHE_TTL_S", "3600", "cache", "검색 캐시 TTL"),
    # 보고서
    Setting("REPORT_DEADLINE_S", "300", "report", "보고서 전체 데드라인(로컬 writer 시 상향)"),
    Setting("REPORT_MAX_CONCURRENCY", "1", "report", "writer(27B) 동시 실행 상한 — 단일 GPU 보호(초과 대기)"),
    Setting("REPORT_ATTACH_FORMAT", "docx", "report", "완료 이메일 첨부 포맷(docx|md). 변환 불가 시 md 폴백"),
    Setting("BLOB_RETENTION_DAYS", "30", "report", "보고서 보존일 — 만료 시 전문·메타(목록·제목) 모두 삭제. 작성한 서식(doc)은 제외"),
    Setting("CHAT_RETENTION_DAYS", "90", "chatloop", "대화(thread) 보존일 — 마지막 활동 기준, prune_threads 자동 파기(방침 §3)"),
    Setting("REPORT_SOURCE_TIMEOUT_S", "60", "report", "소스 수집 per-source 타임아웃"),
    Setting("REPORT_DECOMPOSE_MODEL", None, "report", "질의 분해 모델(미설정=SUBAGENT_MODEL)"),
    Setting("REPORT_GROUND_MODEL", None, "report", "보고서 grounding 모델(미설정=haiku)"),
    Setting("REPORT_CRITIQUE_MODEL", None, "report", "보고서 비평(검수) 교차 모델(미설정=haiku 교차검수, self=writer 자기검수)"),
    Setting("REPORT_TIER_UPGRADE_MAX", "3", "report", "웹(T3) 언급 조문의 T1(법령 원문) 승격 표적 재검색 상한. 0=끔"),
    Setting("REPORT_STALE_AFTER_S", "10800", "report", "running run 을 죽은 것으로 보는 임계(초) — 실소요 상한(큐+정비 대기+writer 2회) 이상이어야 오탐 없음"),
    Setting("REPORT_WRITER_BASE_URL", None, "report", "writer 로컬 vLLM /v1 URL(미설정=Sonnet)"),
    Setting("REPORT_WRITER_MODEL", None, "report", "writer 모델 id(미설정=/v1/models 서빙 모델 자동 감지)"),
    Setting("REPORT_WRITER_API_KEY", None, "report", "writer vLLM 인증", secret=True),
    Setting("ANNEX_VIEW_CACHE_DIR", None, "report", "별표·서식 뷰어 HTML 디스크 캐시 디렉터리(미설정=임시 폴더, 2026-09-08)"),
    Setting("REPORT_WRITER_PROBE_TTL_S", "30", "report", "writer 도달 프로브 캐시(초) — /load reports.writer_up(2026-09-07)"),
    Setting("REPORT_WRITER_TIMEOUT_S", "1800", "report", "writer 요청 타임아웃 — 초장기 허용(챗 우선 정책, DGX 점유 억제 시 느려짐)"),
    Setting("REPORT_WRITER_STREAM_CHUNK_TIMEOUT_S", "900", "report",
            "writer 스트림 **콘텐츠 침묵** 상한(초). langchain-openai 기본 120s 는 "
            "긴 prefill 에서 오폭발(2026-08-02 보고서 실패) — 0=비활성"),
    Setting("REPORT_WRITER_MAX_TOKENS", "8000", "report", "writer 최대 출력 토큰(심층 보고서)"),
    Setting("REPORT_SECTIONED", "1", "report",
            "1=섹션 분할 작성(기본, 분량 확대) · 0=구 단발 writer"),
    Setting("REPORT_SECTION_TARGET_CHARS", "4000", "report",
            "섹션 1개 기본 목표 글자수(배분 배수 합산이 총 분량 — 기본 ~18,000자)"),
    Setting("REPORT_MAX_QUERIES", "5", "report", "분해 쿼리 상한(하위질문 수)"),
    Setting("REPORT_MAINT_WAIT_MAX_S", "2700", "report", "새벽 갱신/점검 구간 보고서 대기 상한(초) — 잡을 죽이지 않고 pause/resume"),
    Setting("REPORT_SEARCH_MAX_CONCURRENCY", "1", "report", "보고서 rag 동시 검색 상한 — 채팅 우선 레인(전역 슬롯 중 1개를 채팅 몫으로 보장). 0=끔"),
    Setting("REPORT_QDRANT_TOP_K", "20", "report", "보고서 수집 top_k(채팅보다 깊게 — 근거 폭↑, rerank_pool=25 이내)"),
    Setting("REPORT_MIN_CITATIONS", "6", "report", "수집 근거 최소 건수 — 미달이면 1회 재수집 후 run 실패(얇은 보고서를 완성품으로 내보내지 않음)"),
    Setting("REPORT_REVISE_ENABLE", "1", "report", "1=초안→자기비평→개정 패스(품질↑·지연↑). 0=단발 합성"),
    Setting("REPORT_REGATHER_ENABLE", "1", "report",
            "1=검수 지적 기반 표적 재수집 1회(질의≤3·신규 근거≤5) 후 개정. 0=끔"),
    # ops 관측·알림
    Setting("OPS_ALERT_WEBHOOK_URL", None, "ops", "장애 알림 Slack webhook"),
    Setting("OPS_ALERT_DEDUP_S", "600", "ops", "알림 dedup 쿨다운"),
    Setting("READYZ_PROBE_TIMEOUT_S", "4", "ops", "/readyz probe 타임아웃"),
    Setting("SINGLE_INSTANCE_LOCK", "strict", "ops",
            "인스턴스 1개 강제(PG 어드바이저리 락). strict=충돌 시 부팅 차단 | "
            "warn=경고만 | off=검사 안 함. 동시성 제어가 전부 프로세스 로컬이라"
            "(CLAUDE.md §7) 2번째가 뜨면 대화 히스토리 손상·429 폭풍·중복 공지"),
    Setting("SINGLE_INSTANCE_WAIT_S", "20", "ops",
            "락 대기(초) — 배포 시 옛 컨테이너 종료를 기다린다"),
    Setting("TOKEN_USAGE_MISS_LOG_INTERVAL_S", "300", "ops",
            "토큰 usage 누락 경고 주기(초) — 쿼터·비용이 조용히 0 이 되는 걸 관측"),
    # tavily
    Setting("TAVILY_API_KEY", None, "web", "Tavily 웹검색 키", secret=True),
    Setting("TAVILY_EXCLUDE_DOMAINS", None, "web",
            "웹 검색 제외 도메인(CSV). 미설정=기본 UGC·영상 차단(네이버 블로그/카페·"
            "티스토리·브런치·유튜브). 빈 문자열=차단 끔 — 규제 답변에 블로그가 "
            "근거로 붙으면 신뢰가 깎인다(2026-08-03 실사용 실측)"),
    Setting("TAVILY_MAX_RESULTS", "5", "web", "웹검색 결과수"),

    # ── 2026-08-04 감사 H-14로 추가 ────────────────────────────────────────
    # 코드가 읽는데 레지스트리에 없던 41개. `/admin/config` 가 이 레지스트리를
    # 근거로 그리므로, 등록 전에는 **운영자가 값을 볼 수 없었다** — 특히
    # `*_DISABLE` 계열은 보안 기능을 끄는 스위치라 꺼져 있어도 아무도 몰랐다.
    # 킬스위치
    Setting("RATE_LIMIT_DISABLE", "0", "guard", "1=rate limit 전면 해제 ⚠️"),
    Setting("SECURITY_HEADERS_DISABLE", None, "guard",
            "1=보안 헤더(nosniff·DENY·Referrer-Policy) 미부착 ⚠️"),
    Setting("MEDICAL_FILTER_DISABLE", "1", "guard", "1=의료 도메인 필터 해제"),
    Setting("CHAT_GROUNDING_GATE_DISABLE", None, "guard",
            "1=답변 인용 검증 게이트 해제 ⚠️ 근거 없는 인용이 그대로 나간다"),
    Setting("CHAT_CONTACT_GUARD_DISABLE", None, "guard",
            "1=미검증 URL·전화번호 backstop 해제"),
    Setting("CLAIM_AUDIT_DISABLE", None, "guard", "1=주장 감사 이벤트 미적재"),
    Setting("LLM_RATE_LIMIT_DISABLE", None, "guard", "1=전역 LLM RPS 캡 해제 ⚠️"),
    Setting("DISABLE_TOKEN_LOGGER", None, "ops",
            "1=토큰·비용 집계 중단 ⚠️ 쿼터가 무력화된다"),
    # 보안 헤더 값
    Setting("STRICT_TRANSPORT_SECURITY", None, "guard",
            "HSTS 헤더 값(미설정=미부착). 예: max-age=31536000; includeSubDomains"),
    Setting("CSP", None, "guard", "Content-Security-Policy 헤더 값(미설정=미부착)"),
    Setting("API_CORS_ORIGINS", None, "guard",
            "허용 origin(CSV). 미설정 시 localhost 개발 origin 4종 — 운영에선 반드시 지정"),
    Setting("TRUSTED_PROXY_HOPS", "0", "guard",
            "신뢰하는 리버스 프록시 홉 수. 0=X-Forwarded-For 무시(위조 방지). nginx 1단이면 1"),
    # rate limit 한도
    Setting("RATE_LIMIT_PER_IP_PER_MIN", "60", "guard", "IP당 분당 요청"),
    Setting("RATE_LIMIT_PER_USER_PER_MIN", "30", "guard", "사용자당 분당 요청"),
    Setting("RATE_LIMIT_PER_USER_PER_HOUR", "600", "guard", "사용자당 시간당 요청"),
    # 영속 백엔드 선택자
    Setting("REPORTS_BACKEND", "postgres", "persist", "sqlite(dev) | postgres(운영)"),
    Setting("REPORTS_PG_DSN", None, "persist", "운영 Postgres DSN", secret=True),
    Setting("ALLOW_REMOTE_PG", "", "persist",
            "1=배포 이미지 밖(로컬 dev)에서 원격 PG 연결 허용. 기본은 차단 — 로컬 설정 실수가 "
            "운영 DB 쓰기·단일 인스턴스 락 경쟁이 되던 사고(2026-09-17). 의도한 운영 스크립트 실행에만"),
    Setting("REPORTS_SQLITE_PATH", "./medi_reports.db", "persist", "dev SQLite 경로"),
    Setting("BLOB_BACKEND", "local", "persist", "local | gcs — 보고서 .md 저장소"),
    Setting("BLOB_LOCAL_DIR", "/app/data/blobs", "persist", "local blob 디렉터리"),
    Setting("BLOB_GCS_BUCKET", None, "persist", "GCS 버킷명(BLOB_BACKEND=gcs)"),
    Setting("PG_POOL_MAX", "20", "persist", "openlaw PG 커넥션 풀 상한"),
    Setting("MONGO_URI", None, "persist", "openlaw Mongo URI", secret=True),
    Setting("MONGO_DB", "openlaw", "persist", "openlaw Mongo DB명"),
    # 한도·모델
    Setting("DEFAULT_DAILY_TOKEN_LIMIT", "20000000", "quota",
            "사용자 일일 토큰 기본 한도. 초과 시 429. 2026-08-19: 2M→20M — "
            "베타 동안 사실상 무제한(실측 p90 79.3만의 25배), 폭주·남용만 차단. "
            "0=무제한(사고 상한이 사라지므로 시스템 기본값으로는 비권장). "
            "개별 조정은 admin 의 daily_token_limit_override"),
    Setting("DEFAULT_MONTHLY_TOKEN_LIMIT", "1000000000", "quota", "사용자 월간 토큰 기본 한도"),
    Setting("USAGE_DAY_UTC_OFFSET_HOURS", "9", "quota",
            "일·월 쿼터 경계 타임존(UTC 오프셋 시). 기본 9=KST 자정 리셋. "
            "0 이면 UTC 자정(구 동작)"),
    Setting("LLM_MAX_RPS", "8", "llm", "전역 LLM 호출 RPS 캡(프로세스 로컬)"),
    Setting("LLM_RATE_BUCKET", "8", "llm",
            "RPS 버스트 버킷(미설정=LLM_MAX_RPS 와 동일). RPS 를 낮추면 함께 낮출 것"),
    Setting("MODEL_RETRY_MAX", "2", "llm", "LLM 호출 재시도 횟수"),
    Setting("TITLE_MODEL", "anthropic:claude-haiku-4-5-20251001", "llm", "대화 제목 생성 모델"),
    Setting("GROUND_MODEL", None, "llm", "grounding 검증 모델(미설정=SUBAGENT_MODEL)"),
    Setting("MAX_QDRANT_CALLS_PER_RUN", "4", "llm", "턴당 법령검색 호출 상한"),
    Setting("MAX_TAVILY_CALLS_PER_RUN", "2", "llm", "턴당 웹검색 호출 상한"),
    Setting("SELECTED_GROUNDING_MAX", "20", "llm", "선택 법령 grounding 상한"),
    # 보고서 튜닝
    Setting("REPORT_JOB_MAX_PENDING", "4", "report", "보고서 큐 대기 상한(초과 시 429)"),
    Setting("REPORT_MAX_CITATIONS", "40", "report", "종류별 인용 상한"),
    Setting("REPORT_GUIDE_TOP_K", "6", "report", "가이드 문서 top-k"),
    Setting("REPORT_PER_SOURCE_TEXT_CAP", "1500", "report", "출처별 본문 길이 cap"),
    Setting("REPORT_WRITER_INPUT_CHARS", "60000", "report", "writer 입력 문자 예산"),
    Setting("DOC_FILL_DISABLE", "", "chatloop",
            "1이면 서류 초안 턴 대조 기입(document_update) 끔"),
    Setting("DOC_FILL_MODEL", "", "chatloop",
            "서류 기입 대조/작성 모델(미설정=SUBAGENT_MODEL→haiku)"),
    Setting("DOC_FILL_BASE_URL", "", "chatloop",
            "서류 기입 모델 온프레미스 엔드포인트(OpenAI 호환). 설정 시 **원문**"
            "(성명·연락처 등)을 그대로 넘겨 서류 칸을 채운다 — 미설정이면 "
            "마스킹본만 처리해 개인정보 항목은 사용자가 직접 입력해야 한다. "
            "보고서 writer 와 **다른 호스트**여야 GPU 경합이 없다"),
    Setting("DOC_FILL_API_KEY", "", "chatloop", "서류 기입 엔드포인트 키(기본 EMPTY)", secret=True),
    Setting("DOC_FILL_TIMEOUT_S", "60", "chatloop", "서류 기입 모델 타임아웃(초)"),
    Setting("QREG_MAX_AGE_DAYS", "7", "chatloop",
            "야간 골든셋 회귀(medi-cron) — 배포 지문(커밋·프롬프트·모델)이 직전과 같으면 건너뛰되, "
            "이 일수마다 한 번은 강제 실행(검색 데이터 변동 감시)"),
    Setting("QREG_ALWAYS", "", "chatloop", "1=야간 골든셋 회귀를 변경 여부와 무관하게 매일 실행(구 동작)"),
    Setting("FILLED_VALUES_ENC_KEY", "", "chatloop",
            "저장 암호화 Fernet 키 — 서류 기입값(reports.filled_values)·기밀 메시지"
            "(chat_messages.sensitive)·조합 파일(workflow_files). 쉼표로 여러 개=회전. "
            "미설정 시 NEXTAUTH_SECRET 파생 키(세션 시크릿 회전 시 전부 복호화 불가 — 분리 권장). "
            "둘 다 없으면 평문·경고",
            secret=True),
    Setting("IDENT_AUDIT_DISABLE", "", "chatloop",
            "1=식별자 대조 감사 끔(답변의 서식·별표 번호 ↔ 이번 턴 근거 결정적 대조, events.identifier_audit)"),
    Setting("ENUM_AUDIT_DISABLE", "", "chatloop",
            "1이면 열거 커버리지 감사(enum_coverage events) 끔"),
    Setting("KORDOC_CLI", "", "report",
            "kordoc CLI 경로(cli.js 또는 실행파일) — 원본 서식(.hwpx) 기입 "
            "다운로드용. 미설정 시 PATH 의 kordoc, 둘 다 없으면 503"),
    Setting("REPORT_WRITER_CTX_ANSWER_CHARS", "8000", "report",
            "writer 맥락 provisional_answer 문자 예산"),
    Setting("REPORT_WRITER_CTX_CITATION_CHARS", "20000", "report",
            "writer 맥락 accumulated_citations 문자 예산(무예산 → 컨텍스트 초과 400 사고, 2026-08-20)"),
    # 기타
    Setting("STRICT_CONFIG", "1", "ops", "1=prod 필수 env 누락 시 부팅 차단"),
    Setting("SERVICE_LAUNCH_AT", None, "ops",
            "서비스 개시 시각(ISO) — admin 통계 기준선. 이 전 가입 계정은 자동 '테스트'(src/account_class.py)"),
    Setting("WEEKLY_REPORT_ENABLED", "1", "ops",
            "주간 이용 보고서 메일 자동 발송(src/weekly_report.py). 0=끔 — 기본값, 관리자 화면 저장값이 우선"),
    Setting("WEEKLY_REPORT_TO", "admin@example.com", "ops", "주간 보고서 수신자(쉼표) — 기본값, 관리자 화면 저장값이 우선"),
    Setting("WEEKLY_REPORT_SEND_HOUR", "9", "ops",
            "주간 보고서 발송 시각 N시(KST) — 기본값, 관리자 화면 저장값이 우선"),
    Setting("WEEKLY_REPORT_SEND_WEEKDAY", "0", "ops",
            "주간 보고서 발송 요일 0=월~6=일 — 기본값, 관리자 화면 저장값이 우선"),
    Setting("WEEKLY_REPORT_CHECK_INTERVAL_S", "900", "ops", "주간 보고서 발송 점검 주기(초). 0=루프 끔"),
    Setting("MONITOR_RECOMMEND_DISABLE", "", "report",
            "1=관찰 추천(하이쿠 1콜) 끔. 후보 목록만 보여 준다"),
    Setting("MONITOR_ALERT_INTERVAL_S", "3600", "report",
            "규제 변경 감지 주기(초). 발송 주기와 별개 — 감지는 자주, 발송은 드물게"),
    Setting("MONITOR_ALERT_DISABLE", "", "report",
            "1=변경 감지 루프 끔(알람이 쌓이지 않는다)"),
    Setting("MONITOR_REPORT_CHECK_INTERVAL_S", "900", "ops",
            "규제 모니터링 리포트 발송 점검 주기(초). 0=루프 끔"),
    Setting("MONITOR_REPORT_SEND_ON_NO_CHANGE", "0", "ops",
            "변경 0건이어도 리포트를 보낼지(1=보냄). 기본 0=생략"),
    Setting("USAGE_WEEKLY_SNAPSHOT_INTERVAL_S", "21600", "ops",
            "주간 이용 집계 스냅샷 보장 주기(초, 기본 6h). 0=끔 — 관리자 화면 조회 시에도 없는 주는 저장된다"),
)

_BY_KEY = {s.key: s for s in ENV_REGISTRY}

_TRUE = ("1", "true", "yes", "on")


def _raw(key: str) -> str | None:
    v = os.getenv(key)
    if v is not None:
        return v
    s = _BY_KEY.get(key)
    return s.default if s else None


def env_str(key: str, default: str | None = None) -> str | None:
    v = _raw(key)
    return v if v is not None else default


def env_nonempty(key: str) -> str:
    """값이 비었으면(미설정·빈 문자열) 레지스트리 기본값. compose 의 `${X:-}` 가 빈 값을 넣어도 기본값이 산다."""
    v = (os.getenv(key) or "").strip()
    if v:
        return v
    s = _BY_KEY.get(key)
    return (s.default or "") if s else ""


def env_int(key: str, default: int = 0) -> int:
    try:
        return int(_raw(key))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def env_float(key: str, default: float = 0.0) -> float:
    try:
        return float(_raw(key))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def env_bool(key: str, default: bool = False) -> bool:
    v = _raw(key)
    return (v.strip().lower() in _TRUE) if v is not None else default


def missing_prod_required() -> list[str]:
    """prod 필수인데 미설정인 키 — 부팅 검증/`/readyz`/`check_config` 용."""
    return [s.key for s in ENV_REGISTRY
            if s.prod_required and not (os.getenv(s.key) or "").strip()]


def dump(*, reveal_secrets: bool = False) -> list[dict]:
    """현재 설정 스냅샷(시크릿은 마스킹) — 운영 점검용."""
    out = []
    for s in ENV_REGISTRY:
        raw = os.getenv(s.key)
        set_ = raw is not None and raw.strip() != ""
        if s.secret and set_ and not reveal_secrets:
            val = "***set***"
        else:
            val = raw if set_ else (s.default and f"(default: {s.default})")
        out.append({"key": s.key, "group": s.group, "set": set_,
                    "value": val, "prod_required": s.prod_required, "doc": s.doc})
    return out


class Settings:
    """핵심 노브 타입 접근자 — 신규·핫패스 코드가 `from src.config import settings`."""

    # llm
    @property
    def llm_model(self) -> str:
        return env_str("LLM_MODEL") or "anthropic:claude-sonnet-4-6"

    @property
    def subagent_model(self) -> str:
        return (env_str("SUBAGENT_MODEL")
                or "anthropic:claude-haiku-4-5-20251001")

    # cache
    @property
    def search_cache_ttl_s(self) -> int:
        return env_int("SEARCH_CACHE_TTL_S", 3600)

    # ops
    @property
    def ops_alert_webhook(self) -> str:
        return (env_str("OPS_ALERT_WEBHOOK_URL") or "").strip()


settings = Settings()
