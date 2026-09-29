"""관리자 대화 목록 페이지네이션(2026-08-20) — 필터 SQL 이관 + limit/offset.

배경: 종전 `/admin/threads` 는 '최근 N개'를 먼저 뽑고 사후 필터해, 내부
트래픽(`qreg_` 야간 회귀 등)이 상한을 잡아먹으면 그보다 오래된 실사용
대화가 아예 조회되지 않았다(8/16 22:05 이전 대화 실종 — 운영자 지적).
"""
from __future__ import annotations

from src.persistence.threads_repo import get_threads_repo


def test_list_admin_filters_in_sql():
    """내부 접두·익명 제외가 상한 **이전에** 적용된다."""
    repo = get_threads_repo()
    repo.ensure_thread("qreg_20260820_0300_01", user_id="u-admin")
    repo.ensure_thread("t_anon")  # 익명 — /chat 은 JWT 필수라 스크립트 산물
    repo.ensure_thread("t_real", user_id="u-1")
    rows, total = repo.list_admin(
        limit=10, exclude_prefixes=("qreg_",), require_user=True)
    assert total == 1
    assert [r["id"] for r in rows] == ["t_real"]


def test_list_admin_prefix_underscore_is_not_wildcard():
    """접두의 `_` 를 LIKE 와일드카드로 해석하면 'qregX…' 실사용 대화까지
    걸러진다 — SUBSTR 정확 일치여야 한다."""
    repo = get_threads_repo()
    repo.ensure_thread("qregX_real", user_id="u-1")
    rows, total = repo.list_admin(limit=10, exclude_prefixes=("qreg_",))
    assert total == 1
    assert rows[0]["id"] == "qregX_real"


def test_list_admin_offset_pagination_covers_all_rows():
    repo = get_threads_repo()
    for i in range(5):
        repo.ensure_thread(f"t_{i}", user_id="u-1")
    page1, total = repo.list_admin(limit=2, offset=0)
    page2, _ = repo.list_admin(limit=2, offset=2)
    page3, _ = repo.list_admin(limit=2, offset=4)
    assert total == 5
    ids = [r["id"] for r in page1 + page2 + page3]
    assert len(ids) == 5 and len(set(ids)) == 5


def test_list_admin_since_excludes_older_threads():
    repo = get_threads_repo()
    repo.ensure_thread("t_old", user_id="u-1")
    repo.ensure_thread("t_new", user_id="u-1")
    with repo._lock, repo._conn() as c:
        c.execute("UPDATE chat_threads SET updated_at = "
                  "'2026-08-01T00:00:00.000000Z' WHERE id = 't_old'")
    rows, total = repo.list_admin(
        limit=10, since="2026-08-03T00:00:00+00:00")
    assert total == 1
    assert [r["id"] for r in rows] == ["t_new"]


def _emit_question(repo, *, user_id, question, ts=None):
    from src.persistence.events_repo import Event
    from src.persistence._common import new_id, utcnow_iso
    import json

    repo.emit(Event(id=new_id(), ts=ts or utcnow_iso(),
                    event_type="user_question", user_id=user_id,
                    thread_id="t_x",
                    payload_json=json.dumps({"question": question})))


def test_events_list_by_type_sql_excludes():
    """user_question 페이지도 필터가 SQL(LIMIT 이전) — 익명·제외자 미포함."""
    from src.persistence import get_events_repo

    repo = get_events_repo()
    _emit_question(repo, user_id=None, question="스크립트")
    _emit_question(repo, user_id="u-admin", question="관리자")
    _emit_question(repo, user_id="u-1", question="실사용")
    events = repo.list_by_type(
        "user_question", limit=10,
        exclude_user_ids=("u-admin",), exclude_anonymous=True)
    assert [e.user_id for e in events] == ["u-1"]
    assert repo.count_by_type(
        "user_question",
        exclude_user_ids=("u-admin",), exclude_anonymous=True) == 1
    # scope=all 상당(필터 없음)은 전부.
    assert repo.count_by_type("user_question") == 3


def test_admin_questions_route_pagination():
    """/admin/questions 응답 계약 — total 은 페이지가 아니라 전체 건수."""
    from src.persistence import get_events_repo
    from src.routes.admin import admin_user_questions

    repo = get_events_repo()
    for i in range(5):
        _emit_question(repo, user_id="u-1", question=f"q{i}")
    res = admin_user_questions(days=30, limit=2, offset=0, scope="all")
    assert res["total"] == 5 and res["count"] == 2 and res["has_more"] is True
    # 랭킹·유저 수는 페이지가 아니라 기간 전체 기준.
    assert res["unique_users"] == 1
    assert len(res["top_questions"]) == 5
    res2 = admin_user_questions(days=30, limit=2, offset=4, scope="all")
    assert res2["count"] == 1 and res2["has_more"] is False
    assert res2["items"][0]["question"] == "q0"


def test_route_returns_pagination_fields():
    """응답 계약 — count/total/limit/offset/has_more(프런트 페이지 UI 소비)."""
    from src.routes.admin import admin_list_threads

    repo = get_threads_repo()
    for i in range(3):
        repo.ensure_thread(f"t_r{i}", user_id="u-1")
    res = admin_list_threads(limit=2, offset=0, scope="all")
    assert res["count"] == 2 and res["total"] == 3
    assert res["limit"] == 2 and res["offset"] == 0
    assert res["has_more"] is True
    res2 = admin_list_threads(limit=2, offset=2, scope="all")
    assert res2["count"] == 1 and res2["has_more"] is False


# ── 턴 소요시간 (2026-09-15, 관리자 요청) ───────────────────────────────
def test_annotate_turn_elapsed_marks_final_ai_only():
    from src.routes.admin import annotate_turn_elapsed

    views = [
        {"id": "h1", "type": "human", "content": "q"},
        {"id": "a1", "type": "ai", "content": "", "tool_calls": ["load_skill"]},
        {"id": "t1", "type": "tool", "content": "..."},
        {"id": "a2", "type": "ai", "content": "답"},
        {"id": "h2", "type": "human", "content": "q2"},
        {"id": "a3", "type": "ai", "content": "답2"},
        {"id": "h3", "type": "human", "content": "q3(진행 중)"},
    ]
    stamps = {
        "h1": "2026-09-14T22:44:26.482138+00:00", "a1": "2026-09-14T22:44:57+00:00",
        "t1": "2026-09-14T22:44:57+00:00", "a2": "2026-09-14T22:49:36.5+00:00",
        "h2": "2026-09-14 22:50:00+00:00", "a3": "2026-09-14 22:50:12+00:00",
        "h3": "2026-09-14T22:51:00Z",
    }
    turns = annotate_turn_elapsed(views, stamps)
    assert [t["elapsed_s"] for t in turns] == [310.0, 12.0]
    assert views[3]["elapsed_s"] == 310.0 and "elapsed_s" not in views[1]
    assert views[0]["created_at"] == stamps["h1"]
    assert turns[0]["human_id"] == "h1" and turns[0]["ai_id"] == "a2"
    # 시각이 없으면 조용히 생략
    assert annotate_turn_elapsed([{"id": "h", "type": "human"}, {"id": "a", "type": "ai"}], {}) == []


def test_admin_thread_route_reports_elapsed(tmp_path, monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage

    from src.persistence import threads_repo as tr
    from src.persistence.threads_repo import SqliteThreadsRepo
    from src.routes import admin as admin_routes

    repo = SqliteThreadsRepo(str(tmp_path / "t.db"))
    repo.ensure_thread("t_abc")
    repo.append_messages("t_abc", [HumanMessage(content="q", id="h1")])
    repo.append_messages("t_abc", [AIMessage(content="a", id="a1")])
    monkeypatch.setattr(tr, "get_threads_repo", lambda: repo)
    out = admin_routes.admin_get_thread("t_abc", _admin=None)
    assert len(out["turns"]) == 1 and out["turns"][0]["ai_id"] == "a1"
    assert out["messages"][1]["elapsed_s"] >= 0 and out["messages"][0]["created_at"]


def test_list_admin_excludes_internal_user_ids():
    """'실사용만' 대화 목록에 운영진(관리자)·테스트 계정 대화가 섞이면 안 된다
    (2026-09-22 신고 — 접두·익명만 거르고 계정 축을 빠뜨렸다)."""
    repo = get_threads_repo()
    repo.ensure_thread("t_admin", user_id="u-admin")
    repo.ensure_thread("t_real", user_id="u-1")
    rows, total = repo.list_admin(limit=10, require_user=True,
                                  exclude_user_ids=("u-admin",))
    assert total == 1
    assert [r["id"] for r in rows] == ["t_real"]


def test_admin_threads_route_hides_admin_accounts(monkeypatch):
    from src.persistence import get_users_repo
    from src.routes import admin as admin_routes

    get_users_repo().upsert(id="u-adm", email="boss@x.com", is_admin=True)
    get_users_repo().upsert(id="u-usr", email="user@x.com")
    repo = get_threads_repo()
    repo.ensure_thread("t_aaaaaaaaaaaa1111", user_id="u-adm")
    repo.ensure_thread("t_bbbbbbbbbbbb2222", user_id="u-usr")
    monkeypatch.setattr(admin_routes, "_launch_cutoff", lambda: "2000-01-01T00:00:00+00:00")
    from src import account_class
    account_class.invalidate()
    out = admin_routes.admin_list_threads(limit=50, offset=0, scope="real", _admin=None)
    ids = [t["thread_id"] for t in out["threads"]]
    assert "t_bbbbbbbbbbbb2222" in ids and "t_aaaaaaaaaaaa1111" not in ids
