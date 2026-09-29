"""_carryover_citation_step — 이전 턴 근거 재인용 carry-over 검증.

무검색·부분검색 턴에서 답변이 이전 턴 citation 을 [n] 로 재인용하면, 그 citation
(스레드-안정 번호 그대로)을 이번 턴 step 으로 이어붙여 각주·grounding 이 붙게 한다.

핵심 불변식:
- 무결: 기존 citation 만 이어붙임(새 출처 생성 X), 이번 턴 커버 번호는 중복 제외.
- 정확: body 에 없는/pool 에 없는 [n] 은 무시(날조 0), escape \\[n\\] 제외.
- 정합: 번호 재배정 없음, 현재 턴 source_message_id/turn_idx 로 매핑.
"""

from types import SimpleNamespace

from src.chat_loop import _carryover_citation_step

_MSGS = [
    {"type": "human", "id": "h1"},
    {"type": "ai", "id": "a1"},
    {"type": "human", "id": "h2"},  # 현재 턴
]
_PRIOR = [
    {
        "id": "s1",
        "source_message_id": "h1",
        "turn_idx": 0,
        "citations": [{"id": "cite_doc_A", "number": 1, "title": "법1"}],
    }
]


def _state(steps=None, messages=None):
    return SimpleNamespace(
        steps=_PRIOR if steps is None else steps,
        messages=_MSGS if messages is None else messages,
    )


def test_reuse_prior_citation_carried():
    """이전 턴 [1] 재인용 → 같은 출처·번호로 이번 턴 step, 현재 턴 매핑."""
    step = _carryover_citation_step(_state(), [], "앞서 본 [1] 근거로 답합니다.")
    assert step is not None
    assert step["citations"][0]["id"] == "cite_doc_A"
    assert step["citations"][0]["number"] == 1  # 번호 재배정 없음
    assert step["source_message_id"] == "h2"      # 현재 턴
    assert step["turn_idx"] == 1
    assert step["label"] == "이전 근거 재인용"
    assert "tool_name" not in step                # 기술명 노출 안 함


def test_unknown_number_ignored():
    """pool 에 없는 [5] → 날조 금지 → None."""
    assert _carryover_citation_step(_state(), [], "새 주장 [5].") is None


def test_covered_this_turn_excluded():
    """이번 턴이 이미 [1] 을 검색으로 확보 → 중복 제외 → None."""
    turn_steps = [{"id": "s2", "citations": [{"id": "cite_doc_A", "number": 1}]}]
    assert _carryover_citation_step(_state(), turn_steps, "[1]") is None


def test_no_marker():
    """[n] 없는 답변 → None(출처 없는 답은 그대로 무출처)."""
    assert _carryover_citation_step(_state(), [], "출처 없는 답변.") is None


def test_escaped_marker_ignored():
    r"""escape \[1\] 는 인용 마커가 아님 → None."""
    assert _carryover_citation_step(_state(), [], r"코드 예시 \[1\] 리터럴") is None


def test_mixed_only_pool_numbers():
    """여러 [n] 중 pool 에 있는 것만 carry, 없는 번호는 무시."""
    prior2 = _PRIOR + [
        {"id": "s0", "citations": [{"id": "cite_doc_B", "number": 2, "title": "법2"}]}
    ]
    step = _carryover_citation_step(
        _state(steps=prior2), [], "[1] 과 [2] 는 근거, [9] 는 없음"
    )
    assert step is not None
    assert {c["number"] for c in step["citations"]} == {1, 2}


def test_partial_search_carries_older_ref():
    """이번 턴 새 검색([3])을 하면서 이전 [1] 도 재인용 → [1] 만 carry(3은 이번 턴)."""
    turn_steps = [{"id": "s3", "citations": [{"id": "cite_doc_C", "number": 3}]}]
    step = _carryover_citation_step(
        _state(), turn_steps, "새로 찾은 [3] 과 앞서 본 [1]"
    )
    assert step is not None
    assert {c["number"] for c in step["citations"]} == {1}
