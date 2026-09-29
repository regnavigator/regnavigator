"""점검(유지보수) 모드 — 관리자가 서버 사용을 일시 차단.

용도: 매일 오전 4시 데이터 갱신 등 정비 중 일반 사용자의 요청을 막는다. 켜지면
AuthMiddleware 가 **비관리자**의 API 요청을 503 으로 거절한다(관리자는 통과 —
점검 해제·확인 가능). 공개 라우트(health·readyz·load·legal·beta)는 계속 열려
프런트가 점검 화면을 띄우고 상태를 폴링할 수 있다.

**두 가지 트리거** (효과 = 둘 중 하나라도 참):
- 수동(`manual`): 관리자가 즉시 on/off. 켜 있으면 항상 차단.
- 예약(`schedule`): **매일 반복 시간대**(예 04:00~04:20, KST). 서버가 매 요청 시
  현재 시각이 창 안이면 자동 차단 — 크론 없이 시간만 설정하면 매일 자동 on/off.

진실원은 `app_settings` DB('maintenance' 키, JSON). 재기동해도 유지된다. 매 요청
DB 조회를 피하려 짧은 TTL 캐시를 쓰고, 관리자 API 변경 시 즉시 무효화한다.
외부 프로세스(4시 갱신 크론의 `scripts/maintenance.py`)가 DB 를 직접 바꾸면
서버는 TTL(≤5s) 후 반영한다.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

_log = logging.getLogger(__name__)

_KEY = "maintenance"
_TTL_S = 5.0
_DEFAULT_TZ = "Asia/Seoul"
_DEFAULT_MESSAGE = (
    "현재 서버 정기 점검 중입니다. 데이터 갱신이 끝나면 곧 정상화됩니다. "
    "잠시 후 다시 이용해 주세요."
)

# 프로세스 로컬 캐시 (워커 1개 — CLAUDE.md §7). {"raw": dict|None, "at": monotonic}
_CACHE: dict = {"raw": None, "at": 0.0}


# 기능 단위 일시 중단(2026-09-07): 전체 점검과 달리 **그 기능만** 막고 채팅은 정상.
# 첫 용도: 보고서 writer(DGX vLLM)를 다른 작업에 쓰는 동안 "보고서만 못 한다" 안내.
FEATURES: tuple[str, ...] = ("reports",)
_FEATURE_DEFAULT_MESSAGE = {
    "reports": "보고서 기능 점검 중입니다. 채팅·검색은 정상 이용 가능합니다.",
}


def _empty_raw() -> dict:
    return {"manual": False, "message": "", "updated_by": None,
            "since": None, "schedule": None, "features": {}}


def _load_raw() -> dict:
    """DB 저장 상태(수동 플래그 + 예약)를 그대로 로드. 하위호환 마이그레이션."""
    try:
        from src.persistence.settings_repo import get_settings_repo

        raw = get_settings_repo().get(_KEY)
    except Exception as e:  # noqa: BLE001 — DB 장애가 전체 요청을 막으면 안 됨
        _log.warning("maintenance 상태 조회 실패(열림으로 처리): %s", e)
        return _empty_raw()
    if not raw:
        return _empty_raw()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return _empty_raw()
    except Exception:  # noqa: BLE001
        return _empty_raw()
    # 하위호환: 구 스키마는 manual 대신 'active' 를 썼다.
    manual = bool(data.get("manual", data.get("active", False)))
    return {
        "manual": manual,
        "message": str(data.get("message") or ""),
        "updated_by": data.get("updated_by"),
        "since": data.get("since"),
        "schedule": _norm_schedule(data.get("schedule")),
        "features": {k: v for k, v in (data.get("features") or {}).items()
                     if isinstance(v, dict)} if isinstance(data.get("features"), dict) else {},
    }


def _norm_schedule(s) -> Optional[dict]:
    if not isinstance(s, dict):
        return None
    start = _norm_hm(s.get("start"))
    end = _norm_hm(s.get("end"))
    if start is None or end is None:
        return None
    return {
        "enabled": bool(s.get("enabled")),
        "start": start,
        "end": end,
        "tz": str(s.get("tz") or _DEFAULT_TZ),
    }


def _norm_hm(v) -> Optional[str]:
    """"H:M"/"HH:MM" → "HH:MM". 유효하지 않으면 None."""
    if not isinstance(v, str):
        return None
    parts = v.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def _hm_to_min(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def _local_minutes(tz: str) -> int:
    """tz 기준 자정 이후 경과 분(0~1439). tzdata 미설치(Windows) 시 오프셋 폴백."""
    now_utc = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        local = now_utc.astimezone(ZoneInfo(tz))
    except Exception:  # noqa: BLE001 — tzdata 없음 등
        # KST/JST 는 DST 없음 → 고정 +9 로 정확. 그 외는 UTC.
        offset_h = {"Asia/Seoul": 9, "Asia/Tokyo": 9, "UTC": 0}.get(tz, 0)
        local = now_utc + timedelta(hours=offset_h)
    return local.hour * 60 + local.minute


def _in_daily_window(schedule: dict) -> bool:
    """현재 시각이 매일 반복 창 안인지. start==end 는 '없음'(0 길이). 자정 넘김 지원."""
    if not schedule or not schedule.get("enabled"):
        return False
    start = _hm_to_min(schedule["start"])
    end = _hm_to_min(schedule["end"])
    if start == end:
        return False
    now = _local_minutes(schedule.get("tz") or _DEFAULT_TZ)
    if start < end:  # 같은 날 (예 04:00~04:20)
        return start <= now < end
    # 자정 넘김 (예 23:50~00:10)
    return now >= start or now < end


def _effective(raw: dict) -> tuple[bool, str]:
    """(active, source). source: 'manual' | 'schedule' | ''."""
    if raw.get("manual"):
        return True, "manual"
    if _in_daily_window(raw.get("schedule") or {}):
        return True, "schedule"
    return False, ""


def get_state() -> dict:
    """관리자용 전체 상태 — 저장값 + 계산된 effective active/source."""
    now = time.monotonic()
    if _CACHE["raw"] is not None and now - _CACHE["at"] < _TTL_S:
        raw = _CACHE["raw"]
    else:
        raw = _load_raw()
        _CACHE["raw"] = raw
        _CACHE["at"] = now
    active, source = _effective(raw)
    return {**raw, "active": active, "source": source}


def is_active() -> bool:
    return get_state()["active"]


def feature_paused(name: str) -> tuple[bool, str]:
    """(paused, message) — 기능 단위 일시 중단 상태. 전체 점검과 독립."""
    f = (get_state().get("features") or {}).get(name) or {}
    if not f.get("paused"):
        return False, ""
    return True, (f.get("message") or _FEATURE_DEFAULT_MESSAGE.get(name) or "")


def set_feature_pause(name: str, paused: bool, *, message: Optional[str] = None,
                      updated_by: Optional[str] = None) -> dict:
    """기능 일시 중단 on/off. 알 수 없는 기능명은 ValueError."""
    from src.persistence._common import utcnow_iso

    if name not in FEATURES:
        raise ValueError(f"알 수 없는 기능: {name} (가능: {', '.join(FEATURES)})")
    raw = _load_raw()
    feats = dict(raw.get("features") or {})
    cur = dict(feats.get(name) or {})
    cur["paused"] = bool(paused)
    if message is not None:
        cur["message"] = message.strip()
    cur["since"] = utcnow_iso() if paused else None
    cur["updated_by"] = updated_by
    feats[name] = cur
    raw["features"] = feats
    st = _save(raw, updated_by=updated_by)
    _log.info("maintenance feature %s paused=%s by=%s", name, paused, updated_by)
    return st


def public_features() -> dict:
    """공개 노출용 기능 중단 상태 — 중단된 것만 {name: {paused, message, since}}."""
    out = {}
    for name in FEATURES:
        paused, msg = feature_paused(name)
        if paused:
            f = (get_state().get("features") or {}).get(name) or {}
            out[name] = {"paused": True, "message": msg, "since": f.get("since")}
    return out


def public_status() -> dict:
    """프런트 공개 노출용 — 내부 필드(updated_by) 제외."""
    st = get_state()
    if not st["active"]:
        return {"active": False}
    return {
        "active": True,
        "message": st.get("message") or _DEFAULT_MESSAGE,
        "source": st.get("source"),
        "since": st.get("since") if st.get("source") == "manual" else None,
    }


def invalidate_cache() -> None:
    _CACHE["raw"] = None
    _CACHE["at"] = 0.0


def _save(raw: dict, *, updated_by: Optional[str]) -> dict:
    from src.persistence.settings_repo import get_settings_repo

    raw = {**raw, "updated_by": updated_by}
    get_settings_repo().set(_KEY, json.dumps(raw, ensure_ascii=False),
                            updated_by=updated_by)
    invalidate_cache()
    return get_state()


def set_state(active: bool, *, message: Optional[str] = None,
              updated_by: Optional[str] = None) -> dict:
    """수동 점검 on/off. active=True 면 즉시 차단(예약과 무관하게 항상 차단).

    message 를 주면 갱신(수동·예약 공용 안내 문구). 반환: 계산된 전체 상태.
    """
    from src.persistence._common import utcnow_iso

    raw = _load_raw()
    raw["manual"] = bool(active)
    if message is not None:
        raw["message"] = message.strip()
    raw["since"] = utcnow_iso() if active else None
    st = _save(raw, updated_by=updated_by)
    _log.info("maintenance manual=%s by=%s", "ON" if active else "OFF", updated_by)
    return st


def set_schedule(*, enabled: bool, start: Optional[str], end: Optional[str],
                 tz: Optional[str] = None, message: Optional[str] = None,
                 updated_by: Optional[str] = None) -> dict:
    """매일 반복 점검 시간대 설정. start/end 는 "HH:MM"(tz 기준, 기본 KST).

    enabled=False 면 예약 해제(수동 플래그는 유지). 잘못된 시각 형식이면 ValueError.
    """
    ns = _norm_hm(start)
    ne = _norm_hm(end)
    if enabled and (ns is None or ne is None):
        raise ValueError("start/end 는 HH:MM 형식이어야 합니다 (예: 04:00).")

    raw = _load_raw()
    if enabled:
        raw["schedule"] = {
            "enabled": True,
            "start": ns,
            "end": ne,
            "tz": (tz or _DEFAULT_TZ),
        }
    else:
        # 값이 오면 보존하되 비활성, 안 오면 그대로 비활성 표시
        prev = raw.get("schedule") or {}
        raw["schedule"] = {
            "enabled": False,
            "start": ns or prev.get("start") or "04:00",
            "end": ne or prev.get("end") or "04:20",
            "tz": (tz or prev.get("tz") or _DEFAULT_TZ),
        }
    if message is not None:
        raw["message"] = message.strip()
    st = _save(raw, updated_by=updated_by)
    _log.info("maintenance schedule enabled=%s %s~%s tz=%s by=%s",
              enabled, ns, ne, tz or _DEFAULT_TZ, updated_by)
    return st


def default_message() -> str:
    return _DEFAULT_MESSAGE


def default_tz() -> str:
    return _DEFAULT_TZ
