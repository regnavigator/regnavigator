"""보고서 폴링 응답의 세부 진행(`progress`) — 2026-09-10.

왜 서버가 주는가: 종전엔 프런트가 5초마다 `GET /chat/{tid}/state` 로 **스레드
전체(메시지 포함)** 를 받아 report step 라벨 한 줄만 뽑아 썼다. 보고서는 5~40분
이라 폴링이 수백 회 돌고, 단일 워커(CLAUDE.md §7) 서버에 그대로 부하였다.
`/reports/runs/{key}` 가 이미 5초마다 불리므로 여기 실어 보내면 호출이 하나로 준다.
"""
from __future__ import annotations

from src.routes.reports import _REPORT_PHASES, _run_progress


class _Stub:
    def __init__(self, steps):
        self._steps = steps

    def get_state(self, _tid):
        class S:
            steps = self._steps
        return S()


def _patch(monkeypatch, steps):
    import src.persistence.threads_repo as tr
    monkeypatch.setattr(tr, "get_threads_repo", lambda: _Stub(steps))


def test_phase_is_last_report_step(monkeypatch):
    _patch(monkeypatch, [
        {"tool_name": "qdrant_search", "label": "검색", "status": "done"},
        {"tool_name": "report_decompose", "label": "쿼리 분해 중", "status": "done"},
        {"tool_name": "report_gather", "label": "자료 수집 중 · 웹 + 법령",
         "status": "running"},
    ])
    p = _run_progress("t_x")
    assert p == {"phase": 2, "total": len(_REPORT_PHASES),
                 "label": "자료 수집 중 · 웹 + 법령"}


def test_progress_message_surfaces_when_running(monkeypatch):
    """새벽 갱신 대기 등 — 멈춰 보이는 이유를 사용자에게 설명해야 한다."""
    _patch(monkeypatch, [
        {"tool_name": "report_gather", "label": "자료 수집 중", "status": "running",
         "progress_message": "새벽 데이터 갱신 중 — 끝나면 자동 재개됩니다"},
    ])
    p = _run_progress("t_x")
    assert p["message"] == "새벽 데이터 갱신 중 — 끝나면 자동 재개됩니다"
    assert p["phase"] == 2


def test_done_step_has_no_message(monkeypatch):
    _patch(monkeypatch, [
        {"tool_name": "report_writer", "label": "본문 작성 중", "status": "done",
         "progress_message": "이건 끝난 단계라 노출 안 함"},
    ])
    p = _run_progress("t_x")
    assert "message" not in p and p["phase"] == 3


def test_no_report_step_yet_returns_none(monkeypatch):
    """트리거 직후 몇 초 — 단계가 아직 없으면 표시할 게 없다(빈 라벨 금지)."""
    _patch(monkeypatch, [{"tool_name": "qdrant_search", "label": "검색"}])
    assert _run_progress("t_x") is None


def test_repo_failure_is_logged_not_swallowed_silently(monkeypatch, caplog):
    """조용히 None 만 돌려주면 진행 표시가 죽은 걸 아무도 모른다(CLAUDE.md §6)."""
    import src.persistence.threads_repo as tr

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(tr, "get_threads_repo", _boom)
    with caplog.at_level("WARNING"):
        assert _run_progress("t_x") is None
    assert any("진행 단계 조회 실패" in r.message for r in caplog.records)


def test_phases_match_runner_step_names():
    """`report_runner` 가 발행하는 tool_name 과 어긋나면 진행률이 조용히 멈춘다."""
    import pathlib
    src = pathlib.Path("src/report_runner.py").read_text(encoding="utf-8")
    for name, _ in _REPORT_PHASES:
        assert f'tool_name="{name}"' in src, f"{name} 을 runner 가 발행하지 않는다"
