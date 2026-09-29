"""뉴스레터 관리(2026-09-22) — 작성·수정·수신 자격(미동의 비활성)·발송·발송 이력."""
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
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("AUTH_DEV_BYPASS_USER", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)
    monkeypatch.delenv("BETA_GATE", raising=False)
    from src import persistence as P
    from src.middleware.auth import invalidate_whitelist_cache
    from src.persistence.settings_repo import reset_settings_repo_cache
    from src.persistence.whitelist_repo import reset_whitelist_repo_cache

    caches = (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo)
    for f in caches:
        f.cache_clear()
    reset_whitelist_repo_cache()
    reset_settings_repo_cache()
    invalidate_whitelist_cache()
    yield
    for f in caches:
        f.cache_clear()
    reset_whitelist_repo_cache()
    reset_settings_repo_cache()
    invalidate_whitelist_cache()


def _tok(*, sub: str, email: str) -> str:
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


def _register(client, tok):
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})




def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _capture_send(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def _fake(**kwargs):
        calls.append(kwargs)
        return kwargs["to"] != "fail@example.com"

    import src.observability.notifications as N
    monkeypatch.setattr(N, "send_email", _fake)
    return calls


def _consent(uid: str, marketing: bool):
    import json
    from src.persistence import get_events_repo
    from src.persistence.events_repo import Event

    scopes = ["terms", "transfer"] + (["marketing"] if marketing else [])
    get_events_repo().emit(Event(id="", ts="", event_type="legal_consent", user_id=uid,
                                 payload_json=json.dumps({"version": "v1", "scopes": scopes})))


def _seed(client):
    boss = _tok(sub="a-root", email="boss@example.com")
    _register(client, boss)
    for sub, email in (("u-ok", "ok@example.com"), ("u-out", "out@example.com"),
                       ("u-fail", "fail@example.com")):
        _register(client, _tok(sub=sub, email=email))
    from src.persistence import get_users_repo
    get_users_repo().set_notice_email_opt_in("u-out", False)
    _consent("u-ok", True)
    _consent("u-fail", False)
    return boss


def test_html_to_text_strips_markup():
    from src.newsletters import html_to_text

    t = html_to_text("<html><head><style>p{}</style></head><body><h1>제목</h1>"
                     "<p>본문 <a href='https://x.io'>링크</a></p><ul><li>하나</li></ul></body></html>")
    assert "p{}" not in t and "제목" in t and "링크 (https://x.io)" in t and "· 하나" in t


def test_crud_preview_and_recipients(monkeypatch):
    client = _client()
    boss = _seed(client)
    r = client.post("/admin/newsletters", headers=_hdr(boss), json={
        "subject": "9월 소식", "body_html": "<p>안녕하세요</p>", "source_filename": "nl.html"})
    assert r.status_code == 201, r.text
    nid = r.json()["newsletter"]["id"]
    r = client.put(f"/admin/newsletters/{nid}", headers=_hdr(boss), json={"subject": "9월 소식(수정)"})
    assert r.status_code == 200 and r.json()["newsletter"]["subject"] == "9월 소식(수정)"
    assert r.json()["newsletter"]["body_html"] == "<p>안녕하세요</p>"  # 준 키만 바뀐다
    items = client.get("/admin/newsletters", headers=_hdr(boss)).json()["items"]
    assert [i["id"] for i in items] == [nid]

    pv = client.post("/admin/newsletters/preview", headers=_hdr(boss),
                     json={"subject": "s", "body_text": "## 소제목\n- 항목", "marketing": True}).json()
    assert pv["subject"].startswith("(광고)") and "소제목" in pv["html"]

    # 서비스 안내(비광고): 수신거부자만 비활성
    rec = client.get("/admin/newsletters/recipients", headers=_hdr(boss)).json()["recipients"]
    by = {r["email"]: r for r in rec}
    assert by["out@example.com"]["eligible"] is False
    assert by["out@example.com"]["reason"] == "notice_optout"
    assert by["fail@example.com"]["eligible"] is True
    # 광고성: 마케팅 미동의도 비활성
    rec = client.get("/admin/newsletters/recipients?marketing=true",
                     headers=_hdr(boss)).json()["recipients"]
    by = {r["email"]: r for r in rec}
    assert by["ok@example.com"]["eligible"] is True
    assert by["fail@example.com"]["reason"] == "no_marketing_consent"


def test_send_filters_ineligible_and_records_history(monkeypatch):
    calls = _capture_send(monkeypatch)
    client = _client()
    boss = _seed(client)
    nid = client.post("/admin/newsletters", headers=_hdr(boss), json={
        "subject": "소식", "body_html": "<p>본문</p>"}).json()["newsletter"]["id"]

    r = client.post(f"/admin/newsletters/{nid}/send", headers=_hdr(boss), json={
        "emails": ["ok@example.com", "out@example.com", "fail@example.com", "nobody@x.com"]})
    assert r.status_code == 200, r.text
    run = r.json()["run"]
    # 수신거부자·목록 밖 주소는 발송하지 않고 사유를 남긴다
    assert sorted(c["to"] for c in calls) == ["fail@example.com", "ok@example.com"]
    assert {s["email"]: s["reason"] for s in run["skipped"]} == {
        "out@example.com": "notice_optout", "nobody@x.com": "unknown"}
    assert {x["email"]: x["ok"] for x in run["recipients"]} == {
        "ok@example.com": True, "fail@example.com": False}
    assert calls[0]["body_html"] == "<p>본문</p>" and "본문" in calls[0]["body_text"]

    detail = client.get(f"/admin/newsletters/{nid}", headers=_hdr(boss)).json()
    assert len(detail["sends"]) == 1 and detail["sent_count"] == 1
    rec = client.get(f"/admin/newsletters/recipients?newsletter_id={nid}",
                     headers=_hdr(boss)).json()["recipients"]
    got = {r["email"]: r["received_at"] for r in rec}
    assert got["ok@example.com"] and got["fail@example.com"] is None
    # 발송 이력이 있으면 삭제 불가
    assert client.delete(f"/admin/newsletters/{nid}", headers=_hdr(boss)).status_code == 409


def test_marketing_send_blocks_nonconsented_and_prefixes_subject(monkeypatch):
    calls = _capture_send(monkeypatch)
    client = _client()
    boss = _seed(client)
    nid = client.post("/admin/newsletters", headers=_hdr(boss), json={
        "subject": "행사 안내", "body_text": "본문", "marketing": True}).json()["newsletter"]["id"]
    r = client.post(f"/admin/newsletters/{nid}/send", headers=_hdr(boss),
                    json={"emails": ["fail@example.com"]})
    assert r.status_code == 422 and not calls
    r = client.post(f"/admin/newsletters/{nid}/send", headers=_hdr(boss),
                    json={"emails": ["ok@example.com"]})
    assert r.status_code == 200
    assert calls[0]["subject"] == "(광고) 행사 안내"


def test_test_send_goes_only_to_requester(monkeypatch):
    calls = _capture_send(monkeypatch)
    client = _client()
    boss = _seed(client)
    nid = client.post("/admin/newsletters", headers=_hdr(boss), json={
        "subject": "소식", "body_text": "본문"}).json()["newsletter"]["id"]
    r = client.post(f"/admin/newsletters/{nid}/send", headers=_hdr(boss), json={"test": True})
    assert r.status_code == 200 and r.json()["run"]["test"] is True
    assert [c["to"] for c in calls] == ["boss@example.com"]
    assert calls[0]["subject"].startswith("[테스트]")
    detail = client.get(f"/admin/newsletters/{nid}", headers=_hdr(boss)).json()
    assert detail["sent_count"] == 0  # 테스트는 수신 기록에 안 잡힌다
    # 테스트만 보낸 뉴스레터는 삭제 가능
    assert client.delete(f"/admin/newsletters/{nid}", headers=_hdr(boss)).status_code == 200


def test_newsletters_require_mail_perm():
    client = _client()
    boss = _seed(client)
    helper = _tok(sub="a-help", email="helper@example.com")
    _register(client, helper)
    client.patch("/admin/users/a-help", json={"is_admin": True, "admin_perms": ["announcements"]},
                 headers=_hdr(boss))
    assert client.get("/admin/newsletters", headers=_hdr(helper)).status_code == 403
    client.patch("/admin/users/a-help", json={"admin_perms": ["mail"]}, headers=_hdr(boss))
    assert client.get("/admin/newsletters", headers=_hdr(helper)).status_code == 200


def test_recipients_exclude_test_accounts():
    """테스트 계정(오픈 전 가입·초대 기록 없음 등)은 수신 후보에 안 나온다."""
    client = _client()
    boss = _seed(client)
    from src.persistence import get_users_repo
    get_users_repo().set_account_class("u-ok", "test")
    from src import account_class
    account_class.invalidate()
    rec = client.get("/admin/newsletters/recipients", headers=_hdr(boss)).json()["recipients"]
    assert "ok@example.com" not in {r["email"] for r in rec}
