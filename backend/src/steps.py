"""Step 라이프사이클 헬퍼 — `step_start` / `step_done` / `step_error`.

spec: ../02_INTERFACE.md §2.1, ../03_ARCHITECTURE.md §4.1.

각 도구는 호출 직전·직후로 state.steps에 두 번 write — reducer가 id로 merge.

step shape 갱신 (2026-05-01~):
- `source_message_id`: 이 step을 트리거한 human message id (state.messages에서 추출).
  프런트가 step↔turn 매핑을 ts 휴리스틱 없이 정확히 할 수 있게.
- `turn_idx`: 같은 thread의 human 메시지 0-based 순번.
"""

from __future__ import annotations

import time
from typing import Any, Optional
from uuid import uuid4

from src.schemas import Citation, Step


def now_ms() -> int:
    """Unix epoch 밀리초 — `02_INTERFACE I11`."""
    return int(time.time() * 1000)


def new_step_id() -> str:
    return f"s_{uuid4().hex[:10]}"


def _msg_attr(m: Any, key: str):
    """BaseMessage 또는 dict 둘 다에서 key 추출."""
    v = getattr(m, key, None)
    if v is None and isinstance(m, dict):
        v = m.get(key)
    return v


def resolve_turn_context(
    state: Optional[dict],
) -> tuple[Optional[str], Optional[int]]:
    """state.messages에서 *가장 최근 human message*의 id + turn_idx 추출.

    프런트는 이 값으로 step↔turn 매핑을 ts 휴리스틱 없이 처리한다.

    Returns:
        (source_message_id, turn_idx)
        - source_message_id: 마지막 human message의 id (없으면 None)
        - turn_idx: 그 human message의 0-based 순번 (state.messages 안에서)
    """
    if not state:
        return None, None
    messages = state.get("messages") or []
    human_ids: list[Optional[str]] = []
    for m in messages:
        if _msg_attr(m, "type") == "human":
            human_ids.append(_msg_attr(m, "id"))
    if not human_ids:
        return None, None
    return human_ids[-1], len(human_ids) - 1


def step_start(
    label: str,
    *,
    tool_name: str,
    input_preview: Optional[str] = None,
    state: Optional[dict] = None,
    source_message_id: Optional[str] = None,
    turn_idx: Optional[int] = None,
) -> tuple[str, Step]:
    """단계 시작 dict 발행. 반환은 (step_id, Step).

    - `label` ≤ 70자, 사용자 향 한국어. 길면 input_preview로 분리.
    - `state`를 넘기면 `source_message_id`와 `turn_idx`를 자동 추출.
    - 명시적으로 `source_message_id` / `turn_idx`를 전달하면 그 값 우선.
    - `02_INTERFACE.md §2.1` Step shape 정합.
    """
    sid = new_step_id()
    payload: Step = {
        "id": sid,
        "ts": now_ms(),
        "label": label[:70],
        "status": "running",
        "tool_name": tool_name,
    }
    if input_preview:
        payload["input_preview"] = input_preview

    # turn 컨텍스트 — 명시 인자 > state에서 자동 추출
    if source_message_id is None and turn_idx is None and state is not None:
        source_message_id, turn_idx = resolve_turn_context(state)
    if source_message_id is not None:
        payload["source_message_id"] = source_message_id
    if turn_idx is not None:
        payload["turn_idx"] = turn_idx

    return sid, payload


def step_done(
    sid: str,
    *,
    output_preview: Optional[str] = None,
    citations: Optional[list[Citation]] = None,
    doc_kinds: Optional[list[str]] = None,
) -> Step:
    """단계 종료(success) merge dict — 같은 id로 update.

    `doc_kinds`: 이 검색이 지목한 종별 — 보고서가 채팅 맥락(근거 코퍼스)을
    이어받는 재료로 남긴다(2026-08-25).
    """
    payload: Step = {
        "id": sid,
        "status": "done",
        "ended_at": now_ms(),
    }
    if output_preview:
        payload["output_preview"] = output_preview[:80]
    if citations:
        payload["citations"] = citations
    if doc_kinds:
        payload["doc_kinds"] = list(doc_kinds)
    return payload


def step_error(sid: str, *, message: str) -> Step:
    """단계 종료(error) merge dict.

    `message`는 사용자 향 한국어 — raw exception 노출 금지(`06_SKILLS §4`).
    """
    return {
        "id": sid,
        "status": "error",
        "ended_at": now_ms(),
        "error_message": message,
    }


# ── state reducers (구 src/state.py 이관 — ADR-0001 Phase 5) ──────────────
def merge_steps_by_id(left: list[Step], right: list[Step]) -> list[Step]:
    """`steps` reducer — 같은 id 의 step 은 나중 게 필드 단위로 덮어씀(running→done).

    running 후 done 이 늦게 도착해도 안전 merge. 결과는 ts 오름차순
    (ts 없으면 ended_at, 둘 다 없으면 0).
    """
    by_id: dict[str, dict] = {s["id"]: dict(s) for s in left}
    for s in right:
        sid = s["id"]
        by_id[sid] = {**by_id.get(sid, {}), **s}
    return sorted(
        by_id.values(),
        key=lambda s: s.get("ts", s.get("ended_at", 0)),
    )


def keep_last_selection(left, right):
    """`selected_law_keys` reducer — 마지막 명시 값 유지(None=미변경, []=해제)."""
    return right if right is not None else left
