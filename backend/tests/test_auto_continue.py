"""자동 이어쓰기(2026-08-24) — max_tokens 잘림 시 assistant prefill 연장.

베타 피드백: 서류 작성형 요청이 CHAT_MAX_TOKENS(4096)에서 여러 턴으로 끊김.
_stream_model 이 stop_reason=max_tokens 를 감지해 상한(CHAT_AUTO_CONTINUE_MAX,
기본 2회)까지 같은 message_id 로 이어 생성하고, 그래도 잘리면
response_metadata.truncated 를 세워 FE [이어서 작성] 폴백으로 넘긴다.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk

from src.chat_loop import _stream_model


class _FakeModel:
    """스크립트된 스트림 시퀀스 — 호출마다 다음 시나리오를 재생."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls: list[list] = []

    def astream(self, messages, config=None):
        self.calls.append(list(messages))
        script = self.scripts.pop(0)

        async def gen():
            for text, meta in script:
                yield AIMessageChunk(
                    content=text, response_metadata=meta or {},
                    usage_metadata={"input_tokens": 10, "output_tokens": 5,
                                    "total_tokens": 15},
                )
        return gen()


def _events():
    out = []
    return out, out.append


@pytest.mark.asyncio
async def test_no_continue_on_normal_stop():
    m = _FakeModel([[("안녕하세요", {}), ("", {"stop_reason": "end_turn"})]])
    events, emit = _events()
    ai = await _stream_model(m, [], None, emit)
    assert ai.content == "안녕하세요"
    assert len(m.calls) == 1
    assert not (ai.response_metadata or {}).get("truncated")


@pytest.mark.asyncio
async def test_auto_continue_merges_text_and_keeps_message_id():
    m = _FakeModel([
        [("서류 전문 1부 ", {"stop_reason": "max_tokens"})],
        [("이어지는 2부", {"stop_reason": "end_turn"})],
    ])
    events, emit = _events()
    ai = await _stream_model(m, [], None, emit)
    assert ai.content == "서류 전문 1부 이어지는 2부"
    assert len(m.calls) == 2
    # 연장 호출은 assistant prefill(공백 제거)로 끝난다
    prefill = m.calls[1][-1]
    assert prefill.content == "서류 전문 1부"
    # 모든 토큰이 같은 message_id 로 emit — FE 누적 리셋 방지
    mids = {e["message_id"] for e in events if e["type"] == "token"}
    assert len(mids) == 1
    assert not (ai.response_metadata or {}).get("truncated")
    # 토큰 회계 합산
    assert ai.usage_metadata["output_tokens"] == 10


@pytest.mark.asyncio
async def test_truncated_flag_after_cap(monkeypatch):
    monkeypatch.setenv("CHAT_AUTO_CONTINUE_MAX", "1")
    m = _FakeModel([
        [("1부", {"stop_reason": "max_tokens"})],
        [("2부", {"stop_reason": "max_tokens"})],  # 상한 후에도 잘림
    ])
    events, emit = _events()
    ai = await _stream_model(m, [], None, emit)
    assert ai.content == "1부2부"
    assert len(m.calls) == 2  # 상한 1회만 연장
    assert (ai.response_metadata or {}).get("truncated") is True


@pytest.mark.asyncio
async def test_tool_call_stream_never_continues(monkeypatch):
    monkeypatch.setenv("CHAT_AUTO_CONTINUE_MAX", "2")

    class _ToolChunkModel(_FakeModel):
        def astream(self, messages, config=None):
            self.calls.append(list(messages))

            async def gen():
                c = AIMessageChunk(content="", response_metadata={"stop_reason": "max_tokens"})
                c.tool_calls = [{"name": "qdrant_search", "args": {}, "id": "t1"}]
                yield c
            return gen()

    m = _ToolChunkModel([None])
    events, emit = _events()
    ai = await _stream_model(m, [], None, emit)
    assert len(m.calls) == 1  # tool_calls 스트림은 연장 금지
    assert not (ai.response_metadata or {}).get("truncated")


@pytest.mark.asyncio
async def test_continue_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CHAT_AUTO_CONTINUE_MAX", "0")
    m = _FakeModel([[("잘림", {"stop_reason": "max_tokens"})]])
    events, emit = _events()
    ai = await _stream_model(m, [], None, emit)
    assert len(m.calls) == 1
    assert (ai.response_metadata or {}).get("truncated") is True
