"""요구사항 ④ — /law-graph 서브그래프 엔드포인트 검증.

Neo4j 라이브 의존 없이 라우트 검증 경로(인증·파라미터·rel 화이트리스트·503)를
확인한다. 실 그래프 빌더(fetch_law_subgraph)는 monkeypatch.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest

SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    yield


def _token(sub="u-1", email="alice@example.com"):
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


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


def test_missing_keys_param_422():
    # keys 쿼리 자체가 없으면 FastAPI 필수 검증 422
    res = _client().get("/law-graph", headers=_auth())
    assert res.status_code == 422


def test_empty_keys_422():
    res = _client().get("/law-graph?keys=%20,%20", headers=_auth())
    assert res.status_code == 422
    assert "keys" in res.json()["detail"]


def test_too_many_seeds_422():
    keys = ",".join(f"k{i}" for i in range(21))
    res = _client().get(f"/law-graph?keys={keys}", headers=_auth())
    assert res.status_code == 422
    assert "최대" in res.json()["detail"]


def test_disallowed_rel_type_422():
    res = _client().get(
        "/law-graph?keys=006364_000100&rels=CITES,DROP_TABLE", headers=_auth()
    )
    assert res.status_code == 422
    assert "DROP_TABLE" in str(res.json()["detail"])


def test_happy_path_passthrough(monkeypatch):
    fake = {
        "seeds": ["006364_000100"],
        "nodes": [{"id": "006364_000100", "label": "공증인 수수료 규칙 제1조",
                   "is_seed": True}],
        "edges": [],
        "node_count": 1, "edge_count": 0, "truncated": False,
    }
    monkeypatch.setattr("src.routes.law_graph.fetch_law_subgraph",
                        lambda *a, **k: fake)
    res = _client().get("/law-graph?keys=006364_000100&depth=2", headers=_auth())
    assert res.status_code == 200
    assert res.json() == fake


def test_neo4j_inactive_503(monkeypatch):
    monkeypatch.setattr("src.routes.law_graph.fetch_law_subgraph",
                        lambda *a, **k: None)
    res = _client().get("/law-graph?keys=006364_000100", headers=_auth())
    assert res.status_code == 503


def test_depth_out_of_range_422():
    res = _client().get("/law-graph?keys=k1&depth=5", headers=_auth())
    assert res.status_code == 422
