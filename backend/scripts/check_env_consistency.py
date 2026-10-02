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
    "TZ", "PYTHONPATH",  # 컨테이너 런타임 — 앱 코드가 getenv 하지 않는 게 정상(2026-10-03)
    # 라이브러리가 읽는 키 — langchain 이 직접 본다. "아무도 안 읽음"으로 지우면 안 된다
    # (2026-10-03 실수로 지웠다가 test_compose_env_mapping 이 잡았다). false 고정은 §5 국외이전 방지.
    "LANGSMITH_TRACING",
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

    # [D]는 **생성되는** 예시(.env.docker.example)와 대조한다(2026-10-03). 그 파일은
    # `gen_env_docker_example.py --write` 로 레지스트리+compose 에서 만들어지므로
    # 어긋남 = "재생성을 잊음"(CLAUDE.md 불변식 7). 손편집 dev 예시(.env.example)는
    # dev 에 필요한 것만 담는 게 맞아 대조 대상이 아니다.
    envex = _keys(".env.docker.example", r"^#?\s*([A-Z][A-Z0-9_]+)=")
    compose = _keys("docker-compose.yml", r"^\s{6}([A-Z][A-Z0-9_]+):")

    def _reads(paths) -> set[str]:
        out: set[str] = set()
        for f in paths:
            t = f.read_text(encoding="utf-8")
            out |= set(re.findall(r'getenv\(\s*["\']([A-Z][A-Z0-9_]+)["\']', t))
            out |= set(re.findall(r'env_(?:str|int|float|bool)\(\s*["\']([A-Z][A-Z0-9_]+)["\']', t))
        return out

    # 런타임(src)과 도구(scripts)를 나눈다(2026-10-03). [A] "문서화 누락"은 런타임
    # 설정에만 묻는다 — eval·A/B·export 스크립트의 EVAL_TOP_K 같은 노브 16개가
    # [A]로 잡혀 strict 가 늘 빨갰고, 그래서 아무도 strict 를 켜지 않았다.
    code_src = _reads(pathlib.Path("src").rglob("*.py"))
    code = code_src | _reads(pathlib.Path("scripts").glob("*.py"))

    errors: list[str] = []
    warns: list[str] = []

    # [C] prod 필수인데 compose 에 없다 → 배포 시 STRICT_CONFIG 가 부팅 차단.
    for k in sorted(required - compose):
        errors.append(f"[C] prod 필수 '{k}' 가 docker-compose.yml 에 없음 → 배포 시 부팅 차단")

    for k in sorted(code_src - reg - _INFRA):
        warns.append(f"[A] 코드가 읽는 '{k}' 가 ENV_REGISTRY 에 없음(문서화 누락)")
    for k in sorted(compose - code - reg - _INFRA):
        warns.append(f"[B] compose 의 '{k}' 를 아무도 안 읽음(죽은 env?)")
    # compose 에 **있어서는 안 되는** 레지스트리 키(2026-10-03) — [D] 대상 아님.
    _NOT_IN_COMPOSE = {
        "APP_GIT_SHA", "APP_BUILD_TIME",   # Dockerfile ARG→ENV 로 박힌다(compose 참조 없음)
        "AUTH_DEV_BYPASS_USER",            # dev 전용 — 운영 compose 에 들어가면 인증 우회
        "ALLOW_REMOTE_PG",                 # 로컬에서 원격 PG 허용 스위치 — 배포 이미지 안에선 무의미
    }
    # compose 가 리터럴로 조립하는 키(REPORTS_PG_DSN 등)는 `${}` 참조가 없어 생성기가
    # 예시에 못 싣는다 — compose 에 있으면 충족으로 본다.
    for k in sorted(reg - envex - compose - _INFRA - _NOT_IN_COMPOSE):
        warns.append(f"[D] 레지스트리의 '{k}' 가 .env.docker.example 에 없음 — gen_env_docker_example.py --write")

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
