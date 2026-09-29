"""보고 노트 — 관리자 전용 업데이트 기록 (2026-09-21).

운영자 요청: "관리자만 보는 노트를 추가해서 거기다만 올리기. 앞으로도 기능 추가하면 알아서 올리고,
포함/해제 토글로 포함된 건만 자동화된 보고 레터에 포함".

- 사용자 공지(`src/announcements.py`, /updates 게시판·로그인 팝업)와 **완전히 분리** — 사용자에게
  노출되지 않는다. 주간 보고 메일(`src/weekly_report.py`)의 "이번 주 업데이트"가 이 노트에서 온다.
- 노트 = 사용자가 체감하는 기능 변화 1건(뉴스레터에 남길 만한 것). 내부 수정·버그 수정은 올리지 않는다.
- `include`(기본 True): 해제하면 보고 메일에서 빠진다. 노트는 남는다.
- 기능을 배포하면 개발 쪽(에이전트)이 `scripts/report_note.py add` 로 올린다 — 운영자는 관리자 ›
  보고 노트에서 확인·수정·토글.
- 저장: app_settings `report_notes`(JSON 배열, 최신이 앞). 상한 500건.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import date
from typing import Optional

_log = logging.getLogger(__name__)

_KEY = "report_notes"
_MAX_NOTES = 500
_TITLE_MAX = 80
_ITEM_MAX = 300
_MAX_ITEMS = 8
_lock = threading.Lock()


def _settings():
    from src.persistence.settings_repo import get_settings_repo

    return get_settings_repo()


def _load() -> list[dict]:
    raw = _settings().get(_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except ValueError:
        _log.warning("report_notes 손상 — 빈 목록으로 취급")
        return []


def _save(notes: list[dict], *, by: Optional[str]) -> None:
    _settings().set(_KEY, json.dumps(notes[:_MAX_NOTES], ensure_ascii=False), updated_by=by)


def _now() -> str:
    from src.persistence._common import utcnow_iso

    return utcnow_iso()


def _today_kst() -> str:
    from datetime import datetime, timezone

    from src.persistence.events_repo import _usage_tz

    return datetime.now(timezone.utc).astimezone(_usage_tz()).date().isoformat()


def _clean(*, title=None, items=None, feature=None, day=None) -> dict:
    out: dict = {}
    if title is not None:
        t = str(title).strip()
        if not t or len(t) > _TITLE_MAX:
            raise ValueError(f"제목은 1~{_TITLE_MAX}자")
        out["title"] = t
    if items is not None:
        lst = [str(i).strip()[:_ITEM_MAX] for i in (items or []) if str(i).strip()]
        if len(lst) > _MAX_ITEMS:
            raise ValueError(f"항목은 최대 {_MAX_ITEMS}개")
        out["items"] = lst
    if feature is not None:
        f = str(feature).strip()
        if len(f) > 30:
            raise ValueError("기능 영역은 30자 이내")
        out["feature"] = f or None
    if day is not None:
        d = str(day).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise ValueError("날짜는 YYYY-MM-DD")
        date.fromisoformat(d)  # 존재하지 않는 날짜면 ValueError
        out["date"] = d
    return out


def add(*, title: str, items: Optional[list[str]] = None, feature: Optional[str] = None,
        day: Optional[str] = None, include: bool = True, by: Optional[str] = None,
        refs: Optional[list[str]] = None) -> dict:
    """노트 추가(최신이 앞). `day` 미지정 = 오늘(KST). `refs` = 관련 커밋 등(관리자 화면 참고용)."""
    fields = _clean(title=title, items=items or [], feature=feature or "", day=day or _today_kst())
    note = {"id": f"rn_{uuid.uuid4().hex[:12]}", **fields, "include": bool(include),
            "refs": [str(r)[:40] for r in (refs or [])][:10],
            "created_by": by, "created_at": _now(), "updated_at": None}
    with _lock:
        _save([note] + _load(), by=by)
    return note


def update(note_id: str, *, by: Optional[str] = None, **patch) -> Optional[dict]:
    """준 항목만 수정(title·items·feature·date·include). 없으면 None."""
    fields = _clean(title=patch.get("title"), items=patch.get("items"),
                    feature=patch.get("feature"), day=patch.get("date"))
    if "include" in patch and patch["include"] is not None:
        fields["include"] = bool(patch["include"])
    with _lock:
        notes = _load()
        for n in notes:
            if n.get("id") == note_id:
                n.update(fields)
                n["updated_at"] = _now()
                n["updated_by"] = by
                _save(notes, by=by)
                return n
    return None


def delete(note_id: str, *, by: Optional[str] = None) -> bool:
    with _lock:
        notes = _load()
        kept = [n for n in notes if n.get("id") != note_id]
        if len(kept) == len(notes):
            return False
        _save(kept, by=by)
    return True


def list_notes(*, since: Optional[str] = None, until: Optional[str] = None,
               include_only: bool = False) -> list[dict]:
    """날짜(YYYY-MM-DD, 양끝 포함) 범위. 최신 날짜 먼저."""
    out = []
    for n in _load():
        d = str(n.get("date") or "")
        if since and d < since:
            continue
        if until and d > until:
            continue
        if include_only and not n.get("include", True):
            continue
        out.append(n)
    out.sort(key=lambda n: (str(n.get("date") or ""), str(n.get("created_at") or "")), reverse=True)
    return out
