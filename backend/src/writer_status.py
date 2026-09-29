"""보고서 writer(DGX vLLM) 도달 여부 — 공개 /load 에 실어 "보고서만 안 된다"를 보이게(2026-09-07).

writer 는 모델 고정이 아니고 운영자가 다른 작업에 쓰려고 내리기도 한다. 그동안
채팅은 정상인데 보고서만 안 되므로, 전체 점검이 아니라 **기능 단위** 안내가 맞다.
운영자 토글(maintenance.feature_paused("reports")) 없이도 실제로 내려가 있으면
경고를 띄우기 위해 여기서 짧게 캐시(기본 30s)하며 프로브한다.

/load 는 프런트가 5~15s 마다 폴링하므로 매번 프로브하면 안 된다. TTL 안에서는
직전 결과. 프로브 자체는 동기 urllib(타임아웃 3s) — 반드시 스레드풀(`def` 라우트)
에서 부른다(CLAUDE.md §7).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_CACHE: dict = {"up": None, "at": 0.0}


def _ttl() -> float:
    try:
        return float((os.getenv("REPORT_WRITER_PROBE_TTL_S") or "").strip() or "30")
    except ValueError:
        return 30.0


def writer_reachable() -> bool | None:
    """True/False = 프로브 결과, None = 로컬 writer 미설정(Sonnet 폴백이라 항상 가능)."""
    base = (os.getenv("REPORT_WRITER_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return None
    now = time.monotonic()
    with _lock:
        if _CACHE["up"] is not None and now - _CACHE["at"] < _ttl():
            return _CACHE["up"]
    up = True
    try:
        urllib.request.urlopen(f"{base}/models", timeout=3).read(64)
    except Exception as e:  # noqa: BLE001
        up = False
        _log.info("report writer 미도달: %s", type(e).__name__)
    with _lock:
        _CACHE["up"] = up
        _CACHE["at"] = now
    return up


def invalidate_cache() -> None:
    with _lock:
        _CACHE["up"] = None
        _CACHE["at"] = 0.0
