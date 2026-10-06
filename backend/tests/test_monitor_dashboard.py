"""모니터링 대시보드 재료 — 집계·점검 시각·이름 필수·보고서=읽음 처리 (2026-10-06)."""

from __future__ import annotations

import pytest


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "d.db"))
    monkeypatch.setenv("REPORTS_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)

    import src.persistence as P
    import src.persistence.threads_repo as TR

    monkeypatch.setattr(TR, "_repo", None)
    caches = (P.get_reports_repo, P.get_report_runs_repo, P.get_blob_store,
              P.get_users_repo, P.get_events_repo, P.get_monitor_watch_repo,
              P.get_monitor_alert_repo, P.get_contacts_repo, P.get_monitor_targets_repo)
    for f in caches:
        f.cache_clear()
    from fastapi.testclient import TestClient

    from src.api import app

    yield TestClient(app)
    for f in caches:
        f.cache_clear()


def _alert(tid, ak, kind, day, read=False):
    from src.persistence.monitor_alert_repo import Alert

    return Alert(id="", thread_id=tid, article_key=ak, kind=kind, summary=f"{ak} {kind}",
                 detected_at=day, read_at=("2026-10-06T00:00:00Z" if read else None))


def test_title_required(api):
    assert api.post("/monitor/threads", json={}).status_code == 422
    assert api.post("/monitor/threads", json={"title": "  "}).status_code == 422
    r = api.post("/monitor/threads", json={"title": "아크로제약 수입규제"})
    assert r.status_code == 200 and r.json()["title"] == "아크로제약 수입규제"


def test_summary_for_threads_counts_undismissed_only(api):
    from src.persistence import get_monitor_alert_repo

    t1 = api.post("/monitor/threads", json={"title": "A"}).json()["thread_id"]
    t2 = api.post("/monitor/threads", json={"title": "B"}).json()["thread_id"]
    repo = get_monitor_alert_repo()
    repo.add(_alert(t1, "k1", "repealed", "2026-10-01"))
    repo.add(_alert(t1, "k2", "amended", "2026-10-03", read=True))
    repo.add(_alert(t1, "k3", "amended", "2026-10-05"))
    did = repo.add(_alert(t1, "k4", "pending", "2026-10-02"))
    repo.dismiss(did)  # 해제된 것은 어디에도 안 센다
    s = repo.summary_for_threads([t1, t2])
    assert s[t1]["changed_count"] == 3 and s[t1]["unread_alerts"] == 2
    assert s[t1]["kinds"] == {"repealed": 1, "amended": 2}
    assert s[t1]["latest_alert"]["detected_at"] == "2026-10-05" and s[t1]["latest_alert"]["kind"] == "amended"
    assert s[t2] == {"changed_count": 0, "unread_alerts": 0, "kinds": {}, "latest_alert": None, "last_alert_at": None}


def test_list_threads_carries_dashboard_fields(api):
    from src.persistence import get_monitor_alert_repo
    from src.persistence.threads_repo import get_threads_repo

    tid = api.post("/monitor/threads", json={"title": "A"}).json()["thread_id"]
    get_monitor_alert_repo().add(_alert(tid, "k1", "repealed", "2026-10-01"))
    rows = api.get("/monitor/threads").json()["threads"]
    row = next(r for r in rows if r["id"] == tid)
    assert row["changed_count"] == 1 and row["unread_alerts"] == 1
    assert row["kinds"] == {"repealed": 1} and row["latest_alert"]["kind"] == "repealed"
    assert row["last_checked_at"] == "2026-10-01"  # 명시 기록 없으면 최신 알람 시각
    get_threads_repo().set_monitor_checked(tid, "2026-10-06T09:00:00Z")
    row = next(r for r in api.get("/monitor/threads").json()["threads"] if r["id"] == tid)
    assert row["last_checked_at"] == "2026-10-06T09:00:00Z"


def test_detect_records_checked_even_without_watch(api):
    from src.monitor_alerts import detect_for_thread
    from src.persistence.threads_repo import get_threads_repo

    tid = api.post("/monitor/threads", json={"title": "A"}).json()["thread_id"]
    assert detect_for_thread(tid)["complete"] is True
    row = next(t for t in get_threads_repo().list_for_user("dev-bypass-user", limit=50) if t["id"] == tid)
    assert row.get("monitor_checked_at")


def test_report_marks_thread_alerts_read(api):
    from src.persistence import get_monitor_alert_repo

    tid = api.post("/monitor/threads", json={"title": "A"}).json()["thread_id"]
    repo = get_monitor_alert_repo()
    repo.add(_alert(tid, "k1", "repealed", "2026-10-01"))
    repo.add(_alert(tid, "k2", "amended", "2026-10-02"))
    assert repo.unread_counts([tid]) == {tid: 2}
    r = api.post(f"/monitor/threads/{tid}/report", json={})
    assert r.status_code == 200 and r.json()["marked_read"] == 2 and r.json()["alerts"] == 2
    assert repo.unread_counts([tid]) == {}
    # 처리된 뒤에도 changed_count(미해제)는 남는다 — 읽음 ≠ 해제
    assert repo.summary_for_threads([tid])[tid]["changed_count"] == 2
