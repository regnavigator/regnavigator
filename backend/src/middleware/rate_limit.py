"""Rate limit 미들웨어 — per-IP·per-user sliding window 다단.

토큰 한도(QuotaMiddleware)와는 별개:
- QuotaMiddleware = 모델 토큰량 기반 (월·일)
- RateLimitMiddleware = 요청 수 기반 (분·시)

용도:
- 인증 안 된 IP 폭주 방지 (스크래퍼·봇)
- 인증된 사용자가 단시간에 너무 많은 요청 (UI 버그·스크립트 사용)
- LLM 호출 폭주로 비용 폭탄 방지 (1차 방어선; QuotaMiddleware는 2차)

저장소: 인메모리 sliding window. 분산 배포 시엔 Redis로 갈아야 하지만, 단일 VM
배포(P1 docker-compose)에서는 인메모리로 충분. 컨테이너 재시작 시 카운터 리셋.

env:
- `RATE_LIMIT_PER_IP_PER_MIN`        — IP당 분당 요청 수 (기본 60)
- `RATE_LIMIT_PER_USER_PER_MIN`      — 사용자당 분당 요청 수 (기본 30)
- `RATE_LIMIT_PER_USER_PER_HOUR`     — 사용자당 시간당 요청 수 (기본 600)
- `RATE_LIMIT_DISABLE=1`             — 비활성 (테스트·디버그)
"""

from __future__ import annotations

import collections
import logging
import os
import threading
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

_log = logging.getLogger(__name__)


# 공개 라우트 — rate limit 적용 안 함
_PUBLIC_PATHS = (
    "/healthz",
    "/readyz",      # LB/모니터가 자주 폴링 — rate limit 제외(false 429 방지)
    "/suggestions",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class _SlidingWindow:
    """O(1) sliding window — bucket별 deque로 timestamp 누적.

    `record(key)` → bool: 한도 통과면 True, 초과면 False.
    """

    # 버킷 수 상한 — 키가 무한히 늘어나는 것 자체가 메모리 고갈 경로다.
    # X-Forwarded-For 를 매 요청 바꾸면 `ip:<랜덤>` 버킷이 계속 생기는데,
    # cleanup 은 60초마다 **빈** deque 만 걷어내므로 지속 유입은 못 막는다.
    # 인스턴스가 1개로 고정된 구조라(단일 인스턴스 강제) 메모리 고갈 = 전체 장애.
    # 상한에 닿으면 가장 오래된 버킷부터 버린다 — 그 키는 한도가 리셋되지만,
    # 한도 우회보다 메모리 고갈이 더 큰 피해다(2026-08-04 감사 H-2).
    MAX_BUCKETS = 50_000

    def __init__(self, *, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._buckets: collections.OrderedDict[str, collections.deque[float]] = (
            collections.OrderedDict())
        self._lock = threading.Lock()

    def record(self, key: str, now: Optional[float] = None) -> tuple[bool, int]:
        """key가 이번 요청을 받을 수 있는지. (allowed, retry_after_sec) 반환."""
        now = now or time.time()
        cutoff = now - self.window
        with self._lock:
            dq = self._buckets.setdefault(key, collections.deque())
            # 윈도우 밖 timestamp 제거
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.limit:
                # 가장 오래된 timestamp가 윈도우 밖으로 나갈 때까지 대기
                retry = max(1, int(self.window - (now - dq[0])))
                return False, retry
            dq.append(now)
            self._buckets.move_to_end(key)          # LRU 갱신
            while len(self._buckets) > self.MAX_BUCKETS:
                self._buckets.popitem(last=False)   # 가장 오래 안 쓰인 것부터
            return True, 0

    def cleanup(self, now: Optional[float] = None) -> None:
        """주기 호출 — empty deque 제거. 메모리 정리."""
        now = now or time.time()
        cutoff = now - self.window
        with self._lock:
            empty = []
            for k, dq in self._buckets.items():
                while dq and dq[0] < cutoff:
                    dq.popleft()
                if not dq:
                    empty.append(k)
            for k in empty:
                self._buckets.pop(k, None)


# 프로세스 내 생성된 미들웨어 인스턴스 — 테스트 격리용 리셋 대상.
_INSTANCES: list["RateLimitMiddleware"] = []


def reset_windows() -> None:
    """**테스트 전용** — 모든 인스턴스의 sliding window 초기화.

    app 은 모듈 싱글턴이라 윈도우가 프로세스 수명으로 누적된다. TestClient 는
    전부 같은 IP("testclient")로 잡혀 스위트 전체가 분당 예산을 공유 → 테스트가
    늘 때마다 무관한 테스트가 429 로 깨지는 순서 오염이 생긴다(2026-07-13 실측:
    test_quota_admin). conftest 의 autouse fixture 가 매 테스트 호출한다.
    """
    for m in _INSTANCES:
        for w in (m.ip_window, m.user_min_window, m.user_hour_window):
            with w._lock:
                w._buckets.clear()


def _trusted_proxy_hops() -> int:
    """신뢰하는 리버스 프록시 홉 수(`TRUSTED_PROXY_HOPS`). 0=XFF 무시."""
    try:
        return max(0, int((os.getenv("TRUSTED_PROXY_HOPS") or "").strip() or "0"))
    except ValueError:
        return 0


def _client_ip(request) -> str:
    """rate limit 키로 쓸 클라이언트 IP.

    ⚠️ X-Forwarded-For 는 **클라이언트가 마음대로 넣는 헤더**다. 예전엔 맨 앞 값을
    무조건 신뢰해서, 매 요청 헤더를 바꾸면 per-IP 한도가 통째로 무의미해지고
    버킷도 계속 늘어났다(2026-08-04 감사 H-2).

    이제 `TRUSTED_PROXY_HOPS` 만큼만 **오른쪽에서** 되짚는다. 오른쪽 끝은 바로 앞
    프록시가 덧붙인 값이라 위조가 안 되고, 왼쪽(클라이언트가 쓴 부분)은 신뢰하지
    않는다. 프록시가 없으면(기본 0) XFF 를 무시하고 소켓 주소를 쓴다.
    nginx 1홉이면 `TRUSTED_PROXY_HOPS=1`.
    """
    hops = _trusted_proxy_hops()
    if hops:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            parts = [p.strip() for p in fwd.split(",") if p.strip()]
            if parts:
                # 홉 수보다 목록이 짧으면(=중간 프록시가 덜 붙였거나 위조)
                # 가장 왼쪽까지만 — 그래도 소켓 주소보다 나은 근사치.
                return parts[max(0, len(parts) - hops)]
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """per-IP + per-user 다단 rate limit.

    공개 라우트(`/healthz`, `/suggestions`, `/docs`)는 적용 안 함.
    """

    def __init__(self, app):
        super().__init__(app)
        self.disabled = os.getenv("RATE_LIMIT_DISABLE") == "1"
        # 한도
        self.per_ip_min = int((os.getenv("RATE_LIMIT_PER_IP_PER_MIN") or "").strip() or "60")
        self.per_user_min = int((os.getenv("RATE_LIMIT_PER_USER_PER_MIN") or "").strip() or "30")
        self.per_user_hour = int((os.getenv("RATE_LIMIT_PER_USER_PER_HOUR") or "").strip() or "600")
        # 윈도우
        self.ip_window = _SlidingWindow(limit=self.per_ip_min, window_seconds=60)
        self.user_min_window = _SlidingWindow(limit=self.per_user_min, window_seconds=60)
        self.user_hour_window = _SlidingWindow(limit=self.per_user_hour, window_seconds=3600)
        # 마지막 cleanup 시각 — 1분마다
        self._last_cleanup = time.time()
        _INSTANCES.append(self)

    async def dispatch(self, request, call_next):
        if self.disabled:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(p) for p in _PUBLIC_PATHS):
            return await call_next(request)

        # IP 단계 — 인증 여부 무관
        ip = _client_ip(request)
        ok, retry = self.ip_window.record(f"ip:{ip}")
        if not ok:
            return _too_many("IP", retry, "too many requests from your IP")

        # User 단계 — auth 미들웨어 통과 후
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            ok, retry = self.user_min_window.record(f"user_min:{user_id}")
            if not ok:
                return _too_many("user_min", retry,
                                 "분당 요청 한도에 도달했습니다. 잠시 후 다시 시도해주세요.")
            ok, retry = self.user_hour_window.record(f"user_hour:{user_id}")
            if not ok:
                return _too_many("user_hour", retry,
                                 "시간당 요청 한도에 도달했습니다.")

        # 주기 cleanup
        now = time.time()
        if now - self._last_cleanup > 60:
            self.ip_window.cleanup(now)
            self.user_min_window.cleanup(now)
            self.user_hour_window.cleanup(now)
            self._last_cleanup = now

        return await call_next(request)


def _too_many(scope: str, retry_after: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": detail,
            "scope": scope,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
