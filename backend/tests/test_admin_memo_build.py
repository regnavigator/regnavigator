"""관리자 식별 메모·프로필 기입 + 배포 식별(2026-09-15)."""
import asyncio
import json

import pytest


class _Req:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()
        self.state = type("S", (), {"user_id": "adm", "user_email": "admin@x"})()

    async def body(self):
        return self._body


@pytest.fixture
def users(tmp_path, monkeypatch):
    from src.persistence import users_repo as ur
    from src.persistence.users_repo import SqliteUsersRepo
    from src.routes import admin as admin_routes

    repo = SqliteUsersRepo(str(tmp_path / "u.db"))
    monkeypatch.setattr(admin_routes, "get_users_repo", lambda: repo)
    monkeypatch.setattr(ur, "get_users_repo", lambda: repo, raising=False)
    repo.upsert(id="u1", email="old@x.com")
    return repo


def test_admin_memo_and_profile_fill(users):
    from src.routes import admin as r

    out = asyncio.run(r.admin_update_user("u1", _Req({"admin_memo": "  OO대 내과 A교수 "}), _admin=None))
    assert users.get("u1").admin_memo == "OO대 내과 A교수"
    assert out.get("admin_memo") == "OO대 내과 A교수" if isinstance(out, dict) and "admin_memo" in out else True
    # 프로필은 준 키만 바꾸고 나머지는 보존
    asyncio.run(r.admin_update_user("u1", _Req({"affiliation": "화순전남대병원"}), _admin=None))
    asyncio.run(r.admin_update_user("u1", _Req({"job_role": "의사"}), _admin=None))
    u = users.get("u1")
    assert u.affiliation == "화순전남대병원" and u.job_role == "의사" and u.display_name is None
    # 메모 비우기
    asyncio.run(r.admin_update_user("u1", _Req({"admin_memo": ""}), _admin=None))
    assert users.get("u1").admin_memo is None


def test_admin_memo_not_in_user_facing_profile(users):
    """admin_memo 는 관리자 화면 전용 — /me/profile 응답에 없다."""
    from src.routes import privacy

    users.set_admin_memo("u1", "비밀 메모")
    req = type("R", (), {"state": type("S", (), {"user_id": "u1"})()})()
    import inspect
    src = inspect.getsource(privacy)
    assert "admin_memo" not in src
    out = privacy.get_my_profile(req)
    assert "admin_memo" not in out


def test_build_info_route(monkeypatch):
    from src.routes import admin as r

    monkeypatch.setenv("APP_GIT_SHA", "abc1234")
    monkeypatch.setenv("APP_BUILD_TIME", "2026-09-15T05:00:00Z")
    out = r.admin_build_info(_admin=None)
    assert out["git_sha"] == "abc1234" and out["built_at"] == "2026-09-15T05:00:00Z"
    assert out["started_at"] and out["prompt_version"].startswith("v")
    monkeypatch.delenv("APP_GIT_SHA"); monkeypatch.delenv("APP_BUILD_TIME")
    out = r.admin_build_info(_admin=None)
    assert out["git_sha"] == "unknown" and out["built_at"] is None
