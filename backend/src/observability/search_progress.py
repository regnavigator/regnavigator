"""검색 도구 진행상황 emit — stream_mode="custom" 채널.

`src/tools/search.py` 에서 분리. 프런트 라이브 progress 표시용 이벤트를 발행한다.
graph/루프 context 밖(테스트·CLI)에서 호출되면 silently no-op — 저장소 write 가
아니라 순수 스트림 이벤트다.

발행 경로 2개 (ADR-0001 Phase 1):
1. **progress sink** (contextvar) — 자체 `/chat` 루프(`src/chat_loop.py`)가 턴 시작 시
   `set_progress_sink()` 로 설치. `asyncio.to_thread` 는 contextvars 를 복사하므로
   워커 스레드에서 실행되는 도구 코어의 emit 도 sink 로 흐른다.
2. **langgraph stream writer** — sink 미설치 시 기존 동작(graph run 내부).
   langgraph 은퇴(Phase 5) 시 이 폴백만 지우면 된다.
"""

from __future__ import annotations

import contextvars
from typing import Callable, Optional

# 사용자 향 진행 이벤트 sink — /chat 루프가 턴 스코프로 설치.
_PROGRESS_SINK: contextvars.ContextVar[Optional[Callable[[dict], None]]] = (
    contextvars.ContextVar("progress_sink", default=None)
)


def set_progress_sink(sink: Callable[[dict], None]) -> contextvars.Token:
    """현재 컨텍스트에 진행 이벤트 sink 설치. 반환 token 으로 reset."""
    return _PROGRESS_SINK.set(sink)


def reset_progress_sink(token: contextvars.Token) -> None:
    _PROGRESS_SINK.reset(token)


def _write(payload: dict) -> None:
    """sink 로 발행 — 미설치(테스트·CLI·백그라운드 잡)면 no-op.

    ADR-0001 Phase 5: langgraph stream writer 폴백 제거 — sink 단일화.
    """
    sink = _PROGRESS_SINK.get()
    if sink is None:
        return
    try:
        sink(payload)
    except Exception:
        pass  # 이벤트 발행 실패가 도구 실행을 막으면 안 됨


def _emit_progress(tool: str, phase: str, message: str) -> None:
    """도구 실행 중 진행 상황 emit (type=tool_progress).

    프런트가 streamMode "custom"(langgraph) 또는 /chat SSE 로 받아 라이브 표시.
    """
    _write({
        "type": "tool_progress",
        "tool": tool,
        "phase": phase,
        "message": message,
    })


def _emit_step_lifecycle(phase: str, step: dict) -> None:
    """tool 진입 시 start step 을 custom 채널로 박아 FE 가 즉시 임시 step
    생성하게(RFC §6.1 대안 B). state.steps 는 done 만 발행 → reducer 가
    같은 id 로 merge.
    """
    _write({
        "type": "step_lifecycle",
        "phase": phase,
        "step": step,
    })


def _emit_result(
    tool: str,
    *,
    index: int,
    title: str,
    subtitle: str = "",
    url: str = "",
) -> None:
    """검색 결과 *각 건*을 phase="result" 이벤트로 emit (frontend 라이브 표시용).

    payload:
      type="tool_progress", tool, phase="result",
      index, title, subtitle, url, message (기본 표시 텍스트)
    """
    msg = f"[{index}] {title}" + (f" — {subtitle}" if subtitle else "")
    _write({
        "type": "tool_progress",
        "tool": tool,
        "phase": "result",
        "index": index,
        "title": title,
        "subtitle": subtitle,
        "url": url,
        "message": msg,
    })
