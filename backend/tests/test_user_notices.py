"""사용자별 앱 내 알림(2026-09-15) — 전체 공지 오발송 사고 후 도입."""
import pytest


@pytest.fixture
def settings(tmp_path, monkeypatch):
    from src.persistence import settings_repo as sr
    from src.persistence.settings_repo import SqliteSettingsRepo

    repo = SqliteSettingsRepo(str(tmp_path / "s.db"))
    monkeypatch.setattr(sr, "get_settings_repo", lambda: repo)
    return repo


def test_send_pending_seen_flow(settings):
    from src import user_notices as un

    sent = un.send(["u1", "u2", "u1"], title="피드백 반영", items=["a", " ", "b"], created_by="admin")
    assert len(sent) == 2 and {n["user_id"] for n in sent} == {"u1", "u2"}
    assert sent[0]["items"] == ["a", "b"]
    p = un.pending("u1")
    assert p and p["title"] == "피드백 반영" and p["seen_at"] is None
    assert un.pending("u3") is None
    assert un.mark_seen("u1", p["id"]) is True
    assert un.pending("u1") is None
    assert un.mark_seen("u1", p["id"]) is False  # 이미 읽음
    assert un.list_for_user("u1")[0]["seen_at"]


def test_pending_returns_oldest_unseen_first(settings):
    from src import user_notices as un

    a = un.send(["u"], title="첫째", items=["1"], created_by=None)[0]
    b = un.send(["u"], title="둘째", items=["2"], created_by=None)[0]
    assert un.pending("u")["id"] == a["id"]
    un.mark_seen("u", a["id"])
    assert un.pending("u")["id"] == b["id"]


def test_validation(settings):
    from src import user_notices as un

    with pytest.raises(ValueError):
        un.send(["u"], title="", items=["x"], created_by=None)
    with pytest.raises(ValueError):
        un.send(["u"], title="t", items=[], created_by=None)


def test_routes(settings, monkeypatch):
    import asyncio

    from fastapi import HTTPException

    from src.routes import notices as r

    class _State:
        def __init__(self, uid=None, email=None):
            self.user_id = uid; self.user_email = email

    class _Req:
        def __init__(self, uid=None, email=None, body=None):
            self.state = _State(uid, email); self._body = body
        async def json(self):
            return self._body

    with pytest.raises(HTTPException) as ei:
        r.get_my_pending_notice(_Req())
    assert ei.value.status_code == 401
    out = asyncio.run(r.admin_send_notices(
        _Req("adm", "admin@x", {"user_ids": ["u9"], "title": "t", "items": ["i"]}), _admin=None))
    assert out["count"] == 1
    nid = out["notices"][0]["id"]
    assert r.get_my_pending_notice(_Req("u9"))["notice"]["id"] == nid
    assert r.get_my_pending_notice(_Req("other"))["notice"] is None
    assert r.mark_my_notice_seen(nid, _Req("u9"))["ok"] is True
    assert r.get_my_pending_notice(_Req("u9"))["notice"] is None
    assert r.admin_list_user_notices("u9", _admin=None)["count"] == 1
    with pytest.raises(HTTPException):
        asyncio.run(r.admin_send_notices(_Req("adm", None, {"title": "t", "items": ["i"]}), _admin=None))


def test_me_notices_is_not_public():
    from src.middleware.auth import PUBLIC_PATH_PREFIXES

    assert not any("/me" == p or p.startswith("/me/") for p in PUBLIC_PATH_PREFIXES)
    assert not any(p.startswith("/admin") for p in PUBLIC_PATH_PREFIXES)
