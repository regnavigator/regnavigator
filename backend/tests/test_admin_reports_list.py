"""관리자 보고서 목록(2026-08-21) — 요청(run)·생성·이메일 발송 결과 한 화면.

배경: 베타 보고서 3연속 실패(writer 400)를 사용자 신고로야 알았고, 발송
여부는 컨테이너 로그로도 확인할 수 없었다. report_runs 를 reports(제목)·
users(이메일)·events(report_email)와 조인하는 `list_admin` + `/admin/reports`.
"""
from __future__ import annotations

import json

from src.persistence import (
    get_events_repo,
    get_report_runs_repo,
    get_reports_repo,
    get_users_repo,
)
from src.persistence.events_repo import Event
from src.persistence.reports_repo import ReportMeta


def _seed_run(idem: str, *, user_id="u-1", thread_id="t_x", status="completed",
              report_id=None, error=None, prompt="이 주제로 종합 보고서"):
    runs = get_report_runs_repo()
    ok, _ = runs.acquire(idempotency_key=idem, thread_id=thread_id,
                         user_id=user_id, prompt=prompt)
    assert ok
    if status != "running":
        runs.finish(idem, status=status, report_id=report_id, error=error)


def test_list_admin_joins_title_email_and_send_status():
    get_users_repo().upsert(id="u-1", email="tester@example.com")
    get_reports_repo().create(ReportMeta(
        id="rep-1", thread_id="t_x", mode="deep", kind="final",
        status="done", title="비교 보고서"))
    _seed_run("rpt_a", report_id="rep-1")
    get_events_repo().emit(Event(
        id="", ts="", event_type="report_email", user_id="u-1",
        thread_id="t_x", run_id="rep-1",
        payload_json=json.dumps({"ok": True})))

    rows, total = get_report_runs_repo().list_admin(limit=10)
    assert total == 1
    r = rows[0]
    assert r["user_email"] == "tester@example.com"
    assert r["report_title"] == "비교 보고서"
    p = r["email_event"]
    p = p if isinstance(p, dict) else json.loads(p)
    assert p["ok"] is True


def test_list_admin_failed_run_without_report_or_email():
    """실패 run — 조인 대상이 전부 없어도 행은 나온다(LEFT JOIN)."""
    _seed_run("rpt_fail", status="failed", error="writer 오류(BadRequestError)")
    rows, total = get_report_runs_repo().list_admin(limit=10)
    assert total == 1
    r = rows[0]
    assert r["status"] == "failed"
    assert "BadRequestError" in r["error"]
    assert r["report_title"] is None and r["email_event"] is None


def test_list_admin_latest_email_event_only():
    """재발송 시 최신 발송 결과 1건만 — 행 중복 금지."""
    get_users_repo().upsert(id="u-1", email="tester@example.com")
    _seed_run("rpt_b", report_id="rep-2")
    ev = get_events_repo()
    ev.emit(Event(id="", ts="", event_type="report_email", user_id="u-1",
                  thread_id="t_x", run_id="rep-2",
                  payload_json=json.dumps({"ok": False, "error": "SMTPError"})))
    ev.emit(Event(id="", ts="", event_type="report_email", user_id="u-1",
                  thread_id="t_x", run_id="rep-2",
                  payload_json=json.dumps({"ok": True})))
    rows, total = get_report_runs_repo().list_admin(limit=10)
    assert total == 1  # 이벤트 2건이어도 run 행은 1개


def test_list_admin_pagination():
    for i in range(5):
        _seed_run(f"rpt_p{i}", thread_id=f"t_{i}")
    p1, total = get_report_runs_repo().list_admin(limit=2, offset=0)
    p2, _ = get_report_runs_repo().list_admin(limit=2, offset=2)
    p3, _ = get_report_runs_repo().list_admin(limit=2, offset=4)
    assert total == 5
    keys = [r["idempotency_key"] for r in p1 + p2 + p3]
    assert len(keys) == 5 and len(set(keys)) == 5


def test_admin_route_shapes_email_status():
    """라우트 응답 계약 — email_status sent/failed/None + 페이지 필드."""
    from src.routes.admin import admin_list_reports

    get_users_repo().upsert(id="u-1", email="tester@example.com")
    get_reports_repo().create(ReportMeta(
        id="rep-3", thread_id="t_x", mode="deep", kind="final",
        status="done", title="T"))
    _seed_run("rpt_ok", report_id="rep-3")
    get_events_repo().emit(Event(
        id="", ts="", event_type="report_email", user_id="u-1",
        thread_id="t_x", run_id="rep-3", payload_json=json.dumps({"ok": True})))
    _seed_run("rpt_mailfail", report_id="rep-4")
    get_events_repo().emit(Event(
        id="", ts="", event_type="report_email", user_id="u-1",
        thread_id="t_x", run_id="rep-4",
        payload_json=json.dumps({"ok": False, "error": "SMTPError"})))
    _seed_run("rpt_norec", status="failed", error="writer 오류(X)")

    # scope="all" — 시드 thread 가 hex 형이 아니라 새 내부 판정에 걸린다.
    # 이 테스트의 관심사는 필터가 아니라 행 셰이핑(이메일 상태 등).
    out = admin_list_reports(limit=10, offset=0, scope="all", tab="all",
                             _admin=None)
    assert out["total"] == 3 and out["has_more"] is False
    by_key = {r["idempotency_key"]: r for r in out["runs"]}
    assert by_key["rpt_ok"]["email_status"] == "sent"
    assert by_key["rpt_mailfail"]["email_status"] == "failed"
    assert by_key["rpt_mailfail"]["email_error"] == "SMTPError"
    assert by_key["rpt_norec"]["email_status"] is None


def test_orphan_completed_run_hidden_in_real_scope():
    """산출물이 삭제된 완료 run — 기본(real) 목록에서 숨김, all 에선 표시.

    사용자 삭제·중복 정리 뒤 "(제목 없음)·본문 없음" 행이 남던 것(2026-08-28).
    (다른 테스트와 같은 세션 DB 공유 — idem 키로만 검증하므로 무해.)
    """
    from src.routes.admin import admin_list_reports

    # 실사용 형태(hex) 스레드 + 완료 run, reports 행은 없음(=삭제됨).
    get_report_runs_repo().acquire(
        idempotency_key="rpt_orph1", thread_id="t_" + "a1" * 16,
        user_id="u-real", prompt="[서식] 허가신청서", purpose="document_draft")
    get_report_runs_repo().finish(
        "rpt_orph1", status="completed", report_id="doc_gone123")

    real = admin_list_reports(limit=10, offset=0, scope="real", tab="all",
                              _admin=None)
    assert all(x["idempotency_key"] != "rpt_orph1" for x in real["runs"])
    everything = admin_list_reports(limit=10, offset=0, scope="all", tab="all",
                                    _admin=None)
    assert any(x["idempotency_key"] == "rpt_orph1" for x in everything["runs"])


def test_admin_list_reports_real_scope_excludes_staff_accounts():
    """관리자(운영진)·테스트 계정 보고서는 '실사용'에서 빠진다 — 스레드가 실사용
    형식(t_hex)이어도 계정 축으로 거른다(2026-09-22 신고)."""
    from src import account_class
    from src.routes.admin import admin_list_reports

    get_users_repo().upsert(id="u-adm", email="boss@example.com", is_admin=True)
    get_users_repo().upsert(id="u-usr", email="user@example.com")
    account_class.invalidate()
    _seed_run("rpt_adm", user_id="u-adm", thread_id="t_aaaaaaaa1111")
    _seed_run("rpt_usr", user_id="u-usr", thread_id="t_bbbbbbbb2222")
    real = admin_list_reports(limit=10, offset=0, scope="real", tab="all", _admin=None)
    keys = {r["idempotency_key"] for r in real["runs"]}
    assert keys == {"rpt_usr"}
    everything = admin_list_reports(limit=10, offset=0, scope="all", tab="all", _admin=None)
    flags = {r["idempotency_key"]: r["internal"] for r in everything["runs"]}
    assert flags == {"rpt_adm": True, "rpt_usr": False}
