"""베타 초대 — 등록과 분리된 **수동 1건 발송** + 발송 이력. 2026-08-05.

처음엔 화이트리스트 등록에 딸려 자동 발송하게 만들었는데, 그 구조는 벌크
붙여넣기 한 번이 곧 되돌릴 수 없는 무더기 발송이다. 관리자가 화면에서 한 건씩
버튼으로 보내고, 누구에게 보냈는지는 `invited_at` 이 들고 있는 형태로 바꿨다.

잠그는 것:
  · 등록(POST /admin/whitelist)은 **절대 메일을 보내지 않는다**
  · 발송(POST /admin/whitelist/{entry}/invite)은 1건씩, 성공했을 때만 이력 기록
  · 실패를 성공으로 기록하지 않는다 — 안 간 메일을 '보냄'으로 찍으면 그 사람은
    영영 초대받지 못한다
  · 문구는 2026-08-03 실제 발송 공지를 이어받는다(새로 지어내지 않는다)
"""
from __future__ import annotations

import time as _time

import jwt as _pyjwt
import pytest

_SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "inv.db"))
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("NEXTAUTH_SECRET", _SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)

    from src import persistence as P
    from src.middleware.auth import invalidate_whitelist_cache
    from src.persistence.whitelist_repo import reset_whitelist_repo_cache

    def _reset():
        for f in (P.get_users_repo, P.get_events_repo, P.get_reports_repo,
                  P.get_feedback_repo, P.get_blob_store):
            f.cache_clear()
        reset_whitelist_repo_cache()
        invalidate_whitelist_cache()

    _reset()
    yield
    _reset()


@pytest.fixture
def sent(monkeypatch):
    """실제 SMTP 대신 발송 호출을 가로챈다. 반환값은 성공(1통)."""
    from src import notices

    calls: list[list[str]] = []

    def _fake(emails, *, invited_by=None):
        calls.append(list(emails))
        return {"sent": len(emails), "failed": [], "smtp_configured": True}

    monkeypatch.setattr(notices, "send_beta_invite", _fake)
    return calls


def _h(email="boss@example.com", sub="adm"):
    now = int(_time.time())
    tok = _pyjwt.encode({"sub": sub, "email": email, "email_verified": True,
                         "iat": now, "exp": now + 3600},
                        _SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _client():
    from fastapi.testclient import TestClient

    from src.api import app
    return TestClient(app)


# ── 등록은 보내지 않는다 ───────────────────────────────────────────────────
def test_adding_never_sends_mail(sent):
    """자동 발송 폐지 — 벌크 붙여넣기가 곧 무더기 발송이 되면 안 된다."""
    r = _client().post("/admin/whitelist",
                       json={"entries": "a@x.com,b@x.com,c@x.com"}, headers=_h())

    assert r.status_code == 201
    assert len(r.json()["added"]) == 3
    assert sent == [], "등록만 했는데 메일이 나갔다"
    assert "invite" not in r.json()


def test_newly_added_entry_is_not_invited_yet(sent):
    c = _client()
    c.post("/admin/whitelist", json={"entry": "new@x.com"}, headers=_h())

    rows = c.get("/admin/whitelist", headers=_h()).json()["db_entries"]
    row = next(r for r in rows if r["entry"] == "new@x.com")
    assert row["invited_at"] is None, "발송한 적 없는데 발송완료로 보인다"


# ── 개별 발송 ──────────────────────────────────────────────────────────────
def test_invite_button_sends_one_and_records_it(sent):
    c = _client()
    c.post("/admin/whitelist", json={"entry": "one@x.com"}, headers=_h())

    r = c.post("/admin/whitelist/one@x.com/invite", headers=_h())

    assert r.status_code == 200
    assert sent == [["one@x.com"]]
    body = r.json()
    assert body["resent"] is False
    assert body["invited_at"], "발송 시각이 기록되지 않았다"

    rows = c.get("/admin/whitelist", headers=_h()).json()["db_entries"]
    row = next(x for x in rows if x["entry"] == "one@x.com")
    assert row["invited_at"] and row["invited_by"] == "boss@example.com"


def test_resend_is_allowed_and_flagged(sent):
    """재발송은 관리자의 명시적 선택 — 막지 않되 어느 쪽인지 알려준다."""
    c = _client()
    c.post("/admin/whitelist", json={"entry": "two@x.com"}, headers=_h())
    c.post("/admin/whitelist/two@x.com/invite", headers=_h())

    r = c.post("/admin/whitelist/two@x.com/invite", headers=_h())

    assert r.status_code == 200 and r.json()["resent"] is True
    assert len(sent) == 2


def test_unknown_entry_is_404(sent):
    r = _client().post("/admin/whitelist/nobody@x.com/invite", headers=_h())
    assert r.status_code == 404 and sent == []


def test_domain_entry_cannot_be_invited(sent):
    """`@company.com` 은 수신자가 없다 — 조용히 성공하면 관리자가 착각한다."""
    c = _client()
    c.post("/admin/whitelist", json={"entry": "@company.com"}, headers=_h())

    r = c.post("/admin/whitelist/@company.com/invite", headers=_h())

    assert r.status_code == 422 and sent == []


def test_non_admin_cannot_invite(sent):
    c = _client()
    c.post("/admin/whitelist", json={"entry": "x@x.com"}, headers=_h())

    r = c.post("/admin/whitelist/x@x.com/invite",
               headers=_h(email="rando@x.com", sub="u-r"))

    assert r.status_code in (401, 403) and sent == []


# ── 기존 가입자 오발송 방지 ────────────────────────────────────────────────
def _make_member(email: str):
    """이 이메일로 가입한 계정을 만든다(= JWT 로 한 번이라도 접근한 사용자)."""
    _client().get("/me/usage", headers=_h(email=email, sub=f"u-{email}"))
    from src.persistence import get_users_repo
    assert get_users_repo().get_by_email(email), "가입자 생성 실패"


def test_existing_member_is_blocked_by_default(sent):
    """며칠째 쓰고 있는 사람에게 '베타 서비스를 시작합니다'가 나가면 안 된다.

    invited_at 은 이 기능이 생긴 뒤의 발송만 안다 — 그 전에 공지를 받고 이미
    가입한 사람도 전부 '미발송'으로 보인다. 가입 여부가 그 오발송을 막는다.
    """
    _make_member("member@x.com")
    c = _client()
    c.post("/admin/whitelist", json={"entry": "member@x.com"}, headers=_h())

    r = c.post("/admin/whitelist/member@x.com/invite", headers=_h())

    assert r.status_code == 409, "가입자에게 초대가 그냥 나갔다"
    assert "이미 가입" in r.json()["detail"]
    assert sent == []


def test_existing_member_can_be_forced(sent):
    """막되 봉인하지는 않는다 — 관리자가 정말 원하면 force 로 보낸다."""
    _make_member("force@x.com")
    c = _client()
    c.post("/admin/whitelist", json={"entry": "force@x.com"}, headers=_h())

    r = c.post("/admin/whitelist/force@x.com/invite",
               json={"force": True}, headers=_h())

    assert r.status_code == 200
    assert r.json()["forced_member"] is True
    assert sent == [["force@x.com"]]


def test_non_member_needs_no_force(sent):
    c = _client()
    c.post("/admin/whitelist", json={"entry": "fresh@x.com"}, headers=_h())

    assert c.post("/admin/whitelist/fresh@x.com/invite",
                  headers=_h()).status_code == 200
    assert sent == [["fresh@x.com"]]


def test_list_marks_who_already_joined(sent):
    """화면이 '가입완료'를 보여줘야 관리자가 누르기 전에 안다."""
    _make_member("joined@x.com")
    c = _client()
    c.post("/admin/whitelist", json={"entries": "joined@x.com,notyet@x.com"},
           headers=_h())

    rows = {r["entry"]: r for r in
            c.get("/admin/whitelist", headers=_h()).json()["db_entries"]}

    assert rows["joined@x.com"]["joined_at"], "가입자인데 표시가 없다"
    assert rows["notyet@x.com"]["joined_at"] is None


# ── 실패를 성공으로 기록하지 않는다 ────────────────────────────────────────
def test_failed_send_is_not_recorded_as_invited(monkeypatch):
    """안 간 메일을 '보냄'으로 찍으면 그 사람은 영영 초대받지 못한다."""
    from src import notices

    c = _client()
    c.post("/admin/whitelist", json={"entry": "fail@x.com"}, headers=_h())
    monkeypatch.setattr(notices, "send_beta_invite",
                        lambda emails, *, invited_by=None:
                        {"sent": 0, "failed": list(emails), "smtp_configured": True})

    r = c.post("/admin/whitelist/fail@x.com/invite", headers=_h())

    assert r.status_code == 502
    rows = c.get("/admin/whitelist", headers=_h()).json()["db_entries"]
    assert next(x for x in rows if x["entry"] == "fail@x.com")["invited_at"] is None


def test_send_exception_surfaces_and_records_nothing(monkeypatch):
    from src import notices

    c = _client()
    c.post("/admin/whitelist", json={"entry": "boom@x.com"}, headers=_h())

    def _boom(emails, *, invited_by=None):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(notices, "send_beta_invite", _boom)
    r = c.post("/admin/whitelist/boom@x.com/invite", headers=_h())

    assert r.status_code == 502 and "smtp down" in r.json()["detail"]
    rows = c.get("/admin/whitelist", headers=_h()).json()["db_entries"]
    assert next(x for x in rows if x["entry"] == "boom@x.com")["invited_at"] is None


# ── 이력 저장 ──────────────────────────────────────────────────────────────
def test_repo_migrates_existing_db_without_columns(tmp_path):
    """운영 DB 에는 이미 테이블이 있다 — 컬럼 추가가 기동을 깨면 안 된다."""
    import sqlite3

    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE beta_whitelist (entry TEXT PRIMARY KEY, "
                     "added_by TEXT, created_at TEXT NOT NULL)")
        conn.execute("INSERT INTO beta_whitelist VALUES ('old@x.com', 'a', '2026-01-01')")

    from src.persistence.whitelist_repo import SqliteWhitelistRepo

    repo = SqliteWhitelistRepo(path=path)
    rows = repo.list()

    assert rows[0]["entry"] == "old@x.com"
    assert rows[0]["invited_at"] is None, "기존 항목이 발송완료로 둔갑했다"
    assert repo.mark_invited("old@x.com", invited_by="boss@x.com") is True
    assert repo.get("old@x.com")["invited_at"]


def test_mark_invited_on_missing_entry_is_false(tmp_path):
    from src.persistence.whitelist_repo import SqliteWhitelistRepo

    repo = SqliteWhitelistRepo(path=str(tmp_path / "w.db"))
    assert repo.mark_invited("ghost@x.com") is False
    assert repo.get("ghost@x.com") is None


# ── 문구 ───────────────────────────────────────────────────────────────────
def test_invite_body_matches_the_launch_notice():
    """문구는 2026-08-03 실제 발송 공지를 이어받는다 — 새로 지어내지 않는다.

    지어냈다가 어긋난 전례: 서비스명을 다르게 쓰고 "별도 가입 절차 없음"이라고
    안내했는데, 실제로는 /landing 에서 계정을 만들고 비밀번호를 쓴다.
    """
    from src.notices import (
        SIGNUP_URL, _INVITE_BODY, INVITE_SUBJECT, render_notice_html,
    )

    assert "MediReg AI" in _INVITE_BODY and "MediReg AI" in INVITE_SUBJECT
    assert SIGNUP_URL in _INVITE_BODY, "계정 생성 주소가 본문에 없다"
    assert "사전등록하신 이메일 주소로만 가입할 수 있습니다." in _INVITE_BODY
    assert "가입 절차는 없" not in _INVITE_BODY, "가입 절차를 부정하는 문구"

    html = render_notice_html(subject=INVITE_SUBJECT, body_text=_INVITE_BODY,
                              cta_url=SIGNUP_URL, cta_label="계정 만들기")
    assert SIGNUP_URL in html
    # 평문 파트는 마크다운 표식을 걷어낸 버전이 나간다 — `**` 는 to_plain_text 가
    # 지우지 않으므로 본문에 쓰면 그대로 노출된다(실측).
    assert "**" not in _INVITE_BODY, "평문 메일에 마크다운 강조가 그대로 보인다"
    assert "위 주소" not in _INVITE_BODY   # CTA 버튼은 본문 아래에 렌더된다


def test_invite_uses_branded_individual_send(monkeypatch):
    """send_notice 경유 — 개별 발송(수신자 상호 비노출)이 여기서 보장된다."""
    from src import notices

    got = {}
    monkeypatch.setattr(notices, "send_notice",
                        lambda **kw: got.update(kw) or {"sent": 1, "failed": []})
    notices.send_beta_invite(["a@b.com"], invited_by="admin@x.com")

    assert got["emails"] == ["a@b.com"]
    assert got["cta_url"] == notices.SIGNUP_URL
    assert got["subject"] == notices.INVITE_SUBJECT


# ── 과거 공지 이력 이관 ────────────────────────────────────────────────────
def test_mark_invited_can_record_a_past_timestamp(tmp_path):
    """이관한 건에 오늘 날짜를 찍으면 화면이 '8/5에 보냈다'고 거짓말한다."""
    from src.persistence.whitelist_repo import SqliteWhitelistRepo

    repo = SqliteWhitelistRepo(path=str(tmp_path / "b.db"))
    repo.add("past@x.com")
    repo.mark_invited("past@x.com", invited_by="admin", at="2026-08-02T21:00:27Z")

    assert repo.get("past@x.com")["invited_at"] == "2026-08-02T21:00:27Z"


def test_backfill_marks_prior_recipients_and_is_idempotent(tmp_path, monkeypatch):
    """오픈 공지(to=beta_testers)를 받은 사람은 '발송완료'로 시작해야 한다.

    실측: 2026-08-02 공지가 requested 16 / sent 16 으로 화이트리스트 전원에게
    나갔다. 이관하지 않으면 화면이 16명 전원을 미발송으로 보여주고, 성실하게
    버튼을 누를수록 전원이 같은 메일을 두 번 받는다.
    """
    import json
    import runpy
    import sys

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "bf.db"))
    from src.persistence.settings_repo import (
        get_settings_repo, reset_settings_repo_cache,
    )
    from src.persistence.whitelist_repo import (
        get_whitelist_repo, reset_whitelist_repo_cache,
    )

    reset_settings_repo_cache()
    reset_whitelist_repo_cache()
    repo = get_whitelist_repo()
    repo.add("early@x.com")        # 공지 이전 등록 → 받았다
    repo.add("@dom.com")           # 도메인 → 수신자 없음
    for r in repo.list():          # created_at 을 공지 이전으로 맞춘다
        pass
    get_settings_repo().set("admin.scheduled_notices", json.dumps([{
        "subject": "[MediReg AI] 베타 서비스를 시작합니다",
        "status": "sent", "to": "beta_testers",
        "sent_at": "2099-01-01T00:00:00+00:00",   # 모든 기존 항목보다 나중
        "created_by": "admin@x.com",
    }]))

    def _run():
        sys.argv = ["backfill", "--apply"]
        runpy.run_path("scripts/backfill_invite_history.py", run_name="__main__")

    with pytest.raises(SystemExit):
        _run()

    rows = {r["entry"]: r for r in repo.list()}
    assert rows["early@x.com"]["invited_at"] == "2099-01-01T00:00:00+00:00"
    assert rows["@dom.com"]["invited_at"] is None, "도메인 항목에 이력이 찍혔다"

    # 멱등 — 다시 돌려도 값이 흔들리지 않는다.
    with pytest.raises(SystemExit):
        _run()
    assert get_whitelist_repo().get("early@x.com")["invited_at"] == \
        "2099-01-01T00:00:00+00:00"
    reset_settings_repo_cache()
    reset_whitelist_repo_cache()
