"""보고서 잡 ↔ 채팅 턴 경합 belt 회귀 — 비차단 설계 유지하되 순서 튐 차단.

- is_report_running: thread 별 실행 중 잡 추적(진행 배지·컨텍스트 주입 신호).
- hold_turn_lock: 보고서 개요 append 를 채팅 턴 락과 상호배제(순서 보존).
"""

from __future__ import annotations

import asyncio


def test_is_report_running_reflects_active_index():
    import src.report_runner as rr

    assert rr.is_report_running("tX") is False
    rr._active_by_thread["tX"] = 1
    try:
        assert rr.is_report_running("tX") is True
    finally:
        rr._active_by_thread.pop("tX", None)
    assert rr.is_report_running("tX") is False


def test_report_append_serializes_with_chat_turn_lock():
    """채팅 턴이 락을 쥔 동안 보고서 개요 append 는 대기 → 순서 보존."""
    import src.chat_loop as cl

    order: list[str] = []

    async def scenario() -> None:
        chat_lock = cl._acquire_turn_lock("tL")
        async with chat_lock:  # 채팅 턴 진행 중
            async def reporter() -> None:
                async with cl.hold_turn_lock("tL"):  # 같은 thread 락 — 대기해야
                    order.append("report")

            t = asyncio.create_task(reporter())
            await asyncio.sleep(0.05)   # 보고서가 끼어들 기회
            order.append("chat")        # 채팅이 먼저 기록(락 보유 중)
        await t
        cl._release_turn_lock("tL")

    asyncio.run(scenario())
    assert order == ["chat", "report"]  # interleave 없음
