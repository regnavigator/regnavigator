"""보고서 중단(2026-09-02) — [중단] 버튼 + 대화 중단 발화 안내.

원칙: 트리거와 대칭 — 파괴적 행동(중단)은 자유 텍스트로 실행하지 않는다.
채팅 발화는 안내만, 실제 중단은 명시 버튼(취소 API)만.
"""
from __future__ import annotations

import asyncio

import pytest


def _clear_persistence_caches():
    from src import persistence as P

    for f in (P.get_users_repo, P.get_events_repo, P.get_reports_repo,
              P.get_feedback_repo, P.get_report_runs_repo, P.get_blob_store):
        f.cache_clear()


@pytest.fixture()
def repos(tmp_path, monkeypatch):
    import src.persistence.threads_repo as tr

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setattr(tr, "_repo", None)
    _clear_persistence_caches()
    yield
    monkeypatch.setattr(tr, "_repo", None)
    _clear_persistence_caches()


# ── cancel_run ────────────────────────────────────────────────────────────

def test_cancel_run_cancels_inflight_task_and_marks_db(repos):
    """이 프로세스의 진행 태스크 → cancel + DB cancelled 마감(핸들러)."""
    from src import report_runner as rr
    from src.persistence import get_report_runs_repo

    runs = get_report_runs_repo()
    runs.acquire(idempotency_key="rpt_c1", thread_id="t_x", user_id="u1")

    async def main():
        started = asyncio.Event()

        async def fake_job():
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                runs.finish("rpt_c1", status="cancelled", error=None)
                return

        task = asyncio.create_task(fake_job())
        rr._active_jobs["rpt_c1"] = task
        await started.wait()
        assert rr.cancel_run("rpt_c1") is True
        await asyncio.wait_for(task, 5)
        rr._active_jobs.pop("rpt_c1", None)

    asyncio.run(main())
    assert runs.get("rpt_c1").status == "cancelled"


def _run_real_job_then_cancel(monkeypatch, idem, *, via_button):
    """실제 _run_report_job 을 decompose 단계에서 멈춰 두고 취소한다."""
    from src import report_pipeline as rp
    from src import report_runner as rr
    from src.persistence import get_report_runs_repo

    get_report_runs_repo().acquire(idempotency_key=idem, thread_id="t_x", user_id="u1")

    async def main():
        started = asyncio.Event()

        async def hang(*_a, **_k):
            started.set()
            await asyncio.sleep(60)

        monkeypatch.setattr(rp, "decompose_and_classify", hang)
        task = rr.spawn_report_job(thread_id="t_x", user_id="u1", idempotency_key=idem)
        await asyncio.wait_for(started.wait(), 5)
        if via_button:
            assert rr.cancel_run(idem) is True
        else:
            task.cancel()  # 프로세스 종료 시 이벤트 루프가 하는 취소와 동일
        try:
            await asyncio.wait_for(task, 5)
        except asyncio.CancelledError:
            pass
        assert idem not in rr._user_cancelled

    asyncio.run(main())
    return get_report_runs_repo().get(idem)


def test_real_job_button_cancel_marks_cancelled(repos, monkeypatch):
    assert _run_real_job_then_cancel(monkeypatch, "rpt_b1", via_button=True).status == "cancelled"


def test_real_job_shutdown_cancel_stays_running_for_resume(repos, monkeypatch):
    """배포 재시작 취소는 cancelled 로 마감하지 않는다 — orphan 재기동 대상 유지.

    2026-09-15 사고: 23분 진행 보고서가 배포와 겹쳐 cancelled 로 마감돼 복원 안 됨.
    """
    from src.persistence import get_report_runs_repo

    run = _run_real_job_then_cancel(monkeypatch, "rpt_b2", via_button=False)
    assert run.status == "running"
    assert any(r.idempotency_key == "rpt_b2" for r in get_report_runs_repo().list_running())


def test_cancel_run_db_only_when_no_task(repos):
    """태스크가 없는 running(재시작 직후) — DB 만 마감해 orphan 재기동 차단."""
    from src.report_runner import cancel_run
    from src.persistence import get_report_runs_repo

    runs = get_report_runs_repo()
    runs.acquire(idempotency_key="rpt_c2", thread_id="t_x", user_id="u1")
    assert cancel_run("rpt_c2") is True
    assert runs.get("rpt_c2").status == "cancelled"
    # cancelled 는 orphan 재기동 목록(list_running)에 안 나온다.
    assert all(r.idempotency_key != "rpt_c2" for r in runs.list_running())


def test_cancel_run_noop_when_finished(repos):
    from src.report_runner import cancel_run
    from src.persistence import get_report_runs_repo

    runs = get_report_runs_repo()
    runs.acquire(idempotency_key="rpt_c3", thread_id="t_x", user_id="u1")
    runs.finish("rpt_c3", status="completed", report_id="rep_1")
    assert cancel_run("rpt_c3") is False


# ── 대화 중단 발화 → 결정적 안내(LLM 무호출) ─────────────────────────────

def test_chat_cancel_intent_regex():
    from src.chat_loop import _CANCEL_INTENT_RE as R

    assert R.search("보고서 중단해줘")
    assert R.search("리포트 그만 만들어")
    assert R.search("지금 만드는 보고서 취소")
    assert R.search("취소해줘 보고서")
    assert not R.search("보고서 언제 완료돼?")
    assert not R.search("중단 없이 계속 진행해줘")


def test_chat_cancel_intent_guides_to_button(repos, monkeypatch, tmp_path):
    """진행 중 run 이 있으면 LLM 없이 [중단] 버튼 안내로 턴 종료."""
    import src.persistence.threads_repo as tr
    from src.persistence import get_report_runs_repo
    from src.chat_loop import run_chat_turn

    monkeypatch.setenv("CHAT_GROUNDING_GATE_DISABLE", "1")
    monkeypatch.delenv("PII_NER_API_URL", raising=False)
    monkeypatch.setenv("INTENT_SEARCH_DISABLE", "1")
    monkeypatch.delenv("SKILL_BUNDLE_DIR", raising=False)
    get_report_runs_repo().acquire(idempotency_key="rpt_c4", thread_id="t_cancel1", user_id="u@x")

    async def _run():
        return [ev async for ev in run_chat_turn(
            "t_cancel1", "보고서 중단해줘", user_id="u@x")]

    events = asyncio.run(_run())
    done = events[-1]
    assert done["type"] == "done"
    assert "[중단] 버튼" in done["text"]
    # run 은 그대로 running — 대화가 중단을 실행하지 않았다.
    assert get_report_runs_repo().get("rpt_c4").status == "running"
