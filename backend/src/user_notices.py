"""사용자별 앱 내 알림(2026-09-15) — 특정 사용자에게만 최초 접속 1회 팝업.

배경: 피드백 반영 안내를 전체 공지(announcements)로 냈다가 즉시 철회한 사고.
announcements 는 전원 대상 패치노트이고, 이 모듈은 **수신자를 지정한** 알림이다.

저장: app_settings KV — 키 `user_notices:<user_id>`, 값 JSON 배열(최신순, 최대
`_MAX_PER_USER`). 읽음 상태는 서버가 갖는다(`seen_at`) — 기기·브라우저 무관 1회.
단일 워커라 캐시 없이 매 조회 DB(사용자당 접속 1회 조회).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

_log = logging.getLogger(__name__)

_KEY_PREFIX = "user_notices:"
_MAX_PER_USER = 30
_MAX_ITEMS = 10
_ITEM_MAX = 300
_TITLE_MAX = 120


def _key(user_id: str) -> str:
    return f"{_KEY_PREFIX}{user_id}"


def _load(user_id: str) -> list[dict]:
    from src.persistence.settings_repo import get_settings_repo

    raw = get_settings_repo().get(_key(user_id))
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    return [n for n in data if isinstance(n, dict)] if isinstance(data, list) else []


def _save(user_id: str, notices: list[dict], *, updated_by: Optional[str]) -> None:
    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(_key(user_id), json.dumps(notices[:_MAX_PER_USER], ensure_ascii=False),
                            updated_by=updated_by)


def validate(title: str, items: list) -> tuple[str, list[str]]:
    t = (title or "").strip()
    if not t or len(t) > _TITLE_MAX:
        raise ValueError(f"title 은 1~{_TITLE_MAX}자여야 합니다.")
    cleaned = [str(i).strip()[:_ITEM_MAX] for i in (items or []) if str(i).strip()]
    if not cleaned:
        raise ValueError("items 에 내용이 없습니다.")
    if len(cleaned) > _MAX_ITEMS:
        raise ValueError(f"items 는 최대 {_MAX_ITEMS}개입니다.")
    return t, cleaned


def send(user_ids: list[str], *, title: str, items: list, created_by: Optional[str],
         date: Optional[str] = None) -> list[dict]:
    """지정 사용자들에게 같은 알림을 넣는다(사용자마다 별도 id). 반환: 생성된 알림들."""
    from src.persistence._common import utcnow_iso

    t, cleaned = validate(title, items)
    now = utcnow_iso()
    out: list[dict] = []
    for uid in dict.fromkeys(str(u).strip() for u in user_ids if str(u).strip()):
        note = {
            "id": f"un_{uuid.uuid4().hex[:12]}",
            "user_id": uid,
            "date": (date or now[:10]),
            "title": t,
            "items": cleaned,
            "created_at": now,
            "created_by": created_by,
            "seen_at": None,
        }
        _save(uid, [note] + _load(uid), updated_by=created_by)
        out.append(note)
    return out


def pending(user_id: str) -> Optional[dict]:
    """안 본 알림 중 가장 오래된 것(발송 순서대로 보여준다). 없으면 None."""
    # 저장 순서가 최신순(앞이 최신)이라 마지막 미확인 항목이 가장 오래된 것 —
    # created_at 정렬은 같은 초에 보낸 두 건의 순서를 못 가른다.
    unseen = [n for n in _load(user_id) if not n.get("seen_at")]
    return unseen[-1] if unseen else None


def mark_seen(user_id: str, notice_id: str) -> bool:
    from src.persistence._common import utcnow_iso

    notes = _load(user_id)
    hit = False
    for n in notes:
        if n.get("id") == notice_id and not n.get("seen_at"):
            n["seen_at"] = utcnow_iso()
            hit = True
    if hit:
        _save(user_id, notes, updated_by=user_id)
    return hit


def list_for_user(user_id: str) -> list[dict]:
    return _load(user_id)
