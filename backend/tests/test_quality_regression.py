"""골든셋 야간 회귀(scripts/quality_regression.py) — 채점·판정 순수 함수 검증.

실제 턴 실행(run_chat_turn)은 e2e 영역 — 여기선 집계(aggregate)·회귀 판정
(detect_regression)·스케줄 계산(next_run_delay_s)이 대상. 판정 로직이 틀리면
회귀를 놓치거나(미탐) 매일 아침 헛알림(오탐)이 오므로 경계를 고정한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.quality_regression import (
    GOLDEN_QUESTIONS,
    aggregate,
    detect_regression,
    next_run_delay_s,
)

_KST = timezone(timedelta(hours=9))


def _row(**kw) -> dict:
    base = {
        "q": "테스트 질문", "expect_search": True,
        "done_s": 15.0, "total_s": 15.0, "ttft_s": 6.0,
        "citations": 3, "verified": 3, "next_steps": True, "error": None,
        "claim_total": 2, "claim_flagged": 0,
    }
    base.update(kw)
    return base


# ── aggregate ──────────────────────────────────────────────────────────────

def test_aggregate_basic():
    s = aggregate([_row(), _row(citations=2, verified=1, total_s=25.0)])
    assert s["n"] == 2 and s["errors"] == 0
    assert s["citations"] == 5 and s["verified"] == 4
    assert s["verified_rate"] == round(4 / 5, 3)
    assert s["avg_total_s"] == 20.0 and s["max_total_s"] == 25.0
    assert s["next_steps_rate"] == 1.0


def test_aggregate_excludes_no_search_questions_from_citation_metrics():
    """expect_search=False(인사 등)는 무인용이 정상 — 인용 분모·무인용 목록에서 제외."""
    s = aggregate([_row(), _row(expect_search=False, citations=0, verified=0)])
    assert s["citations"] == 3 and s["verified_rate"] == 1.0
    assert s["no_citation_questions"] == []


def test_aggregate_error_rows_excluded_from_averages():
    s = aggregate([_row(), _row(error="boom", done_s=None, total_s=None,
                                ttft_s=None, citations=0, verified=0)])
    assert s["errors"] == 1 and s["error_questions"]
    assert s["avg_total_s"] == 15.0  # 실패 턴이 평균을 오염하지 않는다


def test_done_and_total_are_tracked_separately():
    """체감 완료(done)와 후처리 포함(total)은 다른 지표 — 섞으면 ~9s 부풀려진다."""
    s = aggregate([_row(done_s=20.0, total_s=30.0),
                   _row(done_s=22.0, total_s=32.0)])
    assert s["avg_done_s"] == 21.0 and s["max_done_s"] == 22.0
    assert s["avg_total_s"] == 31.0


def test_aggregate_flags_zero_citation_regulatory_question():
    s = aggregate([_row(citations=0, verified=0)])
    assert s["no_citation_questions"] and s["verified_rate"] is None


# ── detect_regression ──────────────────────────────────────────────────────

def test_no_regression_on_healthy_run():
    cur = aggregate([_row()])
    prev = aggregate([_row()])
    assert detect_regression(cur, prev) == []


def test_first_run_without_prev_is_quiet_unless_broken():
    assert detect_regression(aggregate([_row()]), None) == []


def test_errors_always_flagged():
    cur = aggregate([_row(error="ReadTimeout")])
    assert any("턴 실패" in i for i in detect_regression(cur, None))


def test_verified_rate_drop_needs_both_relative_and_absolute():
    prev = {"verified_rate": 0.95, "avg_total_s": 15.0, "next_steps_rate": 1.0}
    # 0.95→0.88: -0.07 하락이지만 절대치 양호 — 노이즈로 보고 침묵.
    assert detect_regression(
        {"verified_rate": 0.88, "errors": 0, "citations": 10}, prev) == []
    # 0.95→0.70: 상대·절대 모두 악화 — 알림.
    issues = detect_regression(
        {"verified_rate": 0.70, "errors": 0, "citations": 10}, prev)
    assert any("검증률" in i for i in issues)


def test_all_regulatory_questions_uncited_flags_search_path():
    cur = aggregate([_row(citations=0, verified=0)])
    assert any("검색 경로" in i for i in detect_regression(cur, None))


def test_latency_regression_needs_relative_and_absolute():
    prev = {"verified_rate": 0.9, "avg_done_s": 15.0}
    # 15→20s: 1.5배 미만 — 침묵. 15→30s(>25s): 알림.
    assert detect_regression(
        {"errors": 0, "avg_done_s": 20.0, "verified_rate": 0.9}, prev) == []
    issues = detect_regression(
        {"errors": 0, "avg_done_s": 30.0, "verified_rate": 0.9}, prev)
    assert any("응답시간" in i for i in issues)


def test_latency_judged_on_done_not_total():
    """후처리(grounding·audit)가 길어진 것은 체감 악화가 아니다 — 오알림 금지."""
    prev = {"verified_rate": 0.9, "avg_done_s": 20.0, "avg_total_s": 22.0}
    cur = {"errors": 0, "verified_rate": 0.9,
           "avg_done_s": 21.0, "avg_total_s": 40.0}  # done 은 그대로, total 만 급증
    assert detect_regression(cur, prev) == []


def test_next_steps_contract_breach_flagged():
    cur = {"errors": 0, "verified_rate": 0.9, "next_steps_rate": 0.5}
    assert any("next_steps" in i for i in detect_regression(cur, None))


# ── next_run_delay_s / 질문셋 불변식 ───────────────────────────────────────

def test_next_run_delay_future_same_day_and_rollover():
    now = datetime(2026, 8, 16, 1, 0, tzinfo=_KST)
    assert next_run_delay_s(now, "03:00") == 2 * 3600
    after = datetime(2026, 8, 16, 3, 5, tzinfo=_KST)
    # 이미 지났으면 내일 — 재시작 루프가 같은 밤에 두 번 돌지 않게.
    assert next_run_delay_s(after, "03:00") == 24 * 3600 - 5 * 60


def test_golden_set_shape():
    assert len(GOLDEN_QUESTIONS) >= 15
    assert all(s["q"].strip() for s in GOLDEN_QUESTIONS)
    # 라우팅 감시용 비검색 발화가 최소 1개 포함돼야 한다.
    assert any(s.get("expect_search") is False for s in GOLDEN_QUESTIONS)


# ── "바뀐 날만 돈다"(2026-09-18) — 매일 실행이 LLM 비용의 80% 였다 ──────────

def _fp(sha="abc1234", pv="v30_chat_fast", model="haiku"):
    return {"git_sha": sha, "prompt_version": pv, "chat_model": model}


def test_should_run_skips_when_nothing_changed_and_recent():
    from scripts.quality_regression import should_run
    now = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    run, why = should_run(_fp(), {"fingerprint": _fp()}, now - timedelta(days=1), now)
    assert run is False and "변경 없음" in why


def test_should_run_on_any_change():
    from scripts.quality_regression import should_run
    now = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    prev_ts = now - timedelta(days=1)
    for changed in (_fp(sha="def5678"), _fp(pv="v31_chat_fast"), _fp(model="sonnet")):
        run, why = should_run(changed, {"fingerprint": _fp()}, prev_ts, now)
        assert run is True and why.startswith("변경:")


def test_should_run_weekly_even_without_change():
    from scripts.quality_regression import should_run
    now = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    assert should_run(_fp(), {"fingerprint": _fp()}, now - timedelta(days=6.9), now)[0] is False
    run, why = should_run(_fp(), {"fingerprint": _fp()}, now - timedelta(days=7), now)
    assert run is True and "주기 점검" in why
    assert should_run(_fp(), {"fingerprint": _fp()}, now - timedelta(days=2), now, max_age_days=2)[0] is True


def test_should_run_when_unsure():
    """모르면 돈다 — 기록 없음·지문 없음(도입 전)·커밋 미상."""
    from scripts.quality_regression import should_run
    now = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)
    ts = now - timedelta(hours=1)
    assert should_run(_fp(), None, None, now)[0] is True
    assert should_run(_fp(), {"summary": {}}, ts, now)[0] is True
    assert should_run(_fp(sha="unknown"), {"fingerprint": _fp(sha="unknown")}, ts, now)[0] is True


def test_last_full_run_ignores_partial_runs(monkeypatch, tmp_path):
    import json as _json

    from scripts.quality_regression import _last_full_run
    from src.persistence import get_events_repo
    from src.persistence.events_repo import Event

    repo = get_events_repo()
    repo.emit(Event(id="", ts="", event_type="quality_regression",
                    payload_json=_json.dumps({"summary": {"n": 16}, "fingerprint": _fp()})))
    repo.emit(Event(id="", ts="", event_type="quality_regression",
                    payload_json=_json.dumps({"summary": {"n": 3}, "partial": True})))
    payload, ts = _last_full_run()
    assert payload["summary"]["n"] == 16 and ts is not None and ts.tzinfo is not None
