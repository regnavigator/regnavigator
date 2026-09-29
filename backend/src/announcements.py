"""패치노트 공지 저장소 — "매일 개선한다"를 사용자에게 보여주는 창구(2026-08-13).

관리자가 배포 후 개선사항을 발행(POST /admin/announcements)하면, 프런트는
로그인 후 최초 접속 시 GET /announcements/latest 를 조회해 **안 본 노트만**
팝업 1회 띄운다(본 노트 id 는 localStorage — 서버는 read 상태를 들고 있지 않다).

진실원은 app_settings DB('announcements' 키, JSON 배열 최신순, 최근 20건) —
재기동 생존·배포 없이 발행. 단일 워커라 프로세스 로컬 TTL 캐시로 충분
(maintenance·pii_terms 와 같은 패턴).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Optional

_log = logging.getLogger(__name__)

_KEY = "announcements"
_TTL_S = 10.0
_MAX_NOTES = 100   # 2026-09-02: 20→100 — '업데이트 내역' 게시판이 놓친 기능을 되짚는 창구
_MAX_ITEMS = 20
_ITEM_MAX = 200
_TITLE_MAX = 120
_VERSION_MAX = 20   # 예: v0.8.0 — 2026-09-02 버전별 정리 요청
_FEATURE_MAX = 30

# 기능 영역(2026-09-07 사용자 지적: "버전별 릴리스 노트는 사용자 대상이 아니다 —
# 기능 단위로 알아듣게"). 노트 하나 = 기능 하나의 변화. `feature` 는 자유 문자열이되
# 게시판 탭 순서는 이 목록을 따르고, 목록 밖 값은 뒤에 붙는다. 프런트(UpdatesBoard·
# admin 발행 화면)와 문구를 맞춘다.
FEATURES: tuple[str, ...] = (
    "검색·답변",
    "심층 보고서",
    "IRB·DRB 심의 상담",
    "서류 작성",
    "개인정보 보호",
    "계정·이용",
    "화면·편의",
)

_CACHE: dict = {"notes": None, "at": 0.0}
_lock = threading.Lock()


def _load() -> list[dict]:
    try:
        from src.persistence.settings_repo import get_settings_repo

        raw = get_settings_repo().get(_KEY)
    except Exception as e:  # noqa: BLE001 — DB 장애가 접속을 막으면 안 됨
        _log.warning("announcements 조회 실패(빈 목록): %s", e)
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [n for n in data if isinstance(n, dict)]
    except Exception:  # noqa: BLE001
        pass
    return []


def _save(notes: list[dict], *, updated_by: Optional[str]) -> None:
    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(_KEY, json.dumps(notes, ensure_ascii=False),
                            updated_by=updated_by)
    invalidate_cache()


def invalidate_cache() -> None:
    _CACHE["notes"] = None
    _CACHE["at"] = 0.0


def _cached() -> list[dict]:
    now = time.monotonic()
    if _CACHE["notes"] is not None and now - _CACHE["at"] < _TTL_S:
        return _CACHE["notes"]
    notes = _load()
    _CACHE["notes"] = notes
    _CACHE["at"] = now
    return notes


def publish(*, title: str, items: list[str], date: Optional[str] = None,
            version: Optional[str] = None,
            feature: Optional[str] = None,
            popup: bool = True,
            created_by: Optional[str] = None) -> dict:
    """새 패치노트 발행 — 목록 맨 앞(최신)에 넣고 상한 초과분은 잘린다.

    `version`(선택, ≤20자): 'v0.8.0' 같은 릴리스 표기 — 게시판·팝업 배지.
    `feature`(선택, ≤30자): 기능 영역(FEATURES 권장) — 게시판 탭·배지. 제목은
    "무엇을 할 수 있게 됐는지"를 사용자 언어로.
    """
    from src.persistence._common import utcnow_iso

    t = (title or "").strip()
    if not t or len(t) > _TITLE_MAX:
        raise ValueError(f"title 은 1~{_TITLE_MAX}자여야 합니다.")
    v = (version or "").strip()
    if len(v) > _VERSION_MAX:
        raise ValueError(f"version 은 {_VERSION_MAX}자 이내여야 합니다.")
    f = (feature or "").strip()
    if len(f) > _FEATURE_MAX:
        raise ValueError(f"feature 는 {_FEATURE_MAX}자 이내여야 합니다.")
    cleaned = [str(i).strip()[:_ITEM_MAX] for i in items if str(i).strip()]
    if not cleaned:
        raise ValueError("items 에 내용이 없습니다.")
    if len(cleaned) > _MAX_ITEMS:
        raise ValueError(f"items 는 최대 {_MAX_ITEMS}개입니다.")
    note = {
        "id": f"note_{uuid.uuid4().hex[:12]}",
        # date = 사용자에게 보여줄 배포일(KST 기준 표기 자유) — 미지정 시 발행 시각의 날짜.
        "date": (date or utcnow_iso()[:10]),
        "title": t,
        "version": v or None,
        "feature": f or None,
        "items": cleaned,
        # popup=False → 게시판(/updates)에만 쌓고 로그인 팝업은 띄우지 않는다(2026-09-18).
        "popup": bool(popup),
        "created_at": utcnow_iso(),
        "created_by": created_by,
    }
    with _lock:
        notes = [note] + _load()
        _save(notes[:_MAX_NOTES], updated_by=created_by)
    return note


def set_hidden(note_id: str, hidden: bool, *,
               updated_by: Optional[str] = None) -> bool:
    """노출 금지/재노출(2026-08-28) — 삭제와 구분되는 두 번째 철회 옵션.

    숨긴 노트는 기록으로 남되 사용자 팝업(latest)에서 빠진다. 종전엔 삭제뿐
    이라 "잠깐 내리고 싶다"가 곧 영구 소실이었다(운영자 지적).
    """
    with _lock:
        notes = _load()
        for n in notes:
            if n.get("id") == note_id:
                n["hidden"] = bool(hidden)
                _save(notes, updated_by=updated_by)
                return True
    return False


def set_popup(note_id: str, popup: bool, *, updated_by: Optional[str] = None) -> bool:
    """팝업 노출만 켜고 끈다 — 게시판 노출(hidden)과 독립(2026-09-18)."""
    with _lock:
        notes = _load()
        for n in notes:
            if n.get("id") == note_id:
                n["popup"] = bool(popup)
                _save(notes, updated_by=updated_by)
                return True
    return False


def delete(note_id: str, *, removed_by: Optional[str] = None) -> bool:
    with _lock:
        notes = _load()
        kept = [n for n in notes if n.get("id") != note_id]
        if len(kept) == len(notes):
            return False
        _save(kept, updated_by=removed_by)
    return True


def latest(seen_ids: Optional[list[str]] = None) -> Optional[dict]:
    """사용자 팝업용 노트 — **목록 맨 앞(가장 최근 발행) 1건만** 후보다.

    종전엔 "숨기지 않은 것 중 첫 번째"라, 최신 노트를 숨기면 그 이전 노트가 후보로
    올라와 사용자에게 **옛 노트가 새 팝업으로 되살아났다**(2026-09-18 사고: 9/18 노트를
    숨기자 9/14 노트가 팝업). 이제 후보는 맨 앞 1건뿐이고, 그게 숨김이거나
    `popup=False` 면 팝업은 없다 — 이전 노트로 내려가지 않는다.

    `seen_ids`: 사용자가 이미 본 노트 id 들 — 후보가 그 안에 있으면 띄우지 않는다.
    """
    notes = _cached()
    if not notes:
        return None
    head = notes[0]
    if head.get("hidden") or head.get("popup") is False:
        return None
    if seen_ids and head.get("id") in seen_ids:
        return None
    return head


def feature_order(include_hidden: bool = False) -> list[str]:
    """게시판 탭용 기능 영역 목록 — FEATURES 순서로, 실제 노트가 있는 것만 + 목록 밖 값은 뒤에."""
    present: list[str] = []
    for n in _cached():
        if not include_hidden and n.get("hidden"):
            continue
        f = (n.get("feature") or "").strip()
        if f and f not in present:
            present.append(f)
    ordered = [f for f in FEATURES if f in present]
    return ordered + [f for f in present if f not in FEATURES]


def _matches(note: dict, tokens: list[str]) -> bool:
    hay = " ".join([str(note.get("title") or ""), str(note.get("version") or ""),
                    str(note.get("feature") or ""),
                    *map(str, note.get("items") or [])]).lower()
    return all(t in hay for t in tokens)


def list_notes(limit: int = 10, *, q: Optional[str] = None,
               feature: Optional[str] = None,
               include_hidden: bool = False) -> list[dict]:
    """업데이트 내역 목록(최신순).

    - `include_hidden=False`(사용자 게시판): 숨긴 노트 제외 — 팝업과 같은 기준.
    - `q`: 키워드 검색(2026-09-02 사용자 피드백 — "원하던 기능이 들어왔는지
      찾아보고 싶다"). 공백 구분 토큰 전부가 제목+항목 어딘가에 있어야 매치
      (대소문자 무시, 부분 일치).
    - `feature`: 기능 영역 일치(정확히) — 게시판 탭.
    """
    notes = _cached()
    if not include_hidden:
        notes = [n for n in notes if not n.get("hidden")]
    if feature and feature.strip():
        notes = [n for n in notes if (n.get("feature") or "") == feature.strip()]
    tokens = [t.lower() for t in (q or "").split() if t.strip()][:8]
    if tokens:
        notes = [n for n in notes if _matches(n, tokens)]
    return notes[: max(1, min(int(limit), _MAX_NOTES))]
