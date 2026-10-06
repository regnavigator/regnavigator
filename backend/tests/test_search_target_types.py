"""검색 종별 — 서버 서빙 목록 조회·캐시·폴백·env 우선 (2026-10-06)."""

from __future__ import annotations

import pytest

import src.retrieval.search_api_client as C


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("RAG_SEARCH_API_URL", "http://search.test")
    monkeypatch.setenv("RAG_SEARCH_API_KEY", "k")
    monkeypatch.delenv("RAG_SEARCH_TARGET_TYPES", raising=False)
    C._TT_CACHE.update(at=0.0, value=None)
    yield
    C._TT_CACHE.update(at=0.0, value=None)


def _stub_client(get):
    """conftest 가 teardown 에서 `_client.cache_clear()` 를 부른다 — lru_cache 모양을 맞춘다."""
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _c():
        return type("X", (), {"get": get})()
    return _c


class _Resp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


def _health(guide=True, attach=False, addendum=False, law_points=3994514):
    return {"qdrant_points": law_points, "bm25_loaded": True, "reranker_loaded": True,
            "guide": {"qdrant_points": 153466 if guide else 0, "reranker_loaded": guide},
            "admrul_attach": {"qdrant_points": 60600, "reranker_loaded": attach},
            "addendum": {"qdrant_points": 108844, "reranker_loaded": addendum}}


def test_probe_reads_live_engines(monkeypatch):
    monkeypatch.setattr(C, "_client", _stub_client(lambda self, *a, **k: _Resp(_health())))
    assert C.available_target_types(refresh=True) == ["law", "admrul", "ordin", "prec", "expc", "guide"]
    # 기본 검색엔 DocChunk 엔진을 넣지 않는다
    assert C._default_target_types() == ["law", "admrul", "ordin", "prec", "expc"]


def test_probe_includes_attach_when_reranker_loaded(monkeypatch):
    monkeypatch.setattr(C, "_client", _stub_client(lambda self, *a, **k: _Resp(_health(attach=True, addendum=True))))
    assert C.available_target_types(refresh=True)[-3:] == ["guide", "admrul_attach", "addendum"]


def test_fallback_to_code_default_when_server_down(monkeypatch):
    import httpx

    def boom(*a, **k): raise httpx.ConnectError("down")
    monkeypatch.setattr(C, "_client", _stub_client(boom))
    assert C.available_target_types(refresh=True) == C._DEFAULT_TARGET_TYPES
    assert C._default_target_types() == C._DEFAULT_TARGET_TYPES


def test_cache_and_stale_value_on_later_failure(monkeypatch):
    calls = []
    def ok(self, *a, **k): calls.append(1); return _Resp(_health())
    monkeypatch.setattr(C, "_client", _stub_client(ok))
    C.available_target_types(refresh=True); C.available_target_types(); C.available_target_types()
    assert len(calls) == 1  # 10분 캐시
    import httpx
    monkeypatch.setattr(C, "_client", _stub_client(lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down"))))
    assert "guide" in C.available_target_types(refresh=True)  # 실패 시 마지막 성공값 유지


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("RAG_SEARCH_TARGET_TYPES", "law, prec")
    monkeypatch.setattr(C, "_client", _stub_client(lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not probe"))))
    assert C.available_target_types(refresh=True) == ["law", "prec"]
    assert C._default_target_types() == ["law", "prec"]


def test_amendment_status_maps_and_swallows_errors(monkeypatch):
    monkeypatch.setattr(C, "_post", lambda path, payload: {"status": {"001": "current", "002": "pending"}})
    assert C.amendment_status(["001", "002", "001", ""]) == {"001": "current", "002": "pending"}
    monkeypatch.setattr(C, "_post", lambda *a: (_ for _ in ()).throw(C.SearchApiError("x")))
    assert C.amendment_status(["001"]) == {}
    assert C.amendment_status([]) == {}
