"""/chat/{id}/state 메시지 뷰 — 잘린 답변의 truncated 복원(2026-09-15).

종전엔 SSE done 에만 실려 새로고침하면 [이어서 작성] 버튼이 사라졌다.
"""
from langchain_core.messages import AIMessage, HumanMessage

from src.routes.chat import _message_view


def test_truncated_flag_restored():
    m = AIMessage(content="긴 답변", id="a1",
                  response_metadata={"stop_reason": "max_tokens", "truncated": True})
    assert _message_view(m)["truncated"] is True


def test_legacy_max_tokens_without_flag():
    m = AIMessage(content="긴 답변", id="a2", response_metadata={"stop_reason": "max_tokens"})
    assert _message_view(m)["truncated"] is True


def test_not_truncated_cases():
    assert "truncated" not in _message_view(
        AIMessage(content="끝", id="a3", response_metadata={"stop_reason": "end_turn"}))
    # 도구 호출 스트림의 max_tokens 는 답변 잘림이 아니다.
    tc = AIMessage(content="", id="a4", response_metadata={"stop_reason": "max_tokens"},
                   tool_calls=[{"name": "qdrant_search", "args": {}, "id": "t1"}])
    assert "truncated" not in _message_view(tc)
    assert "truncated" not in _message_view(HumanMessage(content="질문", id="h1"))
