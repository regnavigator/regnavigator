"""steps.py 헬퍼 — step_start / step_done / step_error / now_ms / new_step_id 테스트.

spec: 02_INTERFACE.md §2.1
"""

from __future__ import annotations

import time

import pytest

from src.steps import new_step_id, now_ms, step_done, step_error, step_start


def test_now_ms_is_int_milliseconds():
    before = int(time.time() * 1000) - 50
    got = now_ms()
    after = int(time.time() * 1000) + 50
    assert isinstance(got, int)
    assert before <= got <= after


def test_new_step_id_unique_with_prefix():
    ids = {new_step_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(sid.startswith("s_") for sid in ids)


def test_step_start_basic():
    sid, payload = step_start("웹 검색", tool_name="tavily_search",
                              input_preview="의료기기")
    assert sid.startswith("s_")
    assert payload["id"] == sid
    assert payload["status"] == "running"
    assert payload["label"] == "웹 검색"
    assert payload["tool_name"] == "tavily_search"
    assert payload["input_preview"] == "의료기기"
    assert isinstance(payload["ts"], int)


def test_step_start_no_input_preview():
    sid, payload = step_start("작업", tool_name="custom")
    assert "input_preview" not in payload
    assert payload["label"] == "작업"


def test_step_start_label_truncated_at_70_chars():
    long_label = "의료기기 광고 심의 기준에 관한 매우 긴 제목 " * 10
    sid, payload = step_start(long_label, tool_name="t")
    assert len(payload["label"]) == 70


def test_step_done_basic():
    payload = step_done("s_abc", output_preview="결과 5건")
    assert payload["id"] == "s_abc"
    assert payload["status"] == "done"
    assert payload["output_preview"] == "결과 5건"
    assert isinstance(payload["ended_at"], int)


def test_step_done_with_citations():
    cites = [{"id": "c1", "number": 1, "title": "x"}]
    payload = step_done("s_abc", citations=cites)
    assert payload["citations"] == cites


def test_step_done_no_optional_keys():
    payload = step_done("s_abc")
    assert "output_preview" not in payload
    assert "citations" not in payload
    assert payload["status"] == "done"


def test_step_done_output_preview_truncated_at_80():
    long_text = "a" * 200
    payload = step_done("s_abc", output_preview=long_text)
    assert len(payload["output_preview"]) == 80


def test_step_error_basic():
    payload = step_error("s_abc", message="검색 일시 실패")
    assert payload["id"] == "s_abc"
    assert payload["status"] == "error"
    assert payload["error_message"] == "검색 일시 실패"
    assert isinstance(payload["ended_at"], int)


def test_step_lifecycle_with_reducer():
    """start → done이 reducer를 거치면 정상 merge."""
    from src.steps import merge_steps_by_id

    sid, start = step_start("웹 검색", tool_name="tavily_search")
    done = step_done(sid, output_preview="3건")
    result = merge_steps_by_id([], [start, done])
    assert len(result) == 1
    s = result[0]
    assert s["status"] == "done"
    assert s["label"] == "웹 검색"
    assert s["output_preview"] == "3건"


# ---------------------------------------------------------------------------
# source_message_id / turn_idx (2026-05-01~)
# ---------------------------------------------------------------------------
def test_step_start_extracts_source_message_id_from_state():
    """state.messages에서 가장 최근 human message의 id·turn_idx 자동 추출."""
    from src.steps import step_start

    state = {
        "messages": [
            {"type": "human", "id": "msg-1", "content": "첫 질문"},
            {"type": "ai", "id": "ai-1", "content": "답변"},
            {"type": "human", "id": "msg-2", "content": "두 번째 질문"},
        ]
    }
    sid, payload = step_start("test", tool_name="qdrant_search", state=state)
    assert payload["source_message_id"] == "msg-2"
    assert payload["turn_idx"] == 1


def test_step_start_no_human_returns_no_turn_context():
    from src.steps import step_start
    sid, payload = step_start("test", tool_name="x", state={"messages": []})
    assert "source_message_id" not in payload
    assert "turn_idx" not in payload


def test_step_start_explicit_overrides_state():
    """명시 source_message_id / turn_idx 인자가 state 자동 추출보다 우선."""
    from src.steps import step_start
    state = {"messages": [{"type": "human", "id": "msg-A"}]}
    sid, payload = step_start(
        "test", tool_name="x", state=state,
        source_message_id="msg-OVERRIDE", turn_idx=99,
    )
    assert payload["source_message_id"] == "msg-OVERRIDE"
    assert payload["turn_idx"] == 99


def test_resolve_turn_context_handles_both_dict_and_basemessage():
    """LangChain BaseMessage·dict 둘 다 처리."""
    from src.steps import resolve_turn_context
    from types import SimpleNamespace

    state = {
        "messages": [
            SimpleNamespace(type="human", id="bm-1", content="..."),
            SimpleNamespace(type="ai", id="bm-ai", content="..."),
            {"type": "human", "id": "dict-1", "content": "..."},
        ]
    }
    src_id, idx = resolve_turn_context(state)
    assert src_id == "dict-1"
    assert idx == 1


def test_resolve_turn_context_none_or_empty():
    from src.steps import resolve_turn_context
    assert resolve_turn_context(None) == (None, None)
    assert resolve_turn_context({}) == (None, None)
    assert resolve_turn_context({"messages": []}) == (None, None)
