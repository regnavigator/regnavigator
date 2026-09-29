"""답변 후 grounding 검증 훅 — chat_loop._apply_grounding.

(구 GroundingGateMiddleware 는 ADR-0001 Phase 5 은퇴 — 동일 의미론을 훅이 담당:
현재 답변에 실제 인용된 [n] citation 만 검증해 steps merge dict 로 반환.)
"""
from __future__ import annotations

import asyncio

from src.chat_loop import _apply_grounding


def _steps(cites: list[dict]) -> list[dict]:
    return [{"id": "s1", "citations": cites}]


def _run(turn_steps, body):
    return asyncio.run(_apply_grounding(turn_steps, body))


def test_hook_updates_verified_for_cited(monkeypatch):
    async def fake_ground(body, cites, **kw):
        out = []
        for c in cites:
            nc = dict(c)
            if c["number"] == 1:
                nc["verified"] = True
                nc["supporting_quote"] = "근거 문장"
            out.append(nc)
        return out

    import src.grounding as G
    monkeypatch.setattr(G, "ground_answer", fake_ground)

    cites = [{"id": "c1", "number": 1, "verified": False},
             {"id": "c2", "number": 2, "verified": False}]
    updates = _run(_steps(cites), "결론입니다 [1]")
    assert updates and updates[0]["id"] == "s1"
    by_id = {c["id"]: c for c in updates[0]["citations"]}
    assert by_id["c1"]["verified"] is True
    assert by_id["c1"]["supporting_quote"] == "근거 문장"
    assert by_id["c2"]["verified"] is False  # 미인용 — 불변


def test_hook_disabled(monkeypatch):
    monkeypatch.setenv("CHAT_GROUNDING_GATE_DISABLE", "1")
    cites = [{"id": "c1", "number": 1, "verified": False}]
    assert _run(_steps(cites), "결론 [1]") == []


def test_hook_no_citation_in_body(monkeypatch):
    monkeypatch.delenv("CHAT_GROUNDING_GATE_DISABLE", raising=False)
    cites = [{"id": "c1", "number": 1, "verified": False}]
    assert _run(_steps(cites), "인용 없는 답변") == []


def test_hook_error_is_swallowed(monkeypatch):
    """검증 실패가 답변을 막으면 안 됨 — 빈 업데이트로 무해 종료."""
    monkeypatch.delenv("CHAT_GROUNDING_GATE_DISABLE", raising=False)

    async def boom(body, cites, **kw):
        raise RuntimeError("ground fail")

    import src.grounding as G
    monkeypatch.setattr(G, "ground_answer", boom)
    cites = [{"id": "c1", "number": 1, "verified": False}]
    assert _run(_steps(cites), "결론 [1]") == []
