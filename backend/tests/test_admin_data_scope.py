"""실사용/테스트 데이터 분리 — 8/3 베타 오픈 경계.

오픈 전 데이터는 개발·e2e 가 만든 것이라, 섞어 집계하면 "LLM 72회" 같은 숫자가
실제 이용자 지표로 읽힌다(초대 전날 72회는 전부 내부 테스트였다).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SERVICE_LAUNCH_AT", raising=False)
    yield


def test_default_cutoff_is_beta_open_kst():
    from src.routes.admin import _launch_cutoff

    # 2026-08-03 00:00 KST == 2026-08-02 15:00 UTC
    assert _launch_cutoff().startswith("2026-08-02T15:00")


def test_env_override(monkeypatch):
    from src.routes.admin import _launch_cutoff

    monkeypatch.setenv("SERVICE_LAUNCH_AT", "2026-09-01T00:00:00+09:00")
    assert _launch_cutoff().startswith("2026-08-31T15:00")


def test_bad_env_falls_back_to_default(monkeypatch):
    from src.routes.admin import _launch_cutoff

    monkeypatch.setenv("SERVICE_LAUNCH_AT", "쓰레기")
    assert _launch_cutoff().startswith("2026-08-02T15:00")


def test_scope_real_clamps_since_to_launch():
    """days=30 을 줘도 오픈 이전으로는 거슬러 올라가지 않는다."""
    from src.routes.admin import _launch_cutoff, _scope_since

    old = "2026-07-01T00:00:00+00:00"
    assert _scope_since("real", old) == _launch_cutoff()


def test_scope_real_keeps_later_since():
    """오픈보다 늦은 since 는 그대로 — 짧은 기간 조회를 넓히지 않는다."""
    from src.routes.admin import _scope_since

    recent = "2026-08-10T00:00:00+00:00"
    assert _scope_since("real", recent) == recent


@pytest.mark.parametrize("scope", ["all", "ALL", "All"])
def test_scope_all_passes_through(scope):
    from src.routes.admin import _scope_since

    old = "2026-07-01T00:00:00+00:00"
    assert _scope_since(scope, old) == old


def test_missing_scope_defaults_to_real():
    from src.routes.admin import _launch_cutoff, _scope_since

    assert _scope_since("", "2026-07-01T00:00:00+00:00") == _launch_cutoff()
    assert _scope_since(None, "2026-07-01T00:00:00+00:00") == _launch_cutoff()
