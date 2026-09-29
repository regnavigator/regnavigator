"""tavily / qdrant 검색 도구 단위 테스트 (mock).

ADR-0001 Phase 5: @tool 래퍼(`tavily_search`/`qdrant_search`) 삭제 —
`src/chat_loop.py` 의 `_tool_tavily`/`_tool_qdrant`(ToolExec 반환)를 직접 검증.
코어(run_tavily/run_qdrant)와 헬퍼(_assign_turn_citation_numbers 등)는
여전히 `src/tools/search.py`.

spec: 06_SKILLS M1·M2
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


def _call(tool_fn, args: dict, *, tool_call_id: str = "call_1", state: dict | None = None):
    """chat_loop 도구 래퍼 직접 호출 — ToolExec 반환.

    (구 @tool `.invoke()` 대체 — steps 는 `exec.steps`, LLM 텍스트는
    `exec.tool_message.content`.)
    """
    return tool_fn(args, state or {"steps": [], "messages": []}, tool_call_id)


# ---------------------------------------------------------------------------
# tavily (_tool_tavily)
# ---------------------------------------------------------------------------
def test_tavily_missing_api_key_returns_step_error(monkeypatch):
    from src.chat_loop import _tool_tavily

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    exec_ = _call(_tool_tavily, {"query": "광고"})
    steps = exec_.steps
    # start + error 두 dict (state 에 start 보존 — FE citation 렌더).
    assert len(steps) == 2
    assert steps[1]["status"] == "error"
    assert "TAVILY_API_KEY" in steps[1]["error_message"]


def test_tavily_success_with_mock(monkeypatch):
    from src.chat_loop import _tool_tavily

    monkeypatch.setenv("TAVILY_API_KEY", "test")

    class FakeClient:
        def __init__(self, api_key):  # noqa: D401
            self.api_key = api_key

        def search(self, query, max_results, search_depth, **kw):
            return {
                "results": [
                    {"title": "식약처 가이드", "url": "https://mfds.go.kr/a",
                     "content": "광고 표시"},
                    {"title": "기타", "url": "https://example.com/b",
                     "content": "기타 내용"},
                ]
            }

    fake_module = SimpleNamespace(TavilyClient=FakeClient)
    monkeypatch.setitem(sys.modules, "tavily", fake_module)

    exec_ = _call(_tool_tavily, {"query": "의료기기 광고"})
    steps = exec_.steps
    # start + done (state 에 start 보존 — FE citation 렌더).
    assert len(steps) == 2
    start, done = steps
    assert start["status"] == "running"
    assert done["status"] == "done"
    assert "결과 2건" in done["output_preview"]
    assert len(done["citations"]) == 2
    # 첫 결과의 publisher 매핑
    assert done["citations"][0]["publisher"] == "식품의약품안전처"


def test_tavily_exception_returns_step_error(monkeypatch):
    from src.chat_loop import _tool_tavily

    monkeypatch.setenv("TAVILY_API_KEY", "test")

    class BoomClient:
        def __init__(self, api_key):
            pass

        def search(self, **_):
            raise RuntimeError("network down")

    monkeypatch.setitem(sys.modules, "tavily",
                        SimpleNamespace(TavilyClient=BoomClient))

    exec_ = _call(_tool_tavily, {"query": "x"})
    err = exec_.steps[1]  # start + error
    assert err["status"] == "error"
    assert "잠시 후" in err["error_message"]


# ---------------------------------------------------------------------------
# qdrant (_tool_qdrant)
# ---------------------------------------------------------------------------
def _api_hit(**over):
    """openlaw-etl /search API hit 형태의 고정 응답."""
    h = {
        "article_key": "013476_0022001", "law_id": "013476", "mst_id": "013476",
        "law_title": "의료기기법", "article_num": "제45조",
        "article_title": "광고 심의", "target_type": "law", "chunk_type": "article",
        "attachment_subtype": None, "attachment_link": None,
        "article_url": "https://www.law.go.kr/x", "score": 2.4,
        "enforcement_date": "2026-07-01", "is_current": True,
        "department": "보건복지부", "snippet": "조항 본문",
    }
    h.update(over)
    return h


def test_qdrant_search_with_mock(monkeypatch):
    from src.chat_loop import _tool_qdrant
    monkeypatch.setattr("src.retrieval.search_api_client.search_articles",
                        lambda q, top_k=8, target_types=None: [_api_hit()])

    exec_ = _call(_tool_qdrant, {"query": "광고"})
    steps = exec_.steps
    # start + done (state 에 start 보존).
    assert len(steps) == 2
    done = steps[1]
    assert done["status"] == "done"
    assert "1건 매칭" in done["output_preview"]
    assert len(done["citations"]) == 1
    assert done["citations"][0]["article"] == "제45조"


def test_qdrant_search_empty(monkeypatch):
    from src.chat_loop import _tool_qdrant
    monkeypatch.setattr("src.retrieval.search_api_client.search_articles",
                        lambda q, top_k=8, target_types=None: [])
    exec_ = _call(_tool_qdrant, {"query": "없음"})
    done = exec_.steps[1]  # start + done
    assert done["status"] == "done"
    assert "0건 매칭" in done["output_preview"]


def test_qdrant_search_exception(monkeypatch):
    from src.chat_loop import _tool_qdrant

    def boom(q, top_k=8, target_types=None):
        raise RuntimeError("conn refused")

    monkeypatch.setattr("src.retrieval.search_api_client.search_articles", boom)

    exec_ = _call(_tool_qdrant, {"query": "x"})
    err = exec_.steps[1]  # start + error
    assert err["status"] == "error"
    assert "잠시 후" in err["error_message"]


# ---------------------------------------------------------------------------
# turn 전역 단조 인용 번호 (회귀: 도구 호출마다 [1] 재시작 → 출처 인용 깨짐)
# ---------------------------------------------------------------------------
def test_assign_turn_citation_numbers_monotonic_across_calls():
    from src.tools.search import _assign_turn_citation_numbers

    # 1) 첫 호출 — prior step 없음 → 1,2부터
    c1 = [{"id": "cite_doc_A"}, {"id": "cite_doc_B"}]
    out1 = _assign_turn_citation_numbers({"steps": []}, c1)
    assert [c["number"] for c in out1] == [1, 2]

    # 2) 다음 도구 호출 — 직전 step.citations 누적 상태에서 *이어서* 매김
    state = {"steps": [{"status": "done", "citations": out1}]}
    c2 = [{"id": "cite_web_X"}, {"id": "cite_doc_B"}, {"id": "cite_web_Y"}]
    out2 = _assign_turn_citation_numbers(state, c2)
    nums = {c["id"]: c["number"] for c in out2}
    assert nums["cite_web_X"] == 3            # 새 출처 — 1 재시작 금지
    assert nums["cite_doc_B"] == 2            # 기존 출처 — 같은 번호 재사용
    assert nums["cite_web_Y"] == 4


def test_assign_turn_citation_numbers_dedupes_same_call():
    from src.tools.search import _assign_turn_citation_numbers
    out = _assign_turn_citation_numbers(
        {"steps": []},
        [{"id": "cite_doc_A"}, {"id": "cite_doc_A"}, {"id": "cite_doc_C"}],
    )
    assert [(c["id"], c["number"]) for c in out] == [
        ("cite_doc_A", 1), ("cite_doc_C", 2)]


# ---------------------------------------------------------------------------
# 도구 호출 한도: 현재 turn 스코프 (회귀: thread 누적 → 여러 질문 후 오발)
# ---------------------------------------------------------------------------
def test_count_tool_calls_scoped_to_current_turn():
    from src.tools.search import _count_tool_calls
    # 같은 thread, 질문 2개. 1턴(h1)에서 tavily 3회 누적, 현재 turn = h2.
    state = {
        "messages": [
            {"type": "human", "id": "h1"},
            {"type": "human", "id": "h2"},
        ],
        "steps": [
            {"tool_name": "tavily_search", "source_message_id": "h1", "turn_idx": 0},
            {"tool_name": "tavily_search", "source_message_id": "h1", "turn_idx": 0},
            {"tool_name": "tavily_search", "source_message_id": "h1", "turn_idx": 0},
            {"tool_name": "tavily_search", "source_message_id": "h2", "turn_idx": 1},
        ],
    }
    # 1턴 3회가 누적 안 됨 → 현재 turn(h2)은 1회로만 카운트
    assert _count_tool_calls(state, "tavily_search") == 1
    assert _count_tool_calls(state, "qdrant_search") == 0


def test_count_tool_calls_no_turn_context_falls_back_to_cumulative():
    from src.tools.search import _count_tool_calls
    # messages 없음(단위테스트/CLI) — 폴백: 누적 카운트로 가드 자체는 유지
    state = {"messages": [], "steps": [
        {"tool_name": "tavily_search"}, {"tool_name": "tavily_search"}]}
    assert _count_tool_calls(state, "tavily_search") == 2


# ── 웹 레인 저품질 출처 차단 (2026-08-03 실사용 실측) ────────────────
def test_tavily_excludes_ugc_domains_by_default(monkeypatch):
    """규제 답변 인용에 네이버 블로그·유튜브가 실리던 문제.

    실측: 최종 인용 목록에 유튜브 7건·네이버 블로그 10건. 사용자가 의사·RA/QA라
    이런 출처는 신뢰를 직접 깎는다.
    """
    import src.tools.search as S

    monkeypatch.delenv("TAVILY_EXCLUDE_DOMAINS", raising=False)
    ex = S._web_exclude_domains()
    for d in ("blog.naver.com", "m.blog.naver.com", "youtube.com", "tistory.com"):
        assert d in ex, f"{d} 가 제외 목록에 없다"


def test_tavily_exclude_domains_env_override(monkeypatch):
    import src.tools.search as S

    monkeypatch.setenv("TAVILY_EXCLUDE_DOMAINS", "a.com, b.com")
    assert S._web_exclude_domains() == ["a.com", "b.com"]


def test_tavily_exclude_can_be_disabled(monkeypatch):
    """빈 값이면 차단을 끈다(긴급 시 되돌릴 수 있어야 한다)."""
    import src.tools.search as S

    monkeypatch.setenv("TAVILY_EXCLUDE_DOMAINS", "")
    assert S._web_exclude_domains() == []


def test_run_tavily_passes_exclude_domains(monkeypatch):
    """실제 호출에 인자가 실리는지 — 상수만 있고 안 넘기면 무의미하다."""
    import src.tools.search as S

    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.delenv("TAVILY_EXCLUDE_DOMAINS", raising=False)
    captured = {}

    class _FakeClient:
        def __init__(self, api_key=None): pass
        def search(self, **kw):
            captured.update(kw)
            return {"results": []}

    import sys, types
    mod = types.ModuleType("tavily")
    mod.TavilyClient = _FakeClient
    monkeypatch.setitem(sys.modules, "tavily", mod)

    S.run_tavily("의료기기 광고 심의")
    assert "blog.naver.com" in captured.get("exclude_domains", [])
