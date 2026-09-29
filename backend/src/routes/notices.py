"""사용자별 앱 내 알림 라우트(2026-09-15).

- GET  /me/notices/pending      — 내 미확인 알림 1건(없으면 null). 최초 접속 팝업용.
- POST /me/notices/{id}/seen    — 닫음(읽음) 기록. 서버 보관이라 기기 무관 1회.
- POST /admin/notices           — {user_ids:[...], title, items:[...]} 지정 발송.
- GET  /admin/users/{uid}/notices — 그 사용자에게 보낸 알림 이력.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from src import user_notices
from src.middleware import require_admin

router = APIRouter()


def _uid(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user_id)


@router.get("/me/notices/pending")
def get_my_pending_notice(request: Request):
    return {"notice": user_notices.pending(_uid(request))}


@router.post("/me/notices/{notice_id}/seen")
def mark_my_notice_seen(notice_id: str, request: Request):
    ok = user_notices.mark_seen(_uid(request), notice_id)
    return {"ok": ok, "id": notice_id}


@router.post("/admin/notices", status_code=201)
async def admin_send_notices(request: Request, _admin=Depends(require_admin)):
    """지정 사용자 앱 내 알림 — body {user_ids: [..] | emails: [..], title, items: [..], date?}."""
    body = await request.json()
    body = body or {}
    user_ids = [str(u) for u in (body.get("user_ids") or []) if u]
    emails = [str(e).strip().lower() for e in (body.get("emails") or []) if e]
    if emails:
        from src.persistence import get_users_repo

        repo = get_users_repo()
        for e in emails:
            u = repo.get_by_email(e)
            if u:
                user_ids.append(u.id)
    if not user_ids:
        raise HTTPException(status_code=422, detail="user_ids 또는 emails(가입 회원) 필요")
    try:
        sent = user_notices.send(
            user_ids, title=str(body.get("title") or ""), items=body.get("items") or [],
            created_by=getattr(request.state, "user_email", None),
            date=str(body.get("date") or "").strip() or None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ok": True, "count": len(sent), "notices": sent}


@router.get("/admin/users/{user_id}/notices")
def admin_list_user_notices(user_id: str, _admin=Depends(require_admin)):
    items = user_notices.list_for_user(user_id)
    return {"count": len(items), "items": items}
