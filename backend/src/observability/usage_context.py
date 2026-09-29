"""LLM 사용량 귀속 컨텍스트 — 호출부가 잊어도 새지 않게 하는 축.

배경(2026-08-05 실측): `events.llm_call` 119건 중 58건(36만 토큰, 15%)이
`user_id` NULL 로 쌓이고 있었고, 그 위에 **아예 이벤트가 안 남는** 호출이 셋 더
있었다(coverage 판정·auto-title·대화 압축 요약). 원인은 전부 같다 — 귀속과 계측이
**호출부의 책임**이라, 새 호출부를 추가할 때마다 잊으면 조용히 샜다. 이미 세 번
잊었다.

그래서 호출부를 하나씩 고치는 대신 축을 옮긴다:

  ① 귀속 — 요청/잡 **진입점**에서 한 번 심고(`bind`), 로거가 폴백으로 읽는다.
  ② 계측 — `build_chat_model()` 이 항상 로거를 달아 내보낸다(src/models.py).

ADR-0001 로 langgraph 를 걷어낸 뒤 `ensure_config()` 는 항상 빈 값이므로, 실질적
으로 이 모듈이 유일한 신뢰 귀속 경로다.

contextvar 는 **태스크 생성 시점에 복사**된다 — `bind()` 이후에 만든
`asyncio.create_task`·`to_thread` 는 값을 물려받고, 그 안에서의 변경은 밖으로
새지 않는다. 요청 단위 격리가 공짜로 따라온다.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Iterator, Optional

_user_id: ContextVar[Optional[str]] = ContextVar("usage_user_id", default=None)
_thread_id: ContextVar[Optional[str]] = ContextVar("usage_thread_id", default=None)
_run_id: ContextVar[Optional[str]] = ContextVar("usage_run_id", default=None)

# 실사용자가 아닌 값 — 집계·쿼터를 오염시키므로 심지 않는다.
_NOT_A_USER = ("", "anonymous", "none", "null")


def _clean(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in _NOT_A_USER else s


def bind(*, user_id=None, thread_id=None, run_id=None) -> None:
    """현 컨텍스트에 귀속 정보를 심는다. None 인 항목은 **건드리지 않는다**.

    부분 갱신을 허용하는 이유: 미들웨어가 user 를 심고, 이후 채팅 루프가 thread 를
    덧붙이는 식으로 진입점이 나뉘기 때문이다.
    """
    if (u := _clean(user_id)) is not None:
        _user_id.set(u)
    if (t := _clean(thread_id)) is not None:
        _thread_id.set(t)
    if (r := _clean(run_id)) is not None:
        _run_id.set(r)


def current() -> dict:
    """로거가 읽는 스냅샷 — {user_id, thread_id, run_id} (없으면 None)."""
    return {
        "user_id": _user_id.get(),
        "thread_id": _thread_id.get(),
        "run_id": _run_id.get(),
    }


@contextlib.contextmanager
def scope(*, user_id=None, thread_id=None, run_id=None) -> Iterator[None]:
    """블록 안에서만 귀속을 바꾸고 나갈 때 원복 — 백그라운드 잡·테스트용."""
    tokens = [
        _user_id.set(_clean(user_id) if user_id is not None else _user_id.get()),
        _thread_id.set(_clean(thread_id) if thread_id is not None else _thread_id.get()),
        _run_id.set(_clean(run_id) if run_id is not None else _run_id.get()),
    ]
    try:
        yield
    finally:
        _user_id.reset(tokens[0])
        _thread_id.reset(tokens[1])
        _run_id.reset(tokens[2])


def clear() -> None:
    """테스트용 초기화."""
    _user_id.set(None)
    _thread_id.set(None)
    _run_id.set(None)
