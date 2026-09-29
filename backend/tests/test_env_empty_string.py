"""빈 문자열 env 가 기본값을 잡아먹지 않는지 — 2026-08-03 운영 장애 회귀.

`os.getenv(K, "4")` 는 **K 가 빈 문자열로 존재하면 "" 를 돌려준다**(기본값 아님).
docker-compose 가 `CHAT_GUIDE_TOP_K: ${CHAT_GUIDE_TOP_K:-}` 로 빈 값을 주입하자
`int("")` → ValueError 가 `run_qdrant` 안에서 터져 **검색 전체가 실패**했다.
증상은 사용자에게 "검색 일시 실패"로만 보여 원인 추적이 어려웠다.

방어는 두 겹이다.
  1) 코드: `os.getenv(K) or "기본값"` — 미설정과 빈 값을 같게 취급.
  2) compose: 숫자 노브에 빈 기본값(`:-`)을 쓰지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


def _numeric_env_keys() -> set[str]:
    """소스에서 int()/float() 로 변환되는 env 키 수집."""
    keys: set[str] = set()
    pat = re.compile(r'(?:int|float)\(\s*os\.getenv\(\s*"([A-Z0-9_]+)"')
    for p in Path("src").rglob("*.py"):
        keys.update(pat.findall(p.read_text(encoding="utf-8")))
    return keys


def test_no_bare_getenv_default_in_numeric_conversions():
    """`int(os.getenv(K, "N"))` 패턴이 남아 있으면 빈 값에서 터진다."""
    bad: list[str] = []
    pat = re.compile(r'(?:int|float)\(\s*os\.getenv\(\s*"[A-Z0-9_]+"\s*,')
    for p in Path("src").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                bad.append(f"{p}:{i}  {line.strip()}")
    assert not bad, (
        "빈 문자열 env 에서 ValueError — `os.getenv(K) or \"기본값\"` 으로 바꿀 것:\n"
        + "\n".join(bad))


def test_compose_gives_real_defaults_to_numeric_knobs():
    """숫자 노브에 `${K:-}`(빈 기본값)를 주면 컨테이너에 ""가 들어간다."""
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    numeric = _numeric_env_keys()
    bad = []
    for m in re.finditer(r"^\s*([A-Z0-9_]+):\s*\$\{([A-Z0-9_]+):-\}\s*$",
                         compose, re.M):
        if m.group(1) in numeric:
            bad.append(m.group(1))
    assert not bad, f"숫자 노브인데 compose 기본값이 비어 있다: {bad}"


@pytest.mark.parametrize("value", ["", "  ", "	"])
def test_numeric_env_idiom_survives_blank(value, monkeypatch):
    """소스가 쓰는 관용구가 빈 값·공백에서도 기본값을 준다.

    `or` 만으로는 부족하다 — "  " 는 truthy 라 int("  ") 로 또 터진다.
    그래서 소스는 `(os.getenv(K) or "").strip() or "기본값"` 을 쓴다.
    """
    import os

    monkeypatch.setenv("CHAT_GUIDE_TOP_K", value)
    assert int((os.getenv("CHAT_GUIDE_TOP_K") or "").strip() or "4") == 4


def test_guide_top_k_site_uses_blank_safe_idiom():
    """실제 장애 지점이 관용구를 쓰는지 소스로 확인."""
    src = Path("src/tools/search.py").read_text(encoding="utf-8")
    assert 'int((os.getenv("CHAT_GUIDE_TOP_K") or "").strip() or "4")' in src
