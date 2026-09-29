"""/chat SSE 하트비트 — 무이벤트 구간에 ping 이 흘러 FE 60s 타임아웃을 막는다.

(실측 2026-07-24: 느린 검색/첫 토큰 대기 중 이벤트 공백 → FE
StreamInactivityTimeoutError "streamchunk timeout" 반복.)
"""
from __future__ import annotations

import asyncio


def test_chat_sse_heartbeat_fills_silence(monkeypatch):
    monkeypatch.setenv("CHAT_SSE_HEARTBEAT_S", "0.05")

    async def _slow_turn(thread_id, message, **kw):
        yield {"type": "meta", "human_message_id": "m1"}
        await asyncio.sleep(0.25)  # 무이벤트 구간 — ping 이 채워야 함
        yield {"type": "done", "thread_id": thread_id, "text": "답"}

    import src.chat_loop as CL
    monkeypatch.setattr(CL, "run_chat_turn", _slow_turn)

    from fastapi.testclient import TestClient

    from src.api import app

    c = TestClient(app)
    with c.stream("POST", "/chat",
                  json={"message": "안녕", "thread_id": "t_hb_test"}) as r:
        body = "".join(r.iter_text())
    assert "event: ping" in body
    assert '"type": "ping"' in body
    # 이벤트 순서 보존: meta → (ping…) → done
    assert body.index("event: meta") < body.index("event: ping")
    assert body.index("event: ping") < body.index("event: done")


def test_chat_sse_no_ping_when_fast(monkeypatch):
    """이벤트가 촘촘하면 ping 없음 — 불필요한 프레임 미발생."""
    monkeypatch.setenv("CHAT_SSE_HEARTBEAT_S", "5")

    async def _fast_turn(thread_id, message, **kw):
        yield {"type": "meta", "human_message_id": "m1"}
        yield {"type": "done", "thread_id": thread_id, "text": "답"}

    import src.chat_loop as CL
    monkeypatch.setattr(CL, "run_chat_turn", _fast_turn)

    from fastapi.testclient import TestClient

    from src.api import app

    c = TestClient(app)
    with c.stream("POST", "/chat",
                  json={"message": "안녕", "thread_id": "t_hb_fast"}) as r:
        body = "".join(r.iter_text())
    assert "event: ping" not in body
    assert "event: done" in body
