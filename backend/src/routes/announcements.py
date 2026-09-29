"""패치노트 조회 API — **공개 라우트**(발행은 /admin/announcements).

프런트 계약(docs/contracts/frontend_chat_v2.md §4b): 로그인 후 최초 접속 시
GET /announcements/latest → id 가 localStorage 의 마지막 확인 id 와 다르면
팝업 1회 → 닫으면 id 저장. 서버는 사용자별 read 상태를 저장하지 않는다.

2026-09-02: 목록(`GET /announcements`)이 랜딩의 '업데이트 내역' 게시판
(`/updates`, 비로그인 열람 가능)을 받치므로 인증 제외(auth PUBLIC_PATH_PREFIXES).
숨긴 노트는 목록에서도 빠진다 — 전체(숨김 포함)는 admin 전용
`GET /admin/announcements`.
"""

from __future__ import annotations

from fastapi import APIRouter

from src import announcements

router = APIRouter()


@router.get("/announcements/latest")
def get_latest_announcement(seen: str = ""):
    """로그인 팝업용 노트 1건 — 없으면 {"announcement": null}.

    가장 최근 발행 1건만 후보(숨김·`popup=false` 면 null — 이전 노트로 내려가지 않는다).
    `seen`: 클라이언트가 이미 본 노트 id(쉼표 구분) — 포함돼 있으면 null.
    """
    ids = [s.strip() for s in seen.split(",") if s.strip()][:10]
    return {"announcement": announcements.latest(ids or None)}


@router.get("/announcements")
def list_announcements(limit: int = 50, q: str = "", feature: str = ""):
    """업데이트 내역(최신순, 숨김 제외, 최대 100) — '/updates' 게시판용.

    `q`: 키워드 검색(공백 구분 AND, 제목+항목 부분 일치, 대소문자 무시).
    `feature`: 기능 영역 필터(정확 일치) — 게시판 탭. 응답 `features` 는 탭 순서
    (announcements.FEATURES 순 + 목록 밖 값).
    """
    items = announcements.list_notes(limit, q=q.strip()[:100] or None,
                                     feature=feature.strip()[:30] or None)
    return {"count": len(items), "items": items, "q": q.strip()[:100],
            "feature": feature.strip()[:30], "features": announcements.feature_order()}
