"""report_runs 멱등성 락 — SqliteReportRunsRepo 단위.

원자적 신규 획득 / 중복 차단 / completed·failed 비-reclaim(기존 반환) /
스테일 running reclaim / sweep_stale.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.persistence.report_runs_repo import SqliteReportRunsRepo


@pytest.fixture
def repo(tmp_path) -> SqliteReportRunsRepo:
    return SqliteReportRunsRepo(path=str(tmp_path / "rr.db"))


def _backdate(repo: SqliteReportRunsRepo, key: str, started_at_iso: str) -> None:
    """테스트 결정성 — started_at 을 과거로 직접 조작."""
    c = sqlite3.connect(repo.path)
    try:
        c.execute(
            "UPDATE report_runs SET started_at=? WHERE idempotency_key=?",
            (started_at_iso, key),
        )
        c.commit()
    finally:
        c.close()


def test_fresh_acquire(repo):
    ok, existing = repo.acquire(
        idempotency_key="rpt_a", thread_id="t1", user_id="u1")
    assert ok is True and existing is None
    run = repo.get("rpt_a")
    assert run is not None
    assert run.status == "running"
    assert run.thread_id == "t1" and run.user_id == "u1"


def test_duplicate_running_blocked(repo):
    repo.acquire(idempotency_key="rpt_b", thread_id="t1", user_id="u1")
    ok, existing = repo.acquire(
        idempotency_key="rpt_b", thread_id="t1", user_id="u1")
    assert ok is False
    assert existing is not None and existing.status == "running"


def test_completed_returns_existing_not_reclaimed(repo):
    repo.acquire(idempotency_key="rpt_c", thread_id="t1", user_id="u1")
    repo.finish("rpt_c", status="completed", report_id="rep_42")
    ok, existing = repo.acquire(
        idempotency_key="rpt_c", thread_id="t1", user_id="u1")
    assert ok is False
    assert existing is not None
    assert existing.status == "completed"
    assert existing.report_id == "rep_42"  # 캐시된 결과 그대로


def test_failed_returns_existing_not_reclaimed(repo):
    repo.acquire(idempotency_key="rpt_d", thread_id="t1", user_id="u1")
    repo.finish("rpt_d", status="failed", error="boom")
    ok, existing = repo.acquire(
        idempotency_key="rpt_d", thread_id="t1", user_id="u1")
    assert ok is False  # failed 는 자동 reclaim 안 함 (결정적)
    assert existing is not None and existing.status == "failed"
    assert existing.error == "boom"


def test_stale_running_reclaimed(repo):
    repo.acquire(idempotency_key="rpt_e", thread_id="t1", user_id="u1")
    # deadline+여유(400s) 훨씬 넘긴 죽은 running 으로 위조.
    _backdate(repo, "rpt_e", "2000-01-01T00:00:00.000000Z")
    ok, existing = repo.acquire(
        idempotency_key="rpt_e", thread_id="t1", user_id="u1")
    assert ok is True and existing is None  # reclaim 성공
    run = repo.get("rpt_e")
    assert run.status == "running"
    assert run.started_at > "2001"  # started_at 새로 갱신됨


def test_stale_threshold_respected(repo):
    """살아있는 running 은 reclaim 안 됨 (stale_after_s 경계)."""
    repo.acquire(idempotency_key="rpt_f", thread_id="t1", user_id="u1")
    ok, existing = repo.acquire(
        idempotency_key="rpt_f", thread_id="t1", user_id="u1",
        stale_after_s=400)
    assert ok is False and existing.status == "running"


def test_sweep_stale(repo):
    repo.acquire(idempotency_key="rpt_g", thread_id="t1", user_id="u1")
    repo.acquire(idempotency_key="rpt_h", thread_id="t1", user_id="u1")
    _backdate(repo, "rpt_g", "2000-01-01T00:00:00.000000Z")  # 죽음
    n = repo.sweep_stale(older_than_s=400)
    assert n == 1
    assert repo.get("rpt_g").status == "failed"
    assert repo.get("rpt_g").error == "stale"
    assert repo.get("rpt_h").status == "running"  # 살아있는 건 보존


def test_finish_idempotent_fields(repo):
    repo.acquire(idempotency_key="rpt_i", thread_id="t1", user_id="u1")
    repo.finish("rpt_i", status="completed", report_id="rep_1", run_id="run_1")
    run = repo.get("rpt_i")
    assert run.status == "completed"
    assert run.report_id == "rep_1" and run.run_id == "run_1"
    assert run.finished_at is not None


def test_finish_idempotent_no_op_when_not_running(repo):
    """노드 분할·sweep 경합 시 중복 finish 가 첫 결과를 덮어쓰지 않아야."""
    repo.acquire(idempotency_key="rpt_j", thread_id="t1", user_id="u1")
    repo.finish("rpt_j", status="completed", report_id="rep_first")
    # 두 번째 finish — 'completed' 상태이므로 WHERE status='running' 매칭 X
    repo.finish("rpt_j", status="failed", error="late writer 오류")
    run = repo.get("rpt_j")
    assert run.status == "completed"      # 그대로 보존
    assert run.report_id == "rep_first"   # 그대로 보존
    assert run.error is None              # 두 번째 호출의 error 무시


# ── 재시작 복원(2026-07-24): list_running / latest_running_for_thread ──
def test_list_running_only_running(repo):
    repo.acquire(idempotency_key="rpt_r1", thread_id="t1", user_id="u1")
    repo.acquire(idempotency_key="rpt_r2", thread_id="t2", user_id="u1")
    repo.finish("rpt_r2", status="completed")
    keys = [r.idempotency_key for r in repo.list_running()]
    assert keys == ["rpt_r1"]


def test_latest_running_for_thread(repo):
    repo.acquire(idempotency_key="rpt_old", thread_id="t1", user_id="u1")
    _backdate(repo, "rpt_old", "2020-01-01T00:00:00.000000Z")
    repo.acquire(idempotency_key="rpt_new", thread_id="t1", user_id="u1")
    run = repo.latest_running_for_thread("t1")
    assert run is not None and run.idempotency_key == "rpt_new"
    assert repo.latest_running_for_thread("t_none") is None


def test_latest_running_ignores_finished(repo):
    repo.acquire(idempotency_key="rpt_f", thread_id="t9", user_id="u1")
    repo.finish("rpt_f", status="failed", error="x")
    assert repo.latest_running_for_thread("t9") is None


def test_acquire_stale_zero_reclaims_any_running(repo):
    """resume_orphan_runs 경로 — stale_after_s=0 이면 running 잔재를 즉시 reclaim.

    (reclaim 조건이 started_at < now 라 같은 타임스탬프면 간헐 실패 — 1초
    backdate 로 결정화. 실제 복원 경로는 프로세스 재시작 후라 항상 과거.)
    """
    repo.acquire(idempotency_key="rpt_orphan", thread_id="t1", user_id="u1")
    _backdate(repo, "rpt_orphan", "2020-01-01T00:00:00.000000Z")
    ok, _ = repo.acquire(
        idempotency_key="rpt_orphan", thread_id="t1", user_id="u1",
        stale_after_s=0)
    assert ok is True


def test_acquire_stores_prompt_purpose(repo):
    """재설계(2026-07-24): 주제·목적을 run 에 저장 — 대화록 append 대체."""
    repo.acquire(idempotency_key="rpt_p1", thread_id="t1", user_id="u1",
                 prompt="의료기기 허가 보고서 만들어줘", purpose="license_strategy")
    r = repo.get("rpt_p1")
    assert r.prompt == "의료기기 허가 보고서 만들어줘"
    assert r.purpose == "license_strategy"


def test_stale_reclaim_preserves_prompt(repo):
    """복원 재기동(acquire stale_after_s=0, prompt=None)이 기존 주제를 보존."""
    repo.acquire(idempotency_key="rpt_p2", thread_id="t1", user_id="u1",
                 prompt="원래 주제", purpose="reg_summary")
    _backdate(repo, "rpt_p2", "2020-01-01T00:00:00.000000Z")  # started_at<now 결정화
    ok, _ = repo.acquire(idempotency_key="rpt_p2", thread_id="t1", user_id="u1",
                         stale_after_s=0)
    assert ok is True
    r = repo.get("rpt_p2")
    assert r.prompt == "원래 주제" and r.purpose == "reg_summary"
