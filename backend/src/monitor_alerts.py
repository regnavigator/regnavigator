"""규제 변경 감지 → 알람 적재 (2026-10-02).

설계: `docs/spec/monitor-threads-design.md`.

종전 개정 감지는 **조회형**이었다 — 화면을 떠나면 사라지고 다음에 열면 같은
변경을 또 보여 준다. 적재해야 ①"알람만 모아 보기"가 되고 ②같은 변경을 두 번
알리지 않는다.

**DB 가 죽어 있으면 알람을 만들지 않는다.** `detect_with_status()` 가
`complete=False` 를 주면 그건 "변경 없음"이 아니라 "확인 못 함"이다. 그 구분을
잃으면 리포트가 DB 다운 중에 "변경 없음"이라고 단언한다(2026-10-01 실측 사고).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

_log = logging.getLogger(__name__)

#: 알람 종류별 사람이 읽는 한 줄
_SUMMARY = {
    "repealed": "폐지된 법령입니다 — 적용 여부를 다시 확인하십시오.",
    "pending": "개정이 예정되어 있습니다.",
    "amended": "시행일이 바뀌었습니다.",
    "effective_date": "시행일이 바뀌었습니다.",
}


def check_interval_s() -> int:
    """감지 주기 — 발송 주기와 **별개**다. 감지는 자주, 발송은 드물게가 맞다."""
    try:
        return max(60, int((os.getenv("MONITOR_ALERT_INTERVAL_S") or "").strip()
                           or "3600"))
    except ValueError:
        return 3600


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def detect_for_thread(thread_id: str, *, day: Optional[str] = None) -> dict:
    """한 스레드의 관찰 조문을 검사해 **새 알람만** 적재한다.

    반환: {"checked", "changed", "created", "complete"}
    `complete=False` 면 아무것도 적재하지 않는다(확인 불가 ≠ 변경 없음).
    """
    from src.amendments import detect_with_status
    from src.persistence import get_monitor_alert_repo, get_monitor_watch_repo
    from src.persistence.monitor_alert_repo import Alert

    watch = get_monitor_watch_repo().list_for_thread(thread_id)
    if not watch:
        return {"checked": 0, "changed": 0, "created": 0, "complete": True}

    changes, status = detect_with_status(watch)
    if not status.get("complete"):
        _log.info("monitor_alerts: %s 확인 불가 — 적재 생략 (%s)", thread_id, status)
        return {"checked": status.get("checked", 0), "changed": 0,
                "created": 0, "complete": False}

    repo = get_monitor_alert_repo()
    at = day or _today()
    created = 0
    for ch in changes:
        kind = str(ch.get("kind") or "amended")
        ak = str(ch.get("article_key") or "")
        if not ak:
            # detect 는 citation_id 로도 식별한다 — 접두를 떼어 키를 복원.
            cid = str(ch.get("citation_id") or "")
            ak = cid[len("cite_doc_"):] if cid.startswith("cite_doc_") else ""
        if not ak:
            continue
        title = str(ch.get("title") or ak)
        summary = f"{title} — {_SUMMARY.get(kind, '변경이 감지되었습니다.')}"
        if repo.add(Alert(
            id="", thread_id=thread_id, article_key=ak, kind=kind,
            summary=summary[:300],
            payload_json=json.dumps(ch, ensure_ascii=False, default=str)[:4000],
            detected_at=at,
        )):
            created += 1

    return {"checked": status.get("checked", 0), "changed": len(changes),
            "created": created, "complete": True}


def detect_all(*, day: Optional[str] = None) -> dict:
    """모든 모니터링 스레드 검사. 반환: {"threads", "created", "incomplete"}."""
    from src.persistence import get_monitor_watch_repo
    from src.persistence.threads_repo import get_threads_repo

    items = get_monitor_watch_repo().list_all_active()
    thread_ids = sorted({w.thread_id for w in items})
    if not thread_ids:
        return {"threads": 0, "created": 0, "incomplete": 0}

    # 스레드가 지워졌는데 관찰만 남은 경우를 거른다.
    repo = get_threads_repo()
    created = incomplete = 0
    for tid in thread_ids:
        try:
            if not repo.get_meta(tid):
                continue
            r = detect_for_thread(tid, day=day)
            created += r["created"]
            if not r["complete"]:
                incomplete += 1
        except Exception:  # noqa: BLE001 — 한 스레드 실패가 전체를 멈추면 안 된다
            _log.warning("monitor_alerts: %s 검사 실패", tid, exc_info=True)
            incomplete += 1
    if created or incomplete:
        _log.info("monitor_alerts: 스레드 %d개, 새 알람 %d건, 확인불가 %d개",
                  len(thread_ids), created, incomplete)
    return {"threads": len(thread_ids), "created": created,
            "incomplete": incomplete}
