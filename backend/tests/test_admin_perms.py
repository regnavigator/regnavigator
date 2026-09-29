"""관리자 기능별 권한(2026-09-22) — 루트/권한 관리자 구분 + 라우트 매핑 누락 방지."""
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


def _admin_routes():
    from src.api import app

    out = []
    for r in app.routes:
        for rr in getattr(getattr(r, "original_router", None), "routes", []) or [r]:
            p = getattr(rr, "path", "")
            if p.startswith("/admin"):
                for m in sorted(getattr(rr, "methods", []) or []):
                    out.append((m, p))
    return out


def test_every_admin_route_has_a_perm_mapping():
    """새 /admin 라우트가 매핑 없이 추가되면 루트 전용으로 막힌다(fail-closed) —
    의도한 것인지 여기서 드러나게 한다. 루트 전용 의도라면 _ROUTE_RULES 에 ROOT 로 적을 것."""
    from src import admin_perms as P

    routes = _admin_routes()
    assert len(routes) > 40
    unmapped = [(m, p) for m, p in routes
                if P.perm_for_route(m, p) == P.ROOT
                and not any(p == pre or p.startswith(pre + "/")
                            for _, pre, perm in P._ROUTE_RULES if perm == P.ROOT)]
    assert unmapped == []


def test_perm_mapping_samples():
    from src import admin_perms as P

    assert P.perm_for_route("POST", "/admin/notify") == "mail"
    assert P.perm_for_route("POST", "/admin/announcements") == "announcements"
    assert P.perm_for_route("GET", "/admin/users/{user_id}/notices") == "mail"
    assert P.perm_for_route("PATCH", "/admin/users/{user_id}") == "users"
    assert P.perm_for_route("GET", "/admin/weekly-report/preview") == "stats"
    assert P.perm_for_route("POST", "/admin/weekly-report/send") == "mail"
    assert P.perm_for_route("GET", "/admin/unknown-new-thing") == P.ROOT


def _setup_admins(client):
    boss = _tok(sub="a-root", email="boss@example.com")
    helper = _tok(sub="a-help", email="helper@example.com")
    _register(client, boss)
    _register(client, helper)
    return boss, helper


def test_new_admin_starts_without_perms_and_root_grants(monkeypatch):
    client = _client()
    boss, helper = _setup_admins(client)
    # 관리자 지정(루트) → 권한 없음에서 시작
    r = client.patch("/admin/users/a-help", json={"is_admin": True}, headers=_hdr(boss))
    assert r.status_code == 200, r.text
    assert r.json()["admin_perms_list"] == []
    me = client.get("/admin/me", headers=_hdr(helper)).json()
    assert me["is_root"] is False and me["perms"] == []
    assert client.post("/admin/announcements", json={"title": "t", "items": ["a"]},
                       headers=_hdr(helper)).status_code == 403
    # 업데이트 등록만 켜기
    r = client.patch("/admin/users/a-help", json={"admin_perms": ["announcements"]},
                     headers=_hdr(boss))
    assert r.status_code == 200 and r.json()["admin_perms_list"] == ["announcements"]
    assert client.post("/admin/announcements", json={"title": "t", "items": ["a"], "popup": False},
                       headers=_hdr(helper)).status_code == 201
    # 메일 발신은 여전히 막힘
    res = client.post("/admin/notify", json={"subject": "s", "body": "b", "dry_run": True},
                      headers=_hdr(helper))
    assert res.status_code == 403 and "메일 발신" in res.json()["detail"]
    # 루트는 전부
    assert client.post("/admin/notify", json={"subject": "s", "body": "b", "dry_run": True},
                       headers=_hdr(boss)).status_code == 200


def test_only_root_can_change_admin_or_perms():
    client = _client()
    boss, helper = _setup_admins(client)
    client.patch("/admin/users/a-help", json={"is_admin": True, "admin_perms": ["users"]},
                 headers=_hdr(boss))
    # users 권한이 있어도 권한 확장·관리자 지정은 불가
    r = client.patch("/admin/users/a-help", json={"admin_perms": ["users", "mail"]},
                     headers=_hdr(helper))
    assert r.status_code == 403
    # 일반 편집(메모)은 users 권한으로 가능
    r = client.patch("/admin/users/a-help", json={"admin_memo": "도우미"}, headers=_hdr(helper))
    assert r.status_code == 200
    # 모르는 키 거부
    r = client.patch("/admin/users/a-help", json={"admin_perms": ["nope"]}, headers=_hdr(boss))
    assert r.status_code == 422


def test_legacy_admin_without_perms_keeps_all():
    """도입 전부터 관리자였던 계정(admin_perms NULL)은 전 권한 유지."""
    from src.persistence import get_users_repo

    client = _client()
    boss, helper = _setup_admins(client)
    get_users_repo().set_admin("a-help", True)  # 권한 칸은 NULL 그대로
    me = client.get("/admin/me", headers=_hdr(helper)).json()
    from src.admin_perms import PERM_KEYS
    assert me["perms"] == list(PERM_KEYS)


def test_ops_manual_open_to_every_admin():
    """운영 매뉴얼은 기능 권한 없이도 모든 관리자가 본다(2026-09-23) — 비관리자는 403."""
    client = _client()
    boss, helper = _setup_admins(client)
    assert client.get("/admin/ops-manual", headers=_hdr(helper)).status_code == 403
    client.patch("/admin/users/a-help", json={"is_admin": True}, headers=_hdr(boss))  # 권한 0개
    r = client.get("/admin/ops-manual", headers=_hdr(helper))
    assert r.status_code == 200, r.text
    assert r.json()["markdown"].startswith("# MEDIREG AI 운영진 기능 설명서")


def test_ops_manual_ships_in_image():
    """이미지에 매뉴얼이 들어가야 한다 — docs/* 가 .dockerignore 로 통째 빠진다(.dockerignore 함정)."""
    from pathlib import Path
    assert "!docs/product/ops_feature_manual.md" in Path(".dockerignore").read_text(encoding="utf-8")
    assert "COPY docs/product/ops_feature_manual.md" in Path("Dockerfile").read_text(encoding="utf-8")
