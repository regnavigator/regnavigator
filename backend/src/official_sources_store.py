"""공식 창구 레지스트리 — **동적 등재분**(app_settings KV) + 자동 유지보수.

왜 필요한가: 본문 URL 강제(2026-08-19, `official_sources.sanitize_body_urls`)로
"레지스트리 밖 링크는 제거"가 됐다. 그러면 **레지스트리 커버리지가 곧 링크
커버리지**가 되는데, 코드 상수만 쓰면 창구 하나 늘 때마다 사람이 배포해야 한다
— 케이스를 손으로 쫓는 구조가 그대로 돌아온다.

그래서 PII 오탐 신고 루프(`guardrail/pii_terms.py`)와 **같은 형태**로 만든다:

    관측(제거된 URL) → 자동 검증(실접속) → 자동 등재 → 주기 헬스체크 → 자동 비활성

진실원은 app_settings `official_sources` 키(JSON) — 재기동 생존, 단일 워커라
프로세스 락으로 read-modify-write 직렬화. 코드 상수(`OFFICIAL_SOURCES`)는
**시드**로 남고, 소비자는 둘을 합쳐 본다.

⚠️ 자동 등재의 안전 조건(아래 `is_auto_registrable`)은 보수적으로 잡는다.
잘못 등재되면 **틀린 주소가 검증된 것처럼** 답변에 나간다 — 강제 도입 전보다
나쁜 상태가 된다. 그래서 ① 공공·협회 도메인 ② https 실접속 성공 ③ 루트 경로
④ 반복 등장(1회성 배제) 을 모두 만족할 때만 자동 등재하고, 나머지는 후보로만
쌓아 관리자가 본다.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Optional

_log = logging.getLogger(__name__)

_KEY = "official_sources"
_TTL_S = 10.0          # 소비자 캐시(핫패스에서 매 턴 DB 조회 방지)
_MAX_ENTRIES = 200

_CACHE: dict = {"data": None, "at": 0.0}
_lock = threading.Lock()

# 자동 등재 허용 도메인 접미 — 공공기관·협회·학술.
# 상용(.com/.co.kr)은 자동 등재하지 않는다: 광고·대행사 페이지가 공식 창구인 양
# 등재되면 서비스 신뢰가 무너진다. 필요하면 관리자가 수동 승인.
AUTO_TLD_SUFFIXES = (".go.kr", ".or.kr", ".re.kr", ".ac.kr", ".gov")

# 자동 등재 최소 등장 횟수(우발적 1회 배제).
AUTO_MIN_HITS = 3


def _now() -> str:
    from src.persistence._common import utcnow_iso

    return utcnow_iso()


def _load() -> dict:
    """DB 원본. {"entries": {host: entry}} — 실패 시 빈 구조(답변 비차단)."""
    try:
        from src.persistence.settings_repo import get_settings_repo

        raw = get_settings_repo().get(_KEY)
    except Exception as e:  # noqa: BLE001 — DB 장애가 답변을 막으면 안 됨
        _log.warning("official_sources 조회 실패(빈 목록): %s", e)
        return {"entries": {}}
    if not raw:
        return {"entries": {}}
    try:
        data = json.loads(raw)
        entries = data.get("entries")
        if isinstance(entries, dict):
            return {"entries": entries}
    except Exception:  # noqa: BLE001
        pass
    return {"entries": {}}


def _save(data: dict, *, updated_by: Optional[str] = None) -> None:
    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(_KEY, json.dumps(data, ensure_ascii=False),
                            updated_by=updated_by)
    invalidate_cache()


def invalidate_cache() -> None:
    _CACHE["data"] = None
    _CACHE["at"] = 0.0


def _cached() -> dict:
    now = time.monotonic()
    if _CACHE["data"] is not None and now - _CACHE["at"] < _TTL_S:
        return _CACHE["data"]
    data = _load()
    _CACHE["data"] = data
    _CACHE["at"] = now
    return data


# ---------------------------------------------------------------------------
# 조회 — official_sources 가 합쳐서 쓴다
# ---------------------------------------------------------------------------
def active_entries() -> list[dict]:
    """활성 등재분만(헬스체크 실패로 비활성된 건 제외)."""
    return [e for e in _cached()["entries"].values() if e.get("active", True)]


def all_entries() -> list[dict]:
    return list(_cached()["entries"].values())


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/\s]+)", (url or "").strip(), re.IGNORECASE)
    return (m.group(1) if m else "").lower().removeprefix("www.")


def is_auto_registrable(url: str) -> bool:
    """자동 등재 가능한 도메인인가(실접속 검증은 별도)."""
    h = host_of(url)
    if not h or ":" in h:
        return False
    return h.endswith(AUTO_TLD_SUFFIXES)


# ---------------------------------------------------------------------------
# 등재·상태 변경
# ---------------------------------------------------------------------------
def upsert(*, url: str, name: str, note: str = "", source: str = "auto",
           updated_by: Optional[str] = None) -> dict:
    """호스트 단위 등재(루트 URL 로 정규화). 이미 있으면 갱신."""
    h = host_of(url)
    if not h:
        raise ValueError(f"URL 이 아닙니다: {url!r}")
    root = f"https://{h}"
    with _lock:
        data = _load()
        entries = data["entries"]
        prev = entries.get(h) or {}
        entry = {
            "host": h,
            "url": root,
            "name": (name or prev.get("name") or h)[:80],
            "note": (note or prev.get("note") or "")[:200],
            "source": prev.get("source") or source,   # 최초 출처 보존
            "active": True,
            "created_at": prev.get("created_at") or _now(),
            "checked_at": prev.get("checked_at"),
            "fail_count": prev.get("fail_count", 0),
            "hits": prev.get("hits", 0),
        }
        entries[h] = entry
        if len(entries) > _MAX_ENTRIES:
            # 오래된 auto 항목부터 정리(수동 등재는 보존).
            autos = sorted((e for e in entries.values() if e.get("source") == "auto"),
                           key=lambda e: str(e.get("created_at") or ""))
            for old in autos[: len(entries) - _MAX_ENTRIES]:
                entries.pop(old["host"], None)
        _save(data, updated_by=updated_by)
    return entry


def bump_hits(host: str, n: int = 1) -> None:
    """후보 등장 횟수 누적(자동 등재 임계 판정용)."""
    h = (host or "").lower().removeprefix("www.")
    if not h:
        return
    with _lock:
        data = _load()
        e = data["entries"].get(h)
        if not e:
            return
        e["hits"] = int(e.get("hits", 0)) + n
        _save(data)


def set_active(host: str, active: bool, *, reason: str = "",
               updated_by: Optional[str] = None) -> Optional[dict]:
    h = (host or "").lower().removeprefix("www.")
    with _lock:
        data = _load()
        e = data["entries"].get(h)
        if not e:
            return None
        e["active"] = bool(active)
        e["checked_at"] = _now()
        if reason:
            e["last_reason"] = reason[:200]
        if active:
            e["fail_count"] = 0
        else:
            e["fail_count"] = int(e.get("fail_count", 0)) + 1
        _save(data, updated_by=updated_by)
        return e


def remove(host: str, *, updated_by: Optional[str] = None) -> bool:
    h = (host or "").lower().removeprefix("www.")
    with _lock:
        data = _load()
        if h not in data["entries"]:
            return False
        data["entries"].pop(h)
        _save(data, updated_by=updated_by)
        return True
