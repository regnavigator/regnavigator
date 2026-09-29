"""운영 장애 알림 — 의존성 다운·임계 이벤트를 ops 채널로 통보.

`OPS_ALERT_WEBHOOK_URL` 설정 시 그 webhook 으로 POST(Slack-compatible `{"text": ...}`).
미설정이면 WARNING 로그만(개발·미구성 안전). 동일 알림은 dedup 쿨다운 동안 1회만 —
LB 가 `/readyz` 를 자주 폴링해도 스팸 안 되게.

※ 사용자 향 알림(quota·보고서 완료 email)은 `notifications.py`(별개). 이건 ops 전용.
"""

from __future__ import annotations

import logging
import os
import threading
import time

_log = logging.getLogger(__name__)

_lock = threading.Lock()
_last_sent: dict[str, float] = {}


def _dedup_ok(key: str, cooldown_s: float) -> bool:
    now = time.monotonic()
    with _lock:
        last = _last_sent.get(key)  # None = 보낸 적 없음 — 항상 통과.
        # ⚠️ 0.0 기본값 금지: time.monotonic()은 부팅 기준이라 갓 뜬 프로세스에선
        #    now 가 작아(예 30) now-0.0 < cooldown 이 참 → 첫 알림이 억제됨.
        if last is not None and now - last < cooldown_s:
            return False
        _last_sent[key] = now
        return True


def send_ops_alert(
    title: str,
    detail: str = "",
    *,
    severity: str = "warning",
    dedup_key: str | None = None,
) -> bool:
    """ops 장애 알림. 전송했으면 True(미전송·dedup·webhook미설정 시 False).

    dedup_key 동일 알림은 `OPS_ALERT_DEDUP_S`(기본 600s) 동안 1회만.
    """
    cooldown = float((os.getenv("OPS_ALERT_DEDUP_S") or "").strip() or "600")
    if not _dedup_ok(dedup_key or title, cooldown):
        return False

    text = f"[{severity.upper()}] {title}" + (f"\n{detail}" if detail else "")
    url = (os.getenv("OPS_ALERT_WEBHOOK_URL") or "").strip()
    if not url:
        _log.warning("OPS ALERT(미전송 — OPS_ALERT_WEBHOOK_URL 미설정): %s", text)
        return False
    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            client.post(url, json={"text": text})
        return True
    except Exception as e:  # noqa: BLE001 — 알림 실패가 본 흐름 죽이면 안 됨
        _log.warning("ops alert 전송 실패: %s", e)
        return False


def reset_dedup() -> None:
    """테스트용 — dedup 상태 초기화."""
    with _lock:
        _last_sent.clear()
