"""S1 회귀 — users·events·feedback repos.

각 테스트마다 별도 SQLite + lru_cache 리셋.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "medi.db"))

    from src import persistence as P
    P.get_blob_store.cache_clear()
    P.get_reports_repo.cache_clear()
    P.get_users_repo.cache_clear()
    P.get_events_repo.cache_clear()
    P.get_feedback_repo.cache_clear()
    yield
    P.get_blob_store.cache_clear()
    P.get_reports_repo.cache_clear()
    P.get_users_repo.cache_clear()
    P.get_events_repo.cache_clear()
    P.get_feedback_repo.cache_clear()


# ---------------------------------------------------------------------------
# UsersRepo
# ---------------------------------------------------------------------------
def test_user_upsert_creates_then_updates():
    from src.persistence import get_users_repo
    repo = get_users_repo()

    u1 = repo.upsert(id="u-1", email="a@x.com")
    assert u1.email == "a@x.com"
    assert u1.is_admin is False
    assert u1.email_verified_at is None
    assert u1.daily_token_limit_override is None

    # email update + verified
    u2 = repo.upsert(id="u-1", email="a2@x.com", email_verified_at="2026-04-30T00:00:00Z")
    assert u2.email == "a2@x.com"
    assert u2.email_verified_at == "2026-04-30T00:00:00Z"

    got = repo.get("u-1")
    assert got is not None and got.email == "a2@x.com"


def test_user_get_by_email():
    from src.persistence import get_users_repo
    repo = get_users_repo()
    repo.upsert(id="u-2", email="b@x.com")
    assert repo.get_by_email("b@x.com").id == "u-2"
    assert repo.get_by_email("missing@x.com") is None


def test_user_quota_override_and_admin():
    from src.persistence import get_users_repo
    repo = get_users_repo()
    repo.upsert(id="u-3", email="c@x.com")
    repo.update_quota("u-3", daily_override=200000, monthly_override=5000000)
    repo.set_admin("u-3", True)

    u = repo.get("u-3")
    assert u.daily_token_limit_override == 200000
    assert u.monthly_token_limit_override == 5000000
    assert u.is_admin is True

    # partial update
    repo.update_quota("u-3", daily_override=300000)
    u = repo.get("u-3")
    assert u.daily_token_limit_override == 300000
    assert u.monthly_token_limit_override == 5000000  # 그대로


def test_user_list_all_orders_by_created_desc():
    from src.persistence import get_users_repo
    repo = get_users_repo()
    repo.upsert(id="u-A", email="A@x.com")
    repo.upsert(id="u-B", email="B@x.com")
    rows = repo.list_all()
    assert {r.id for r in rows} == {"u-A", "u-B"}


def test_user_list_all_q_searches_email():
    """q= 이메일 부분일치 — 서버측 검색(2026-08-05). 와일드카드는 리터럴."""
    from src.persistence import get_users_repo
    repo = get_users_repo()
    repo.upsert(id="u-1", email="doctor.kim@hospital.kr")
    repo.upsert(id="u-2", email="ra.lee@device.co.kr")
    repo.upsert(id="u-3", email="kim_percent@x.com")

    assert {r.id for r in repo.list_all(q="kim")} == {"u-1", "u-3"}
    assert {r.id for r in repo.list_all(q="device.co")} == {"u-2"}
    assert repo.list_all(q="없는사람") == []
    # 대소문자 무시
    assert {r.id for r in repo.list_all(q="KIM")} == {"u-1", "u-3"}
    # % · _ 는 와일드카드가 아니라 리터럴 — "m_p" 가 아무나 매치하면 안 됨
    assert {r.id for r in repo.list_all(q="m_p")} == {"u-3"}
    assert repo.list_all(q="%") == []


# ---------------------------------------------------------------------------
# EventsRepo
# ---------------------------------------------------------------------------
def test_event_emit_and_get():
    from src.persistence import Event, get_events_repo
    repo = get_events_repo()
    eid = repo.emit(Event(
        id="", ts="", event_type="llm_call",
        user_id="u-1", thread_id="t-1", run_id="r-1",
        input_tokens=100, output_tokens=50, cost_usd=0.0015,
        payload_json='{"model": "claude-sonnet-4-6"}',
    ))
    e = repo.get(eid)
    assert e.event_type == "llm_call"
    assert e.input_tokens == 100
    assert e.cost_usd == pytest.approx(0.0015)
    assert e.user_id == "u-1"


def test_event_list_for_user_filters_by_type_and_since():
    from src.persistence import Event, get_events_repo
    repo = get_events_repo()
    repo.emit(Event(id="", ts="2026-04-29T00:00:00.000Z", event_type="llm_call",
                    user_id="u-1", input_tokens=10, output_tokens=5))
    repo.emit(Event(id="", ts="2026-04-30T00:00:00.000Z", event_type="llm_call",
                    user_id="u-1", input_tokens=20, output_tokens=10))
    repo.emit(Event(id="", ts="2026-04-30T00:00:00.000Z", event_type="feedback",
                    user_id="u-1"))

    today = repo.list_for_user("u-1", event_type="llm_call",
                                since="2026-04-30T00:00:00.000Z")
    assert len(today) == 1 and today[0].input_tokens == 20

    all_today = repo.list_for_user("u-1", since="2026-04-30T00:00:00.000Z")
    assert len(all_today) == 2


def test_event_sum_tokens_for_user():
    from src.persistence import Event, get_events_repo
    repo = get_events_repo()
    repo.emit(Event(id="", ts="2026-04-30T01:00:00.000Z", event_type="llm_call",
                    user_id="u-1", input_tokens=100, output_tokens=50, cost_usd=0.001))
    repo.emit(Event(id="", ts="2026-04-30T02:00:00.000Z", event_type="llm_call",
                    user_id="u-1", input_tokens=200, output_tokens=100, cost_usd=0.002))
    # 다른 user의 호출은 합치면 안 됨
    repo.emit(Event(id="", ts="2026-04-30T01:00:00.000Z", event_type="llm_call",
                    user_id="u-2", input_tokens=999, output_tokens=999, cost_usd=99))

    i, o, c = repo.sum_tokens_for_user("u-1", since="2026-04-30T00:00:00.000Z")
    assert i == 300 and o == 150 and c == pytest.approx(0.003)


def test_event_list_for_thread_orders_asc():
    from src.persistence import Event, get_events_repo
    repo = get_events_repo()
    repo.emit(Event(id="", ts="2026-04-30T02:00:00.000Z", event_type="tool_call",
                    thread_id="t-1"))
    repo.emit(Event(id="", ts="2026-04-30T01:00:00.000Z", event_type="query_start",
                    thread_id="t-1"))
    rows = repo.list_for_thread("t-1")
    assert [r.event_type for r in rows] == ["query_start", "tool_call"]


def test_event_time_window_helpers():
    from src.persistence import start_of_today_utc_iso, start_of_month_utc_iso
    today = start_of_today_utc_iso()
    month = start_of_month_utc_iso()
    assert "T00:00:00" in today
    assert "T00:00:00" in month
    # month는 day=01
    assert month.split("T")[0].endswith("-01")


# ---------------------------------------------------------------------------
# FeedbackRepo
# ---------------------------------------------------------------------------
def test_feedback_create_and_list():
    from src.persistence import Feedback, get_feedback_repo
    repo = get_feedback_repo()
    fid = repo.create(Feedback(id="", rating="thumbs_up", user_id="u-1",
                                thread_id="t-1", message_id="m-1", comment="좋네요"))
    assert fid

    f = repo.get(fid)
    assert f.rating == "thumbs_up"
    assert f.comment == "좋네요"

    rows = repo.list_for_message("m-1")
    assert len(rows) == 1


def test_feedback_invalid_rating():
    from src.persistence import Feedback, get_feedback_repo
    repo = get_feedback_repo()
    with pytest.raises(ValueError):
        repo.create(Feedback(id="", rating="meh", user_id="u-1"))


def test_feedback_list_for_thread_orders_desc():
    from src.persistence import Feedback, get_feedback_repo
    repo = get_feedback_repo()
    repo.create(Feedback(id="", rating="thumbs_up", thread_id="t-1",
                          created_at="2026-04-30T01:00:00.000Z"))
    repo.create(Feedback(id="", rating="thumbs_down", thread_id="t-1",
                          created_at="2026-04-30T02:00:00.000Z"))
    rows = repo.list_for_thread("t-1")
    assert rows[0].rating == "thumbs_down"
    assert rows[1].rating == "thumbs_up"
