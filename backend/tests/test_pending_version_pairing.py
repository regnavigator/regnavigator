"""현행 + 개정 예정본 동반(ETL RFC LAW_VERSION_CURRENT_VS_PENDING R3 소비).

ETL 이 `include_pending=true` 에서 현행 hit 바로 뒤에 같은 조문의 예정본을
붙여 준다(키 `_ef{YYYYMMDD}` 접미, `version_status`·`supersedes_article_key`).
medi-back 은 ① 요청에 플래그를 싣고 ② 예정본을 '개정 예정'으로 **현행과 구분해**
모델에 알리고 ③ citation 에 버전 축을 실어 FE 가 짝을 표시할 수 있게 한다.

핵심 구분: 단독 미시행 조문("아직 효력 없음")과 현행과 짝지어 온 개정본
("이렇게 바뀐다")은 사용자에게 의미가 다르다.
"""
from __future__ import annotations

from src.tools.citations import build_citation_from_api_hit
from src.tools.search import _effective_marker, _format_rag_hits


def _current(**kw) -> dict:
    base = {
        "article_key": "001788_0057001", "law_id": "001788",
        "law_title": "의료법", "article_num": "제57조",
        "article_title": "의료광고의 심의", "target_type": "law",
        "chunk_type": "article", "snippet": "현행 조문 본문",
        "is_current": True, "effective_status": "시행중", "enforced": True,
        "enforcement_date": "2026-04-07", "version_status": "current",
    }
    base.update(kw)
    return base


def _pending(**kw) -> dict:
    base = {
        "article_key": "001788_0057001_ef20270429", "law_id": "001788",
        "law_title": "의료법", "article_num": "제57조",
        "article_title": "의료광고의 심의", "target_type": "law",
        "chunk_type": "article", "snippet": "개정 후 조문 본문",
        "is_current": False, "effective_status": "미시행", "enforced": False,
        "enforcement_date": "2027-04-29", "version_status": "pending",
        "supersedes_article_key": "001788_0057001", "article_url": None,
    }
    base.update(kw)
    return base


# ── 요청 파라미터 ──────────────────────────────────────────────────────────

def test_include_pending_sent_by_default(monkeypatch):
    from src.retrieval import search_api_client as c

    sent: dict = {}
    monkeypatch.setattr(c, "_post", lambda path, body: sent.update(body) or [])
    monkeypatch.delenv("SEARCH_INCLUDE_PENDING", raising=False)
    c._search_cache.clear()
    c.search_articles("의료광고 심의")
    assert sent.get("include_pending") is True


def test_include_pending_can_be_disabled_by_env(monkeypatch):
    from src.retrieval import search_api_client as c

    sent: dict = {}
    monkeypatch.setattr(c, "_post", lambda path, body: sent.update(body) or [])
    monkeypatch.setenv("SEARCH_INCLUDE_PENDING", "0")
    c._search_cache.clear()
    c.search_articles("의료광고 심의")
    assert "include_pending" not in sent


def test_cache_key_separates_pending(monkeypatch):
    """같은 질의라도 동반 여부가 다르면 응답 집합이 다르다 — 캐시가 섞이면 안 된다."""
    from src.retrieval import search_api_client as c

    calls: list = []

    def _fake(path, body):
        calls.append(bool(body.get("include_pending")))
        return [{"article_key": "k1"}]

    monkeypatch.setattr(c, "_post", _fake)
    c._search_cache.clear()
    c.search_articles("동일 질의", include_pending=True)
    c.search_articles("동일 질의", include_pending=False)
    assert calls == [True, False]  # 두 번 다 서버로 나갔다(캐시 오염 없음)


# ── 모델 컨텍스트 마커 ────────────────────────────────────────────────────

def test_pending_pair_marker_says_amendment_not_ineffective():
    m = _effective_marker(_pending(), {})
    assert "개정 예정" in m and "2027-04-29" in m
    assert "위 현행 조문의 개정본" in m


def test_standalone_pending_keeps_ineffective_wording():
    """짝(supersedes)이 없는 단독 미시행 조문은 '아직 효력 없음' 그대로."""
    m = _effective_marker(
        {"effective_status": "미시행", "enforcement_date": "2026-11-12"}, {})
    assert "시행 예정" in m and "효력" in m
    assert "개정본" not in m


def test_format_pairs_current_then_pending():
    text = _format_rag_hits([(1, _current(), None), (2, _pending(), None)])
    lines = [ln for ln in text.splitlines() if ln.startswith("[")]
    assert "⚠️" not in lines[0]                    # 현행은 무표기
    assert "개정 예정" in lines[1] and "2027-04-29" in lines[1]


# ── citation 버전 축 ──────────────────────────────────────────────────────

def test_citation_carries_version_axis():
    c = build_citation_from_api_hit(_pending(), number=2)
    assert c["version_status"] == "pending"
    assert c["supersedes_article_key"] == "001788_0057001"
    assert c["status"] == "amended_pending"        # 폐지 아님
    assert c["effective_status"] == "미시행"


def test_current_citation_marked_current():
    c = build_citation_from_api_hit(_current(), number=1)
    assert c["version_status"] == "current"
    assert "supersedes_article_key" not in c
    assert c["status"] == "active"


def test_pending_citation_id_uses_versioned_key():
    """예정본 인용 id 는 `_ef` 접미 키 — 현행 인용과 충돌하지 않아야 한다."""
    cur = build_citation_from_api_hit(_current(), number=1)
    pen = build_citation_from_api_hit(_pending(), number=2)
    assert cur["id"] != pen["id"]
    assert pen["id"].endswith("_ef20270429")
