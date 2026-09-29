"""Postgres Repos 통합 테스트.

`MEDI_TEST_PG_DSN` env가 설정된 경우에만 실행. **CI 는 postgres 서비스로 항상 실행**(2026-09-22 —
그전엔 CI 에 DSN 이 없어 수개월간 한 번도 안 돌았다. 운영은 PG 인데 SQL 이 SQLite 와 따로라,
PG 전용 구문은 여기서만 검증된다). 로컬은 아래처럼 띄우면 돈다(미설정이면 skip).

로컬 PG 빠르게 띄우기:
    docker run --rm -d -p 5433:5432 -e POSTGRES_PASSWORD=test \
      --name medi-test-pg postgres:16-alpine
    export MEDI_TEST_PG_DSN=postgresql://postgres:test@localhost:5433/postgres

각 테스트는 격리된 schema 사용 — 다른 테스트와 간섭 없음.
"""
from __future__ import annotations

import os
import uuid

import pytest


_PG_DSN = os.getenv("MEDI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(
    not _PG_DSN,
    reason="MEDI_TEST_PG_DSN 미설정 — Postgres 통합 테스트 skip",
)


def test_threads_repo_pg_roundtrip(monkeypatch):
    """PostgresThreadsRepo — 메시지/steps merge/선택키/요약 왕복 (ADR-0001 Phase 3)."""
    import src.persistence.threads_repo as tr
    from langchain_core.messages import AIMessage, HumanMessage

    monkeypatch.setattr(tr, "_repo", None)
    repo = tr.get_threads_repo()
    assert type(repo).__name__ == "PostgresThreadsRepo"

    repo.ensure_thread("t1", user_id="u1")
    repo.ensure_thread("t1")  # 멱등
    repo.append_messages("t1", [
        HumanMessage(content="질문", id="m1"),
        AIMessage(content="답변", id="m2"),
    ])
    repo.merge_steps("t1", [{"id": "s1", "status": "running", "ts": 1,
                             "label": "검색", "tool_name": "qdrant_search"}])
    repo.merge_steps("t1", [{"id": "s1", "status": "done", "ended_at": 2}])
    repo.set_selected_law_keys("t1", ["009514_0006001"])
    repo.set_selected_law_keys("t1", None)  # None=미변경
    repo.set_summary("t1", "요약본", 0)

    st = repo.get_state("t1")
    assert [m.type for m in st.messages] == ["human", "ai"]
    assert st.seqs == [0, 1]
    assert st.steps[0]["status"] == "done"
    assert st.steps[0]["label"] == "검색"  # 필드 단위 merge — start 필드 보존
    assert st.selected_law_keys == ["009514_0006001"]
    assert st.summary_text == "요약본" and st.summary_upto_seq == 0


@pytest.fixture(autouse=True)
def _isolated_schema(monkeypatch):
    """각 테스트별 별도 schema. 테스트 종료 시 drop."""
    if not _PG_DSN:
        yield
        return

    schema_name = f"medi_test_{uuid.uuid4().hex[:8]}"
    dsn = f"{_PG_DSN}?options=-csearch_path%3D{schema_name}"

    # schema 생성
    import psycopg
    with psycopg.connect(_PG_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema_name}"')

    # _pg 모듈 pool 캐시 리셋 + DSN env 주입
    import src.persistence._pg as _pg_mod
    _pg_mod._pool = None
    monkeypatch.setenv("REPORTS_PG_DSN", dsn)
    monkeypatch.setenv("REPORTS_BACKEND", "postgres")
    from src import persistence as P
    for f in (P.get_users_repo, P.get_events_repo,
              P.get_feedback_repo, P.get_reports_repo):
        f.cache_clear()

    yield

    # cleanup
    try:
        if _pg_mod._pool is not None:
            _pg_mod._pool.close()
            _pg_mod._pool = None
    except Exception:
        pass
    with psycopg.connect(_PG_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA "{schema_name}" CASCADE')

    for f in (P.get_users_repo, P.get_events_repo,
              P.get_feedback_repo, P.get_reports_repo):
        f.cache_clear()


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------
def test_pg_users_upsert_and_get():
    from src.persistence import get_users_repo
    repo = get_users_repo()
    u = repo.upsert(id="u-pg-1", email="alice@example.com",
                    email_verified_at="2026-04-30T00:00:00.000Z")
    assert u.email == "alice@example.com"
    assert u.email_verified_at is not None

    got = repo.get("u-pg-1")
    assert got is not None and got.id == "u-pg-1"

    repo.upsert(id="u-pg-1", email="alice2@example.com")  # email 갱신
    assert repo.get("u-pg-1").email == "alice2@example.com"


def test_pg_users_admin_and_quota():
    from src.persistence import get_users_repo
    repo = get_users_repo()
    repo.upsert(id="u-pg-2", email="b@x.com")
    repo.set_admin("u-pg-2", True)
    repo.update_quota("u-pg-2", daily_override=200000, monthly_override=5000000)
    u = repo.get("u-pg-2")
    assert u.is_admin is True
    assert u.daily_token_limit_override == 200000
    assert u.monthly_token_limit_override == 5000000


def test_pg_events_emit_and_sum_tokens():
    from src.persistence import Event, get_events_repo
    repo = get_events_repo()
    repo.emit(Event(id="", ts="2026-04-30T01:00:00.000Z",
                    event_type="llm_call", user_id="u-pg-3",
                    input_tokens=100, output_tokens=50, cost_usd=0.001))
    repo.emit(Event(id="", ts="2026-04-30T02:00:00.000Z",
                    event_type="llm_call", user_id="u-pg-3",
                    input_tokens=200, output_tokens=100, cost_usd=0.002))
    i, o, c = repo.sum_tokens_for_user("u-pg-3", since="2026-04-30T00:00:00.000Z")
    assert i == 300 and o == 150 and abs(c - 0.003) < 1e-6


def test_pg_events_payload_jsonb_round_trip():
    from src.persistence import Event, get_events_repo
    import json
    repo = get_events_repo()
    payload = {"model": "claude-sonnet-4-6", "kind": "llm_call"}
    repo.emit(Event(id="", ts="2026-04-30T03:00:00.000Z",
                    event_type="llm_call", user_id="u-pg-4",
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    input_tokens=10, output_tokens=5))
    rows = repo.list_for_user("u-pg-4")
    assert len(rows) == 1
    assert json.loads(rows[0].payload_json) == payload


def test_pg_feedback_create_validation():
    from src.persistence import Feedback, get_feedback_repo
    repo = get_feedback_repo()
    fid = repo.create(Feedback(id="", rating="thumbs_up",
                                user_id="u-pg-5", thread_id="t-1",
                                message_id="m-1", comment="좋아요"))
    f = repo.get(fid)
    assert f.rating == "thumbs_up"
    assert f.comment == "좋아요"

    with pytest.raises(ValueError):
        repo.create(Feedback(id="", rating="meh"))


def test_pg_reports_create_update_get():
    from src.persistence import ReportMeta, get_reports_repo
    repo = get_reports_repo()
    repo.create(ReportMeta(
        id="r-pg-1", thread_id="t-1", mode="deep", kind="final",
        status="running",
    ))
    repo.update_status("r-pg-1", status="done",
                       blob_uri="file:///x", title="최종",
                       citations=[{"n": 1, "title": "법1"}])
    r = repo.get("r-pg-1")
    assert r.status == "done"
    assert r.title == "최종"
    assert r.blob_uri == "file:///x"
    import json
    assert json.loads(r.citations_json) == [{"n": 1, "title": "법1"}]
    assert r.completed_at is not None


def test_pg_reports_list_for_thread_orders_desc():
    from src.persistence import ReportMeta, get_reports_repo
    repo = get_reports_repo()
    repo.create(ReportMeta(id="r-A", thread_id="t-x", mode="deep", kind="rag",
                            status="done",
                            created_at="2026-04-30T01:00:00.000Z"))
    repo.create(ReportMeta(id="r-B", thread_id="t-x", mode="deep", kind="final",
                            status="done",
                            created_at="2026-04-30T02:00:00.000Z"))
    rows = repo.list_for_thread("t-x")
    assert [r.id for r in rows] == ["r-B", "r-A"]


def test_pg_reports_list_expired_excludes_docs():
    """보존정리 — 만료 보고서만, 서식(kind=doc)은 제외(PG TIMESTAMPTZ 비교)."""
    from src.persistence import ReportMeta, get_reports_repo
    repo = get_reports_repo()
    for rid, kind, ts in [("e-old", "final", "2020-01-01T00:00:00.000Z"),
                          ("e-doc", "doc", "2020-01-01T00:00:00.000Z"),
                          ("e-new", "final", "2999-01-01T00:00:00.000Z")]:
        repo.create(ReportMeta(id=rid, thread_id="t-e", mode="deep", kind=kind,
                               status="done", created_at=ts))
    rows = repo.list_expired("2026-01-01T00:00:00.000000Z", limit=10)
    assert [r.id for r in rows] == ["e-old"]


def test_answer_reviews_repo_pg_upsert():
    """PostgresAnswerReviewsRepo — 검수자당 1행 upsert·RETURNING id·조회 (2026-09-17).

    SQLite 와 SQL 이 따로라(ON CONFLICT … RETURNING, TIMESTAMPTZ) 별도 검증이 필요하다.
    """
    from src.persistence import get_answer_reviews_repo
    from src.persistence.answer_reviews_repo import AnswerReview

    repo = get_answer_reviews_repo()
    assert type(repo).__name__ == "PostgresAnswerReviewsRepo"
    a = repo.upsert(AnswerReview(id="", thread_id="t1", message_id="m1", reviewer="a@x",
                                 verdict="wrong", error_types=["misapplied"]))
    b = repo.upsert(AnswerReview(id="", thread_id="t1", message_id="m1", reviewer="a@x",
                                 verdict="partial", error_types=["incomplete"], note="예외 누락"))
    assert a == b                                   # 재채점은 같은 행을 덮어쓴다
    repo.upsert(AnswerReview(id="", thread_id="t1", message_id="m1", reviewer="b@x",
                             verdict="correct"))
    rows = repo.list_for_thread("t1")
    assert len(rows) == 2
    mine = next(r for r in rows if r.reviewer == "a@x")
    assert (mine.verdict, mine.error_types, mine.note) == ("partial", ["incomplete"], "예외 누락")
    assert repo.reviewed_message_ids() == {"m1"}
    assert len(repo.list_since("2000-01-01T00:00:00.000000Z")) == 2
    assert repo.list_since() and len(repo.list_since()) == 2


def test_pg_users_admin_perms_roundtrip():
    """admin_perms 컬럼(2026-09-22) — ALTER 마이그레이션·NULL(전 권한)/빈 문자열(권한 없음) 구분."""
    from src.persistence import get_users_repo
    repo = get_users_repo()
    repo.upsert(id="u-pg-perm", email="perm@x.com")
    assert repo.get("u-pg-perm").admin_perms is None
    repo.set_admin_perms("u-pg-perm", "")
    assert repo.get("u-pg-perm").admin_perms == ""
    repo.set_admin_perms("u-pg-perm", "mail,announcements")
    assert repo.get("u-pg-perm").admin_perms == "mail,announcements"


def test_pg_threads_list_admin_excludes_user_ids(monkeypatch):
    """list_admin exclude_user_ids(2026-09-22) — PG 는 `= ANY(%s)` 배열 바인딩(SQLite 는 IN)."""
    import src.persistence.threads_repo as tr

    monkeypatch.setattr(tr, "_repo", None)
    repo = tr.get_threads_repo()
    repo.ensure_thread("t_aaaa1111", user_id="u-admin")
    repo.ensure_thread("t_bbbb2222", user_id="u-real")
    repo.ensure_thread("qreg_x", user_id="u-real")
    rows, total = repo.list_admin(limit=10, require_user=True,
                                  exclude_prefixes=("qreg_",),
                                  exclude_user_ids=("u-admin",))
    assert total == 1 and [r["id"] for r in rows] == ["t_bbbb2222"]
