"""서버 부하 추적(observability.load) — 혼잡 표시 로직."""

from src.observability import load


def _reset():
    load._search_active = 0
    load._search_waiting = 0
    load._reports_active = 0


def test_snapshot_ok_when_idle(monkeypatch):
    monkeypatch.setenv("SEARCH_MAX_CONCURRENCY", "2")
    _reset()
    s = load.snapshot()
    assert s["status"] == "ok"
    assert s["search"] == {"active": 0, "waiting": 0, "limit": 2}
    assert not load.is_congested()


def test_busy_when_slots_full(monkeypatch):
    monkeypatch.setenv("SEARCH_MAX_CONCURRENCY", "2")
    _reset()
    load.search_active(2)  # 슬롯 만석
    assert load.is_congested()
    assert load.snapshot()["status"] == "busy"
    load.search_active(-2)
    assert load.snapshot()["status"] == "ok"


def test_busy_when_waiting(monkeypatch):
    monkeypatch.setenv("SEARCH_MAX_CONCURRENCY", "2")
    _reset()
    load.search_active(2)
    load.search_wait(1)  # 대기 발생
    s = load.snapshot()
    assert s["status"] == "busy"
    assert s["search"]["waiting"] == 1
    _reset()


def test_reports_active_tracked(monkeypatch):
    _reset()
    load.report_active(1)
    assert load.snapshot()["reports"]["active"] == 1
    load.report_active(-1)
    assert load.snapshot()["reports"]["active"] == 0
