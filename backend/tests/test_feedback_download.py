"""S5 회귀 — feedback API + download event emit.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest


SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "medi.db"))
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    from src import persistence as P
    for f in (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo):
        f.cache_clear()
    yield
    for f in (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo):
        f.cache_clear()


def _make_token(*, sub="u-1", email="alice@example.com"):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "email": email, "email_verified": True,
         "iat": now, "exp": now + 3600},
        SECRET, algorithm="HS256",
    )


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _own_thread(thread_id: str, user_id: str) -> None:
    """보고서 라우트는 소속 thread 소유자만 통과 — 픽스처에 소유자를 기록."""
    from src.persistence.threads_repo import get_threads_repo
    get_threads_repo().ensure_thread(thread_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Message feedback
# ---------------------------------------------------------------------------
def test_message_feedback_creates_record_and_event():
    _own_thread("t-1", "u-1")   # 평가는 본인 thread 에만(2026-08-04 H-6)
    client = _client()
    tok = _make_token(sub="u-1")
    res = client.post(
        "/threads/t-1/messages/m-1/feedback",
        json={"rating": "thumbs_up", "comment": "정확합니다"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200
    assert res.json()["rating"] == "thumbs_up"

    from src.persistence import get_feedback_repo, get_events_repo
    rows = get_feedback_repo().list_for_message("m-1")
    assert len(rows) == 1
    assert rows[0].rating == "thumbs_up"
    assert rows[0].comment == "정확합니다"
    assert rows[0].user_id == "u-1"

    events = get_events_repo().list_for_user("u-1", event_type="feedback")
    assert len(events) == 1
    assert events[0].thread_id == "t-1"
    assert events[0].message_id == "m-1"


def test_message_feedback_canceled_rating_persists():
    """👍/👎 재클릭 취소('canceled') — 라우트는 받는데 repo 가 거부해 500 이던
    배선 오류(2026-08-11). append-only last-wins 계약이라 취소도 행으로 남아야
    직전 평가가 무효화된다."""
    _own_thread("t-c", "u-1")
    client = _client()
    tok = _make_token(sub="u-1")
    for rating in ("thumbs_up", "canceled"):
        res = client.post(
            "/threads/t-c/messages/m-c/feedback",
            json={"rating": rating},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert res.status_code == 200, f"{rating}: {res.text}"

    from src.persistence import get_feedback_repo
    rows = get_feedback_repo().list_for_message("m-c")
    assert len(rows) == 2
    assert rows[0].rating == "canceled"  # 최신순 — last-wins 가 취소


def test_message_feedback_invalid_rating_returns_422():
    client = _client()
    tok = _make_token()
    res = client.post(
        "/threads/t-1/messages/m-1/feedback",
        json={"rating": "meh"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 422   # Pydantic validation


def test_message_feedback_thumbs_down_with_long_comment():
    _own_thread("t-1", "u-1")
    client = _client()
    tok = _make_token()
    long_comment = "잘못된 정보가 많아 신뢰하기 어렵습니다." * 5
    res = client.post(
        "/threads/t-1/messages/m-2/feedback",
        json={"rating": "thumbs_down", "comment": long_comment},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200

    from src.persistence import get_feedback_repo
    rows = get_feedback_repo().list_for_message("m-2")
    assert rows[0].rating == "thumbs_down"
    assert rows[0].comment == long_comment


# ---------------------------------------------------------------------------
# Report feedback
# ---------------------------------------------------------------------------
def test_report_feedback_creates_record():
    from src.persistence import ReportMeta, get_reports_repo, get_blob_store
    blob = get_blob_store()
    uri = blob.put("t-A/r-X.md", "# 보고서")
    get_reports_repo().create(ReportMeta(
        id="r-X", thread_id="t-A", mode="deep", kind="final",
        status="done", blob_uri=uri,
    ))
    _own_thread("t-A", "u-2")

    client = _client()
    tok = _make_token(sub="u-2")
    res = client.post(
        "/reports/r-X/feedback",
        json={"rating": "thumbs_up", "comment": "유용했어요"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200

    from src.persistence import get_feedback_repo
    rows = get_feedback_repo().list_for_thread("t-A")
    assert len(rows) == 1
    assert rows[0].report_id == "r-X"
    assert rows[0].user_id == "u-2"


def test_report_feedback_404_when_report_missing():
    client = _client()
    tok = _make_token()
    res = client.post(
        "/reports/no-such/feedback",
        json={"rating": "thumbs_up"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Download event emit
# ---------------------------------------------------------------------------
def test_download_emits_event():
    from src.persistence import ReportMeta, get_blob_store, get_reports_repo
    blob = get_blob_store()
    uri = blob.put("t-A/r-D.md", "# 보고서 본문")
    get_reports_repo().create(ReportMeta(
        id="r-D", thread_id="t-A", mode="deep", kind="rag",
        status="done", blob_uri=uri,
    ))
    _own_thread("t-A", "u-d")

    client = _client()
    tok = _make_token(sub="u-d")
    res = client.get(
        "/reports/r-D/download",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200
    assert "보고서 본문" in res.text

    from src.persistence import get_events_repo
    events = get_events_repo().list_for_user("u-d", event_type="report_download")
    assert len(events) == 1
    assert events[0].thread_id == "t-A"
    import json as _json
    payload = _json.loads(events[0].payload_json)
    assert payload["report_id"] == "r-D"
    assert payload["kind"] == "rag"
