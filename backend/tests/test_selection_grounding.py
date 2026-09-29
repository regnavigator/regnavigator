"""요구사항 ④ — selection→grounding 연결.

전문가가 법률 네트워크에서 고른 article_key(state.selected_law_keys)가 있으면
qdrant_search 가 벡터검색 대신 그 조문만 PG 에서 fetch 해 grounding(replace)한다.
선택이 없으면 기존 벡터검색 경로 그대로(동작 보존).
"""
from __future__ import annotations

import pytest


def _call(tool_fn, args: dict, *, state: dict | None = None):
    """chat_loop 도구 래퍼(_tool_qdrant) 직접 호출 — ToolExec 반환."""
    return tool_fn(args, state or {"steps": [], "messages": []}, "call_1")


_LONG = "제6조(제조허가) 의료기기를 제조하려는 자는 식약처장의 허가를 받아야 한다. " * 6


def _fake_pg(keys, **kw):
    # 선택된 키마다 PG 메타(full_text 길게 → Mongo fetch 회피).
    return {
        k: {
            "target_type": "law",
            "law_title": "의료기기법",
            "article_num": "제6조",
            "article_title": "제조허가",
            "full_text": _LONG,
            "law_id": "009514",
            "enforce_date": "20210101",
            "department": "식품의약품안전처",
        }
        for k in keys
    }


# ---------------------------------------------------------------------------
# 코어 — run_qdrant_pinned
# ---------------------------------------------------------------------------
def _identity_resolve(keys, **kw):
    return {k: k for k in keys}


def test_run_qdrant_pinned_builds_citations_from_pg(monkeypatch):
    monkeypatch.setattr("src.retrieval.pg_client.fetch_articles", _fake_pg)
    monkeypatch.setattr("src.retrieval.pg_client.resolve_article_keys", _identity_resolve)
    from src.tools.search import run_qdrant_pinned

    core = run_qdrant_pinned(["009514_000600", "009514_000900"])
    assert core.final_keys == ["009514_000600", "009514_000900"]
    assert core.qdrant_keys == []
    # 각 키마다 _PgPoint(payload) + citation
    assert len(core.built) == 2
    for ak, h, c in core.built:
        assert h is not None and h.payload["article_key"] == ak
        assert c["title"].startswith("의료기기법")
        assert c["source_kind"] == "doc"


def test_run_qdrant_pinned_skips_unknown_keys(monkeypatch):
    monkeypatch.setattr("src.retrieval.pg_client.fetch_articles",
                        lambda keys, **kw: {})  # PG 미발견
    monkeypatch.setattr("src.retrieval.pg_client.resolve_article_keys", _identity_resolve)
    from src.tools.search import run_qdrant_pinned
    core = run_qdrant_pinned(["zzz"])
    assert core.final_keys == [] and core.built == []


# ---------------------------------------------------------------------------
# 도구 — 자동 핀
# ---------------------------------------------------------------------------
def test_qdrant_search_pins_when_selection_present(monkeypatch):
    monkeypatch.setattr("src.retrieval.pg_client.fetch_articles", _fake_pg)
    monkeypatch.setattr("src.retrieval.pg_client.resolve_article_keys", _identity_resolve)
    import src.chat_loop as cl

    # 선택이 있으면 벡터검색(run_qdrant)은 절대 호출되면 안 됨.
    # (chat_loop 는 `from src.tools.search import run_qdrant` 로 이름을 복사
    #  하므로 patch 대상은 src.chat_loop attr.)
    monkeypatch.setattr(cl, "run_qdrant",
                        lambda *a, **k: pytest.fail("run_qdrant must not run when pinned"))

    exec_ = _call(
        cl._tool_qdrant, {"query": "제조허가 절차"},
        state={"steps": [], "messages": [],
               "selected_law_keys": ["009514_000600", "009514_000900"]},
    )
    done = exec_.steps[1]
    assert done["status"] == "done"
    # 선택 조문이 grounding citation 으로
    titles = [c["title"] for c in done["citations"]]
    assert all(t.startswith("의료기기법") for t in titles)
    assert len(done["citations"]) == 2
    # LLM 컨텍스트(ToolMessage)도 비어있지 않아야(=핀 본문 렌더)
    assert "의료기기법" in exec_.tool_message.content


def test_qdrant_search_normal_when_no_selection(monkeypatch):
    import src.chat_loop as cl
    from src.tools.search import QdrantCore

    # 선택 없으면 핀(run_qdrant_pinned)은 호출되면 안 됨.
    monkeypatch.setattr(cl, "run_qdrant_pinned",
                        lambda *a, **k: pytest.fail("pinned must not run without selection"))
    monkeypatch.setattr(cl, "run_qdrant", lambda *a, **k: QdrantCore(
        built=[], final_keys=[], qdrant_keys=[],
        pg_meta_by_key={}, qdrant_by_key={}))

    exec_ = _call(cl._tool_qdrant, {"query": "광고"},
                  state={"steps": [], "messages": [], "selected_law_keys": []})
    assert exec_.steps[1]["status"] == "done"


# ---------------------------------------------------------------------------
# 상태 reducer
# ---------------------------------------------------------------------------
def test_keep_last_selection_reducer():
    from src.steps import keep_last_selection
    assert keep_last_selection(["a"], ["b", "c"]) == ["b", "c"]   # 새 값 채택
    assert keep_last_selection(["a"], None) == ["a"]               # 미전송 → 보존
    assert keep_last_selection(["a"], []) == []                    # 빈값 → 해제
