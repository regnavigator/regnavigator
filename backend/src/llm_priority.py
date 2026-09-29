"""로컬 LLM 서버(공유 GPU) 우선순위 — 대화형 우선, 보고서 양보 (2026-08-28).

IRB/DRB 스킬 턴을 로컬 writer vLLM 으로 돌리면(skill_local) 백그라운드 보고서와
같은 GPU 를 나눠 쓴다. 정책: **대화형(즉답)이 우선, 보고서(5~40분 백그라운드)는
섹션 호출 사이에서 양보한다** — 진행 중 생성은 끊지 않고(vLLM continuous
batching), 다음 섹션 시작만 미룬다. 밀려도 몇 분 수준이라 체감이 없다.

구현은 카운터가 아니라 **최근 활동 타임스탬프**다: 대화형 경로가 로컬 모델을
부르기 직전·직후에 `touch()` 하고, 보고서는 최근 HOLD 초 안에 touch 가 있으면
대기한다. 카운터 방식은 예외 경로에서 감소를 빼먹으면 보고서가 영원히 굶는데
(finally 배선 실수 하나면 발생), 타임스탬프는 시간이 지나면 자연 해소된다.

프로세스 로컬 — 단일 인스턴스 강제(CLAUDE.md §7, single_instance)라 충분.
skill_local 미사용이면 touch 가 없어 모든 판정이 즉시 통과(오버헤드 0).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

_log = logging.getLogger(__name__)

_last_touch: float = 0.0  # monotonic. 0 = 대화형 활동 없음


def touch() -> None:
    """대화형 로컬 LLM 호출 직전·직후에 부른다."""
    global _last_touch
    _last_touch = time.monotonic()


def _hold_s() -> float:
    """touch 후 이 시간 동안 보고서가 양보한다(대화형 턴 하나가 이어질 여유)."""
    try:
        return float((os.getenv("REPORT_YIELD_HOLD_S") or "").strip() or "45")
    except ValueError:
        return 45.0


def _max_wait_s() -> float:
    """양보 상한 — 대화형이 연속 유입돼도 보고서가 무한정 굶지 않게."""
    try:
        return float((os.getenv("REPORT_YIELD_MAX_S") or "").strip() or "300")
    except ValueError:
        return 300.0


def interactive_recent() -> bool:
    return _last_touch > 0 and (time.monotonic() - _last_touch) < _hold_s()


async def report_yield(emit=None) -> float:
    """보고서 writer 호출 직전의 양보 지점. 기다린 초를 반환(관측용).

    emit: report_pipeline 의 `_emit_progress(kind, status, label)` 시그니처.
    """
    if not interactive_recent():
        return 0.0
    start = time.monotonic()
    if emit is not None:
        try:
            emit("report_writer", "queued", "대기 중 · 상담 응답 우선 처리")
        except Exception:  # noqa: BLE001 — 진행 표시 실패가 보고서를 막으면 안 됨
            pass
    max_wait = _max_wait_s()
    while interactive_recent():
        waited = time.monotonic() - start
        if waited >= max_wait:
            _log.info("report_yield: 상한 %.0fs 도달 — 보고서 재개", max_wait)
            break
        await asyncio.sleep(1.0)
    waited = time.monotonic() - start
    if waited > 1.0:
        _log.info("report_yield: 대화형 우선으로 %.1fs 양보", waited)
    return waited
