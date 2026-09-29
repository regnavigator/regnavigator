"""경량 TTL LRU 캐시 — 검색·임베딩 결과 캐싱(속도·비용 절감).

법령 코퍼스는 안정적이라 같은 질의의 임베딩·검색 결과를 재사용해도 안전하다.
임베딩은 결정적(모델 고정)이라 만료 불필요(ttl=0), 검색 결과는 코퍼스 갱신 대비
TTL 을 둔다. thread-safe(단일 프로세스 langgraph dev/uvicorn 워커 공유).
"""

from __future__ import annotations

import threading
import time

_MISS = object()


class TTLCache:
    """bounded LRU + 선택적 TTL. `ttl_s<=0` 이면 만료 없음(임베딩용)."""

    def __init__(self, maxsize: int, ttl_s: float = 0):
        self.maxsize = max(1, int(maxsize))
        self.ttl = float(ttl_s)
        self._d: dict = {}
        self._order: list = []  # LRU 순서(오래된 것 앞)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        with self._lock:
            entry = self._d.get(key, _MISS)
            if entry is _MISS:
                self.misses += 1
                return _MISS
            ts, val = entry
            if self.ttl > 0 and (time.monotonic() - ts) > self.ttl:
                self._d.pop(key, None)
                try:
                    self._order.remove(key)
                except ValueError:
                    pass
                self.misses += 1
                return _MISS
            # move to end(최근 사용)
            try:
                self._order.remove(key)
            except ValueError:
                pass
            self._order.append(key)
            self.hits += 1
            return val

    def set(self, key, val) -> None:
        with self._lock:
            self._d[key] = (time.monotonic(), val)
            try:
                self._order.remove(key)
            except ValueError:
                pass
            self._order.append(key)
            while len(self._order) > self.maxsize:
                old = self._order.pop(0)
                self._d.pop(old, None)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self._order.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "size": len(self._d),
                "maxsize": self.maxsize,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
            }
