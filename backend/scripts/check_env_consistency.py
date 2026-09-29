"""환경변수 정합성 감사 — 레지스트리 ↔ 코드 ↔ .env* ↔ docker-compose.

**왜 필요한가**: 2026-07-09 배포 직전, `docker-compose.yml` 에 `RAG_SEARCH_API_URL`
이 아예 없어 **배포하면 RAG 검색이 전면 실패**하는 상태였다(thin-client 전환 미반영).
죽은 env 17개도 남아 있었다. 사람 눈으로는 다시 놓친다 — 스크립트가 지킨다.

검사 항목:
  [A] 코드가 읽는데 레지스트리에 없음      → 문서화 누락(경고)
  [B] compose 에 있는데 아무도 안 읽음      → 죽은 env(경고)
  [C] prod_required 인데 compose 에 없음    → **에러**(배포 시 부팅 차단됨)
  [D] 레지스트리에 있는데 .env.example 에 없음 → 문서화 누락(경고)

usage:
  python scripts/check_env_consistency.py          # 경고는 통과(exit 0)
  python scripts/check_env_consistency.py --strict # 경고도 실패(exit 1) — CI 용
"""

from __future__ import annotations

import pathlib
import re
import sys

# compose/스크립트 전용 — 앱 코드가 안 읽어도 정상.
_INFRA = {
    "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "PGDATA", "PGPASSWORD",
    "PRUNE_APPLY", "PRUNE_INTERVAL_S", "PRUNE_MAX", "BACKUP_INTERVAL_S",
    "BACKUP_RETENTION_DAYS", "OPENLAW_NETWORK", "PYTHONUTF8", "PORT",
    "BLOB_RETENTION_DAYS", "CHECKPOINT_RETENTION_DAYS",   # scripts/ 에서 읽음
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY",                # langchain SDK 가 직접 읽음
    "LANGSMITH_API_KEY", "LANGSMITH_PROJECT",             # langsmith SDK
    "LANGGRAPH_N_JOBS", "BG_JOB_ISOLATED_LOOPS",          # langgraph runtime
    "LOG_LEVEL", "RECURSION_LIMIT",
}


def _keys(path: str, pat: str) -> set[str]:
    p = pathlib.Path(path)
    return set(re.findall(pat, p.read_text(encoding="utf-8"), re.M)) if p.exists() else set()


def main() -> int:
    strict = "--strict" in sys.argv
    from src.config import ENV_REGISTRY

    reg = {s.key for s in ENV_REGISTRY}
    required = {s.key for s in ENV_REGISTRY if s.prod_required}

    envex = _keys(".env.example", r"^#?\s*([A-Z][A-Z0-9_]+)=")
    compose = _keys("docker-compose.yml", r"^\s{6}([A-Z][A-Z0-9_]+):")

    code: set[str] = set()
    for f in list(pathlib.Path("src").rglob("*.py")) + list(pathlib.Path("scripts").glob("*.py")):
        t = f.read_text(encoding="utf-8")
        code |= set(re.findall(r'getenv\(\s*["\']([A-Z][A-Z0-9_]+)["\']', t))
        code |= set(re.findall(r'env_(?:str|int|float|bool)\(\s*["\']([A-Z][A-Z0-9_]+)["\']', t))

    errors: list[str] = []
    warns: list[str] = []

    # [C] prod 필수인데 compose 에 없다 → 배포 시 STRICT_CONFIG 가 부팅 차단.
    for k in sorted(required - compose):
        errors.append(f"[C] prod 필수 '{k}' 가 docker-compose.yml 에 없음 → 배포 시 부팅 차단")

    for k in sorted(code - reg - _INFRA):
        warns.append(f"[A] 코드가 읽는 '{k}' 가 ENV_REGISTRY 에 없음(문서화 누락)")
    for k in sorted(compose - code - reg - _INFRA):
        warns.append(f"[B] compose 의 '{k}' 를 아무도 안 읽음(죽은 env?)")
    for k in sorted(reg - envex - _INFRA):
        warns.append(f"[D] 레지스트리의 '{k}' 가 .env.example 에 없음")

    print(f"레지스트리 {len(reg)} · 코드 {len(code)} · compose {len(compose)} · .env.example {len(envex)}")
    print(f"prod 필수: {sorted(required)}\n")
    for e in errors:
        print("ERROR  " + e)
    for w in warns:
        print("WARN   " + w)
    if not errors and not warns:
        print("정합성 OK — 불일치 없음")

    if errors:
        print(f"\n{len(errors)}건 ERROR — 배포 전 반드시 수정")
        return 1
    if warns and strict:
        print(f"\n{len(warns)}건 WARN (--strict)")
        return 1
    if warns:
        print(f"\n{len(warns)}건 WARN (배포 차단 아님)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
