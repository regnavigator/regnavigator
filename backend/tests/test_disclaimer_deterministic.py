"""면책 결정적 부착 (2026-10-03 감사 S1·S2).

`legal.py` 가 선언한 원칙: "면책 문구를 LLM 이 매번 작성하면 표현이 흔들리고
누락될 수 있다. 법적 고지는 결정적으로 부착해야 한다." — 그런데 채팅은 프롬프트
지시뿐, 의견서는 아무것도 없었다. 여기서 둘 다 고정한다.
"""

from __future__ import annotations

import pytest

from src.legal import (
    DISCLAIMER_CHAT,
    DISCLAIMER_REPORT,
    append_chat_disclaimer,
    append_report_disclaimer,
)


def test_chat_disclaimer_appended_once():
    out = append_chat_disclaimer("답변 본문 [1]")
    assert out.startswith("답변 본문 [1]")
    assert DISCLAIMER_CHAT in out
    assert append_chat_disclaimer(out) == out  # 멱등


def test_chat_disclaimer_skips_if_llm_already_wrote_it():
    body = "답변\n\n" + DISCLAIMER_CHAT
    assert append_chat_disclaimer(body) == body


def test_chat_disclaimer_leaves_empty_alone():
    assert append_chat_disclaimer("") == ""


def test_report_disclaimer_appended_once():
    out = append_report_disclaimer("# 의견서\n\n본문")
    assert "법률자문 또는 관할기관의 유권해석이 아닙니다" in out
    assert DISCLAIMER_REPORT.strip() in out
    assert append_report_disclaimer(out) == out


def test_prompt_no_longer_asks_llm_to_write_disclaimer():
    """프롬프트가 LLM 에게 면책을 쓰라고 하면 이중 부착된다."""
    from src.prompts.supervisor import SUPERVISOR_PROMPT as SYSTEM_PROMPT

    assert "본문 끝에 덧붙인다" not in SYSTEM_PROMPT
    assert "쓰지 않는다" in SYSTEM_PROMPT and "결정적으로" in SYSTEM_PROMPT


@pytest.mark.parametrize("has_cite,expect", [(True, True), (False, False)])
def test_chat_turn_attaches_disclaimer_only_with_citations(monkeypatch, has_cite, expect):
    """법령 근거로 답한 턴(인용 ≥1)에만 붙는다 — 인사·메타 턴에는 안 붙는다."""
    import asyncio
    import tempfile

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", tempfile.mktemp(suffix=".db"))
    monkeypatch.setenv("PII_GATE_ALLOW_NO_NER", "1")
    monkeypatch.setenv("CLAIM_AUDIT_DISABLE", "1")
    import src.persistence.threads_repo as TR

    monkeypatch.setattr(TR, "_repo", None)
    from src import chat_loop as cl

    monkeypatch.setattr(cl, "_turn_citation_count", lambda steps: 1 if has_cite else 0)
    monkeypatch.setattr(cl, "_intent_force_search", lambda *a, **k: False)

    class M:
        def bind_tools(self, *a, **k): return self
        def bind(self, **k): return self
        def with_fallbacks(self, *a, **k): return self
        async def astream(self, *a, **k):
            from langchain_core.messages import AIMessageChunk
            yield AIMessageChunk(content="답변 본문입니다.")

    done = {}

    async def run():
        async for ev in cl.run_chat_turn("t_disc", "안녕하세요", user_id="u",
                                         models=(M(), M())):
            if ev.get("type") == "done":
                done.update(ev)
    asyncio.run(run())
    assert (DISCLAIMER_CHAT in (done.get("text") or "")) is expect
    monkeypatch.setattr(TR, "_repo", None)


# ── 기능별 한계 고지 — 결정적 부착 (2026-10-03 감사 L3·L5·L8) ─────────────

from src.legal import FEATURE_CAVEAT_MARK, append_feature_caveat


def test_feature_caveat_for_known_kinds():
    out = append_feature_caveat("본문", ["ordin"])
    assert FEATURE_CAVEAT_MARK in out and "자치법규는" in out
    assert append_feature_caveat(out, ["ordin"]) == out  # 멱등


def test_feature_caveat_skips_unknown_or_empty():
    assert append_feature_caveat("본문", ["law"]) == "본문"
    assert append_feature_caveat("본문", None) == "본문"
    assert append_feature_caveat("", ["prec"]) == ""


def test_feature_caveat_joins_multiple():
    out = append_feature_caveat("본문", ["admrul_attach", "prec"])
    assert "판례 코퍼스는" in out and out.count(FEATURE_CAVEAT_MARK) == 1


def test_doc_kinds_hint_reaches_qdrant_tool(monkeypatch):
    """프런트 힌트(doc_kinds)가 모델이 종별을 안 고르면 기본 종별로 쓰인다."""
    from src import chat_loop as cl

    seen = {}

    def fake_run(query, top_k=None, target_types=None, **kw):
        seen["kinds"] = target_types
        from src.tools.search import QdrantCore
        return QdrantCore(hits=[], citations=[], tool_text="", final_keys=[])

    monkeypatch.setattr("src.chat_loop.run_qdrant", fake_run)
    monkeypatch.setattr(cl, "step_start", lambda *a, **k: ("sid", 0))
    monkeypatch.setattr(cl, "step_done", lambda *a, **k: {})
    state = {"selected_law_keys": [], "steps": [], "messages": [],
             "default_doc_kinds": ["expc"]}
    try:
        cl._tool_qdrant({"query": "q"}, state, "tc")
    except Exception:
        pass  # 더블이 거친 부분은 상관없다 — 종별 전달만 본다
    assert seen.get("kinds") == ["expc"]
