"""앱 로깅 설정 — root 핸들러 1개 (2026-10-02).

**이 파일이 생기기 전까지 앱 로그는 대부분 사라지고 있었다.**

uvicorn 은 `uvicorn.*` 로거만 설정하고 root 에는 핸들러를 달지 않는다. 그래서
`logging.getLogger(__name__)` 로 만든 앱 로거 276곳의 출력이 root 로 전파돼
`logging.lastResort`(stderr · WARNING 이상 · 포매터 없음)로 떨어졌다. 결과:

- `_log.info` / `_log.debug` → **전부 소멸** (커버리지 게이트 스킵·검색 필터 제외
  건수·스킬 라우팅·orphan 복원·품질 감사 이벤트 5곳)
- `_log.warning` / `error` → 시각·로거명·레벨명 없이 메시지만

`docs/OPERATIONS.md` 의 일일 점검 `docker compose logs | grep ERROR` 는 레벨명이
출력에 없어 **구조적으로 아무것도 잡지 못했고**, `OPERATIONS.md §4-9` 가 경고하는
best-effort `except` 가 삼키는 배선 오류는 그 WARNING 을 읽을 파이프가 없었다.
compose 의 `LOG_LEVEL` 은 아무도 읽지 않았다.

한 번만 부른다(`api.py` 모듈 로드 시). 이미 root 에 핸들러가 있으면(테스트의
caplog·외부 임베딩) 건드리지 않는다.
"""

from __future__ import annotations

import logging
import os
import sys

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"


def setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return  # pytest caplog · 외부 호스팅 — 그쪽 설정을 존중

    level_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    root.addHandler(handler)
    root.setLevel(level)

    # 시끄러운 서드파티는 WARNING 으로 — 앱 로그가 묻히지 않게.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
