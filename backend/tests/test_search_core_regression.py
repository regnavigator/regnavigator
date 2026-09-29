"""search 코어 추출 **회귀 게이트** (#32).

외부 클라(Tavily·qdrant_client·pg_client·reranker)를 고정 응답으로 stub
하고, `_tool_qdrant`/`_tool_tavily`(src/chat_loop.py — 구 @tool 래퍼의 후신)
의 결정적 출력(citations + LLM 텍스트)을 골든으로 캡처한다.

목적: 코어 추출 리팩터 *전후* 이 출력이 **바이트 동일**해야 한다(동작 변경
0). 래퍼는 코어(src/tools/search.py) 호출하는 얇은 층이고, 코어를 직접 부른
결과도 같은 골든과 일치해야 한다(보고서 파이프라인이 그 코어를 씀).

ADR-0001 Phase 5: @tool 래퍼 삭제로 코어=툴 동등성 테스트
(test_run_tavily_core_equals_tool/test_run_qdrant_core_equals_tool)는 비교
대상이 사라져 삭제 — 래퍼 출력 골든과 코어 테스트가 각각 커버.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


def _call(tool_fn, args: dict, *, tool_call_id: str = "call_1",
          state: dict | None = None):
    return tool_fn(args, state or {"steps": [], "messages": []}, tool_call_id)


def _exec_citations_text(exec_):
    """ToolExec → (citations 리스트, LLM 텍스트). 불변식 스냅샷 추출."""
    done = exec_.steps[-1]
    cites = done.get("citations") or []
    text = exec_.tool_message.content
    return cites, text


def _api_hits():
    """openlaw-etl /search API 형태의 결정적 고정 hit 2건."""
    return [
        {"article_key": "law_001_art_5", "law_id": "law_001", "mst_id": "law_001",
         "target_type": "law", "chunk_type": "article",
         "law_title": "의료기기법", "article_num": "제5조", "article_title": "제조허가",
         "attachment_subtype": None, "attachment_link": None,
         "article_url": "https://www.law.go.kr/법령/의료기기법/제5조",
         "is_current": True, "enforcement_date": "2026-01-01",
         "department": "식품의약품안전처", "snippet": "제조허가 …", "score": 2.1},
        {"article_key": "admrul_009_art_2", "law_id": "admrul_009", "mst_id": "admrul_009",
         "target_type": "admrul", "chunk_type": "article",
         "law_title": "의료기기 광고 사전심의 규정", "article_num": "제2조",
         "article_title": "사전심의", "attachment_subtype": None, "attachment_link": None,
         "article_url": None, "is_current": True, "enforcement_date": None,
         "department": None, "snippet": "사전심의 …", "score": 1.8},
    ]


@pytest.fixture
def _stub_external(monkeypatch):
    """모든 외부 의존을 고정 응답으로 — 결정적."""
    monkeypatch.setenv("TAVILY_API_KEY", "test")

    class FakeTavily:
        def __init__(self, api_key): ...
        def search(self, query, max_results, search_depth, **kw):
            return {"results": [
                {"title": "식약처 의료기기 광고 가이드",
                 "url": "https://www.mfds.go.kr/g1", "content": "사전심의 의무 …"},
                {"title": "업계 동향",
                 "url": "https://example.com/n2", "content": "최근 개정 …"},
            ]}
    monkeypatch.setitem(sys.modules, "tavily",
                        SimpleNamespace(TavilyClient=FakeTavily))

    import src.retrieval.search_api_client as sc
    monkeypatch.setattr(sc, "search_articles",
                        lambda q, top_k=8, target_types=None: _api_hits())
    yield


# ── 골든 캡처 — 현행 PASS = 동작 충실 캡처. 리팩터 후도 PASS = 보존 ──

def test_tavily_golden(_stub_external):
    from src.chat_loop import _tool_tavily
    exec_ = _call(_tool_tavily, {"query": "의료기기 광고 사전심의"})
    cites, text = _exec_citations_text(exec_)
    assert len(cites) == 2
    assert [c["number"] for c in cites] == [1, 2]
    assert "식약처" in text and "[1]" in text and "[2]" in text
    # id 안정성(url sha1 기반) — 추출 후도 동일해야.
    assert all(c["id"].startswith("cite_web_") for c in cites)
    test_tavily_golden.captured = (cites, text)  # type: ignore[attr-defined]


def test_qdrant_golden_primary(_stub_external):
    """기본 경로 — /search API hit → citation."""
    from src.chat_loop import _tool_qdrant
    exec_ = _call(_tool_qdrant, {"query": "의료기기 제조허가 절차"})
    cites, text = _exec_citations_text(exec_)
    assert len(cites) == 2
    assert [c["number"] for c in cites] == [1, 2]
    assert "[1]" in text and "[2]" in text
    titles = " ".join(str(c.get("title", "")) for c in cites)
    assert "의료기기법" in titles
    # 서버 제공 정본 URL·부처가 citation 에 실려야.
    assert cites[0].get("url", "").startswith("https://www.law.go.kr/")
    assert cites[0].get("publisher") == "식품의약품안전처"


def test_tavily_missing_key_abort(monkeypatch):
    """키 누락 → _abort (start + error). state 에 start 보존."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from src.chat_loop import _tool_tavily
    exec_ = _call(_tool_tavily, {"query": "광고"})
    assert len(exec_.steps) == 2
    assert exec_.steps[1]["status"] == "error"
    assert "TAVILY_API_KEY" in exec_.steps[1]["error_message"]


def test_qdrant_search_fail_abort(monkeypatch, _stub_external):
    """search API 예외 → _abort (start + error). state 에 start 보존."""
    import src.retrieval.search_api_client as sc

    def _boom(q, top_k=8, target_types=None):
        raise RuntimeError("search api down")
    monkeypatch.setattr(sc, "search_articles", _boom)
    from src.chat_loop import _tool_qdrant
    exec_ = _call(_tool_qdrant, {"query": "제조허가"})
    assert len(exec_.steps) == 2
    assert exec_.steps[1]["status"] == "error"


# ── Tavily snippet 깨짐 가드 (_looks_corrupted) 경계 ──
def test_looks_corrupted_detects_garbage():
    from src.tools.search import _looks_corrupted
    # 그리스/키릴 ≥3 + 한글 < max(3,g): 깨진 PDF 추출 시그니처
    assert _looks_corrupted("DZε ΡRɗ gxџ ⊠ 의료") is True
    # 한글이 충분히 있으면 깨짐 아님(우연한 수학기호 섞임)
    assert _looks_corrupted("의료기기 허가 절차 ∀x∈∃ 식약처 가이드") is False
    # 영문만(깨끗) — 그리스 없음
    assert _looks_corrupted("medical device approval process") is False
    # 빈 문자열·None
    assert _looks_corrupted("") is False
    assert _looks_corrupted(None) is False


def test_tavily_masks_corrupted_snippet(monkeypatch):
    """Tavily 가 깨진 content 를 돌려줘도 snippet 만 비고 URL/title 보존."""
    import sys
    from types import SimpleNamespace

    monkeypatch.setenv("TAVILY_API_KEY", "test")

    class FakeBroken:
        def __init__(self, api_key): ...
        def search(self, query, max_results, search_depth, **kw):
            return {"results": [
                # 깨진 snippet(그리스/키릴 범벅)·정상 URL/title
                {"title": "식약처 의료기기 광고 가이드",
                 "url": "https://www.mfds.go.kr/g1",
                 "content": "DZε ΡRɗ gxџ ⊠ Ϡϡ Ѱѱ ∀∃ ⋐⋑"},
            ]}
    monkeypatch.setitem(sys.modules, "tavily",
                        SimpleNamespace(TavilyClient=FakeBroken))
    from src.tools.search import run_tavily
    built = run_tavily("광고")
    assert len(built) == 1
    raw, cite = built[0]
    assert raw["content"] == ""              # 깨진 snippet 마스킹됨
    assert raw["title"] == "식약처 의료기기 광고 가이드"   # title 보존
    assert raw["url"].endswith("/g1")        # url 보존 → citation 유효
    assert cite["snippet"] == ""             # citation snippet 도 비어있음
    assert cite["title"] == "식약처 의료기기 광고 가이드"
