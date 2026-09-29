"""관리자 답변 검수(2026-09-17) — 큐 선정 규칙·채점 저장·정답률 집계.

핵심 불변식: **무작위 표본은 신호와 독립**이어야 한다. 신호 표본의 오답률로
서비스 정답률을 말하면 구조적으로 과소평가된다(claim_audit 분모 사고와 같은 류).
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src import review_queue as rq


# ── 순수 로직 ──────────────────────────────────────────────────────────────

def _views():
    return [
        {"id": "h1", "type": "human", "content": "의료기기 허가 절차?"},
        {"id": "a0", "type": "ai", "content": "", "tool_calls": ["qdrant_search"]},
        {"id": "t1", "type": "tool", "content": "..."},
        {"id": "a1", "type": "ai", "content": "허가는 [1] 에 따르며 [2] 도 본다."},
        {"id": "h2", "type": "human", "content": "안녕"},
        {"id": "a2", "type": "ai", "content": "안녕하세요."},
    ]


def _steps():
    return [{
        "id": "s_1", "source_message_id": "h1", "tool_name": "qdrant_search",
        "citations": [
            {"number": 1, "title": "의료기기법 6조", "verified": True},
            {"number": 2, "title": "시행규칙 5조", "verified": False},
            {"number": 3, "title": "안 쓴 조문"},
        ],
    }]


def test_build_turns_pairs_final_answer_and_counts_used_citations():
    turns = rq.build_turns(_views(), {}, _steps())
    assert [t["message_id"] for t in turns] == ["a1", "a2"]
    t = turns[0]
    assert t["citations_retrieved"] == 3
    assert t["citations_used"] == 2          # [3] 은 본문에 없다
    assert t["verified_rate"] == 0.5
    assert turns[1]["verified_rate"] is None  # 인용 없는 턴은 0 이 아니라 None


def test_build_turns_skips_kind_tagged_ai_messages():
    views = [
        {"id": "h1", "type": "human", "content": "q"},
        {"id": "r1", "type": "ai", "content": "개요", "kind": "report_overview"},
        {"id": "a1", "type": "ai", "content": "답"},
    ]
    assert [t["message_id"] for t in rq.build_turns(views, {}, [])] == ["a1"]


def test_skill_lane_is_sticky_for_followup_turns():
    """스킬 로드 이후 턴은 도구 호출이 없어도 스킬 턴 — resolve_turn_skill 과 같은 규칙."""
    views = [
        {"id": "h0", "type": "human", "content": "일반 질문"},
        {"id": "a0", "type": "ai", "content": "답 [1]"},
        {"id": "h1", "type": "human", "content": "IRB 심의 대상인가요"},
        {"id": "x1", "type": "ai", "content": "", "tool_calls": ["load_skill"]},
        {"id": "a1", "type": "ai", "content": "판정"},
        {"id": "h2", "type": "human", "content": "추가 질문"},
        {"id": "a2", "type": "ai", "content": "후속 답"},
    ]
    turns = rq.build_turns(views, {}, [])
    assert [rq.is_skill_turn(t) for t in turns] == [False, True, True]


def test_window_events_tolerate_mixed_timestamp_formats():
    """SQLite('…Z')와 PG('+00:00') 표기가 섞여도 같은 창에 떨어진다."""
    turns = [
        {"message_id": "a1", "started_at": "2026-09-17T01:00:00.000000Z"},
        {"message_id": "a2", "started_at": "2026-09-17T02:00:00+00:00"},
    ]
    events = [
        {"type": "rag_search", "ts": "2026-09-17T01:00:05+00:00", "payload": {"hit_count": 0}},
        {"type": "rag_search", "ts": "2026-09-17T02:00:05.000000Z", "payload": {"hit_count": 8}},
    ]
    rq.attach_window_events(turns, events)
    assert turns[0]["_events"][0]["payload"]["hit_count"] == 0
    assert turns[1]["_events"][0]["payload"]["hit_count"] == 8


def test_score_turn_signals():
    base = {"citations_used": 0, "verified_rate": None, "truncated": False}
    forced = {"type": "user_question", "payload": {"forced_search": True}}
    hit = {"type": "rag_search", "payload": {"hit_count": 8}}
    miss = {"type": "rag_search", "payload": {"hit_count": 0}}

    assert rq.score_turn({**base, "_events": [forced, hit]}, feedback=[],
                         claim_audit=None, citation_reported=False) == ["no_citation"]
    assert rq.score_turn({**base, "_events": [forced, miss]}, feedback=[],
                         claim_audit=None, citation_reported=False) == ["search_empty"]
    # 스킬 턴은 설계상 [n] 인용이 없다 — 결함 신호가 아니다.
    skill = {"type": "skill_verdict", "payload": {}}
    assert rq.score_turn({**base, "_events": [forced, hit, skill]}, feedback=[],
                         claim_audit=None, citation_reported=False) == []
    for marker in ({"_events": [forced, hit, {"type": "user_question", "payload": {"skill": True}}]},
                   {"_events": [forced, hit], "tools_called": ["load_skill"]}):
        assert rq.score_turn({**base, **marker}, feedback=[],
                             claim_audit=None, citation_reported=False) == []
    # 캐주얼 턴(강제검색 아님)은 인용이 없어도 신호가 아니다.
    assert rq.score_turn({**base, "_events": []}, feedback=[],
                         claim_audit=None, citation_reported=False) == []
    # 👎 을 취소했으면(last-wins) 신호가 아니다.
    assert rq.score_turn(base, feedback=["canceled", "thumbs_down"],
                         claim_audit=None, citation_reported=False) == []
    assert "thumbs_down" in rq.score_turn(base, feedback=["thumbs_down"],
                                          claim_audit=None, citation_reported=False)
    # 인용 신고는 thumbs_down 으로도 저장된다 — 이중 계상하지 않는다.
    assert rq.score_turn(base, feedback=["thumbs_down"], claim_audit=None,
                         citation_reported=True) == ["citation_report"]
    assert rq.score_turn({**base, "verified_rate": 0.5}, feedback=[],
                         claim_audit={"contradicted": 1, "unverified": 2},
                         citation_reported=False) == ["claim_contradicted", "low_verified"]


def test_random_sample_is_deterministic_and_roughly_proportional():
    ids = [f"msg-{i}" for i in range(2000)]
    picked = [i for i in ids if rq.in_random_sample(i, 10)]
    assert picked == [i for i in ids if rq.in_random_sample(i, 10)]
    assert 140 <= len(picked) <= 260
    assert not any(rq.in_random_sample(i, 0) for i in ids)
    assert all(rq.in_random_sample(i, 100) for i in ids)


def test_wilson_interval():
    assert rq.wilson_interval(0, 0) is None
    lo, hi = rq.wilson_interval(18, 20)
    assert 0.68 < lo < 0.72 and 0.97 < hi < 0.99


# ── repo ──────────────────────────────────────────────────────────────────

def test_repo_upsert_is_per_reviewer():
    from src.persistence import get_answer_reviews_repo
    from src.persistence.answer_reviews_repo import AnswerReview

    repo = get_answer_reviews_repo()
    a = repo.upsert(AnswerReview(id="", thread_id="t1", message_id="m1",
                                 reviewer="a@x", verdict="wrong",
                                 error_types=["misapplied"]))
    b = repo.upsert(AnswerReview(id="", thread_id="t1", message_id="m1",
                                 reviewer="a@x", verdict="partial",
                                 error_types=["incomplete"], note="예외 누락"))
    assert a == b                                    # 재채점은 덮어쓴다
    repo.upsert(AnswerReview(id="", thread_id="t1", message_id="m1",
                             reviewer="b@x", verdict="correct"))
    rows = repo.list_for_thread("t1")
    assert len(rows) == 2
    mine = next(r for r in rows if r.reviewer == "a@x")
    assert (mine.verdict, mine.error_types, mine.note) == ("partial", ["incomplete"], "예외 누락")
    assert repo.reviewed_message_ids() == {"m1"}


def test_repo_rejects_unknown_values():
    from src.persistence import get_answer_reviews_repo
    from src.persistence.answer_reviews_repo import AnswerReview

    repo = get_answer_reviews_repo()
    with pytest.raises(ValueError):
        repo.upsert(AnswerReview(id="", thread_id="t", message_id="m",
                                 reviewer="a", verdict="meh"))
    with pytest.raises(ValueError):
        repo.upsert(AnswerReview(id="", thread_id="t", message_id="m", reviewer="a",
                                 verdict="wrong", error_types=["typo"]))


# ── 라우트(함수 직접 호출 — 인증은 아래 별도 테스트) ────────────────────────

def _seed_thread(tid="t_real", uid="u-1", suffix=""):
    from src.persistence import get_events_repo
    from src.persistence.events_repo import Event
    from src.persistence.threads_repo import get_threads_repo

    repo = get_threads_repo()
    repo.ensure_thread(tid, user_id=uid)
    ev = get_events_repo()
    # 실제 턴과 같은 순서로 적재한다 — human 저장 → user_question emit → 답변 저장.
    # 시각 창 매칭이 이 순서에 기대므로 픽스처가 뒤섞이면 다른 턴에 붙는다.
    repo.append_messages(tid, [HumanMessage(content="체외진단기기 허가 요건?", id="h1" + suffix)])
    ev.emit(Event(id="", ts="", event_type="user_question", user_id=uid, thread_id=tid,
                  payload_json=json.dumps({"question": "q", "forced_search": True})))
    # 강제검색인데 인용 없음 + 출처와 모순되는 무인용 사실.
    repo.append_messages(tid, [AIMessage(content="요건은 다음과 같습니다.", id="a1" + suffix)])
    ev.emit(Event(id="", ts="", event_type="claim_audit", user_id=uid, thread_id=tid,
                  message_id="a1" + suffix + suffix,
                  payload_json=json.dumps({"total": 2, "supported": 1, "contradicted": 1,
                                           "unverified": 0,
                                           "samples": [{"claim": "30일", "verdict": "contradicted"}]})))
    repo.append_messages(tid, [HumanMessage(content="고마워", id="h2" + suffix)])
    ev.emit(Event(id="", ts="", event_type="user_question", user_id=uid, thread_id=tid,
                  payload_json=json.dumps({"question": "고마워", "forced_search": False})))
    repo.append_messages(tid, [AIMessage(content="도움이 되어 기쁩니다.", id="a2" + suffix)])


class _Req:
    class state:  # noqa: N801
        user_email = "admin@x"


def test_queue_surfaces_signal_turn_and_hides_after_review(monkeypatch):
    from src.routes import admin_reviews as R

    _seed_thread()
    out = R.admin_review_queue(days=14, limit=50, random_pct=0, scope="all", _admin=True)
    assert out["turns_scanned"] == 2
    assert [i["message_id"] for i in out["items"]] == ["a1"]   # 'a2' 는 신호 없음
    item = out["items"][0]
    assert "claim_contradicted" in item["signals"]
    assert item["claim_samples"][0]["claim"] == "30일"
    assert item["random_sample"] is False

    R.admin_save_review(R.ReviewIn(thread_id="t_real", message_id="a1", verdict="wrong",
                                   error_types=["fabricated"]), _Req, _admin=True)
    assert R.admin_review_queue(days=14, random_pct=0, scope="all", _admin=True)["items"] == []
    again = R.admin_review_queue(days=14, random_pct=0, scope="all",
                                 include_reviewed=True, _admin=True)
    assert again["items"][0]["reviewed"] is True


def test_real_scope_excludes_admin_and_prelaunch_accounts(monkeypatch):
    """scope=real 큐엔 베타 사용자 답변만 — 관리자 시연·오픈 전 가입(테스트) 계정은 뺀다.

    실측(2026-09-17): 스레드 필터가 계정 종류를 안 봐서 30일 104턴 중 87턴이 내부 질문이었다.
    그 상태로 채점하면 '서비스 정답률'이 우리 질문의 정답률이 된다.
    """
    from src.persistence import get_users_repo
    from src.routes import admin_reviews as R

    monkeypatch.setenv("SERVICE_LAUNCH_AT", "2020-01-01T00:00:00+00:00")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    users = get_users_repo()
    users.upsert(id="u-beta", email="doc@hospital.kr")
    users.upsert(id="u-admin", email="boss@example.com")
    users.upsert(id="u-old", email="dev@example.com")
    with users._lock, users._conn() as c:   # 오픈 전 가입으로 되돌린다
        c.execute("UPDATE users SET created_at = '2019-06-01T00:00:00.000000Z' WHERE id = 'u-old'")
    # 실제 형식의 thread id — hex 가 아닌 `t_이름` 은 내부 트래픽 규칙에 걸린다.
    t_beta, t_admin, t_old = ("t_" + c * 32 for c in "abc")
    for tid, uid in ((t_beta, "u-beta"), (t_admin, "u-admin"), (t_old, "u-old")):
        _seed_thread(tid=tid, uid=uid, suffix=tid)

    real = R.admin_review_queue(days=14, random_pct=0, scope="real", _admin=True)
    assert {i["thread_id"] for i in real["items"]} == {t_beta}
    assert real["threads_scanned"] == 1
    everything = R.admin_review_queue(days=14, random_pct=0, scope="all", _admin=True)
    assert {i["thread_id"] for i in everything["items"]} == {t_beta, t_admin, t_old}


def test_queue_random_sample_includes_clean_turns():
    from src.routes import admin_reviews as R

    _seed_thread()
    out = R.admin_review_queue(days=14, random_pct=100, scope="all", _admin=True)
    by_id = {i["message_id"]: i for i in out["items"]}
    assert set(by_id) == {"a1", "a2"}
    assert by_id["a2"]["signals"] == [] and by_id["a2"]["random_sample"] is True
    # 신호 턴도 표본에 뽑혔으면 표본이다 — 신호와 독립.
    assert by_id["a1"]["random_sample"] is True
    assert out["items"][0]["message_id"] == "a1"               # 점수순


def test_save_review_clears_error_types_on_correct_and_404s_unknown_thread():
    from fastapi import HTTPException

    from src.persistence import get_answer_reviews_repo
    from src.routes import admin_reviews as R

    _seed_thread()
    R.admin_save_review(R.ReviewIn(thread_id="t_real", message_id="a2", verdict="correct",
                                   error_types=["other"]), _Req, _admin=True)
    row = get_answer_reviews_repo().list_for_thread("t_real")[0]
    assert row.error_types == [] and row.reviewer == "admin@x"

    with pytest.raises(HTTPException) as ei:
        R.admin_save_review(R.ReviewIn(thread_id="nope", message_id="x", verdict="correct"),
                            _Req, _admin=True)
    assert ei.value.status_code == 404
    with pytest.raises(HTTPException) as ei:
        R.admin_save_review(R.ReviewIn(thread_id="t_real", message_id="a2", verdict="meh"),
                            _Req, _admin=True)
    assert ei.value.status_code == 422


def test_stats_separate_random_sample_accuracy():
    from src.routes import admin_reviews as R

    _seed_thread()
    R.admin_save_review(R.ReviewIn(thread_id="t_real", message_id="a1", verdict="wrong",
                                   error_types=["fabricated", "incomplete"]), _Req, _admin=True)
    R.admin_save_review(R.ReviewIn(thread_id="t_real", message_id="a2", verdict="correct"),
                        _Req, _admin=True)
    none = R.admin_review_stats(days=30, random_pct=0, _admin=True)
    assert none["reviewed"] == 2
    assert none["accuracy_random"]["n"] == 0 and none["accuracy_random"]["strict"] is None
    assert none["accuracy_all_reviewed"]["strict"] == 0.5
    assert none["error_types"] == {"fabricated": 1, "incomplete": 1}
    full = R.admin_review_stats(days=30, random_pct=100, _admin=True)
    assert full["accuracy_random"]["n"] == 2
    assert full["accuracy_random"]["strict_ci95"] is not None


def test_routes_require_admin():
    from fastapi.testclient import TestClient

    from src.api import app

    c = TestClient(app)
    assert c.get("/admin/review-queue").status_code in (401, 403)
    assert c.get("/admin/reviews/stats").status_code in (401, 403)
    assert c.get("/admin/reviews/archive").status_code in (401, 403)
    assert c.post("/admin/reviews", json={"thread_id": "t", "message_id": "m",
                                          "verdict": "correct"}).status_code in (401, 403)


def test_http_flow_queue_review_stats(monkeypatch):
    """HTTP 전 구간 — 관리자 JWT 로 큐 조회 → 채점 → 재채점 → 집계, 비관리자는 403.

    함수 직접 호출 테스트는 미들웨어·의존성 주입·pydantic 바디 파싱·reviewer 식별을
    건너뛴다. 드물게 타는 관리자 경로라 e2e 로 한 번 묶어 둔다.
    """
    import time

    import jwt as pyjwt
    from fastapi.testclient import TestClient

    secret = "test-secret-for-answer-reviews-0123456789"
    monkeypatch.setenv("NEXTAUTH_SECRET", secret)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")

    def tok(sub, email):
        now = int(time.time())
        return {"Authorization": "Bearer " + pyjwt.encode(
            {"sub": sub, "email": email, "email_verified": True,
             "iat": now, "exp": now + 3600}, secret, algorithm="HS256")}

    from src.api import app

    c = TestClient(app)
    admin, user = tok("admin-1", "boss@example.com"), tok("u-9", "alice@example.com")
    _seed_thread()

    assert c.get("/admin/review-queue", headers=user).status_code == 403

    q = c.get("/admin/review-queue?days=14&random_pct=0&scope=all", headers=admin)
    assert q.status_code == 200, q.text
    body = q.json()
    assert [i["message_id"] for i in body["items"]] == ["a1"]
    assert body["items"][0]["lane"] == "rag"
    assert "wrong" in body["verdicts"] and "fabricated" in body["error_types"]

    payload = {"thread_id": "t_real", "message_id": "a1", "verdict": "wrong",
               "error_types": ["fabricated"], "note": "기한 날조"}
    r1 = c.post("/admin/reviews", json=payload, headers=admin)
    assert r1.status_code == 201, r1.text
    r2 = c.post("/admin/reviews", json={**payload, "verdict": "partial"}, headers=admin)
    assert r2.json()["review_id"] == r1.json()["review_id"]          # 재채점 = 덮어쓰기
    assert c.post("/admin/reviews", json={**payload, "verdict": "meh"},
                  headers=admin).status_code == 422
    assert c.post("/admin/reviews", json=payload, headers=user).status_code == 403

    rows = c.get("/admin/reviews?thread_id=t_real", headers=admin).json()["reviews"]
    assert len(rows) == 1
    assert (rows[0]["verdict"], rows[0]["reviewer"]) == ("partial", "boss@example.com")

    assert c.get("/admin/review-queue?days=14&random_pct=0&scope=all",
                 headers=admin).json()["items"] == []                # 채점된 턴은 큐에서 빠진다
    st = c.get("/admin/reviews/stats?days=30&random_pct=100", headers=admin).json()
    assert st["verdicts"] == {"partial": 1}
    assert st["accuracy_random"]["n"] == 1 and st["accuracy_random"]["lenient"] == 1.0


# ── 채점 내용 보존(2026-09-18) — 대화가 90일 뒤 지워져도 채점 근거는 남는다 ──

def test_review_keeps_question_and_answer_after_thread_is_pruned():
    from src.persistence import get_answer_reviews_repo
    from src.persistence.threads_repo import get_threads_repo
    from src.routes import admin_reviews as R

    _seed_thread()
    R.admin_save_review(R.ReviewIn(thread_id="t_real", message_id="a1", verdict="wrong",
                                   error_types=["misapplied"], note="조문 오적용"),
                        _Req, _admin=True)
    row = get_answer_reviews_repo().list_for_thread("t_real")[0]
    assert row.question_snapshot == "체외진단기기 허가 요건?"
    assert row.answer_snapshot == "요건은 다음과 같습니다."

    # 보존기간 경과 = thread 삭제. 채점 행과 스냅샷은 남는다.
    get_threads_repo().delete_thread("t_real")
    arch = R.admin_review_archive(days=30, limit=50, verdict=None, _admin=True)
    assert arch["total"] == 1
    item = arch["items"][0]
    assert item["thread_alive"] is False
    assert item["question_snapshot"] == "체외진단기기 허가 요건?"
    assert item["answer_snapshot"] == "요건은 다음과 같습니다."
    assert item["verdict"] == "wrong" and item["note"] == "조문 오적용"
    # 사용자 식별자는 스냅샷에 싣지 않는다
    assert "user_id" not in item and "u-1" not in json.dumps(item, ensure_ascii=False)


def test_regrade_without_thread_keeps_existing_snapshot():
    from src.persistence import get_answer_reviews_repo
    from src.persistence.answer_reviews_repo import AnswerReview

    repo = get_answer_reviews_repo()
    repo.upsert(AnswerReview(id="", thread_id="t", message_id="m", reviewer="a",
                             verdict="partial", question_snapshot="Q", answer_snapshot="A"))
    # 스냅샷 없이 재채점(원 대화가 이미 없을 때) — 기존 스냅샷을 지우지 않는다.
    repo.upsert(AnswerReview(id="", thread_id="t", message_id="m", reviewer="a",
                             verdict="wrong"))
    row = repo.list_for_thread("t")[0]
    assert row.verdict == "wrong"
    assert (row.question_snapshot, row.answer_snapshot) == ("Q", "A")


def test_archive_filters_by_verdict():
    from src.routes import admin_reviews as R

    _seed_thread()
    R.admin_save_review(R.ReviewIn(thread_id="t_real", message_id="a1", verdict="wrong",
                                   error_types=["other"]), _Req, _admin=True)
    R.admin_save_review(R.ReviewIn(thread_id="t_real", message_id="a2", verdict="correct"),
                        _Req, _admin=True)
    assert R.admin_review_archive(days=30, limit=50, verdict="wrong", _admin=True)["total"] == 1
    assert R.admin_review_archive(days=30, limit=50, verdict=None, _admin=True)["total"] == 2


# ── 관리자 식별 메모가 다른 관리자 화면에도 따라온다(2026-09-18) ───────────

def test_admin_memo_follows_user_across_admin_views():
    from src.persistence import get_users_repo
    from src.routes import admin as A
    from src.routes import admin_reviews as R

    users = get_users_repo()
    uid = "u-memo"
    users.upsert(id=uid, email="noprofile@example.com")
    users.set_admin_memo(uid, "OO대 김교수(내과)")
    _seed_thread(tid="t_memo", uid=uid)

    look = A.AdminUserLookup()
    assert look.get(uid)["admin_memo"] == "OO대 김교수(내과)"
    assert look.prefixed(uid)["user_admin_memo"] == "OO대 김교수(내과)"
    assert look.get(None) == {} and look.get("nope") == {}

    detail = A.admin_get_thread("t_memo", _admin=True)
    assert detail["user_admin_memo"] == "OO대 김교수(내과)"
    assert detail["user_email"] == "noprofile@example.com"

    q = R.admin_review_queue(days=30, limit=50, include_reviewed=True, random_pct=100,
                             scope="all", _admin=True)
    mine = [i for i in q["items"] if i["thread_id"] == "t_memo"]
    assert mine and mine[0]["user_admin_memo"] == "OO대 김교수(내과)"
