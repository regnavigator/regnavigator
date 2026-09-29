"""S3 회귀 — NextAuth JWT 검증 + user upsert + ADMIN_EMAILS + dev bypass.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest


SECRET = "test-secret-medi-back"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "medi.db"))
    monkeypatch.delenv("AUTH_DEV_BYPASS_USER", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    from src import persistence as P
    for f in (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo):
        f.cache_clear()
    yield
    for f in (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo):
        f.cache_clear()


def _make_token(*, sub="u-1", email="alice@example.com",
                email_verified=True, expires_in=3600,
                secret=SECRET) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "iat": now,
        "exp": now + expires_in,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _client(monkeypatch=None, **env):
    if monkeypatch is not None:
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
    # FastAPI app은 모듈 import 시 미들웨어 잡히므로 reload 불필요 — env는 요청 시점에 읽음
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


# 인증 동작만 보는 프로브 라우트 — 데이터·소유권에 의존하지 않는 것으로 고른다.
# (구: /threads/_p/reports. 보고서 라우트에 소유권 검사가 생기면서 남의/없는
#  thread 는 404 가 되어 인증 테스트가 엉뚱하게 깨졌다 — 2026-08-04)
_PROBE = "/chat/threads"


# ---------------------------------------------------------------------------
# dev 모드 — NEXTAUTH_SECRET 없음
# ---------------------------------------------------------------------------
def test_dev_mode_passes_without_header(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=None)
    res = client.get(_PROBE)
    assert res.status_code == 200  # auth bypass


def test_dev_mode_with_bypass_user_creates_user(monkeypatch):
    client = _client(monkeypatch,
                     NEXTAUTH_SECRET=None,
                     AUTH_DEV_BYPASS_USER="dev@example.com")
    # 한 번 호출해 user upsert 트리거
    res = client.get(_PROBE)
    assert res.status_code == 200

    from src.persistence import get_users_repo
    u = get_users_repo().get_by_email("dev@example.com")
    assert u is not None
    assert u.id == "dev-bypass-user"


# ---------------------------------------------------------------------------
# 운영 모드 — NEXTAUTH_SECRET 설정
# ---------------------------------------------------------------------------
def test_no_header_returns_401(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET)
    res = client.get(_PROBE)
    assert res.status_code == 401
    assert "Authorization" in res.json()["detail"]


def test_invalid_jwt_returns_401(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET)
    res = client.get(
        _PROBE,
        headers={"Authorization": "Bearer notajwt"},
    )
    assert res.status_code == 401


def test_wrong_secret_returns_401(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET)
    bad = _make_token(secret="wrong-secret")
    res = client.get(
        _PROBE,
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert res.status_code == 401


def test_expired_jwt_returns_401(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET)
    expired = _make_token(expires_in=-10)
    res = client.get(
        _PROBE,
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert res.status_code == 401


def test_missing_email_claim_returns_401(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET)
    tok = _make_token(email="")
    res = client.get(
        _PROBE,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 401


def test_valid_jwt_upserts_user(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET)
    tok = _make_token(sub="user-42", email="bob@example.com")
    res = client.get(
        _PROBE,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200

    from src.persistence import get_users_repo
    u = get_users_repo().get("user-42")
    assert u is not None
    assert u.email == "bob@example.com"
    assert u.email_verified_at is not None
    assert u.is_admin is False


def test_admin_emails_bootstrap(monkeypatch):
    client = _client(
        monkeypatch,
        NEXTAUTH_SECRET=SECRET,
        ADMIN_EMAILS="boss@example.com, other@example.com",
    )
    tok = _make_token(sub="user-99", email="BOSS@example.com")  # 대소문자 무관
    res = client.get(
        _PROBE,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200

    from src.persistence import get_users_repo
    u = get_users_repo().get("user-99")
    assert u.is_admin is True


def test_public_paths_bypass_auth_even_with_secret(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET)
    assert client.get("/healthz").status_code == 200
    assert client.get("/suggestions").status_code == 200
    # docs 페이지도 무인증
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_email_verified_false_still_upserts_but_no_verified_at(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET)
    tok = _make_token(sub="u-unv", email="unv@example.com", email_verified=False)
    res = client.get(
        _PROBE,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200

    from src.persistence import get_users_repo
    u = get_users_repo().get("u-unv")
    assert u.email_verified_at is None


# ---------------------------------------------------------------------------
# 클로즈 베타 화이트리스트 (BETA_WHITELIST_EMAILS)
# ---------------------------------------------------------------------------
def test_beta_whitelist_blocks_unlisted_email(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET,
                     BETA_WHITELIST_EMAILS="vip@example.com, @partner.co.kr")
    tok = _make_token(sub="u-x", email="stranger@example.com")
    res = client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 403
    assert "클로즈 베타" in res.json()["detail"]
    # 차단 사용자는 users 행도 안 생김 (upsert 전 차단)
    from src.persistence import get_users_repo
    assert get_users_repo().get("u-x") is None


def test_beta_whitelist_allows_listed_email_and_domain(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET,
                     BETA_WHITELIST_EMAILS="vip@example.com, @partner.co.kr")
    for sub, email in (("u-vip", "vip@example.com"),
                       ("u-dom", "anyone@partner.co.kr")):
        tok = _make_token(sub=sub, email=email)
        res = client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})
        assert res.status_code == 200, email


def test_beta_whitelist_admin_always_allowed(monkeypatch):
    """운영자 잠금 방지 — ADMIN_EMAILS 는 리스트에 없어도 허용."""
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET,
                     ADMIN_EMAILS="boss@example.com",
                     BETA_WHITELIST_EMAILS="vip@example.com")
    tok = _make_token(sub="u-adm", email="boss@example.com")
    res = client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200


def test_beta_whitelist_unset_allows_everyone(monkeypatch):
    client = _client(monkeypatch, NEXTAUTH_SECRET=SECRET,
                     BETA_WHITELIST_EMAILS=None)
    tok = _make_token(sub="u-open", email="open@example.com")
    res = client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200

# test_beta_whitelist_langgraph_auth_layer 삭제 — langgraph auth 레이어(src/auth.py)
# ADR-0001 Phase 5 은퇴. 화이트리스트 게이트는 AuthMiddleware(위 테스트들)만.


# ── 화이트리스트 정책 단일화 (2026-09-10) ────────────────────────────
# 종전엔 같은 판정이 세 곳(middleware/auth · routes/admin · notices)에 있었고,
# 서비스가 라우트를 import 하는 순환(notices → routes.admin → notices)까지 있었다.
# `src/whitelist.py` 로 올렸다 — 아래는 그게 되돌아가지 않게 하는 잠금.
def test_auth_delegates_to_whitelist_policy(monkeypatch):
    """auth 가 규칙을 다시 구현하면 조용히 어긋난다 — 위임인지 확인."""
    from src import whitelist as W
    from src.middleware import auth

    monkeypatch.setattr(W, "allowed", lambda e: e == "sentinel@x.com")
    assert auth._beta_allowed("sentinel@x.com") is True
    assert auth._beta_allowed("other@x.com") is False


def test_admin_classifier_delegates_to_policy():
    """routes/admin 의 분류기도 같은 정책이어야 한다(출처까지 동일)."""
    from src.routes.admin import _whitelist_classifier
    from src.whitelist import classifier

    assert _whitelist_classifier.__doc__  # 설명 유지
    a_active, a_classify = _whitelist_classifier()
    p_active, p_classify = classifier()
    assert a_active == p_active
    for e in ("admin@example.com", "nobody@example.com", ""):
        assert a_classify(e) == p_classify(e), e


def test_root_admin_never_locked_out(monkeypatch):
    """루트 관리자 누락은 곧 운영자 잠금 — 분리 과정에서 가장 위험했던 지점."""
    from src.whitelist import admin_emails

    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    assert "admin@example.com" in admin_emails()


def test_no_service_to_route_import_cycle():
    """notices 가 routes 를 import 하면 계층 역전이 재발한 것이다."""
    import pathlib
    src = pathlib.Path("src/notices.py").read_text(encoding="utf-8")
    assert "from src.routes" not in src and "src.routes.admin" not in src
