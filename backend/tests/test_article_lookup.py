"""Tier-0 — 자연어 조문 지정 즉답 (/article/lookup) + 파서."""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from src.text.article_query import parse_article_query

SECRET = "test-secret-32-bytes-min-padding-for-hs256"


# ── 파서 (순수) ──────────────────────────────────────────────────
def test_parse_basic():
    assert parse_article_query("의료기기법 제25조 인용해줘") == ("의료기기법", "제25조")


def test_parse_with_spaces_and_gaji():
    assert parse_article_query("의료기기법 시행규칙 제3조의2 알려줘") == (
        "의료기기법 시행규칙", "제3조의2")
    assert parse_article_query("약사법 제 1 조") == ("약사법", "제1조")


def test_parse_no_law_name_returns_none():
    assert parse_article_query("제6조 보여줘") is None


def test_parse_no_article_returns_none():
    assert parse_article_query("의료기기 인증 절차 알려줘") is None
    assert parse_article_query("") is None


# ── 라우트 ───────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    yield


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _auth():
    now = int(time.time())
    tok = pyjwt.encode({"sub": "u-1", "email": "a@b.com", "email_verified": True,
                        "iat": now, "exp": now + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def test_lookup_unparseable_404():
    res = _client().get("/article/lookup?q=안녕하세요", headers=_auth())
    assert res.status_code == 404
    assert "식별" in res.json()["detail"]["message"]


def test_lookup_not_found_404(monkeypatch):
    monkeypatch.setattr("src.retrieval.pg_client.resolve_article_by_name",
                        lambda law, art, **kw: None)
    res = _client().get("/article/lookup?q=없는법 제99조", headers=_auth())
    assert res.status_code == 404
    assert "찾지 못" in res.json()["detail"]["message"]


def test_lookup_success_reuses_get_article(monkeypatch):
    monkeypatch.setattr("src.retrieval.pg_client.resolve_article_by_name",
                        lambda law, art, **kw: {"article_key": "009514_0025001",
                                                "target_type": "law", "law_title": law})

    # get_article·lookup_article 은 둘 다 동기 def — FastAPI 가 스레드풀에서
    # 돌린다(2026-08-04 C-3: DB 만 만지는 라우트는 이벤트 루프를 잡지 않는다).
    def _fake_get_article(key):
        return {"article_key": key, "full_text": "제25조 본문", "law_title": "의료기기법"}

    monkeypatch.setattr("src.routes.articles.get_article", _fake_get_article)
    res = _client().get("/article/lookup?q=의료기기법 제25조 인용해줘", headers=_auth())
    assert res.status_code == 200
    assert res.json()["article_key"] == "009514_0025001"
