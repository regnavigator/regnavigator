"""심층보고서 진입 허들(src/routes/reports.py:_assert_report_ready) 단위 테스트.

빈/인사/서비스소개만 오간 thread 에서 5~12분 27B 잡이 뜨던 사고 차단(2026-07-21).
통과 조건: ① 실질 주제 + ② 누적 citation ≥1(=실제 규제 상담 근거).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture()
def threads(tmp_path, monkeypatch):
    import src.persistence.threads_repo as tr

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "gate.db"))
    monkeypatch.setattr(tr, "_repo", None)
    yield tr.get_threads_repo()
    monkeypatch.setattr(tr, "_repo", None)


def _ready(tid, prompt=None):
    from src.routes.reports import _assert_report_ready

    _assert_report_ready(tid, prompt)


def _seed(threads, tid, msgs, *, with_citation=False):
    threads.ensure_thread(tid, user_id="u1")
    threads.append_messages(tid, msgs)
    if with_citation:
        threads.merge_steps(tid, [{
            "id": "s1", "tool_name": "qdrant_search", "status": "done",
            "citations": [{"id": "c1", "number": 1, "title": "의료기기법 제6조"}],
        }])


def test_empty_thread_blocked(threads):
    threads.ensure_thread("t_empty", user_id="u1")
    with pytest.raises(HTTPException) as ei:
        _ready("t_empty")
    assert ei.value.status_code == 422
    assert "주제" in ei.value.detail


def test_greeting_only_blocked(threads):
    _seed(threads, "t_hi", [
        HumanMessage(content="안녕하세요", id="m1"),
        AIMessage(content="안녕하세요! 무엇을 도와드릴까요?", id="m2"),
    ])
    with pytest.raises(HTTPException) as ei:
        _ready("t_hi")
    assert ei.value.status_code == 422


def test_service_intro_no_citation_blocked(threads):
    """실제 재현 사례 — 서비스 소개/사용법 안내만. 주제는 그럴듯하나 citation 0."""
    _seed(threads, "t_intro", [
        HumanMessage(content="이 서비스 어떻게 쓰나요?", id="m1"),
        AIMessage(content="규제 검색·인허가 상담·보고서 생성을 지원합니다...", id="m2"),
        HumanMessage(content="지금까지의 대화 내용을 종합하여 심층 보고서를 작성해주세요.", id="m3"),
    ])  # with_citation=False
    with pytest.raises(HTTPException) as ei:
        _ready("t_intro")
    assert ei.value.status_code == 422
    assert "상담 근거" in ei.value.detail


def test_real_consultation_passes(threads):
    _seed(threads, "t_ok", [
        HumanMessage(content="SaMD 임상시험 요건을 정리해줘", id="m1"),
        AIMessage(content="임상 요건은 다음과 같습니다 [1]...", id="m2"),
    ], with_citation=True)
    _ready("t_ok")  # 예외 없으면 통과


def test_short_prompt_blocked_even_with_citations(threads):
    _seed(threads, "t_short", [
        HumanMessage(content="의료기기 허가 절차 알려줘", id="m1"),
        AIMessage(content="절차는 [1]...", id="m2"),
    ], with_citation=True)
    with pytest.raises(HTTPException) as ei:
        _ready("t_short", prompt="요약")  # 알맹이 없는 트리거 문구
    assert ei.value.status_code == 422


def test_substantive_prompt_with_citations_passes(threads):
    _seed(threads, "t_prompt", [
        HumanMessage(content="의료기기 허가 절차 알려줘", id="m1"),
        AIMessage(content="절차는 [1]...", id="m2"),
    ], with_citation=True)
    _ready("t_prompt", prompt="허가 절차 전반을 심층 보고서로 정리해줘")
