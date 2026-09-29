"""서버 부하 상태 추적 — 사용자 혼잡 표시용.

검색 백프레셔 세마포어([[search_api_client]])와 보고서 큐(report_pipeline)의
실시간 점유를 추적한다. 목적: 속도가 느려도 **사용자가 "서버 혼잡"을 이해하고**
계속 쓰게 하는 것.

노출 경로:
- `GET /load` (health.py) — 프런트가 폴링해 '원활/혼잡' 배지 표시.
- 채팅 중 혼잡이면 검색 도구가 진행 이벤트로 "서버 혼잡 · 잠시만요" 안내.

동기 스레드풀 + 프로세스 로컬(다중 컨테이너면 집계 필요 — 하드닝 후속).
"""

from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_search_active = 0   # 지금 /search 호출 중(슬롯 점유)
_search_waiting = 0  # 백프레셔로 슬롯 대기 중
_reports_active = 0  # 지금 writer(27B) 생성 중


def _search_limit() -> int:
    try:
        return max(1, int((os.getenv("SEARCH_MAX_CONCURRENCY") or "").strip() or "2"))
    except ValueError:
        return 2


def search_wait(delta: int) -> None:
    global _search_waiting
    with _lock:
        _search_waiting += delta


def search_active(delta: int) -> None:
    global _search_active
    with _lock:
        _search_active += delta


def report_active(delta: int) -> None:
    global _reports_active
    with _lock:
        _reports_active += delta


def is_congested() -> bool:
    """이 순간 검색이 혼잡(대기 발생 또는 슬롯 만석)한가 — 인라인 안내용."""
    with _lock:
        return _search_waiting > 0 or _search_active >= _search_limit()


def snapshot() -> dict:
    """현재 부하 스냅샷 — /load 응답."""
    with _lock:
        lim = _search_limit()
        busy = _search_waiting > 0 or _search_active >= lim
        return {
            "status": "busy" if busy else "ok",
            "search": {
                "active": _search_active,
                "waiting": _search_waiting,
                "limit": lim,
            },
            "reports": {"active": _reports_active},
        }
