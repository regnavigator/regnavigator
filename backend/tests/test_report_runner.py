"""자체 보고서 잡러너(src/report_runner.py) 단위 테스트 — ADR-0001 Phase 3.

파이프라인 코어(decompose/gather/synthesize)는 monkeypatch — 러너의 오케스트
레이션 의미론만 검증:
- 성공 경로: 멱등락 completed 마감 + steps 3쌍 + 개요 AIMessage append
- 수집 빈손: failed 마감 + error step + writer 미호출
- writer 예외: failed 마감(락 누수 0)
- 쿼터 경로 판정: POST /reports 만 검사
"""

from __future__ import annotations

import asyncio

import pytest

from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture()
def repos(tmp_path, monkeypatch):
    """threads_repo + report_runs_repo 를 테스트 스코프 SQLite 로."""
    import src.persistence as P
    import src.persistence.threads_repo as tr

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "rr.db"))
    monkeypatch.setattr(tr, "_repo", None)
    P.get_report_runs_repo.cache_clear()
    yield tr.get_threads_repo(), P.get_report_runs_repo()
    monkeypatch.setattr(tr, "_repo", None)
    P.get_report_runs_repo.cache_clear()


def _seed_thread(threads, tid="th1"):
    threads.ensure_thread(tid, user_id="u1")
    threads.append_messages(tid, [
        HumanMessage(content="SaMD 임상 요건 보고서로 정리해줘", id="m1"),
        AIMessage(content="임상 요건은 다음과 같습니다...", id="m2"),
    ])


def _run(idem="rpt_test1", tid="th1", email=None):
    from src.report_runner import _run_report_job

    asyncio.run(_run_report_job(
        thread_id=tid, user_id="u1", idempotency_key=idem, user_email=email,
    ))


def test_success_path(repos, monkeypatch):
    threads, runs = repos
    _seed_thread(threads)
    runs.acquire(idempotency_key="rpt_ok", thread_id="th1", user_id="u1")

    import src.report_pipeline as RP

    async def fake_decompose(q, ctx, **kw):
        return ["쿼리1", "쿼리2"]

    async def fake_gather(queries, **kw):
        # 근거 충분성 게이트(REPORT_MIN_CITATIONS=6) 통과할 만큼.
        return {"web": [{"u": i} for i in range(3)],
                "rag": [{"a": i} for i in range(4)],
                "web_ok": True, "rag_ok": True}

    async def fake_synth(payload, state, config, **kw):
        assert config["configurable"]["thread_id"] == "th1"
        return ("rep_1", "## 개요\n핵심 결론입니다", [{"id": "c1", "number": 1}])

    monkeypatch.setattr(RP, "decompose_queries", fake_decompose)
    monkeypatch.setattr(RP, "gather_for_report", fake_gather)
    monkeypatch.setattr(RP, "synthesize_and_persist", fake_synth)

    _run(idem="rpt_ok")

    run = runs.get("rpt_ok")
    assert run.status == "completed" and run.report_id == "rep_1"

    st = threads.get_state("th1")
    done = [s for s in st.steps if s.get("status") == "done"]
    assert {s["tool_name"] for s in done} == {
        "report_decompose", "report_gather", "report_writer"}
    writer_step = [s for s in done if s["tool_name"] == "report_writer"][0]
    assert writer_step["citations"] == [{"id": "c1", "number": 1}]

    # ── 채팅↔보고서 완전 분리(2026-07-25) ──────────────────────────
    # 개요를 채팅 메시지로 append 하지 않는다 — 대화록에 보고서 흔적 없음.
    # (구 계약은 kind:"report_overview" AI 메시지를 붙였다.)
    assert not any(
        (getattr(m, "additional_kwargs", {}) or {}).get("kind")
        == "report_overview"
        for m in st.messages
    ), "보고서 개요가 채팅 대화록에 새고 있음"
    assert "핵심 결론" not in "".join(
        str(getattr(m, "content", "")) for m in st.messages)
    # report_* step 은 **채팅 턴에 바인딩되지 않는다** — 프런트가 채팅 턴의
    # step 목록에 보고서 진행을 끼워 넣던 누수 차단(source_message_id 없음).
    for s in st.steps:
        if (s.get("tool_name") or "").startswith("report_"):
            assert s.get("source_message_id") is None, s
            assert s.get("turn_idx") is None, s


def test_gather_empty_fails_without_writer(repos, monkeypatch):
    threads, runs = repos
    _seed_thread(threads, tid="th2")
    runs.acquire(idempotency_key="rpt_empty", thread_id="th2", user_id="u1")

    import src.report_pipeline as RP

    async def fake_decompose(q, ctx, **kw):
        return ["쿼리1"]

    async def fake_gather(queries, **kw):
        return {"web": [], "rag": [], "web_ok": False, "rag_ok": False}

    writer_called = []

    async def fake_synth(*a, **kw):
        writer_called.append(1)

    monkeypatch.setattr(RP, "decompose_queries", fake_decompose)
    monkeypatch.setattr(RP, "gather_for_report", fake_gather)
    monkeypatch.setattr(RP, "synthesize_and_persist", fake_synth)

    _run(idem="rpt_empty", tid="th2")

    run = runs.get("rpt_empty")
    assert run.status == "failed" and "수집 실패" in (run.error or "")
    assert not writer_called
    st = threads.get_state("th2")
    errs = [s for s in st.steps if s.get("status") == "error"]
    assert errs and errs[0]["tool_name"] == "report_gather"


def test_writer_crash_finishes_failed(repos, monkeypatch):
    threads, runs = repos
    _seed_thread(threads, tid="th3")
    runs.acquire(idempotency_key="rpt_crash", thread_id="th3", user_id="u1")

    import src.report_pipeline as RP

    async def fake_decompose(q, ctx, **kw):
        return ["쿼리1"]

    async def fake_gather(queries, **kw):
        return {"web": [{"u": i} for i in range(6)], "rag": [],
                "web_ok": True, "rag_ok": False}

    async def fake_synth(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(RP, "decompose_queries", fake_decompose)
    monkeypatch.setattr(RP, "gather_for_report", fake_gather)
    monkeypatch.setattr(RP, "synthesize_and_persist", fake_synth)

    _run(idem="rpt_crash", tid="th3")

    run = runs.get("rpt_crash")
    assert run.status == "failed" and "writer 오류" in (run.error or "")


def test_thin_evidence_retries_then_fails_without_writer(repos, monkeypatch):
    """근거 부족(min 미달) → 1회 재수집 → 여전히 부족이면 writer 안 돌리고 실패.

    실측 사고(2026-07-25): 검색 간헐 실패 + 웹 쿼터 사망이 겹친 턴에서 근거
    2건으로 종전 가드("1건이라도 있으면 통과")를 통과해 3.9k자 보고서가
    '완료'로 배달됨. 같은 주제 채팅 누적 답변은 19k자였다."""
    threads, runs = repos
    _seed_thread(threads, tid="th4")
    runs.acquire(idempotency_key="rpt_thin", thread_id="th4", user_id="u1")

    import src.report_pipeline as RP

    async def fake_decompose(q, ctx, **kw):
        return ["쿼리1"]

    gather_calls = []

    async def fake_gather(queries, **kw):
        gather_calls.append(1)
        return {"web": [{"u": 1}], "rag": [{"a": 1}],  # 2건 — min 6 미달
                "web_ok": True, "rag_ok": True}

    writer_called = []

    async def fake_synth(*a, **kw):
        writer_called.append(1)

    monkeypatch.setattr(RP, "decompose_queries", fake_decompose)
    monkeypatch.setattr(RP, "gather_for_report", fake_gather)
    monkeypatch.setattr(RP, "synthesize_and_persist", fake_synth)

    _run(idem="rpt_thin", tid="th4")

    assert len(gather_calls) == 2          # 1회 재수집 시도
    assert not writer_called               # 얇은 보고서 생성 안 함
    run = runs.get("rpt_thin")
    assert run.status == "failed" and "근거 부족" in (run.error or "")
    st = threads.get_state("th4")
    errs = [s for s in st.steps if s.get("status") == "error"]
    assert errs and "근거가 2건뿐" in errs[0]["error_message"]


def test_thin_evidence_retry_recovers(repos, monkeypatch):
    """재수집에서 근거가 채워지면 그대로 보고서 작성 진행(일시 실패 회복)."""
    threads, runs = repos
    _seed_thread(threads, tid="th5")
    runs.acquire(idempotency_key="rpt_recover", thread_id="th5", user_id="u1")

    import src.report_pipeline as RP

    async def fake_decompose(q, ctx, **kw):
        return ["쿼리1"]

    calls = []

    async def fake_gather(queries, **kw):
        calls.append(1)
        if len(calls) == 1:                # 1차: 검색 흔들림 → 2건
            return {"web": [{"u": 1}], "rag": [{"a": 1}],
                    "web_ok": True, "rag_ok": True}
        return {"web": [{"u": i} for i in range(4)],   # 2차: 회복 → 9건
                "rag": [{"a": i} for i in range(5)],
                "web_ok": True, "rag_ok": True}

    synth_payloads = []

    async def fake_synth(payload, state, config, **kw):
        synth_payloads.append(payload)
        return ("rep_r", "## 개요\n회복됨", [{"id": "c1", "number": 1}])

    monkeypatch.setattr(RP, "decompose_queries", fake_decompose)
    monkeypatch.setattr(RP, "gather_for_report", fake_gather)
    monkeypatch.setattr(RP, "synthesize_and_persist", fake_synth)

    _run(idem="rpt_recover", tid="th5")

    assert len(calls) == 2
    run = runs.get("rpt_recover")
    assert run.status == "completed" and run.report_id == "rep_r"
    # writer 는 **재수집분**(9건)을 받아야 한다 — 1차 얇은 결과가 아니라.
    p = synth_payloads[0]
    assert len(p["web_results"]) + len(p["rag_results"]) == 9


def test_quota_path_reports_post_only():
    from src.middleware.quota import _is_quota_path

    assert _is_quota_path("/reports", "POST") is True
    assert _is_quota_path("/reports", "GET") is False
    assert _is_quota_path("/reports/abc", "GET") is False
    assert _is_quota_path("/reports/abc/download", "GET") is False
    assert _is_quota_path("/chat", "POST") is True
