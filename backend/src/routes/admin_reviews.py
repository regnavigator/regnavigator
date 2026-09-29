"""관리자 답변 검수(2026-09-17) — 정답성을 사람이 채점하는 경로.

- GET  /admin/review-queue   — 검수할 턴 목록(위험 신호 우선 + 무작위 표본).
- POST /admin/reviews        — 채점 저장(답변 1건 × 검수자 1행, 재채점은 덮어씀).
- GET  /admin/reviews        — thread 의 채점 이력(원문 뷰어에 배지로 얹는 용도).
- GET  /admin/reviews/stats  — 판정·오류유형 분포 + **무작위 표본 정답률**(신뢰구간).

뽑는 규칙은 `src/review_queue.py`(순수 함수). 여긴 DB 를 읽어 넘겨줄 뿐이다.
전부 동기 DB 라 `def`(스레드풀) — 라우트 async 규약.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src import review_queue as rq
from src.middleware import require_admin
from src.persistence.answer_reviews_repo import ERROR_TYPES, VERDICTS

_log = logging.getLogger(__name__)
router = APIRouter()

# 큐 1회 빌드가 읽는 thread 상한 — thread 마다 상태를 복원하므로 무한정 늘리지 않는다.
# 베타 규모(주 수십 thread)에선 닿지 않는다. 닿으면 응답의 `threads_capped` 가 알린다.
_MAX_THREADS = 300
_SIGNAL_EVENT_TYPES = ("claim_audit", "rag_search", "user_question", "citation_report",
                       "skill_verdict", "identifier_audit")
_TEXT_PREVIEW = 400


class ReviewIn(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)
    message_id: str = Field(min_length=1, max_length=200)
    verdict: str
    error_types: list[str] = Field(default_factory=list)
    note: Optional[str] = Field(default=None, max_length=4000)


def _since_iso(days: int, scope: str) -> str:
    from src.routes.admin import _scope_since

    raw = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
    return _scope_since(scope, raw)


def _excluded_user_ids(scope: str) -> frozenset:
    """scope=real 에서 검수 대상이 아닌 계정 — 운영진·테스트(내부) 계정.

    2026-09-17 에 여기만 따로 "관리자 + 오픈 전 가입"을 뺐다. 2026-09-21 부터는
    `src/account_class.py`(관리자 라벨 + 같은 자동 규칙)가 정본이고 이용 조회·통계와
    같은 집합을 쓴다.
    """
    from src.routes.admin import _excluded_admin_user_ids

    return _excluded_admin_user_ids(scope)


def _events_by_thread(since: str, scope: str) -> dict[str, list[dict]]:
    from src.persistence import get_events_repo
    from src.routes.admin import _drop_test_events

    excl = _excluded_user_ids(scope)
    out: dict[str, list[dict]] = {}
    repo = get_events_repo()
    for et in _SIGNAL_EVENT_TYPES:
        for ev in _drop_test_events(repo.list_by_type(et, since=since, limit=20000), scope, excl):
            if not ev.thread_id:
                continue
            try:
                payload = json.loads(ev.payload_json or "{}")
            except Exception:  # noqa: BLE001
                payload = {}
            out.setdefault(ev.thread_id, []).append({
                "type": ev.event_type, "ts": ev.ts,
                "message_id": ev.message_id, "payload": payload,
            })
    return out


def _thread_turns(thread_id: str, events: list[dict]) -> list[dict]:
    """thread 1개 → 신호가 매겨진 턴 목록."""
    from src.persistence import get_feedback_repo
    from src.persistence.threads_repo import get_threads_repo
    from src.routes.chat import _message_view

    repo = get_threads_repo()
    state = repo.get_state(thread_id)
    views = [_message_view(m) for m in state.messages]
    try:
        stamps = repo.message_created_at(thread_id)
    except Exception:  # noqa: BLE001 — 시각이 없으면 창 매칭만 빠진다(id 기반 신호는 유지)
        _log.exception("message_created_at 실패 — thread=%s", thread_id)
        stamps = {}
    turns = rq.build_turns(views, stamps, state.steps)
    # message_id 없는 이벤트(rag_search·user_question, 그리고 2026-09-17 이전의
    # claim_audit)는 시각 창으로 붙인다.
    rq.attach_window_events(turns, [e for e in events if not e.get("message_id")])

    ratings: dict[str, list[str]] = {}
    for fb in get_feedback_repo().list_for_thread(thread_id):  # 최신순
        if fb.message_id:
            ratings.setdefault(fb.message_id, []).append(fb.rating)
    audits = {e["message_id"]: e["payload"] for e in events
              if e["type"] == "claim_audit" and e.get("message_id")}
    idents = {e["message_id"]: e["payload"] for e in events
              if e["type"] == "identifier_audit" and e.get("message_id")}
    reported = {e["message_id"] for e in events
                if e["type"] == "citation_report" and e.get("message_id")}

    for t in turns:
        mid = t.get("message_id") or ""
        audit = audits.get(mid)
        if audit is None:
            audit = next((e["payload"] for e in t.get("_events") or []
                          if e["type"] == "claim_audit"), None)
        t["signals"] = rq.score_turn(
            t, feedback=ratings.get(mid, []), claim_audit=audit,
            citation_reported=mid in reported, identifier_audit=idents.get(mid))
        t["identifier_audit"] = idents.get(mid)
        t["lane"] = "skill" if rq.is_skill_turn(t) else "rag"
        t["claim_samples"] = (audit or {}).get("samples") or []
        t["searches"] = [
            {"query": (e["payload"] or {}).get("query"),
             "hit_count": (e["payload"] or {}).get("hit_count"),
             "top_hits": ((e["payload"] or {}).get("hits") or [])[:5]}
            for e in t.get("_events") or [] if e["type"] == "rag_search"
        ]
        t.pop("_events", None)
    return turns


@router.get("/admin/review-queue")
def admin_review_queue(days: int = 14, limit: int = 50, random_pct: int = 10,
                       include_reviewed: bool = False, scope: str = "real",
                       _admin=Depends(require_admin)):
    """검수할 턴 — 위험 신호 점수순, 그 뒤 무작위 표본.

    `random_sample=true` 인 턴은 신호 유무와 무관하게 해시로 뽑힌 것 — 이 집합의
    채점만 서비스 정답률 추정에 쓴다(/admin/reviews/stats).
    """
    from src.persistence import get_answer_reviews_repo
    from src.persistence.threads_repo import get_threads_repo
    from src.routes.admin import (
        _INTERNAL_THREAD_PREFIXES_ALL,
        _is_real_scope,
        is_internal_thread,
    )

    limit = max(1, min(limit, 200))
    random_pct = max(0, min(random_pct, 100))
    since = _since_iso(days, scope)
    real = _is_real_scope(scope)

    rows, total_threads = get_threads_repo().list_admin(
        limit=_MAX_THREADS, offset=0, since=since,
        exclude_prefixes=_INTERNAL_THREAD_PREFIXES_ALL if real else (),
        require_user=real,
        # 내부 계정은 SQL 에서 — 사후 필터만 두면 운영진 대화가 상한을 잡아먹는다.
        exclude_user_ids=tuple(_excluded_user_ids(scope)))
    if real:
        excl = _excluded_user_ids(scope)
        rows = [r for r in rows
                if not is_internal_thread(r.get("id") or "", r.get("user_id"))
                and r.get("user_id") not in excl]

    events = _events_by_thread(since, scope)
    reviewed = get_answer_reviews_repo().reviewed_message_ids()

    items: list[dict] = []
    from src.routes.admin import AdminUserLookup
    _users = AdminUserLookup()
    turns_seen = 0
    for r in rows:
        tid = r["id"]
        try:
            turns = _thread_turns(tid, events.get(tid, []))
        except Exception:  # noqa: BLE001 — 한 thread 복원 실패가 큐 전체를 막지 않게
            _log.exception("검수 큐: thread 복원 실패 — %s", tid)
            continue
        for t in turns:
            mid = t.get("message_id")
            if not mid:
                continue
            turns_seen += 1
            is_random = rq.in_random_sample(mid, random_pct)
            if not t["signals"] and not is_random:
                continue
            is_reviewed = mid in reviewed
            if is_reviewed and not include_reviewed:
                continue
            items.append({
                "thread_id": tid,
                "user_id": r.get("user_id"),
                **_users.prefixed(r.get("user_id")),
                "thread_title": r.get("title"),
                "message_id": mid,
                "started_at": t.get("started_at"),
                "question": t["question"][:_TEXT_PREVIEW],
                "answer_preview": t["answer"][:_TEXT_PREVIEW],
                "lane": t["lane"],   # rag | skill(기관 지침 스킬 — 인용 축 미적용)
                "signals": t["signals"],
                "priority": rq.priority(t["signals"]),
                "random_sample": is_random,
                "reviewed": is_reviewed,
                "citations_retrieved": t["citations_retrieved"],
                "citations_used": t["citations_used"],
                "verified_rate": t["verified_rate"],
                "claim_samples": t["claim_samples"],
                "identifier_audit": t["identifier_audit"],
                "searches": t["searches"],
            })

    # 점수 높은 순, 같은 점수면 최근 것부터(안정 정렬 2회).
    items.sort(key=lambda i: i.get("started_at") or "", reverse=True)
    items.sort(key=lambda i: i["priority"], reverse=True)
    return {
        "days": days,
        "scope": "real" if real else "all",
        "random_pct": random_pct,
        "threads_scanned": len(rows),
        "threads_capped": total_threads > _MAX_THREADS,
        "turns_scanned": turns_seen,
        "queue_total": len(items),
        "signal_counts": dict(Counter(s for i in items for s in i["signals"])),
        "items": items[:limit],
        "verdicts": list(VERDICTS),
        "error_types": list(ERROR_TYPES),
    }


@router.post("/admin/reviews", status_code=201)
def admin_save_review(body: ReviewIn, request: Request, _admin=Depends(require_admin)):
    from src.persistence import get_answer_reviews_repo
    from src.persistence.answer_reviews_repo import AnswerReview
    from src.persistence.threads_repo import get_threads_repo

    if not get_threads_repo().get_meta(body.thread_id):
        raise HTTPException(status_code=404, detail="thread not found")
    reviewer = (getattr(request.state, "user_email", None)
                or getattr(_admin, "email", None) or getattr(_admin, "id", None) or "admin")
    q_snap, a_snap = _turn_snapshot(body.thread_id, body.message_id)
    review = AnswerReview(
        id="", thread_id=body.thread_id, message_id=body.message_id,
        reviewer=str(reviewer), verdict=body.verdict,
        # correct 에 오류 유형이 붙으면 분포가 오염된다 — 서버에서 비운다.
        error_types=[] if body.verdict == "correct" else list(dict.fromkeys(body.error_types)),
        note=(body.note or "").strip() or None,
        question_snapshot=q_snap, answer_snapshot=a_snap)
    try:
        rid = get_answer_reviews_repo().upsert(review)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ok": True, "review_id": rid}


def _turn_snapshot(thread_id: str, message_id: str) -> tuple[Optional[str], Optional[str]]:
    """채점 대상 턴의 (질문, 답변) — 대화 저장본(마스킹본) 그대로.

    대화는 90일 뒤 지워진다(`prune_threads`). 채점한 턴만은 근거를 남겨야 정답률을
    나중에 되짚을 수 있어 채점 시점에 복사해 둔다(2026-09-18). 못 찾으면 (None, None)
    — 재채점 upsert 는 COALESCE 라 기존 스냅샷을 지우지 않는다.
    """
    from src.persistence.threads_repo import get_threads_repo
    from src.routes.chat import _message_view
    try:
        repo = get_threads_repo()
        state = repo.get_state(thread_id)
        views = [_message_view(m) for m in state.messages]
        for t in rq.build_turns(views, {}, state.steps):
            if t.get("message_id") == message_id:
                return (t.get("question") or None, t.get("answer") or None)
    except Exception:  # noqa: BLE001 — 스냅샷 실패가 채점 저장을 막으면 안 된다
        _log.exception("review snapshot 실패 thread=%s message=%s", thread_id, message_id)
    return None, None


@router.get("/admin/reviews/archive")
def admin_review_archive(days: int = 365, limit: int = 200, verdict: Optional[str] = None,
                         _admin=Depends(require_admin)):
    """채점 내역 — 질문·답변 스냅샷 포함. 원 대화가 보존기간(90일)으로 지워진 뒤에도
    무엇을 어떻게 채점했는지 볼 수 있다. `thread_alive` 로 원 대화 존재 여부를 알린다."""
    from datetime import datetime, timedelta, timezone
    from src.persistence import get_answer_reviews_repo
    from src.persistence.threads_repo import get_threads_repo

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")
    rows = get_answer_reviews_repo().list_since(since, limit=max(1, min(limit, 1000)))
    if verdict:
        rows = [r for r in rows if r.verdict == verdict]
    threads = get_threads_repo()
    alive: dict[str, bool] = {}
    items = []
    for r in rows:
        if r.thread_id not in alive:
            alive[r.thread_id] = bool(threads.get_meta(r.thread_id))
        d = r.as_dict()
        d["thread_alive"] = alive[r.thread_id]
        items.append(d)
    return {"days": days, "total": len(items), "items": items}


@router.get("/admin/reviews")
def admin_list_reviews(thread_id: str, _admin=Depends(require_admin)):
    from src.persistence import get_answer_reviews_repo

    return {"thread_id": thread_id,
            "reviews": [r.as_dict() for r in get_answer_reviews_repo().list_for_thread(thread_id)]}


@router.get("/admin/reviews/stats")
def admin_review_stats(days: int = 30, random_pct: int = 10,
                       _admin=Depends(require_admin)):
    """검수 집계. `accuracy_random` 만이 서비스 정답률의 추정치다.

    - strict  = correct / (correct+partial+wrong)
    - lenient = (correct+partial) / 같은 분모.  unratable 은 분모에서 뺀다.
    같은 답변을 여러 명이 채점했으면 가장 최근 채점 1건만 센다.
    `random_pct` 는 큐를 볼 때 쓴 값과 같아야 한다(표본 재판정이 해시 기반).
    """
    from src.persistence import get_answer_reviews_repo

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")
    latest: dict[str, object] = {}
    for r in get_answer_reviews_repo().list_since(since):  # 최신순 → 첫 등장이 최신
        latest.setdefault(r.message_id, r)
    reviews = list(latest.values())

    def _acc(rs: list) -> dict:
        c = Counter(r.verdict for r in rs)
        n = c["correct"] + c["partial"] + c["wrong"]
        return {
            "n": n,
            "strict": round(c["correct"] / n, 4) if n else None,
            "strict_ci95": rq.wilson_interval(c["correct"], n),
            "lenient": round((c["correct"] + c["partial"]) / n, 4) if n else None,
            "lenient_ci95": rq.wilson_interval(c["correct"] + c["partial"], n),
        }

    random_set = [r for r in reviews if rq.in_random_sample(r.message_id, random_pct)]
    flawed = [r for r in reviews if r.verdict in ("partial", "wrong")]
    return {
        "days": days,
        "random_pct": random_pct,
        "reviewed": len(reviews),
        "verdicts": dict(Counter(r.verdict for r in reviews)),
        "error_types": dict(Counter(e for r in flawed for e in r.error_types)),
        "accuracy_random": _acc(random_set),
        # 참고용 — 신호 표본이 섞여 있어 실제보다 낮게 나온다.
        "accuracy_all_reviewed": _acc(reviews),
    }
