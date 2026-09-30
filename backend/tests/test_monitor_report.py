"""고객사별 규제 모니터링 리포트 — repo · 스케줄 · 수집/렌더 · 발송 게이트."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src import monitor_report as mr
from src.persistence import Bookmark, get_bookmarks_repo, get_monitor_targets_repo
from src.persistence.monitor_targets_repo import MonitorTarget, parse_recipients

KST = timezone(timedelta(hours=9))

#: detect_with_status 의 두 번째 반환값(조회 완전성)
_OK = {"checked": 1, "amendment_status_ok": True, "articles_ok": True, "complete": True}
_DEGRADED = {"checked": 1, "amendment_status_ok": False, "articles_ok": True,
             "complete": False}


def _target(**kw) -> MonitorTarget:
    base = dict(id="", user_id="u1", folder="아크로제약",
                recipients="a@example.com", label=None, cadence="weekly",
                send_weekday=0, send_hour=9, enabled=1)
    base.update(kw)
    return MonitorTarget(**base)


def _bookmark(user_id: str, folder: str, key: str, date_: str) -> Bookmark:
    cid = f"cite_doc_{key}"
    return Bookmark(
        id="", user_id=user_id, citation_id=cid,
        citation_json=json.dumps({"id": cid, "title": f"테스트법 {key}", "date": date_}),
        folder=folder,
    )


# ── parse_recipients ────────────────────────────────────────────────────────

def test_parse_recipients_filters_and_dedups():
    got = parse_recipients("a@x.com, bad, b@y.co.kr\na@x.com;c@z.org")
    assert got == ["a@x.com", "b@y.co.kr", "c@z.org"]


def test_parse_recipients_accepts_list_and_empty():
    assert parse_recipients(["a@x.com", " ", "nope"]) == ["a@x.com"]
    assert parse_recipients(None) == []


# ── repo ────────────────────────────────────────────────────────────────────

def test_upsert_is_idempotent_per_folder():
    repo = get_monitor_targets_repo()
    first = repo.upsert(_target())
    second = repo.upsert(_target(recipients="b@example.com", label="아크로"))
    assert first == second, "같은 (user, folder) 는 갱신이어야 한다"

    got = repo.get("u1", first)
    assert got is not None
    assert got.as_dict()["recipients"] == ["b@example.com"]
    assert got.as_dict()["display_name"] == "아크로"


def test_get_is_user_scoped():
    repo = get_monitor_targets_repo()
    tid = repo.upsert(_target(user_id="owner", folder="scoped"))
    assert repo.get("owner", tid) is not None
    assert repo.get("someone-else", tid) is None


def test_list_enabled_excludes_disabled():
    repo = get_monitor_targets_repo()
    on = repo.upsert(_target(user_id="u2", folder="on"))
    repo.upsert(_target(user_id="u2", folder="off", enabled=0))
    ids = {t.id for t in repo.list_enabled()}
    assert on in ids
    assert all(int(t.enabled) == 1 for t in repo.list_enabled())


def test_mark_sent_sets_timestamp():
    repo = get_monitor_targets_repo()
    tid = repo.upsert(_target(user_id="u3", folder="ts"))
    assert repo.get("u3", tid).last_sent_at is None
    repo.mark_sent(tid)
    assert repo.get("u3", tid).last_sent_at is not None


# ── 스케줄 판정 ──────────────────────────────────────────────────────────────

def test_is_due_false_before_scheduled_hour():
    t = _target(send_weekday=0, send_hour=9)          # 월 09:00
    monday_8am = datetime(2026, 10, 5, 8, 0, tzinfo=KST)
    assert mr.is_due(t, monday_8am) is False


def test_is_due_true_after_scheduled_hour():
    t = _target(send_weekday=0, send_hour=9)
    monday_10am = datetime(2026, 10, 5, 10, 0, tzinfo=KST)
    assert mr.is_due(t, monday_10am) is True


def test_is_due_false_when_already_sent_this_period():
    t = _target(send_weekday=0, send_hour=9)
    t.last_sent_at = datetime(2026, 10, 5, 9, 30, tzinfo=KST).isoformat()
    assert mr.is_due(t, datetime(2026, 10, 7, 10, 0, tzinfo=KST)) is False


def test_is_due_true_next_period_after_previous_send():
    t = _target(send_weekday=0, send_hour=9)
    t.last_sent_at = datetime(2026, 10, 5, 9, 30, tzinfo=KST).isoformat()
    assert mr.is_due(t, datetime(2026, 10, 12, 10, 0, tzinfo=KST)) is True


def test_is_due_false_when_disabled():
    t = _target(enabled=0)
    assert mr.is_due(t, datetime(2026, 10, 5, 23, 0, tzinfo=KST)) is False


def test_monthly_cadence_fires_on_first_of_month():
    t = _target(cadence="monthly", send_hour=8)
    assert mr.is_due(t, datetime(2026, 11, 1, 7, 0, tzinfo=KST)) is False
    assert mr.is_due(t, datetime(2026, 11, 1, 9, 0, tzinfo=KST)) is True


# ── 수집 · 렌더 ──────────────────────────────────────────────────────────────

def test_collect_scopes_to_folder(monkeypatch):
    bms = get_bookmarks_repo()
    bms.create(_bookmark("uf", "고객사A", "001234_0001001", "2026-01-01"))
    bms.create(_bookmark("uf", "고객사B", "005678_0002001", "2026-01-01"))

    seen = {}

    def fake_detect(scoped):
        seen["n"] = len(list(scoped))
        return [], _OK

    monkeypatch.setattr(mr, "detect_amendments", fake_detect)
    data = mr.collect(_target(user_id="uf", folder="고객사A"))
    assert seen["n"] == 1, "다른 고객사 폴더의 북마크가 섞이면 안 된다"
    assert data["watched"] == 1


def test_collect_sorts_repealed_first(monkeypatch):
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([
        {"kind": "amended", "title": "나법", "citation_id": "c2"},
        {"kind": "repealed", "title": "가법", "citation_id": "c1"},
        {"kind": "pending", "title": "다법", "citation_id": "c3"},
    ], _OK))
    data = mr.collect(_target(user_id="us", folder="none"))
    assert [c["kind"] for c in data["changes"]] == ["repealed", "pending", "amended"]
    assert data["counts"]["repealed"] == 1


def test_render_outputs_contain_changes(monkeypatch):
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([
        {"kind": "repealed", "title": "의료기기법", "citation_id": "c1",
         "saved_date": "2025-01-01"},
    ], _OK))
    b = mr.build(_target(user_id="ur", folder="렌더", label="렌더고객"))
    assert "렌더고객" in b["subject"] and "1건" in b["subject"]
    assert "의료기기법" in b["html"] and "폐지" in b["html"]
    assert "의료기기법" in b["text"]
    name, blob = b["attachments"][0]
    assert name.endswith(".csv")
    assert "의료기기법" in blob.decode("utf-8-sig")


def test_subject_says_no_change_when_empty(monkeypatch):
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([], _OK))
    b = mr.build(_target(user_id="un", folder="빈폴더"))
    assert "변경 없음" in b["subject"]
    assert "감지된 변경이 없습니다" in b["html"]


# ── 발송 게이트 ──────────────────────────────────────────────────────────────

def test_send_skips_when_no_change(monkeypatch):
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([], _OK))
    calls = []
    monkeypatch.setattr("src.observability.notifications.send_email",
                        lambda **kw: calls.append(kw) or True)
    r = mr.send(_target(user_id="us1", folder="무변경"))
    assert r["skipped"] == "no_change"
    assert calls == [], "변경 0건이면 메일을 보내지 않는다"


def test_send_force_overrides_no_change(monkeypatch):
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([], _OK))
    calls = []
    monkeypatch.setattr("src.observability.notifications.send_email",
                        lambda **kw: calls.append(kw) or True)
    r = mr.send(_target(user_id="us2", folder="강제"), force=True)
    assert r.get("skipped") is None
    assert len(calls) == 1


def test_send_reports_per_recipient_failure(monkeypatch):
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([
        {"kind": "amended", "title": "가법", "citation_id": "c1"}], _OK))

    def flaky(**kw):
        return kw["to"] != "bad@example.com"

    monkeypatch.setattr("src.observability.notifications.send_email", flaky)
    r = mr.send(_target(user_id="us3", folder="부분실패",
                        recipients="ok@example.com,bad@example.com"))
    assert r["sent"] == ["ok@example.com"]
    assert r["failed"] == ["bad@example.com"]


def test_run_due_marks_sent_and_skips_not_due(monkeypatch):
    repo = get_monitor_targets_repo()
    tid = repo.upsert(_target(user_id="urun", folder="정기", send_weekday=0, send_hour=9))
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([
        {"kind": "pending", "title": "가법", "citation_id": "c1"}], _OK))
    monkeypatch.setattr("src.observability.notifications.send_email", lambda **kw: True)

    before = datetime(2026, 10, 5, 8, 0, tzinfo=KST)
    assert [r for r in mr.run_due(before) if r["target_id"] == tid] == []

    after = datetime(2026, 10, 5, 10, 0, tzinfo=KST)
    got = [r for r in mr.run_due(after) if r["target_id"] == tid]
    assert len(got) == 1 and got[0]["sent"]
    assert repo.get("urun", tid).last_sent_at is not None

    # 같은 주기에 다시 돌아도 재발송하지 않는다.
    assert [r for r in mr.run_due(after) if r["target_id"] == tid] == []


def test_run_due_keeps_going_when_one_target_raises(monkeypatch):
    repo = get_monitor_targets_repo()
    bad = repo.upsert(_target(user_id="uerr", folder="깨짐", send_hour=0))
    good = repo.upsert(_target(user_id="uerr", folder="정상", send_hour=0))

    def selective(target, **kw):
        if target.id == bad:
            raise RuntimeError("boom")
        return {"target_id": target.id, "sent": ["x@y.com"], "failed": [], "changes": 1}

    monkeypatch.setattr(mr, "send", selective)
    ids = {r["target_id"] for r in mr.run_due(datetime(2026, 10, 5, 12, 0, tzinfo=KST))}
    assert good in ids, "한 고객사 실패가 나머지 발송을 막으면 안 된다"
    assert bad not in ids


@pytest.mark.parametrize("cadence", ["weekly", "monthly"])
def test_next_run_at_is_iso(cadence):
    t = _target(cadence=cadence)
    assert mr.next_run_at(t, datetime(2026, 10, 5, 12, 0, tzinfo=KST)).startswith("2026-")


# ── 조회 불완전(degraded) 처리 ───────────────────────────────────────────────

def test_degraded_with_no_changes_is_not_sent(monkeypatch):
    """법령 DB 조회가 실패한 채 '변경 없음'을 보내면 거짓 안심을 준다."""
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([], _DEGRADED))
    calls = []
    monkeypatch.setattr("src.observability.notifications.send_email",
                        lambda **kw: calls.append(kw) or True)
    r = mr.send(_target(user_id="ud1", folder="불완전"))
    assert r["skipped"] == "degraded" and r["degraded"] is True
    assert calls == []


def test_degraded_with_changes_is_sent_with_warning(monkeypatch):
    """일부라도 잡혔으면 보내되, 빠진 게 있을 수 있음을 본문에 밝힌다."""
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([
        {"kind": "repealed", "title": "가법", "citation_id": "c1"},
    ], _DEGRADED))
    monkeypatch.setattr("src.observability.notifications.send_email", lambda **kw: True)
    b = mr.build(_target(user_id="ud2", folder="부분확인"))
    assert "일부 확인 불가" in b["subject"]
    assert "확인하지 못했습니다" in b["html"]
    r = mr.send(_target(user_id="ud2", folder="부분확인"))
    assert r["sent"] and r["degraded"] is True


def test_run_due_does_not_mark_sent_when_degraded(monkeypatch):
    """보류는 기록을 남기지 않아야 다음 점검에 다시 시도한다."""
    repo = get_monitor_targets_repo()
    tid = repo.upsert(_target(user_id="ud3", folder="보류", send_hour=0))
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([], _DEGRADED))
    monkeypatch.setattr("src.observability.notifications.send_email", lambda **kw: True)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=KST)
    got = [r for r in mr.run_due(now) if r["target_id"] == tid]
    assert got and got[0]["skipped"] == "degraded"
    assert repo.get("ud3", tid).last_sent_at is None, "보류인데 발송 기록이 남으면 안 된다"

    # 조회가 회복되면 같은 주기에 다시 시도해 발송된다.
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([
        {"kind": "pending", "title": "가법", "citation_id": "c1"},
    ], _OK))
    got2 = [r for r in mr.run_due(now) if r["target_id"] == tid]
    assert got2 and got2[0]["sent"]
    assert repo.get("ud3", tid).last_sent_at is not None


def test_detect_reports_incomplete_when_source_fails(monkeypatch):
    """pg_client 조회가 깨지면 complete=False 로 표시된다."""
    from src import amendments

    bms = get_bookmarks_repo()
    bms.create(_bookmark("udet", "판정", "009999_0001001", "2026-01-01"))
    scoped = [b for b in bms.list_for_user("udet") if b.folder == "판정"]

    def boom(*a, **kw):
        raise RuntimeError("pg down")

    monkeypatch.setattr("src.retrieval.pg_client.fetch_amendment_status", boom)
    monkeypatch.setattr("src.retrieval.pg_client.fetch_articles", boom)
    changes, status = amendments.detect_with_status(scoped)
    assert changes == []
    assert status["complete"] is False
    assert status["amendment_status_ok"] is False and status["articles_ok"] is False


# ── 이벤트 적재 ──────────────────────────────────────────────────────────────

def test_send_emits_event(monkeypatch):
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([
        {"kind": "amended", "title": "가법", "citation_id": "c1"},
    ], _OK))
    monkeypatch.setattr("src.observability.notifications.send_email", lambda **kw: True)
    repo = get_monitor_targets_repo()
    tid = repo.upsert(_target(user_id="uev", folder="이벤트"))
    mr.send(repo.get("uev", tid))

    from src.persistence import get_events_repo

    evs = get_events_repo().list_by_type("monitor_report", limit=20)
    mine = [e for e in evs if e.user_id == "uev"]
    assert mine, "발송 결과가 events 에 남아야 한다"
    payload = json.loads(mine[0].payload_json)
    assert payload["changes"] == 1 and payload["target_id"] == tid
    assert "folder" not in payload, "고객사명은 이벤트에 남기지 않는다"


def test_event_failure_does_not_break_send(monkeypatch):
    monkeypatch.setattr(mr, "detect_amendments", lambda _b: ([
        {"kind": "amended", "title": "가법", "citation_id": "c1"},
    ], _OK))
    monkeypatch.setattr("src.observability.notifications.send_email", lambda **kw: True)

    def boom(*a, **kw):
        raise RuntimeError("events down")

    monkeypatch.setattr("src.persistence.get_events_repo", boom)
    r = mr.send(_target(user_id="uev2", folder="이벤트실패"))
    assert r["sent"], "이벤트 적재 실패가 발송을 되돌리면 안 된다"
