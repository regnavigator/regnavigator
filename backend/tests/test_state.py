"""state.merge_steps_by_id reducer 테스트.

spec: 02_INTERFACE.md §2 / I2 — 같은 id의 running → done 전이 안전.
"""

from __future__ import annotations


from src.steps import merge_steps_by_id


def test_empty_left_right_returns_empty():
    assert merge_steps_by_id([], []) == []


def test_append_new_step():
    left = []
    right = [{"id": "a", "ts": 1000, "label": "x", "status": "running"}]
    result = merge_steps_by_id(left, right)
    assert len(result) == 1
    assert result[0]["id"] == "a"
    assert result[0]["status"] == "running"


def test_merge_running_to_done_same_id():
    """같은 id의 두 번째 update가 첫 번째를 덮어씀 (label/ts는 보존)."""
    left = [{"id": "a", "ts": 1000, "label": "검색", "status": "running",
             "tool_name": "tavily_search"}]
    right = [{"id": "a", "status": "done", "ended_at": 1500,
              "output_preview": "5건"}]
    result = merge_steps_by_id(left, right)
    assert len(result) == 1
    s = result[0]
    assert s["status"] == "done"
    assert s["ended_at"] == 1500
    assert s["output_preview"] == "5건"
    # 원래 키 보존
    assert s["label"] == "검색"
    assert s["ts"] == 1000
    assert s["tool_name"] == "tavily_search"


def test_multiple_distinct_ids_sorted_by_ts():
    left = [
        {"id": "a", "ts": 2000, "status": "done"},
        {"id": "b", "ts": 1000, "status": "done"},
    ]
    result = merge_steps_by_id(left, [])
    assert [s["id"] for s in result] == ["b", "a"]


def test_merge_preserves_order_among_unchanged():
    left = [
        {"id": "a", "ts": 1000, "status": "done"},
        {"id": "b", "ts": 2000, "status": "running"},
    ]
    right = [{"id": "b", "ts": 2000, "status": "done"}]  # b만 update
    result = merge_steps_by_id(left, right)
    assert len(result) == 2
    by_id = {s["id"]: s for s in result}
    assert by_id["a"]["status"] == "done"
    assert by_id["b"]["status"] == "done"


def test_idempotent_double_update():
    """같은 update 두 번 적용해도 동일 결과."""
    left = [{"id": "a", "ts": 1000, "status": "running"}]
    update = [{"id": "a", "status": "done", "ended_at": 1500}]
    once = merge_steps_by_id(left, update)
    twice = merge_steps_by_id(once, update)
    assert once == twice


def test_lone_done_without_ts_no_keyerror():
    """RFC §6.1 회귀 — chat 도구가 start 없이 done 만 단독 발행(ts 없음).
    reducer 가 KeyError 없이 ended_at 으로 안전 정렬해야(프로덕션 크래시 방지).
    """
    # ts 없는 done(§6.1 chat 도구) + ts 없는 error — 정렬 시 ended_at fallback.
    steps = [
        {"id": "q1", "status": "done", "ended_at": 2000, "citations": []},
        {"id": "t1", "status": "error", "ended_at": 1000,
         "error_message": "x"},
    ]
    result = merge_steps_by_id([], steps)  # KeyError 나면 실패
    assert [s["id"] for s in result] == ["t1", "q1"]  # ended_at 오름차순


def test_mixed_ts_and_no_ts_sorted():
    """ts 있는 step(보고서 노드) + ts 없는 step(chat 도구) 혼재 정렬."""
    left = [{"id": "a", "ts": 1500, "status": "done"}]       # ts 보유
    right = [{"id": "b", "status": "done", "ended_at": 500}]  # ts 없음
    result = merge_steps_by_id(left, right)
    assert [s["id"] for s in result] == ["b", "a"]  # 500 < 1500


def test_left_keys_not_in_right_preserved():
    """뒤의 update에 없는 키도 좌측에서 그대로 살아남는다."""
    left = [{"id": "a", "ts": 1000, "label": "x", "tool_name": "t",
             "input_preview": "ip", "status": "running"}]
    right = [{"id": "a", "status": "done"}]
    result = merge_steps_by_id(left, right)
    s = result[0]
    assert s["label"] == "x"
    assert s["tool_name"] == "t"
    assert s["input_preview"] == "ip"
    assert s["status"] == "done"


def test_concurrent_start_and_done_in_same_call():
    """한 Command(update={'steps':[start, done]})로 두 dict 같이 보냄 (3_ARCHITECTURE §4.1)."""
    left = []
    right = [
        {"id": "a", "ts": 1000, "label": "x", "status": "running",
         "tool_name": "tavily_search"},
        {"id": "a", "status": "done", "ended_at": 1500, "output_preview": "ok"},
    ]
    result = merge_steps_by_id(left, right)
    assert len(result) == 1
    assert result[0]["status"] == "done"
    assert result[0]["label"] == "x"  # start의 label 살아있음
