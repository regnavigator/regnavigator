"""`.env.docker.example` 를 docker-compose.yml + config.ENV_REGISTRY 에서 재생성.

예시 파일을 손으로 유지하다 단일 진실원(compose 참조 + 레지스트리)과 드리프트나는
사고를 막는다. compose 가 host env 에서 기대하는 모든 `${KEY}` 를 뽑아, 레지스트리
문서를 붙이고, 기본값 유무(REQUIRED vs default)로 분류해 그룹별로 출력한다.

    python scripts/gen_env_docker_example.py            # stdout 미리보기
    python scripts/gen_env_docker_example.py --write     # .env.docker.example 덮어쓰기
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import ENV_REGISTRY  # noqa: E402

REG = {s.key: s for s in ENV_REGISTRY}

# 백업 스크립트의 컨테이너 로컬 셸 변수($$escaped) — compose env 아님
FALSE_POS = {"DB", "TS"}

# 그룹 표시 순서 + 헤더. compose 에 있으나 레지스트리엔 없는 인프라 키는
# 아래 EXTRA_GROUP 으로 분류.
GROUP_ORDER = [
    ("auth", "인증·보안 / 접근 게이트"),
    ("llm", "LLM (모델·폴백·호출 상한)"),
    ("chatloop", "채팅 루프 (fast)"),
    ("search", "RAG 검색 API (DGX openlaw-search)"),
    ("guardrail", "가드레일 (PII·의도, DGX — 미설정 시 폴백)"),
    ("datastore", "openlaw-etl 4 DB (외부, 읽기전용)"),
    ("persistence", "운영 영속 (medi 자체 Postgres·blob)"),
    ("report", "보고서 (deep)"),
    ("notify", "이메일 알림 (SMTP)"),
    ("web", "웹검색 (Tavily)"),
    ("ops", "운영 안전장치·관측·한도"),
]

# 레지스트리에 없는 compose/인프라 키의 그룹·문서(예시 가독성용).
EXTRA = {
    "API_CORS_ORIGINS": ("auth", "허용 origin CSV(프런트) — CORS 화이트리스트"),
    "POSTGRES_USER": ("persistence", "medi 운영 PG 사용자(compose 내부)"),
    "POSTGRES_PASSWORD": ("persistence", "medi 운영 PG 비밀번호 — 강한 값 필수"),
    "POSTGRES_DB": ("persistence", "medi 운영 PG DB명"),
    "AUTH_DB": ("persistence", "auth DB명(백업 대상)"),
    "REPORTS_BACKEND": ("persistence", "reports 백엔드(postgres|sqlite)"),
    "CHECKPOINT_BACKEND": ("persistence", "checkpoint 백엔드(존치 유물)"),
    "CHECKPOINT_RETENTION_DAYS": ("persistence", "checkpoint 보존일"),
    "BLOB_BACKEND": ("persistence", "보고서 blob 백엔드(local|gcs)"),
    "BLOB_LOCAL_DIR": ("persistence", "local blob 디렉터리"),
    "BLOB_GCS_BUCKET": ("persistence", "GCS 버킷(BLOB_BACKEND=gcs 일 때)"),
    "PG_POOL_MAX": ("persistence", "openlaw PG 커넥션풀 상한"),
    "MEDICAL_FILTER_DISABLE": ("search", "1=의료 도메인 필터 끔"),
    "MONGO_DB": ("datastore", "Mongo DB명"),
    "MONGO_URI": ("datastore", "Mongo 접속 URI"),
    "OPENLAW_NETWORK": ("datastore", "openlaw-etl docker network 이름(합류용)"),
    "SUBAGENT_FALLBACK": ("llm", "서브에이전트 폴백 모델 스펙"),
    "TITLE_MODEL": ("llm", "스레드 제목 생성 모델"),
    "LLM_MAX_RPS": ("llm", "LLM client-side 초당 호출 상한"),
    "MAX_QDRANT_CALLS_PER_RUN": ("ops", "run당 qdrant 검색 라운드 상한"),
    "MAX_TAVILY_CALLS_PER_RUN": ("ops", "run당 tavily 웹검색 상한"),
    "RECURSION_LIMIT": ("ops", "에이전트 재귀 상한(존치 유물)"),
    "LOG_LEVEL": ("ops", "로그 레벨"),
    "LANGSMITH_API_KEY": ("ops", "LangSmith 트레이싱 키(권장)"),
    "LANGSMITH_PROJECT": ("ops", "LangSmith 프로젝트명"),
    "STRICT_CONFIG": ("ops", "1=prod 필수 env 누락 시 부팅 차단(사고 방지)"),
    "RATE_LIMIT_DISABLE": ("ops", "1=rate limit 끔(dev)"),
    "RATE_LIMIT_PER_IP_PER_MIN": ("ops", "IP당 분당 요청 상한"),
    "RATE_LIMIT_PER_USER_PER_MIN": ("ops", "사용자당 분당 요청 상한"),
    "RATE_LIMIT_PER_USER_PER_HOUR": ("ops", "사용자당 시간당 요청 상한"),
    "DEFAULT_DAILY_TOKEN_LIMIT": ("ops", "사용자 일일 토큰 한도 기본값"),
    "DEFAULT_MONTHLY_TOKEN_LIMIT": ("ops", "사용자 월간 토큰 한도 기본값"),
    "PRUNE_APPLY": ("ops", "1=보존정리 실삭제(0=DRY_RUN)"),
    "PRUNE_INTERVAL_S": ("ops", "보존정리 주기(초)"),
    "BACKUP_INTERVAL_S": ("ops", "pg_dump 백업 주기(초)"),
    "BACKUP_RETENTION_DAYS": ("ops", "백업 보존일"),
}


def compose_refs(compose: str) -> dict[str, str | None]:
    """compose 가 host env 에서 기대하는 ${KEY} → 기본값(없으면 None)."""
    refs: dict[str, str | None] = {}
    for line in compose.splitlines():
        if line.lstrip().startswith("#"):  # 주석 줄(비활성 예시)은 제외
            continue
        for m in re.finditer(r"(?<!\$)\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}", line):
            key, dflt = m.group(1), m.group(2)
            if key in FALSE_POS:
                continue
            refs.setdefault(key, dflt)
    return refs


def group_of(key: str) -> str:
    if key in REG:
        return REG[key].group
    if key in EXTRA:
        return EXTRA[key][0]
    return "ops"


def doc_of(key: str) -> str:
    if key in REG:
        return REG[key].doc
    if key in EXTRA:
        return EXTRA[key][1]
    return ""


def is_secret(key: str) -> bool:
    return key in REG and REG[key].secret


def render(refs: dict[str, str | None]) -> str:
    lines = [
        "# ==========================================================================",
        "# .env.docker — 운영(docker compose) 환경변수 템플릿",
        "# 자동 생성: scripts/gen_env_docker_example.py (docker-compose.yml + config.ENV_REGISTRY)",
        "# 손으로 고치지 말 것 — compose 참조나 레지스트리를 바꾸고 재생성하세요.",
        "#",
        "# REQUIRED = compose 기본값 없음 → 반드시 채워야 함(STRICT_CONFIG=1 이면 일부는 부팅 차단).",
        "# 그 외는 값 그대로가 기본값 — 바꿀 때만 주석 해제/수정.",
        "# ==========================================================================",
        "",
    ]
    by_group: dict[str, list[str]] = {}
    for key in refs:
        by_group.setdefault(group_of(key), []).append(key)

    seen_groups = [g for g, _ in GROUP_ORDER if g in by_group]
    seen_groups += [g for g in by_group if g not in {gg for gg, _ in GROUP_ORDER}]
    headers = dict(GROUP_ORDER)

    for g in seen_groups:
        lines.append(f"# ── {headers.get(g, g)} " + "─" * max(0, 50 - len(headers.get(g, g))))
        for key in sorted(by_group[g]):
            dflt = refs[key]
            doc = doc_of(key)
            if doc:
                lines.append(f"# {doc}")
            if dflt is None:
                placeholder = "<채우세요>" if not is_secret(key) else "<시크릿>"
                lines.append(f"{key}={placeholder}    # REQUIRED")
            else:
                lines.append(f"{key}={dflt}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    refs = compose_refs(compose)
    out = render(refs)
    if "--write" in sys.argv:
        (ROOT / ".env.docker.example").write_text(out, encoding="utf-8")
        req = sum(1 for v in refs.values() if v is None)
        print(f"✓ .env.docker.example 재생성 — {len(refs)}개 키 ({req} REQUIRED)")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
