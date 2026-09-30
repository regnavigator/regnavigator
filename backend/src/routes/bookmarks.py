"""개인 근거 라이브러리(북마크) — 인용을 사용자별로 저장·조회·삭제.

RA/QA 가 답변의 특정 근거(조문·별표/서식·판례)를 저장해 반복 재활용. citation
payload 를 통째로 보관해 원 대화가 지워져도 근거는 남는다. 전부 user 스코프.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request

from src.amendments import detect as detect_amendments
from src.persistence import Bookmark, get_bookmarks_repo

_log = logging.getLogger(__name__)

router = APIRouter()


def _require_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user_id)


@router.post("/bookmarks", status_code=201)
async def add_bookmark(request: Request):
    """근거 저장. body: { citation: <Citation object>, note?: str, thread_id?: str }.

    같은 근거(citation.id) 재저장은 멱등 — 기존 id 반환. 201.
    """
    user_id = _require_user(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be JSON object")
    citation = body.get("citation")
    if not isinstance(citation, dict) or not citation.get("id"):
        raise HTTPException(status_code=422, detail="citation(.id) 필요")
    note = body.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > 1000):
        raise HTTPException(status_code=422, detail="note must be string ≤1000")
    folder = body.get("folder")
    if folder is not None and (not isinstance(folder, str) or len(folder) > 100):
        raise HTTPException(status_code=422, detail="folder must be string ≤100")
    thread_id = body.get("thread_id")
    if thread_id is not None and not isinstance(thread_id, str):
        raise HTTPException(status_code=422, detail="thread_id must be string")

    bm = Bookmark(
        id="",
        user_id=user_id,
        citation_id=str(citation["id"]),
        citation_json=json.dumps(citation, ensure_ascii=False),
        note=(note.strip() if isinstance(note, str) else None),
        folder=(folder.strip() or None) if isinstance(folder, str) else None,
        thread_id=thread_id,
    )
    bid = get_bookmarks_repo().create(bm)
    return {"ok": True, "bookmark_id": bid}


@router.get("/bookmarks")
def list_bookmarks(request: Request, limit: int = 200, offset: int = 0):
    """내 근거 라이브러리 — 최신순. { count, items: [Bookmark(+citation)] }."""
    user_id = _require_user(request)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    items = get_bookmarks_repo().list_for_user(user_id, limit=limit, offset=offset)
    return {"count": len(items), "items": [b.as_dict() for b in items]}


@router.patch("/bookmarks/{bookmark_id}")
async def update_bookmark(bookmark_id: str, request: Request):
    """폴더/메모 변경(부분 PATCH — 보낸 키만 갱신).

    body: { folder?: str|null, note?: str|null } — null/빈문자열 = 해제.
    note 는 write-once 였다(저장 후 수정·삭제 경로 부재, 2026-08-11 해소).
    """
    user_id = _require_user(request)
    body = await request.json()
    if not isinstance(body, dict) or not ({"folder", "note"} & body.keys()):
        raise HTTPException(status_code=422, detail="folder 또는 note 필요")
    out: dict = {"ok": True}
    if "folder" in body:
        folder = body.get("folder")
        if folder is not None and (not isinstance(folder, str) or len(folder) > 100):
            raise HTTPException(status_code=422, detail="folder must be string ≤100")
        folder_val = (folder.strip() or None) if isinstance(folder, str) else None
        get_bookmarks_repo().set_folder(user_id, bookmark_id, folder_val)
        out["folder"] = folder_val
    if "note" in body:
        note = body.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 1000):
            raise HTTPException(status_code=422, detail="note must be string ≤1000")
        note_val = (note.strip() or None) if isinstance(note, str) else None
        get_bookmarks_repo().set_note(user_id, bookmark_id, note_val)
        out["note"] = note_val
    return out


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: str, request: Request):
    """id 로 삭제(본인 것만)."""
    user_id = _require_user(request)
    get_bookmarks_repo().delete(user_id, bookmark_id)
    return {"ok": True}


@router.delete("/bookmarks/by-citation/{citation_id}")
def delete_bookmark_by_citation(citation_id: str, request: Request):
    """citation.id 로 삭제 — 프런트 토글(저장 해제)용."""
    user_id = _require_user(request)
    get_bookmarks_repo().delete_by_citation(user_id, citation_id)
    return {"ok": True}


@router.get("/bookmarks/amendments")
def bookmark_amendments(request: Request):
    """저장 시점 대비 **시행일이 바뀐 북마크(개정 가능성)** 목록.

    판정 2축(law.go.kr enrich + 시행일 비교):
      1) `law_amendment_status`(ETL lawdangle enrich) — law_id 로 **폐지(repealed)/
         개정예정(pending)** 판정 (kind="repealed"|"pending").
      2) 시행일 비교 — citation `id=cite_doc_{article_key}` 에서 key 복원 후
         `fetch_articles` 현재 시행일 vs 저장 시점(date) 비교 (kind="amended").
    반환: { amendments: [{bookmark_id, citation_id, title, kind,
                          saved_date?, current_date?}] }.
    """
    user_id = _require_user(request)
    bms = get_bookmarks_repo().list_for_user(user_id, limit=500)
    return {"amendments": detect_amendments(bms)}
