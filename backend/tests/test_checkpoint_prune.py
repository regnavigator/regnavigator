"""체크포인트 보존 — events.inactive_thread_ids (비활성 thread 판별)."""
from __future__ import annotations


def _repo(tmp_path):
    from src.persistence.events_repo import SqliteEventsRepo
    return SqliteEventsRepo(str(tmp_path / "events.db"))


def _emit(repo, thread_id, ts):
    from src.persistence.events_repo import Event
    repo.emit(Event(id="", ts=ts, event_type="query_start", thread_id=thread_id))


def test_inactive_thread_ids_filters_by_last_activity(tmp_path):
    repo = _repo(tmp_path)
    _emit(repo, "old", "2020-01-01T00:00:00.000000Z")     # 오래된 thread
    _emit(repo, "recent", "2026-06-01T00:00:00.000000Z")  # 최근 thread
    # recent 에 오래된 활동도 있지만 MAX(ts)는 최근 → 비활성 아님
    _emit(repo, "recent", "2019-01-01T00:00:00.000000Z")

    out = repo.inactive_thread_ids(cutoff_iso="2025-01-01T00:00:00.000000Z")
    assert out == ["old"]


def test_inactive_thread_ids_empty_when_all_recent(tmp_path):
    repo = _repo(tmp_path)
    _emit(repo, "a", "2026-06-01T00:00:00.000000Z")
    assert repo.inactive_thread_ids(cutoff_iso="2025-01-01T00:00:00.000000Z") == []


def test_inactive_thread_ids_limit(tmp_path):
    repo = _repo(tmp_path)
    for i in range(5):
        _emit(repo, f"t{i}", "2020-01-01T00:00:00.000000Z")
    out = repo.inactive_thread_ids(cutoff_iso="2025-01-01T00:00:00.000000Z", limit=2)
    assert len(out) == 2
