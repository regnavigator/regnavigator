"""만족도 평가 — 메시지·보고서 단위(👍/👎 + 코멘트) + @feedback 자유 코멘트 + admin 조회."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from src.middleware import require_admin
from src.persistence import (
    Event,
    Feedback,
    get_events_repo,
    get_feedback_repo,
    get_reports_repo,
)
from src.routes._shared import (
    _check_auth,
    _utcnow_iso_safe,
    assert_report_access,
    assert_thread_access,
)

_log = logging.getLogger(__name__)

router = APIRouter()


def _validate_feedback(body: dict) -> tuple[str, Optional[str]]:
    """rating·comment 검증. langgraph user_router 내부 import 시 Pydantic
    TypeAdapter 빌드 실패하는 케이스 회피 — dict로 받아 수동 검증.
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be JSON object")
    rating = body.get("rating")
    # "canceled" = 따봉 재클릭 취소(2026-07-16). 저장은 append-only —
    # 분석 시 (user,message) 최신 row 가 유효 평가(last-wins).
    if rating not in ("thumbs_up", "thumbs_down", "canceled"):
        raise HTTPException(status_code=422,
                            detail="rating must be 'thumbs_up' | 'thumbs_down' | 'canceled'")
    comment = body.get("comment")
    if comment is not None:
        if not isinstance(comment, str):
            raise HTTPException(status_code=422, detail="comment must be string")
        if len(comment) > 2000:
            raise HTTPException(status_code=422, detail="comment too long (max 2000)")
    return rating, comment


@router.post("/threads/{thread_id}/messages/{message_id}/feedback")
async def submit_message_feedback(
    thread_id: str,
    message_id: str,
    request: Request,
):
    """ai 메시지에 대한 사용자 평가."""
    body = await request.json()
    rating, comment = _validate_feedback(body)
    # 남의 thread 에 평가를 꽂지 못하게 — 없으면 임의 thread_id 로 👎·코멘트를
    # 대량 주입해 운영 지표와 관리자 다이제스트를 오염시킬 수 있다(2026-08-04 H-6).
    await asyncio.to_thread(assert_thread_access, thread_id, request)
    user_id = getattr(request.state, "user_id", None)
    fb = Feedback(
        id="",
        rating=rating,
        user_id=user_id,
        thread_id=thread_id,
        message_id=message_id,
        comment=comment,
    )
    fid = get_feedback_repo().create(fb)

    # 분석 일관성을 위해 events에도 동시 emit
    try:
        get_events_repo().emit(Event(
            id="", ts="",
            event_type="feedback",
            user_id=user_id,
            thread_id=thread_id,
            message_id=message_id,
            payload_json=json.dumps({
                "rating": rating,
                "has_comment": bool(comment),
                "comment_length": len(comment or ""),
                "target": "message",
            }, ensure_ascii=False),
        ))
    except Exception:
        pass

    return {"feedback_id": fid, "rating": rating}


@router.post("/reports/{report_id}/feedback")
async def submit_report_feedback(
    report_id: str,
    request: Request,
):
    """심층 보고서에 대한 사용자 평가."""
    body = await request.json()
    rating, comment = _validate_feedback(body)
    user_id = getattr(request.state, "user_id", None)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    # 소유권 검사 없이 404/200 을 갈라 주면 임의 report_id 의 존재·thread·kind 를
    # 확인하는 열거 오라클이 된다 — 조회 라우트 소유권 검사(2026-08-04)와 짝.
    assert_report_access(meta, request)

    fb = Feedback(
        id="",
        rating=rating,
        user_id=user_id,
        thread_id=meta.thread_id,
        report_id=report_id,
        comment=comment,
    )
    fid = get_feedback_repo().create(fb)

    try:
        get_events_repo().emit(Event(
            id="", ts="",
            event_type="feedback",
            user_id=user_id,
            thread_id=meta.thread_id,
            payload_json=json.dumps({
                "rating": rating,
                "has_comment": bool(comment),
                "comment_length": len(comment or ""),
                "target": "report",
                "report_id": report_id,
                "kind": meta.kind,
            }, ensure_ascii=False),
        ))
    except Exception:
        pass

    return {"feedback_id": fid, "rating": rating}


def _validate_general_feedback(body: dict) -> tuple[str, dict]:
    """comment + optional context 검증."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be JSON object")
    comment = body.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        raise HTTPException(status_code=422, detail="comment must be non-empty string")
    if len(comment) > 2000:
        raise HTTPException(status_code=422, detail="comment too long (max 2000)")
    context = body.get("context") or {}
    if not isinstance(context, dict):
        raise HTTPException(status_code=422, detail="context must be JSON object")
    return comment.strip(), context


@router.post("/feedback/general")
async def submit_general_feedback(request: Request):
    """프런트에서 사용자가 `@feedback ...` 입력 시 호출.

    body:
      - comment (str, required, ≤2000자)
      - context (object, optional): { thread_id?, last_message_id?, page?, ... }

    저장: events 테이블에 event_type="user_feedback" emit. message·report 평가와는
    별개의 *자유 코멘트* 채널.
    """
    body = await request.json()
    comment, context = _validate_general_feedback(body)
    user_id = getattr(request.state, "user_id", None)

    thread_id = context.get("thread_id") if isinstance(context.get("thread_id"), str) else None
    message_id = (
        context.get("last_message_id")
        if isinstance(context.get("last_message_id"), str)
        else None
    )

    payload = {
        "comment": comment,
        "comment_length": len(comment),
        "source": "@feedback",
    }
    extra_context_keys = {k: v for k, v in context.items()
                          if k not in ("thread_id", "last_message_id")}
    if extra_context_keys:
        payload["context"] = extra_context_keys

    evt_id = get_events_repo().emit(Event(
        id="", ts="",
        event_type="user_feedback",
        user_id=user_id,
        thread_id=thread_id,
        message_id=message_id,
        payload_json=json.dumps(payload, ensure_ascii=False),
    ))
    return {"feedback_id": evt_id, "ts": _utcnow_iso_safe()}


@router.post("/feedback/pii")
async def submit_pii_feedback(request: Request):
    """PII 오마스킹 신고 (2026-08-13) — 사용자 피드백 루프의 입구.

    프런트: `pii_notice`(masked_text) 로 치환된 단어를 짚어 경고 토스트를 띄우고,
    사용자가 "개인정보가 아닌데 필터됐다"를 누르면 이 엔드포인트로 신고한다.

    body:
      - thread_id (str, required)
      - term (str, required, 2~30자) — 잘못 마스킹된 **원래 단어**(사용자 제공)
      - placeholder (str, optional) — 어떤 자리표시자로 치환됐나(예 "[이름]")
      - message_id (str, optional) — 해당 human 메시지
      - comment (str, optional, ≤200자)

    처리 — **선보고 후조치**(2026-08-13 사용자 결정): 신고 즉시 active 로 허용어
    등재 → 다음 질문부터 그 단어는 마스킹하지 않는다(TTL≤10s). 관리자는
    /admin/pii-terms 개선리스트에서 사후 검토 — reject 시 즉시 마스킹 복귀.
    주민번호·전화번호 등 구조적 PII 형식은 등재 자체가 거부된다(422).
    events(pii_report) 병행 기록 — 관리자 다이제스트에 실린다.
    """
    from src.guardrail import pii_terms

    body = await request.json()
    thread_id = str(body.get("thread_id") or "").strip()
    term = str(body.get("term") or "").strip()
    if not thread_id or not term:
        raise HTTPException(status_code=422, detail="thread_id, term 필요")
    # 남의 thread 를 사칭한 신고 주입 방지(H-6과 동일 원리).
    await asyncio.to_thread(assert_thread_access, thread_id, request)
    user_id = getattr(request.state, "user_id", None)
    placeholder = str(body.get("placeholder") or "").strip() or None
    comment = str(body.get("comment") or "").strip() or None
    message_id = (str(body.get("message_id")).strip()
                  if body.get("message_id") else None)

    try:
        entry = await asyncio.to_thread(
            pii_terms.report, term, placeholder=placeholder,
            user_id=user_id, thread_id=thread_id, comment=comment)
    except pii_terms.TermRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        get_events_repo().emit(Event(
            id="", ts="",
            event_type="pii_report",
            user_id=user_id,
            thread_id=thread_id,
            message_id=message_id,
            payload_json=json.dumps({
                "term": entry["term"],
                "placeholder": placeholder,
                "comment": comment,
                "status": entry.get("status"),
                "report_count": entry.get("report_count"),
            }, ensure_ascii=False),
        ))
    except Exception as e:  # noqa: BLE001 — 이벤트 실패가 신고를 막으면 안 됨
        _log.warning("pii_report event emit failed: %s", e)

    return {"ok": True, "term": entry["term"], "status": entry.get("status"),
            # unmasked=False 면 이미 correct(진짜 개인정보) 라벨된 단어 —
            # 프런트는 "검토 결과 개인정보로 확인된 단어예요" 안내로 분기.
            "unmasked": entry.get("unmasked"),
            "report_count": entry.get("report_count")}


@router.get("/admin/feedback")
def admin_list_feedback(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    since: Optional[str] = None,
    until: Optional[str] = None,
    kind: str = "user_feedback",
):
    """admin: 누적 자유 코멘트(@feedback) 또는 message/report 평가 조회.

    Query:
      - kind: "user_feedback"(기본, @feedback 자유 코멘트) | "feedback"(message·report 평가)
      - limit, offset, since(ISO), until(ISO)

    응답:
      { count, items: [Event] }
        Event: { id, ts, event_type, user_id, thread_id, message_id, payload_json, payload(parsed dict) }
    """
    require_admin(request)
    if kind not in ("user_feedback", "feedback"):
        raise HTTPException(status_code=422, detail="kind must be 'user_feedback' or 'feedback'")
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    events = get_events_repo().list_by_type(
        kind, since=since, until=until, limit=limit, offset=offset,
    )
    items = [e.as_dict() for e in events]
    return {"count": len(items), "items": items}


@router.post("/feedback/citation")
async def submit_citation_feedback(request: Request):
    """인용 단위 오류 신고 (2026-07-15, UX 배치) — retrieval 품질 라벨 수집.

    body:
      - thread_id (str, required)
      - message_id (str, optional) — 신고 대상 답변 ai 메시지
      - citation_id (str, required) — 예 "cite_doc_009514_0006001"
      - citation_number (int, optional) — 표시 번호 [n]
      - citation_title (str, optional)
      - reason (str, optional, ≤500자) — "조문이 답변 주장과 무관" 등

    저장: feedback 테이블(rating=thumbs_down, comment=구조화 JSON) — admin
    피드백 화면에서 함께 조회. events 에도 event_type="citation_report" emit.
    """
    body = await request.json()
    thread_id = str(body.get("thread_id") or "").strip()
    citation_id = str(body.get("citation_id") or "").strip()
    if not thread_id or not citation_id:
        raise HTTPException(status_code=422, detail="thread_id, citation_id 필요")
    # 인용 신고도 retrieval 품질 라벨로 쌓인다 — 남의 대화에 라벨을 꽂으면
    # 평가셋이 오염된다(2026-08-04 H-6).
    await asyncio.to_thread(assert_thread_access, thread_id, request)
    reason = str(body.get("reason") or "").strip()[:500]
    message_id = (str(body.get("message_id")).strip()
                  if body.get("message_id") else None)
    payload = {
        "kind": "citation_report",
        "citation_id": citation_id,
        "citation_number": body.get("citation_number"),
        "citation_title": str(body.get("citation_title") or "")[:120],
        "reason": reason or None,
    }
    user_id = getattr(request.state, "user_id", None)
    fb = Feedback(
        id="",
        rating="thumbs_down",
        user_id=user_id,
        thread_id=thread_id,
        message_id=message_id,
        comment=json.dumps(payload, ensure_ascii=False),
    )
    fid = get_feedback_repo().create(fb)
    try:
        get_events_repo().emit(Event(
            id="", ts="",
            event_type="citation_report",
            user_id=user_id,
            thread_id=thread_id,
            message_id=message_id,
            payload_json=json.dumps(payload, ensure_ascii=False),
        ))
    except Exception as e:  # noqa: BLE001 — 이벤트 실패가 신고를 막으면 안 됨
        _log.warning("citation_report event emit failed: %s", e)
    return {"ok": True, "feedback_id": fid}


@router.post("/feedback/document")
async def report_document_issue(request: Request,
                                authorization: Optional[str] = Header(None)):
    """서류 작성 화면 문제 신고(2026-08-27) — 파싱 오류·서식 아님·내용 불일치.

    body: {"report_id", "reason", "comment"?, "article_key"?, "fields_count"?}
    기록만 한다(events doc_report) — 개선 우선순위의 근거. 값(기입 내용)은
    싣지 않는다.
    """
    _check_auth(authorization)
    body = await request.json()
    reason = str(body.get("reason") or "").strip()[:40]
    if not reason:
        raise HTTPException(status_code=422, detail="reason 이 필요합니다")
    from src.persistence import get_events_repo
    from src.persistence.events_repo import Event

    get_events_repo().emit(Event(
        id="", ts="", event_type="doc_report",
        user_id=str(getattr(request.state, "user_id", "") or None),
        thread_id=str(body.get("thread_id") or "") or None,
        run_id=str(body.get("report_id") or "") or None,
        payload_json=json.dumps({
            "reason": reason,
            "comment": str(body.get("comment") or "")[:500],
            "article_key": str(body.get("article_key") or "")[:120],
            "fields_count": int(body.get("fields_count") or 0),
        }, ensure_ascii=False)))
    return {"ok": True}
