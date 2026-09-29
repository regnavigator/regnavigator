"""src/ 안의 모든 third-party import가 pyproject 의존성에 박혀있는지 검증.

Run: python scripts/check_imports.py

CI에 박으면 의존성 누락 사고 재발 방지. lazy import + try/except 패턴 코드도
모두 잡아냄.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

# stdlib 판정은 인터프리터에게 묻는다(3.10+). 손으로 적던 목록은 **누락이 곧
# CI 실패**였다 — `from html import escape`(공지 템플릿) 하나에 "html 패키지
# 미선언"으로 빌드가 깨졌다(2026-08-02). 아래 리터럴은 하위호환용 보강.
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {
    "__future__",
    "abc", "argparse", "asyncio", "ast", "base64", "collections", "concurrent",
    "contextlib", "contextvars", "copy", "csv", "dataclasses", "datetime",
    "enum", "functools", "gzip", "hashlib", "hmac", "io", "ipaddress", "itertools",
    "json", "logging", "math", "operator", "os", "pathlib", "pickle", "platform",
    "queue", "random", "re", "secrets", "shutil", "signal", "socket", "sqlite3",
    "ssl", "string", "subprocess", "sys", "tempfile", "textwrap", "threading",
    "time", "timeit", "tomllib", "traceback", "types", "typing", "unicodedata",
    "urllib", "uuid", "warnings", "weakref", "zipfile",
    "email", "smtplib",  # stdlib — 보고서 완료 메일(notifications)
    "zoneinfo",  # stdlib(3.9+) — maintenance.py 새벽 점검창 KST 판정
}

# 명시적으로 선언 안 해도 다른 declared 의존성이 가져오는 transitive 패키지.
TRANSITIVE_OK = {
    "numpy",      # sentence-transformers / qdrant-client
    "torch",      # sentence-transformers
    "starlette",  # fastapi
    "pydantic",   # fastapi / langchain-core
    "pypandoc",   # pypandoc-binary(선언명) 이 제공하는 import 명
}

# import 이름 → pyproject 패키지명 매핑 (다른 경우)
PKG_ALIASES = {
    "jwt": "pyjwt",
    "langchain_core": "langchain-core",
    "langchain_anthropic": "langchain-anthropic",
    "langchain_openai": "langchain-openai",
    "psycopg_pool": "psycopg",  # [pool] extra
    "sentence_transformers": "sentence-transformers",
    "tavily": "tavily-python",
    "qdrant_client": "qdrant-client",
    "google": "google-cloud-storage",
    "dotenv": "python-dotenv",
    "docx": "python-docx",  # 파일 업로드 v1 (2026-08-05)
}


def collect_imports(src_dir: Path) -> set[str]:
    imports: set[str] = set()
    pat = re.compile(r"^\s*(?:from|import)\s+([a-z_][a-zA-Z0-9_]*)")
    for f in src_dir.rglob("*.py"):
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = pat.match(line)
            if m:
                imports.add(m.group(1))
    return imports


def declared_packages(pyproject: Path) -> set[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    pkgs: set[str] = set()
    for spec in data["project"]["dependencies"]:
        pkgs.add(_pkg_name(spec))
    for group in data["project"].get("optional-dependencies", {}).values():
        for spec in group:
            pkgs.add(_pkg_name(spec))
    return {p.lower() for p in pkgs}


def _pkg_name(spec: str) -> str:
    # "psycopg[binary,pool]>=3.2" → "psycopg"
    return re.split(r"[\[\s<>=!~]", spec, 1)[0].strip()


def main():
    root = Path(__file__).resolve().parent.parent
    used = collect_imports(root / "src")
    declared = declared_packages(root / "pyproject.toml")

    third_party = {
        m for m in used
        if m not in STDLIB and m not in TRANSITIVE_OK and not m.startswith("src")
    }

    missing = []
    for mod in sorted(third_party):
        pkg = PKG_ALIASES.get(mod, mod).lower().replace("_", "-")
        if pkg not in declared:
            missing.append((mod, pkg))

    if missing:
        print("[FAIL] pyproject.toml missing deps:")
        for mod, pkg in missing:
            print(f"  - {mod}  ->  {pkg}")
        sys.exit(1)
    print(f"[OK] all {len(third_party)} third-party imports declared in pyproject")


if __name__ == "__main__":
    main()
