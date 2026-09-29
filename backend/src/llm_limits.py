"""프로세스 전역 LLM client-side rate limiter (ADR-0001 Phase 5 이관).

구 `src/middleware/llm_rate_limit.py`(langgraph AgentMiddleware)에서 limiter
빌드/전역 공유만 분리 — 모든 모델 인스턴스가 `rate_limiter=` 로 같은 버킷을
공유해야 집계 속도 캡이 된다 (Anthropic 429 폭풍 방지).

env:
- ``LLM_MAX_RPS``              초당 허용 모델 호출 (기본 8)
- ``LLM_RATE_BUCKET``          버스트 버킷 크기 (기본 = LLM_MAX_RPS)
- ``LLM_RATE_LIMIT_DISABLE=1`` 비활성 (테스트·벤치)
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_core.rate_limiters import InMemoryRateLimiter


def _build_limiter() -> Optional[InMemoryRateLimiter]:
    if (os.getenv("LLM_RATE_LIMIT_DISABLE") or "").strip() == "1":
        return None
    try:
        rps = float((os.getenv("LLM_MAX_RPS") or "").strip() or "8")
    except ValueError:
        rps = 8.0
    try:
        # 미설정·빈 값·공백이면 RPS 와 같게(버스트 없음). 바로 `or` 만 쓰면
        # 공백(" ")이 truthy 라 float(" ") 로 터진다 — 프로젝트 관용구로 통일.
        bucket = float((os.getenv("LLM_RATE_BUCKET") or "").strip() or str(rps))
    except ValueError:
        bucket = rps
    return InMemoryRateLimiter(
        requests_per_second=max(0.1, rps),
        check_every_n_seconds=0.1,
        max_bucket_size=max(1.0, bucket),
    )


_LIMITER = _build_limiter()


def global_rate_limiter() -> Optional[InMemoryRateLimiter]:
    """전역 단일 limiter (비활성 시 None) — 모든 모델 생성 시 공유."""
    return _LIMITER
