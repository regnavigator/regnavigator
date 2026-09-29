"""정보주체 삭제 요구 이행 스크립트 — 현행 저장소 전부를 지우고, 성공했을 때만 통지한다(2026-09-23).

종전 스크립트는 은퇴한 langgraph 체크포인트를 지우려 해 대화·서식·저장한 근거·보고서 행이
남았고, 완료 통지는 운영자 수동이었다.
"""
from __future__ import annotations

import json

from langchain_core.messages import HumanMessage


def _seed(uid="u-erase", email="gone@example.com"):
    from src.persistence import (
        get_bookmarks_repo, get_events_repo, get_feedback_repo, get_report_runs_repo,
        get_reports_repo, get_users_repo,
    )
    from src.persistence.bookmarks_repo import Bookmark
    from src.persistence.events_repo import Event
    from src.persistence.feedback_repo import Feedback
    from src.persistence.reports_repo import ReportMeta
    from src.persistence.threads_repo import get_threads_repo

    get_users_repo().upsert(id=uid, email=email)
    th = get_threads_repo()
    th.ensure_thread("t-e1", user_id=uid)
    th.append_messages("t-e1", [HumanMessage(content="질문")])
    reports = get_reports_repo()
    reports.create(ReportMeta(id="r-e1", thread_id="t-e1", mode="deep", kind="final", status="done"))
    reports.create(ReportMeta(id="doc_e1", thread_id="t-gone", mode="deep", kind="doc",
                              status="done", kept=True))   # 대화가 지워진 보관 서식
    runs = get_report_runs_repo()
    runs.acquire(idempotency_key="rpt_e1", thread_id="t-gone", user_id=uid, prompt="[서식] x",
                 purpose="document_draft")
    runs.finish("rpt_e1", status="completed", report_id="doc_e1")
    get_bookmarks_repo().create(Bookmark(id="", user_id=uid, citation_id="c1",
                                         citation_json=json.dumps({"id": "c1"})))
    get_feedback_repo().create(Feedback(id="", rating="thumbs_up", user_id=uid, thread_id="t-e1"))
    get_events_repo().emit(Event(id="", ts="", event_type="legal_consent", user_id=uid,
                                 payload_json="{}"))
    return uid, email


def test_erase_removes_everything_and_notifies(monkeypatch):
    from scripts import erase_user as E
    from src.observability import notifications
    from src.persistence import (
        get_bookmarks_repo, get_events_repo, get_report_runs_repo, get_reports_repo,
        get_users_repo,
    )
    from src.persistence.threads_repo import get_threads_repo

    uid, email = _seed()
    sent = []
    monkeypatch.setattr(notifications, "send_email", lambda **kw: sent.append(kw) or True)

    assert E.erase(uid, apply=True, keep_audit=True, notify=True) == 0
    assert get_users_repo().get(uid) is None
    assert get_threads_repo().list_for_user(uid) == []
    assert get_reports_repo().get("r-e1") is None and get_reports_repo().get("doc_e1") is None
    assert get_bookmarks_repo().list_for_user(uid) == []
    assert get_report_runs_repo().report_ids_for_user(uid) == []
    assert [e.event_type for e in get_events_repo().list_for_user(uid)] == ["legal_consent"]
    assert len(sent) == 1 and sent[0]["to"] == email and "삭제" in sent[0]["subject"]


def test_erase_dry_run_touches_nothing(monkeypatch):
    from scripts import erase_user as E
    from src.persistence import get_users_repo

    uid, _ = _seed()
    assert E.erase(uid, apply=False, keep_audit=False, notify=True) == 0
    assert get_users_repo().get(uid) is not None


def test_erase_failure_skips_notice(monkeypatch):
    """한 단계라도 실패하면 완료 메일을 보내지 않는다 — 거짓 완료 통지 방지."""
    from scripts import erase_user as E
    from src.observability import notifications
    from src.persistence import get_feedback_repo

    uid, _ = _seed()
    sent = []
    monkeypatch.setattr(notifications, "send_email", lambda **kw: sent.append(kw) or True)
    repo = get_feedback_repo()
    monkeypatch.setattr(repo, "delete_for_user", lambda u: (_ for _ in ()).throw(RuntimeError("x")))
    assert E.erase(uid, apply=True, keep_audit=False, notify=True) == 2
    assert sent == []
