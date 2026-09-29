"""계정 구분 라벨 + 실사용/내부/전체 통계 + 주간 스냅샷 (2026-09-21).

운영자 지적: "이용 조회·실사용에 관리자·테스트 계정이 계속 섞인다" → 라벨 하나로
모든 관리자 화면이 같은 집합을 빼야 한다. 주간 집계는 KST 월~일, 끝난 주는 저장.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from src import account_class as ac
from src import usage_weekly as uw
from src.persistence import get_events_repo, get_report_runs_repo, get_users_repo
from src.persistence.events_repo import Event

SECRET = "test-secret-account-class-0123456789"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@medireg.test")
    monkeypatch.setenv("SERVICE_LAUNCH_AT", "2026-08-03T00:00:00+09:00")
    monkeypatch.setenv("USAGE_WEEKLY_SNAPSHOT_INTERVAL_S", "0")
    users = get_users_repo()
    users.upsert(id="u-boss", email="boss@medireg.test")
    users.upsert(id="u-doc", email="doc@hospital.kr")
    users.upsert(id="u-team", email="teammate@gmail.com")   # 팀원 개인 계정(자동 규칙에 안 걸림)
    users.upsert(id="u-old", email="dev@example.com")
    _set_created("u-old", "2026-05-17T00:00:00.000000Z")
    for uid in ("u-boss", "u-doc", "u-team"):
        _set_created(uid, "2026-09-01T00:00:00.000000Z")
    ac.invalidate()
    return users


def _set_created(uid: str, iso: str) -> None:
    users = get_users_repo()
    with users._lock, users._conn() as c:
        c.execute("UPDATE users SET created_at = ? WHERE id = ?", (iso, uid))


def _tid(ch: str) -> str:
    return "t_" + ch * 32


def _emit(ts: datetime, event_type: str, uid, tid, *, cost=0.0, tin=0, tout=0) -> None:
    get_events_repo().emit(Event(
        id=f"ev_{uuid.uuid4().hex[:12]}",
        ts=ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        event_type=event_type, user_id=uid, thread_id=tid,
        cost_usd=cost, input_tokens=tin, output_tokens=tout))


KST = timezone(timedelta(hours=9))


def _admin_client():
    from src.api import app

    now = int(time.time())
    tok = pyjwt.encode({"sub": "u-boss", "email": "boss@medireg.test", "email_verified": True,
                        "iat": now, "exp": now + 600}, SECRET, algorithm="HS256")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


# ── 판정 규칙 ──────────────────────────────────────────────────────────────

def test_classify_manual_beats_auto(env):
    by_id = {u.id: u for u in get_users_repo().list_all()}
    assert ac.classify(by_id["u-boss"]) == ("staff", "auto:admin")
    assert ac.classify(by_id["u-old"]) == ("test", "auto:pre_launch")
    assert ac.classify(by_id["u-doc"]) == ("user", "auto")
    get_users_repo().set_account_class("u-old", "user")   # 오픈 전 가입이지만 실사용자
    get_users_repo().set_account_class("u-team", "staff")
    ac.invalidate()
    by_id = {u.id: u for u in get_users_repo().list_all()}
    assert ac.classify(by_id["u-old"]) == ("user", "manual")
    assert ac.internal_user_ids() == frozenset({"u-boss", "u-team"})


def test_admin_beats_manual_label_and_staff_labels_migrate(env):
    """관리자는 수동 라벨보다 우선(항상 관리자) · 예전 '운영진' 라벨은 실사용자로 이관
    (관리자 지정은 운영자가 직접)."""
    users = get_users_repo()
    users.set_account_class("u-boss", "user")          # 관리자에게 붙은 옛 라벨
    users.set_account_class("u-team", "staff")         # 관리자 아닌 운영진 라벨
    ac.invalidate()
    by_id = {u.id: u for u in users.list_all()}
    assert ac.classify(by_id["u-boss"]) == ("staff", "auto:admin")
    assert ac.migrate_staff_labels() == 1
    t = users.get("u-team")
    assert not t.is_admin and t.account_class == "user"
    assert ac.classify(t) == ("user", "manual")
    assert ac.migrate_staff_labels() == 0             # 멱등


def test_prelaunch_but_beta_invited_is_real_user(env, monkeypatch):
    """오픈 전 가입이라도 베타 초대 명단이면 실사용자(2026-09-21 운영 실측: 오픈 전 가입 10명 중
    4명이 8/2 초대받은 베타 테스터). 초대 기록이 없는 개발 계정만 테스트로 남는다."""
    users = get_users_repo()
    users.upsert(id="u-early", email="early@hospital.kr")
    _set_created("u-early", "2026-05-17T00:00:00.000000Z")
    monkeypatch.setenv("BETA_WHITELIST_EMAILS", "early@hospital.kr")
    from src import whitelist
    whitelist.invalidate_cache()          # 계정 구분 캐시도 함께 비워진다
    by_id = {u.id: u for u in users.list_all()}
    assert ac.classify(by_id["u-early"]) == ("user", "auto:beta_invited")
    assert ac.classify(by_id["u-old"]) == ("test", "auto:pre_launch")   # 초대 기록 없음
    assert "u-early" not in ac.internal_user_ids() and "u-old" in ac.internal_user_ids()


def test_normalize_rejects_unknown_label():
    assert ac.normalize("auto") is None and ac.normalize("") is None
    assert ac.normalize("Test") == "test"
    with pytest.raises(ValueError):
        ac.normalize("vip")
    with pytest.raises(ValueError):   # 관리자는 라벨이 아니라 권한(2026-09-22 통합)
        ac.normalize("staff")


def test_created_at_format_mismatch_does_not_flip_class():
    """PG 는 '+00:00', SQLite 는 'Z' — 문자열 비교였다면 경계에서 뒤집힌다."""
    class U:  # noqa: D401 — 최소 모형
        account_class = None
        is_admin = False
        email = "x@y.kr"
        created_at = "2026-08-02T15:00:00.000001+00:00"   # 오픈(08-03 00:00 KST) 직후
    assert ac.classify(U(), cut="2026-08-02T15:00:00+00:00")[0] == "user"


# ── 관리자 API: 라벨 → 모든 화면이 같은 집합 ──────────────────────────────

def test_label_via_patch_moves_user_out_of_real_stats(env):
    now = datetime.now(timezone.utc)
    _emit(now, "user_question", "u-doc", _tid("a"))
    _emit(now, "llm_call", "u-doc", _tid("a"), cost=0.01, tin=100, tout=50)
    _emit(now, "user_question", "u-team", _tid("b"))
    _emit(now, "llm_call", "u-team", _tid("b"), cost=0.02, tin=200, tout=80)
    c = _admin_client()

    s = c.get("/admin/stats?days=7&scope=real").json()
    assert s["breakdown"]["real"]["active_users"] == 2       # 팀원 계정이 실사용으로 샌다
    assert s["totals"]["llm_calls"] == 2

    # 구분 '관리자' = 관리자 지정(권한 없음) — 운영진 라벨과 관리자 권한을 통합(2026-09-22)
    r = c.patch("/admin/users/u-team", json={"account_class": "staff"})
    assert r.status_code == 200
    assert r.json()["account_class"] == "staff" and r.json()["account_class_source"] == "auto:admin"
    assert r.json()["is_admin"] is True and r.json()["admin_perms_list"] == []

    s = c.get("/admin/stats?days=7&scope=real").json()
    assert s["totals"]["llm_calls"] == 1                     # 일별 표도 같은 집합으로
    b = s["breakdown"]
    assert b["real"]["active_users"] == 1 and b["internal"]["active_users"] == 1
    assert b["all"]["questions"] == b["real"]["questions"] + b["internal"]["questions"]
    assert b["all"]["cost_usd"] == pytest.approx(b["real"]["cost_usd"] + b["internal"]["cost_usd"])

    users = c.get("/admin/users?scope=all").json()["users"]
    row = {u["id"]: u for u in users}
    assert row["u-team"]["is_internal"] and row["u-team"]["account_class_label"] == "관리자"
    assert row["u-old"]["account_class"] == "test" and row["u-old"]["account_class_source"] == "auto:pre_launch"
    real_ids = {u["id"] for u in c.get("/admin/users?scope=real").json()["users"]}
    assert real_ids == {"u-doc"}

    # 관리자 계정은 구분을 못 바꾼다 — 관리자 해제하면 자동 판정으로
    assert c.patch("/admin/users/u-team", json={"account_class": "user"}).status_code == 409
    assert c.patch("/admin/users/u-team", json={"is_admin": False}).json()["account_class"] == "user"
    assert c.patch("/admin/users/u-team", json={"account_class": "vip"}).status_code == 422


def test_review_queue_uses_same_internal_set(env):
    from src.routes.admin import _excluded_admin_user_ids
    from src.routes.admin_reviews import _excluded_user_ids

    get_users_repo().set_account_class("u-team", "test")
    ac.invalidate()
    assert _excluded_user_ids("real") == _excluded_admin_user_ids("real") == ac.internal_user_ids()
    assert _excluded_user_ids("all") == frozenset()


# ── 일별 = KST 날짜 ────────────────────────────────────────────────────────

def test_daily_stats_group_by_local_day(env):
    # KST 09-15 00:30 = UTC 09-14 15:30 → KST 날짜 09-15 로 묶여야 한다
    _emit(datetime(2026, 9, 15, 0, 30, tzinfo=KST), "llm_call", "u-doc", _tid("a"))
    _emit(datetime(2026, 9, 14, 23, 30, tzinfo=KST), "llm_call", "u-doc", _tid("a"))
    days = {d["day"]: d["llm_calls"] for d in get_events_repo().daily_stats(
        since="2026-09-01T00:00:00.000000Z")}
    assert days == {"2026-09-15": 1, "2026-09-14": 1}


# ── 주간 집계 ──────────────────────────────────────────────────────────────

def test_compute_week_scopes_boundaries_and_returning(env):
    ws = date(2026, 9, 14)                                    # 월요일
    # 경계: 일요일 23:30 KST 는 그 주, 월요일 00:30 KST 는 다음 주
    _emit(datetime(2026, 9, 20, 23, 30, tzinfo=KST), "user_question", "u-doc", _tid("a"))
    _emit(datetime(2026, 9, 21, 0, 30, tzinfo=KST), "user_question", "u-doc", _tid("c"))
    _emit(datetime(2026, 9, 15, 10, 0, tzinfo=KST), "user_question", "u-boss", _tid("b"))
    _emit(datetime(2026, 9, 15, 10, 0, tzinfo=KST), "user_question", None, "bench_x")  # 스크립트
    _emit(datetime(2026, 9, 16, 10, 0, tzinfo=KST), "llm_call", "u-doc", _tid("a"),
          cost=0.5, tin=1000, tout=200)
    _emit(datetime(2026, 9, 8, 10, 0, tzinfo=KST), "user_question", "u-doc", _tid("d"))  # 전주
    runs = get_report_runs_repo()
    runs.acquire(idempotency_key="rpt_w1", thread_id=_tid("a"), user_id="u-doc", prompt="p")
    runs.acquire(idempotency_key="rpt_w2", thread_id=_tid("a"), user_id="u-doc", prompt="[서식] x",
                 purpose="document_draft")
    with runs._lock, runs._conn() as c:
        c.execute("UPDATE report_runs SET started_at = '2026-09-16T01:00:00.000000Z'")
    _set_created("u-doc", "2026-09-15T01:00:00.000000Z")

    w = uw.compute_week(ws)
    real, internal, all_ = w["real"], w["internal"], w["all"]
    assert real["questions"] == 1 and real["active_users"] == 1
    assert real["returning_users"] == 1                       # 전주에도 질문
    assert internal["questions"] == 2                         # 관리자 + 스크립트
    assert all_["questions"] == 3
    assert real["reports"] == 1 and real["documents"] == 1
    assert real["tokens"] == 1200 and real["cost_usd"] == 0.5
    assert real["new_users"] == 1 and all_["new_users"] == 1


def test_weekly_series_stores_past_weeks_and_flags_stale(env):
    cur = uw.current_week_start()
    last = cur - timedelta(days=7)
    _emit(datetime(last.year, last.month, last.day, 12, tzinfo=KST), "user_question",
          "u-team", _tid("a"))
    c = _admin_client()

    r = c.get("/admin/stats/weekly?weeks=4").json()
    assert r["weeks"][0]["partial"] is True and r["weeks"][0]["stored"] is False
    past = r["weeks"][1]
    assert past["week_start"] == last.isoformat() and past["stored"] and not past["stale"]
    assert past["scopes"]["real"]["active_users"] == 1
    assert uw.load_snapshot(last) is not None                 # 저장됐다
    assert uw.load_snapshot(cur) is None                       # 진행 중인 주는 저장 안 함

    # 라벨을 바꾸면 저장본은 그대로 두고 stale 표시 → 재계산해야 반영
    c.patch("/admin/users/u-team", json={"account_class": "staff"})
    past = c.get("/admin/stats/weekly?weeks=4").json()["weeks"][1]
    assert past["stale"] is True and past["scopes"]["real"]["active_users"] == 1
    done = c.post("/admin/stats/weekly/recompute", json={}).json()["recomputed"]
    assert last.isoformat() in done
    past = c.get("/admin/stats/weekly?weeks=4").json()["weeks"][1]
    assert past["stale"] is False and past["scopes"]["real"]["active_users"] == 0
    assert past["scopes"]["internal"]["active_users"] == 1

    assert c.post("/admin/stats/weekly/recompute",
                  json={"week_start": cur.isoformat()}).status_code == 422   # 진행 중
    assert c.post("/admin/stats/weekly/recompute",
                  json={"week_start": (last + timedelta(days=1)).isoformat()}).status_code == 422


def test_ensure_recent_snapshots_is_idempotent(env):
    made = uw.ensure_recent_snapshots(2)
    assert made == 2
    assert uw.ensure_recent_snapshots(2) == 0
