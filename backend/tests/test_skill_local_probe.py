"""스킬 로컬 모델 probe 부하 내성(2026-09-15) — 타임아웃=바쁨(통과), KV 성공 캐시."""
import pytest


@pytest.fixture
def kv(tmp_path, monkeypatch):
    import src.skill_local as sl
    from src.persistence import settings_repo as sr
    from src.persistence.settings_repo import SqliteSettingsRepo

    repo = SqliteSettingsRepo(str(tmp_path / "s.db"))
    monkeypatch.setattr(sr, "get_settings_repo", lambda: repo)
    sl._tool_ok_cache.clear()
    return repo


def _fake_post(monkeypatch, behavior):
    import httpx

    calls = []

    def post(url, **kw):
        calls.append(url)
        if behavior == "timeout":
            raise httpx.ReadTimeout("slow")
        if behavior == "down":
            raise httpx.ConnectError("refused")
        class R:
            status_code = 200 if behavior == "ok" else 400
            text = "requires --enable-auto-tool-choice"
        return R()
    monkeypatch.setattr(httpx, "post", post)
    return calls


def test_timeout_is_busy_not_down(kv, monkeypatch):
    import src.skill_local as sl

    calls = _fake_post(monkeypatch, "timeout")
    assert sl._tool_support_ok("http://x/v1", "m1") is True
    assert len(calls) == 1 and "m1" not in sl._tool_ok_cache  # 캐시 안 함
    assert kv.get("skill_local_tool_ok:m1") is None


def test_connect_error_and_400_are_false(kv, monkeypatch):
    import src.skill_local as sl

    _fake_post(monkeypatch, "down")
    assert sl._tool_support_ok("http://x/v1", "m1") is False
    _fake_post(monkeypatch, "400")
    assert sl._tool_support_ok("http://x/v1", "m1") is False
    assert "m1" not in sl._tool_ok_cache


def test_success_persists_and_skips_probe_after_restart(kv, monkeypatch):
    import src.skill_local as sl

    calls = _fake_post(monkeypatch, "ok")
    assert sl._tool_support_ok("http://x/v1", "m2") is True
    assert kv.get("skill_local_tool_ok:m2") == "1" and len(calls) == 1
    # 프로세스 재시작 = 메모리 캐시 소실 → KV 로 확인, HTTP 호출 없음
    sl._tool_ok_cache.clear()
    _fake_post(monkeypatch, "timeout")
    assert sl._tool_support_ok("http://x/v1", "m2") is True
    assert sl._tool_ok_cache.get("m2") is True


def test_warm_up_noop_when_disabled(monkeypatch):
    import src.skill_local as sl

    monkeypatch.delenv("SKILL_LOCAL_MODEL", raising=False)
    assert sl.warm_up() is None
