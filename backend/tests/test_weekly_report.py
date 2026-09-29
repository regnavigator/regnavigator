"""주간 이용 보고서 메일(2026-09-21) — 실사용 필터·피드백 동봉·발송 시각·중복 방지·수신자 제한."""
from __future__ import annotations

import csv
import io
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from src import account_class as ac
from src import weekly_report as wr
from src.persistence import get_events_repo, get_feedback_repo, get_users_repo
from src.persistence.events_repo import Event
from src.persistence.feedback_repo import Feedback

SECRET = "test-secret-weekly-report-0123456789"
KST = timezone(timedelta(hours=9))
WS = date(2026, 9, 14)            # 대상 주(월)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@medireg.test")
    monkeypatch.setenv("WEEKLY_REPORT_TO", "report@medireg.test")
    monkeypatch.setenv("WEEKLY_REPORT_CHECK_INTERVAL_S", "0")
    users = get_users_repo()
    users.upsert(id="u-boss", email="boss@medireg.test")
    users.upsert(id="u-doc", email="doc@hospital.kr")
    users.upsert(id="u-new", email="new@clinic.kr")
    with users._lock, users._conn() as c:
        c.execute("UPDATE users SET created_at='2026-09-01T00:00:00.000000Z'")
        c.execute("UPDATE users SET created_at='2026-09-15T02:00:00.000000Z' WHERE id='u-new'")
    users.set_profile("u-doc", display_name="김의사", affiliation="병원", job_role="의사")
    ac.invalidate()
    sent: list[dict] = []

    def fake_send(**kw):
        sent.append(kw)
        return True
    monkeypatch.setattr("src.observability.notifications.send_email", fake_send)
    return sent


def _emit(ts, et, uid, tid, payload=None):
    get_events_repo().emit(Event(
        id=f"ev_{uuid.uuid4().hex[:12]}",
        ts=ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        event_type=et, user_id=uid, thread_id=tid,
        payload_json=json.dumps(payload or {}, ensure_ascii=False)))


def _tid(ch):
    return "t_" + ch * 32


def _seed():
    d = datetime(2026, 9, 16, 10, tzinfo=KST)
    for _ in range(3):
        _emit(d, "user_question", "u-doc", _tid("a"))
    _emit(d, "user_question", "u-new", _tid("c"))
    _emit(d, "user_question", "u-boss", _tid("b"))                           # 운영진 — 빠져야
    _emit(datetime(2026, 9, 9, 10, tzinfo=KST), "user_question", "u-doc", _tid("d"))  # 전주
    _emit(d, "user_feedback", "u-doc", _tid("a"), {"comment": "서식 <작성> 좋아요"})
    _emit(d, "user_feedback", "u-boss", _tid("b"), {"comment": "내부 테스트 코멘트"})
    _emit(d, "citation_report", "u-doc", _tid("a"),
          {"citation_number": 2, "citation_title": "의료기기법 제6조", "reason": "무관"})
    fb = get_feedback_repo()
    ts = d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    fb.create(Feedback(id="", rating="thumbs_up", user_id="u-doc", thread_id=_tid("a"),
                       message_id="m1", comment="처음엔 별로", created_at=ts))
    fb.create(Feedback(id="", rating="thumbs_down", user_id="u-doc", thread_id=_tid("a"),
                       message_id="m1", comment="다시 보니 틀림",
                       created_at=(d + timedelta(minutes=5)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
    # 인용 신고는 feedback 테이블에도 들어온다 — 평가로 이중 집계되면 안 된다
    fb.create(Feedback(id="", rating="thumbs_down", user_id="u-doc", thread_id=_tid("a"),
                       message_id="m2", comment=json.dumps({"kind": "citation_report"}), created_at=ts))


def test_collect_real_users_only_with_feedback(env):
    _seed()
    data = wr.collect(WS)
    assert data["cur"]["scopes"]["real"]["active_users"] == 2
    assert data["cur"]["scopes"]["real"]["returning_users"] == 1
    assert "users" not in data and "new_users" not in data                   # 개인 단위 명단 없음
    assert data["cur"]["scopes"]["real"]["new_users"] == 1
    # 자유 의견만 — 평가·인용 신고는 목록에 없다
    assert [f["content"] for f in data["feedback"]] == ["서식 <작성> 좋아요"]
    assert data["internal_feedback"] == 1                                    # 운영진 코멘트는 건수만


def test_render_html_escapes_and_includes_sections(env):
    _seed()
    b = wr.build(WS)
    page = b["html"]
    assert "9/14(월) ~ 9/20(일)" in page
    assert "서식 &lt;작성&gt; 좋아요" in page and "<작성>" not in page       # 사용자 입력 이스케이프
    assert "내부 테스트 코멘트" not in page
    assert "/admin/threads?thread=" in page
    assert "사용자별 활동" not in page and "new@clinic.kr" not in page      # 개인 단위 명단 없음
    names = [a[0] for a in b["attachments"]]
    assert names == ["medireg_weekly_report_2026-09-14.html",
                     "medireg_weekly_usage_2026-09-14.csv",
                     "medireg_weekly_opinions_2026-09-14.csv"]
    fb_csv = b["attachments"][2][1].decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(fb_csv)))
    assert rows[0] == ["시각(UTC)", "사용자", "의견", "대화 ID"] and len(rows) == 1 + 1
    assert "무관" not in page and "다시 보니 틀림" not in page              # 인용 신고·평가 코멘트 미포함


def test_due_week_waits_for_monday_send_hour_and_sends_once(env):
    before = datetime(2026, 9, 21, 8, 59, tzinfo=KST)
    after = datetime(2026, 9, 21, 9, 1, tzinfo=KST)
    assert wr.due_week(before) is None
    assert wr.due_week(after) == WS
    res = wr.run_due(after)
    assert res["sent"] == ["report@medireg.test"] and len(env) == 1
    assert env[0]["subject"].startswith("[MEDIREG AI] 주간 이용 보고서")
    assert wr.due_week(datetime(2026, 9, 23, 12, tzinfo=KST)) is None       # 같은 주 재발송 없음
    assert wr.run_due(datetime(2026, 9, 23, 12, tzinfo=KST)) is None
    assert len(env) == 1


def test_failed_send_is_not_recorded(env, monkeypatch):
    monkeypatch.setattr("src.observability.notifications.send_email", lambda **kw: False)
    after = datetime(2026, 9, 21, 10, tzinfo=KST)
    assert wr.run_due(after)["sent"] == []
    assert wr.due_week(after) == WS                                          # 다음 점검에 재시도


def test_disabled_does_nothing(env, monkeypatch):
    monkeypatch.setenv("WEEKLY_REPORT_ENABLED", "0")
    assert wr.run_due(datetime(2026, 9, 21, 10, tzinfo=KST)) is None and env == []


def _admin_client():
    from src.api import app

    now = int(time.time())
    tok = pyjwt.encode({"sub": "u-boss", "email": "boss@medireg.test", "email_verified": True,
                        "iat": now, "exp": now + 600}, SECRET, algorithm="HS256")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


def test_admin_routes_preview_send_status(env):
    c = _admin_client()
    r = c.get("/admin/weekly-report/preview")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert c.get("/admin/weekly-report/preview?week_start=2026-09-15").status_code == 422   # 월요일 아님
    st = c.get("/admin/weekly-report/status").json()
    assert st["to"] == ["report@medireg.test"] and st["send_hour_kst"] == 9
    assert c.post("/admin/weekly-report/send", json={"to": "someone@else.com"}).status_code == 422
    r = c.post("/admin/weekly-report/send", json={"to": "boss@medireg.test"}).json()
    assert r["sent"] == ["boss@medireg.test"]
    # 수동 발송은 자동 발송 기록을 남기지 않는다
    assert c.get("/admin/weekly-report/status").json()["last_week"]["sent"] is None


# ── 관리자 화면 설정(2026-09-21) — env 는 기본값, 저장값이 우선 ──────────────────

def test_config_saved_values_override_env_and_move_schedule(env):
    assert wr.config()["source"] == {"enabled": "env", "to": "env", "weekday": "env", "hour": "env"}
    wr.save_config({"weekday": 2, "hour": 14}, by="boss@medireg.test")      # 수 14시
    cfg = wr.config()
    assert (cfg["weekday"], cfg["hour"]) == (2, 14) and cfg["source"]["weekday"] == "admin"
    assert cfg["to"] == ["report@medireg.test"] and cfg["source"]["to"] == "env"   # 준 항목만
    assert wr.due_week(datetime(2026, 9, 21, 10, tzinfo=KST)) is None       # 월요일엔 아직
    assert wr.due_week(datetime(2026, 9, 23, 13, 59, tzinfo=KST)) is None
    assert wr.due_week(datetime(2026, 9, 23, 14, 1, tzinfo=KST)) == WS
    wr.save_config({"hour": None}, by="boss@medireg.test")                  # 항목 되돌림
    assert wr.config()["hour"] == 9 and wr.config()["source"]["hour"] == "env"
    wr.reset_config(by="boss@medireg.test")
    assert wr.config()["weekday"] == 0


def test_config_recipients_free_but_validated_and_disable_stops_sending(env):
    """수신자는 관리자 화면에서 임의 주소 추가·삭제(2026-09-21) — 형식만 검증."""
    with pytest.raises(ValueError):
        wr.save_config({"to": ["not-an-email"]}, by="x")
    with pytest.raises(ValueError):
        wr.save_config({"to": []}, by="x")
    wr.save_config({"to": ["BOSS@medireg.test", "ceo@partner.co.kr"]}, by="x")
    assert wr.recipients() == ["boss@medireg.test", "ceo@partner.co.kr"]
    wr.save_config({"enabled": False}, by="x")
    assert wr.run_due(datetime(2026, 9, 21, 10, tzinfo=KST)) is None and env == []


def test_config_route(env):
    c = _admin_client()
    st = c.get("/admin/weekly-report/status").json()
    assert "boss@medireg.test" in st["admin_email_options"] and st["send_weekday"] == 0
    assert c.patch("/admin/weekly-report/config", json={"to": ["nobody"]}).status_code == 422
    assert c.patch("/admin/weekly-report/config", json={"hour": 25}).status_code == 422
    st = c.patch("/admin/weekly-report/config",
                 json={"enabled": True, "weekday": 4, "hour": 8, "to": ["boss@medireg.test"]}).json()
    assert (st["send_weekday"], st["send_hour_kst"], st["to"]) == (4, 8, ["boss@medireg.test"])
    assert st["config"]["updated_by"] == "boss@medireg.test"
    assert st["next_run_at"].endswith("08:00+09:00")
    st = c.patch("/admin/weekly-report/config", json={"reset": True}).json()
    assert st["config"]["source"]["hour"] == "env" and st["to"] == ["report@medireg.test"]



def test_weekly_updates_come_from_included_report_notes(env):
    """이번 주 업데이트 = 관리자 전용 보고 노트 중 그 주 날짜·'포함'인 것. 사용자 공지(/updates)는 안 싣는다."""
    from src import announcements as an
    from src import report_notes as rn

    an.publish(title="사용자 공지 노트", items=["x"], date="2026-09-16", popup=False)
    rn.add(title="서식을 다시 열고 관리할 수 있어요", items=["사이드바 › 작성한 서식"],
           feature="서류 작성", day="2026-09-18")
    rn.add(title="출처 종류별 건수를 보여줘요", items=["법령 7 · 웹 2"],
           feature="검색·답변", day="2026-09-15")
    off = rn.add(title="해제한 노트", items=["y"], day="2026-09-16")
    rn.update(off["id"], include=False)
    rn.add(title="다음 주 노트", items=["z"], day="2026-09-21")
    data = wr.collect(WS)
    assert [n["title"] for n in data["updates"]] == [
        "출처 종류별 건수를 보여줘요", "서식을 다시 열고 관리할 수 있어요"]          # FEATURES 순서
    page = wr.render_html(data)
    assert "사이드바 › 작성한 서식" in page
    for hidden in ("사용자 공지 노트", "해제한 노트", "다음 주 노트"):
        assert hidden not in page


def test_report_notes_routes(env):
    c = _admin_client()
    n = c.post("/admin/report-notes", json={"title": "새 기능", "items": ["a"], "feature": "화면·편의",
                                             "date": "2026-09-16"}).json()
    assert n["include"] is True and n["id"].startswith("rn_")
    assert c.post("/admin/report-notes", json={"title": ""}).status_code == 422
    assert c.post("/admin/report-notes", json={"title": "t", "date": "2026-13-01"}).status_code == 422
    r = c.patch(f"/admin/report-notes/{n['id']}", json={"include": False, "title": "고친 제목"}).json()
    assert r["include"] is False and r["title"] == "고친 제목" and r["updated_by"] == "boss@medireg.test"
    lst = c.get("/admin/report-notes?since=2026-09-14&until=2026-09-20").json()
    assert [x["id"] for x in lst["notes"]] == [n["id"]] and "서류 작성" in lst["features"]
    assert c.delete(f"/admin/report-notes/{n['id']}").json()["ok"] is True
    assert c.delete(f"/admin/report-notes/{n['id']}").status_code == 404


def test_report_note_cli(env, capsys):
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "report_note", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "report_note.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["add", "--title", "CLI 노트", "--item", "i1", "--date", "2026-09-17",
                     "--feature", "검색·답변", "--ref", "abc1234"]) == 0
    nid = json.loads(capsys.readouterr().out)["id"]
    assert mod.main(["exclude", nid]) == 0
    from src import report_notes as rn
    assert rn.list_notes(include_only=True) == []
    assert mod.main(["delete", nid]) == 0


def test_no_updates_message(env):
    page = wr.render_html(wr.collect(WS))
    assert "이번 주 보고할 업데이트가 없습니다" in page
