"""검색 캐시 — TTLCache + search_api_client.search_articles 캐싱."""
from __future__ import annotations


# ── TTLCache ─────────────────────────────────────────────────────
def test_ttlcache_lru_evicts():
    from src.retrieval.cache import _MISS, TTLCache
    c = TTLCache(maxsize=2, ttl_s=0)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # a 가 밀려남(LRU)
    assert c.get("a") is _MISS
    assert c.get("b") == 2 and c.get("c") == 3


def test_ttlcache_lru_touch_keeps_recent():
    from src.retrieval.cache import _MISS, TTLCache
    c = TTLCache(maxsize=2, ttl_s=0)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1     # a 최근 사용
    c.set("c", 3)              # → b 가 밀려남
    assert c.get("b") is _MISS
    assert c.get("a") == 1 and c.get("c") == 3


def test_ttlcache_ttl_expiry(monkeypatch):
    import src.retrieval.cache as cache
    clock = [1000.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock[0])
    c = cache.TTLCache(maxsize=10, ttl_s=5)
    c.set("a", 1)
    assert c.get("a") == 1
    clock[0] += 6
    assert c.get("a") is cache._MISS  # 만료


def test_ttlcache_stats():
    from src.retrieval.cache import TTLCache
    c = TTLCache(maxsize=2)
    c.set("a", 1)
    c.get("a")    # hit
    c.get("z")    # miss
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1 and s["hit_rate"] == 0.5


# ── search_articles 캐싱 ─────────────────────────────────────────
def _stub_api(monkeypatch, hits, calls):
    """search_api_client._post 를 스텁 — 호출 기록 + 고정 응답."""
    import src.retrieval.search_api_client as sc
    monkeypatch.setenv("RAG_SEARCH_API_URL", "http://x")
    monkeypatch.setenv("RAG_SEARCH_API_KEY", "k")
    monkeypatch.setattr(sc, "_post",
                        lambda path, body: (calls.append((body["query"], body["top_k"])), hits)[1])
    sc._search_cache.clear()
    return sc


def test_search_articles_caches_by_args(monkeypatch):
    calls = []
    sc = _stub_api(monkeypatch, [{"article_key": "a"}], calls)
    r1 = sc.search_articles("질의", top_k=8)
    r2 = sc.search_articles("질의", top_k=8)
    assert r1 == r2 == [{"article_key": "a"}]
    assert len(calls) == 1            # 두 번째는 캐시 hit
    sc.search_articles("질의", top_k=5)  # 다른 top_k → miss
    assert len(calls) == 2


def test_search_articles_empty_not_cached(monkeypatch):
    calls = []
    sc = _stub_api(monkeypatch, [], calls)
    sc.search_articles("q", top_k=8)
    sc.search_articles("q", top_k=8)
    assert len(calls) == 2            # 빈 결과는 캐시 안 함(재시도 허용)


# ── 항목 무결성 가드(2026-07-25) — 200 OK + 불량 내용물이 하류로 새지 않게 ──
def test_search_articles_drops_malformed_items_and_skips_cache(monkeypatch):
    """비 dict·article_key 없는 항목은 경계에서 폐기 + 그 응답은 캐시 금지.

    실측(2026-07-25): 검색 서버가 흔들리는 순간 200 + 비정상 내용물을 반환.
    불량이 섞인 결과가 1시간 캐시되면 오염이 반복된다."""
    calls = []
    mixed = [{"article_key": "a", "law_title": "의료기기법"},
             "garbage-string", None, {"law_title": "article_key 없음"}]
    sc = _stub_api(monkeypatch, mixed, calls)
    r1 = sc.search_articles("q", top_k=8)
    assert r1 == [{"article_key": "a", "law_title": "의료기기법"}]  # 정상분만
    sc.search_articles("q", top_k=8)
    assert len(calls) == 2            # 불량 섞인 응답은 캐시 안 됨 → 재호출


def test_search_articles_all_malformed_raises(monkeypatch):
    """전건 불량 = 조용한 빈손이 아니라 명시 실패 — 재시도·충분성 게이트가
    정상 발화하도록."""
    import pytest
    calls = []
    sc = _stub_api(monkeypatch, ["오류문자열", {"no": "key"}], calls)
    with pytest.raises(sc.SearchApiError):
        sc.search_articles("q", top_k=8)


def test_search_articles_non_list_raises_with_payload(monkeypatch):
    """200 + 비-list(에러 객체 추정) → SearchApiError, payload 가 메시지에 남아
    ETL 전달 증거가 된다."""
    import pytest
    calls = []
    sc = _stub_api(monkeypatch, {"detail": "internal error"}, calls)
    with pytest.raises(sc.SearchApiError, match="internal error"):
        sc.search_articles("q", top_k=8)


def test_search_articles_normalized_cache_hit(monkeypatch):
    """공백·대소문자 변형은 같은 캐시 키 → 검색 스킵(의미 보존은 조사/어순 유지)."""
    calls = []
    sc = _stub_api(monkeypatch, [{"article_key": "a"}], calls)
    sc.search_articles("의료기기 광고", top_k=8)
    sc.search_articles("  의료기기   광고 ", top_k=8)  # 공백 변형 → 히트
    sc.search_articles("의료기기 광고", top_k=8)
    assert len(calls) == 1            # 변형 전부 캐시 hit


def test_normalize_query():
    from src.retrieval.search_api_client import _normalize_query
    assert _normalize_query("  의료기기   광고 ") == "의료기기 광고"
    assert _normalize_query("ABC  d") == "abc d"


# ── fetch_bodies 청크 분할 (2026-08-02 회귀) ──────────────────────
def test_fetch_bodies_chunks_over_server_cap(monkeypatch):
    """서버 상한(20)을 넘는 키는 청크로 쪼개 보낸다.

    전량을 한 번에 보내던 구현은 422 로 **전건 실패**해 조용히 {} 를 돌려줬고,
    보고서는 조문 원문 없이, grounding 은 대조본 없이 돌았다.
    """
    import src.retrieval.search_api_client as C

    seen: list[list[str]] = []

    def fake_post(path, payload):
        keys = payload["article_keys"]
        seen.append(keys)
        assert len(keys) <= C._BODIES_MAX_KEYS, "상한 초과 요청 = 서버 422"
        return {k: {"full_text": f"본문 {k}"} for k in keys}

    monkeypatch.setattr(C, "_post", fake_post)
    keys = [f"k{i}" for i in range(47)]
    out = C.fetch_bodies(keys)

    assert [len(c) for c in seen] == [20, 20, 7]
    assert len(out) == 47
    assert out["k46"]["full_text"] == "본문 k46"


def test_fetch_bodies_partial_chunk_failure_keeps_rest(monkeypatch):
    """한 청크가 실패해도 나머지 청크 결과는 살린다."""
    import src.retrieval.search_api_client as C

    calls = {"n": 0}

    def fake_post(path, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise C.SearchApiError("검색 API 500")
        return {k: {"full_text": "ok"} for k in payload["article_keys"]}

    monkeypatch.setattr(C, "_post", fake_post)
    out = C.fetch_bodies([f"k{i}" for i in range(30)])
    assert len(out) == 10          # 두 번째 청크만 성공
    assert "k0" not in out and "k25" in out
