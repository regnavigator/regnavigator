"""의도 분류 서비스 클라이언트 — 입력을 4분류(법령문의/업무절차/일반/off-topic).

가드레일 입구에서 "이 질문에 검색이 필요한가"를 **결정적으로** 판정하기 위한
경량 분류(Qwen3.5-0.8B 등, DGX 호스팅). 답변 모델이 검색 여부를 판단하면
(특히 소형 모델) 캐주얼·후속 어투에서 검색을 건너뛰고 환각하므로, 이 판정을
입구로 끌어올린다.

계약(서비스 측) — 이진(0.8B 에 4분류는 부정확, 이진이 정확):
    POST /classify   (헤더 X-API-Key)
    { "text": "...", "context": "직전 주제(옵션)" }
    → { "search_needed": bool, "label": "예"|"아니오" }

env:
- INTENT_API_URL   : 서비스 베이스 URL. 미설정 시 휴리스틱 폴백(intent.py).
- INTENT_API_KEY   : X-API-Key.
- INTENT_TIMEOUT_S : 타임아웃(기본 1 — 입구 저지연).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

_log = logging.getLogger(__name__)


def _base_url() -> str:
    return (os.getenv("INTENT_API_URL") or "").rstrip("/")


def _api_key() -> str:
    return os.getenv("INTENT_API_KEY") or ""


def _timeout_s() -> float:
    try:
        return float((os.getenv("INTENT_TIMEOUT_S") or "").strip() or "1")
    except ValueError:
        return 1.0


def is_available() -> bool:
    return bool(_base_url() and _api_key())


@lru_cache(maxsize=1)
def _client():
    import httpx

    return httpx.Client(timeout=_timeout_s())


def _max_input_chars() -> int:
    try:
        return max(200, int((os.getenv("INTENT_MAX_INPUT_CHARS") or "").strip() or "2000"))
    except ValueError:
        return 2000


def _condense(text: str) -> str:
    """분류기 입력 축약 — 앞뒤를 남기고 가운데를 자른다.

    의도 판정에 필요한 건 "무엇을 묻는가"이지 문서 전문이 아니다. 사용자가 문서를
    붙여넣으면 실제 질문은 **맨 앞이나 맨 뒤**에 붙는 경우가 대부분이라(“아래 문서
    검토해줘” / “…위 내용 관련 규정 알려줘”) 양끝을 함께 남긴다.

    이걸 안 하면 32,000자가 0.8B 분류기로 그대로 날아가 3초 타임아웃에 걸리고,
    호출자가 안전 기본값(True=검색)으로 폴백한다 — 판정이 사실상 무력화된다.
    """
    limit = _max_input_chars()
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]}\n…(중략)…\n{text[-tail:]}"


def classify(text: str, context: str | None = None) -> bool | None:
    """검색 필요 여부(search_needed) 반환. 실패/미설정 시 None(호출자 폴백)."""
    if not text or not is_available():
        return None
    text = _condense(text)
    import httpx

    try:
        r = _client().post(
            f"{_base_url()}/classify",
            json={"text": text, "context": context},
            headers={"X-API-Key": _api_key()},
        )
        r.raise_for_status()
        return bool((r.json() or {}).get("search_needed"))
    except (httpx.HTTPError, ValueError) as e:
        _log.warning("intent classify 실패(휴리스틱 폴백): %s", type(e).__name__)
        return None
