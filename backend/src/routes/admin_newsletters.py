"""뉴스레터 관리 API(2026-09-22) — 권한 '메일 발신'(`src/admin_perms.py`).

- GET    /admin/newsletters                    목록(메타)
- POST   /admin/newsletters                    작성 {subject, body_html?, body_text?, marketing?, reply_to?, source_filename?}
- GET    /admin/newsletters/recipients         수신 후보 + 자격(?marketing=true|false&newsletter_id=)
- POST   /admin/newsletters/preview            렌더 결과(저장 없이) {subject, body_html?, body_text?}
- GET    /admin/newsletters/{id}               본문 + 발송 이력
- PUT    /admin/newsletters/{id}               수정
- DELETE /admin/newsletters/{id}               삭제(발송 이력 있으면 409)
- POST   /admin/newsletters/{id}/send          발송 {emails: [...]} | 테스트 {test: true}(요청자 본인에게 1통)

라우트 선언 순서: `/recipients`·`/preview` 를 `/{newsletter_id}` 보다 먼저 둔다.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from src.middleware import require_admin

router = APIRouter()


def _by(request: Request):
    return getattr(request.state, "user_email", None)


@router.get("/admin/newsletters")
def admin_list_newsletters(_admin=Depends(require_admin)):
    from src.newsletters import list_newsletters

    items = list_newsletters()
    return {"count": len(items), "items": items}


@router.post("/admin/newsletters", status_code=201)
def admin_create_newsletter(body: dict, request: Request, _admin=Depends(require_admin)):
    from src.newsletters import create_newsletter

    try:
        return {"ok": True, "newsletter": create_newsletter(body or {}, by=_by(request))}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/admin/newsletters/recipients")
def admin_newsletter_recipients(marketing: bool = False, newsletter_id: str = "",
                                _admin=Depends(require_admin)):
    from src.newsletters import REASON_LABELS, recipient_catalog

    rows = recipient_catalog(marketing=marketing, nid=newsletter_id.strip() or None)
    return {"count": len(rows), "eligible": sum(1 for r in rows if r["eligible"]),
            "marketing": marketing, "reasons": REASON_LABELS, "recipients": rows}


@router.post("/admin/newsletters/preview")
def admin_preview_newsletter(body: dict, _admin=Depends(require_admin)):
    from src.newsletters import html_to_text, rendered_html, send_subject, sender_info

    item = {"subject": str((body or {}).get("subject") or ""),
            "body_html": str((body or {}).get("body_html") or ""),
            "body_text": str((body or {}).get("body_text") or ""),
            "marketing": bool((body or {}).get("marketing"))}
    return {"subject": send_subject(item), "html": rendered_html(item),
            "text": item["body_text"].strip() or html_to_text(item["body_html"]),
            **sender_info(str((body or {}).get("reply_to") or "").strip() or None)}


@router.get("/admin/newsletters/{newsletter_id}")
def admin_get_newsletter(newsletter_id: str, _admin=Depends(require_admin)):
    from src.newsletters import summary_for

    out = summary_for(newsletter_id)
    if not out:
        raise HTTPException(status_code=404, detail="newsletter not found")
    return out


@router.put("/admin/newsletters/{newsletter_id}")
def admin_update_newsletter(newsletter_id: str, body: dict, request: Request,
                            _admin=Depends(require_admin)):
    from src.newsletters import update_newsletter

    try:
        item = update_newsletter(newsletter_id, body or {}, by=_by(request))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not item:
        raise HTTPException(status_code=404, detail="newsletter not found")
    return {"ok": True, "newsletter": item}


@router.delete("/admin/newsletters/{newsletter_id}")
def admin_delete_newsletter(newsletter_id: str, request: Request,
                            _admin=Depends(require_admin)):
    from src.newsletters import delete_newsletter

    try:
        ok = delete_newsletter(newsletter_id, by=_by(request))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="newsletter not found")
    return {"ok": True, "id": newsletter_id}


@router.post("/admin/newsletters/{newsletter_id}/send")
async def admin_send_newsletter(newsletter_id: str, request: Request,
                                admin=Depends(require_admin)):
    """발송 — 수신 자격은 서버가 다시 판정한다(미동의·수신거부·탈퇴는 제외하고 이력에 사유).

    SMTP 는 동기·수신자당 최대 15초 — 이벤트 루프 밖(스레드)에서 돌린다(CLAUDE.md §7).
    """
    from src.newsletters import send_newsletter

    body = await request.json()
    test = bool((body or {}).get("test"))
    emails = (body or {}).get("emails") or []
    if not test and (not isinstance(emails, list) or not emails):
        raise HTTPException(status_code=422, detail="emails(배열) 필요")
    try:
        run = await asyncio.to_thread(
            send_newsletter, newsletter_id,
            emails=[str(e) for e in emails], by=_by(request),
            test_to=(admin.email if test else None))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ok": True, "run": run}
