"""보고서 조회 소유권 회귀 — 2026-08-04 감사 C-1.

사고: `/threads/{tid}/reports`·`/reports/{rid}`·`/reports/{rid}/download` 셋 다
소유권 검사가 없었다. 유일한 검사이던 `_check_auth` 는 API_TOKEN 미설정 시
무조건 통과라 운영에서 no-op — 로그인한 누구나 report_id 만 알면 타인 보고서
전문을 받을 수 있었다.

여기서 잠그는 것:
  ① 남의 보고서는 404 (403 아님 — 존재를 알려주지 않는다)
  ② 본인 것은 그대로 200 (과잉 차단 아님)
  ③ thread 가 삭제돼 소유자를 확인할 수 없는 고아 보고서도 404 (fail-closed).
     delete_thread 는 reports 를 지우지 않으므로, 통과시키면 "대화 삭제 =
     보고서 전체 공개"가 된다.
  ④ 피드백 라우트도 같은 정책 — 404/200 이 갈리면 그 자체가 열거 오라클이다.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest


SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "medi.db"))
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    from src import persistence as P
    from src.persistence.threads_repo import reset_threads_repo_cache

    caches = (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo)
    for f in caches:
        f.cache_clear()
    reset_threads_repo_cache()
    yield
    for f in caches:
        f.cache_clear()
    reset_threads_repo_cache()


def _token(sub: str) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "email": f"{sub}@example.com", "email_verified": True,
         "iat": now, "exp": now + 3600},
        SECRET, algorithm="HS256",
    )


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _seed(*, thread_id: str, report_id: str, owner: str | None) -> None:
    """보고서 1건 + (owner 가 있으면) 소유자 기록된 thread."""
    from src.persistence import ReportMeta, get_blob_store, get_reports_repo
    from src.persistence.threads_repo import get_threads_repo

    uri = get_blob_store().put(f"{thread_id}/{report_id}.md", "# 대외비 보고서 본문")
    get_reports_repo().create(ReportMeta(
        id=report_id, thread_id=thread_id, mode="deep", kind="final",
        status="done", blob_uri=uri,
    ))
    if owner is not None:
        get_threads_repo().ensure_thread(thread_id, user_id=owner)


def _h(sub: str) -> dict:
    return {"Authorization": f"Bearer {_token(sub)}"}


# ── ① 남의 보고서 ───────────────────────────────────────────────────────────
def test_other_users_report_is_404_on_get():
    _seed(thread_id="t-own", report_id="r-own", owner="alice")
    res = _client().get("/reports/r-own", headers=_h("mallory"))
    assert res.status_code == 404


def test_other_users_report_download_is_404_and_leaks_no_body():
    _seed(thread_id="t-own", report_id="r-own", owner="alice")
    res = _client().get("/reports/r-own/download", headers=_h("mallory"))
    assert res.status_code == 404
    assert "대외비" not in res.text


def test_other_users_thread_report_list_is_404():
    _seed(thread_id="t-own", report_id="r-own", owner="alice")
    res = _client().get("/threads/t-own/reports", headers=_h("mallory"))
    assert res.status_code == 404


# ── ② 본인 것은 통과 ────────────────────────────────────────────────────────
def test_owner_can_read_and_download():
    _seed(thread_id="t-own", report_id="r-own", owner="alice")
    c, h = _client(), _h("alice")

    assert c.get("/reports/r-own", headers=h).status_code == 200

    dl = c.get("/reports/r-own/download", headers=h)
    assert dl.status_code == 200
    assert "대외비" in dl.text

    lst = c.get("/threads/t-own/reports", headers=h)
    assert lst.status_code == 200
    assert lst.json()["count"] == 1


# ── ③ 고아 보고서(thread 삭제)는 fail-closed ────────────────────────────────
def test_orphaned_report_is_denied_not_public():
    """thread 메타도 run 기록도 없으면 소유자 확인 불가 → 차단. 통과시키면
    대화를 지우는 것만으로 보고서가 전체 공개된다."""
    _seed(thread_id="t-gone", report_id="r-gone", owner=None)
    assert _client().get("/reports/r-gone", headers=_h("alice")).status_code == 404
    assert _client().get("/reports/r-gone/download",
                         headers=_h("alice")).status_code == 404


def test_pruned_thread_owner_keeps_access_via_run_record():
    """보관정리(prune_threads.py:62)는 thread 만 지우고 reports 는 남긴다.
    thread 소유자만 보면 **정당한 소유자가 옛 보고서에서 잠긴다** → run 기록으로 복원.
    """
    from src.persistence import get_report_runs_repo
    from src.persistence.threads_repo import get_threads_repo

    _seed(thread_id="t-pruned", report_id="r-old", owner="alice")
    runs = get_report_runs_repo()
    runs.acquire(idempotency_key="rpt_old", thread_id="t-pruned", user_id="alice")
    runs.finish("rpt_old", status="completed", report_id="r-old")

    get_threads_repo().delete_thread("t-pruned")  # 보관정리 재현

    assert _client().get("/reports/r-old", headers=_h("alice")).status_code == 200
    # 그래도 남은 사람은 못 본다
    assert _client().get("/reports/r-old", headers=_h("mallory")).status_code == 404


# ── ④ 피드백 라우트도 같은 정책(열거 오라클 차단) ───────────────────────────
def test_report_feedback_rejects_non_owner():
    _seed(thread_id="t-own", report_id="r-own", owner="alice")
    res = _client().post("/reports/r-own/feedback",
                         json={"rating": "thumbs_up"}, headers=_h("mallory"))
    assert res.status_code == 404

    # 존재하지 않는 보고서와 **구분되지 않아야** 한다 — 응답이 같아야 오라클이 아니다.
    miss = _client().post("/reports/no-such/feedback",
                          json={"rating": "thumbs_up"}, headers=_h("mallory"))
    assert miss.status_code == res.status_code


def test_report_feedback_allows_owner():
    _seed(thread_id="t-own", report_id="r-own", owner="alice")
    res = _client().post("/reports/r-own/feedback",
                         json={"rating": "thumbs_up", "comment": "좋아요"},
                         headers=_h("alice"))
    assert res.status_code == 200
