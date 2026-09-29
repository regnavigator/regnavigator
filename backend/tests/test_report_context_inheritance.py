"""보고서의 채팅 맥락 계승 — 근거 코퍼스(doc_kinds) 이어받기 (2026-08-25).

사고: 보고서는 프롬프트만 자체 분해해 기본 레인(law 5종 + guide)으로 검색했다.
채팅이 `admrul_attach`(심평원 급여기준)로 근거를 찾아둔 대화에서도 보고서는
그 코퍼스를 못 따라가 무관한 법령을 물어왔다(실측: "심평원 심사지침" →
마약류 관리에 관한 법률). 이제 채팅이 **근거를 낸** 종별을 계승한다.
"""
from __future__ import annotations

import pytest

from src.report_pipeline import extract_report_context, inherited_doc_kinds
from src.steps import step_done


def _step(kinds=None, cites=1, tool="qdrant_search", sid="s1"):
    s = {"id": sid, "status": "done", "tool_name": tool}
    if kinds:
        s["doc_kinds"] = list(kinds)
    if cites:
        s["citations"] = [{"id": f"cite_doc_{sid}_{i}"} for i in range(cites)]
    return s


def test_inherits_kind_that_produced_citations():
    state = {"steps": [_step(["admrul_attach"], cites=3)]}
    assert inherited_doc_kinds(state) == ["admrul_attach"]


def test_skips_kind_with_no_citations():
    """근거를 못 낸 검색은 계승하지 않는다 — 빈 레인만 늘리는 낭비."""
    state = {"steps": [_step(["admrul_attach"], cites=0)]}
    assert inherited_doc_kinds(state) == []


def test_skips_default_kinds():
    """law·admrul 등 기본 레인이 이미 도는 종별은 계승 대상 아님."""
    state = {"steps": [_step(["law", "prec"], cites=2)]}
    assert inherited_doc_kinds(state) == []


def test_ignores_non_qdrant_steps():
    state = {"steps": [_step(["admrul_attach"], cites=2, tool="tavily_search")]}
    assert inherited_doc_kinds(state) == []


def test_recent_turns_first_and_capped():
    """최근 턴 우선 + 상한 2 — 레인 폭주로 보고서가 느려지지 않게."""
    state = {"steps": [
        _step(["guide"], cites=1, sid="old"),
        _step(["admrul_attach"], cites=1, sid="mid"),
        _step(["expc_x", "ordin_y"], cites=1, sid="new"),
    ]}
    got = inherited_doc_kinds(state)
    assert len(got) <= 2
    assert got[0] in ("expc_x", "ordin_y")  # 최근 step 부터


def test_extract_report_context_exposes_inherited():
    state = {
        "messages": [{"type": "human", "content": "급여기준 알려줘"},
                     {"type": "ai", "content": "…"}],
        "steps": [_step(["admrul_attach"], cites=2)],
    }
    ctx = extract_report_context(state)
    assert ctx["inherited_kinds"] == ["admrul_attach"]
    assert ctx["user_query"] == "급여기준 알려줘"


def test_step_done_records_doc_kinds():
    """계승 재료가 step 에 남아야 한다(채팅 → 스레드 state → 보고서)."""
    s = step_done("s1", output_preview="x", doc_kinds=["admrul_attach"])
    assert s["doc_kinds"] == ["admrul_attach"]
    # 미지정 검색은 필드 자체가 없다(스키마 total=False).
    assert "doc_kinds" not in step_done("s2", output_preview="x")


@pytest.mark.asyncio
async def test_gather_adds_inherited_lane(monkeypatch):
    """계승 종별마다 **단독 레인**이 추가된다(혼합하면 법령이 랭킹 독식)."""
    from src import report_pipeline as rp

    seen: list = []

    async def _fake_gather_one(kind, q, tmo, event_ctx=None, target_types=None):
        seen.append((kind, target_types))
        return (kind, [])

    monkeypatch.setattr(rp, "_gather_one", _fake_gather_one)
    await rp.gather_for_report(["q1"], inherited_kinds=["admrul_attach"])
    assert ("rag", ["admril_attach"]) not in seen  # 오타 방어
    assert ("rag", ["admrul_attach"]) in seen, seen
    assert ("rag", None) in seen                    # 기본 레인 유지
    assert ("web", None) in seen
