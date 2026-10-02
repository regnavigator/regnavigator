"""PII NER 서비스 클라이언트 — 문맥 의존 민감정보(이름·주소 등) 2차 탐지.

regex 1차(`pii.py`)가 구조적 PII 를 잡고, 이 클라이언트가 별도 가드레일 서비스
(OpenMed/privacy-filter-multilingual 등 토큰 분류 NER 을 호스팅)에 텍스트를 보내
이름·주소·기관 같은 **문맥 PII 스팬**을 받아온다. 모델은 그 서비스가 소유 —
medi-back 은 로컬 ML 을 두지 않는다(thin-client 일관).

계약(서비스 측):
    POST /detect   (헤더 X-API-Key)
    { "text": "..." }
    → { "entities": [ {"start": int, "end": int, "label": str, "text": str}, ... ] }
`label` 은 OpenMed 카테고리(PERSON/NAME·ADDRESS·… 54종). 오프셋은 요청 text 기준.

env:
- PII_NER_API_URL   : 서비스 베이스 URL. 미설정 시 2차 비활성(regex-only).
- PII_NER_API_KEY   : X-API-Key.
- PII_NER_TIMEOUT_S : 타임아웃(기본 3 — 입구 저지연 유지).
- PII_NER_CHUNK_CHARS / _OVERLAP / _MAX_PARALLEL : 긴 입력 분할(아래).

## 긴 입력은 반드시 분할해서 보낸다 (2026-08-04)

서버는 transformers `token-classification` 파이프라인을 truncation·chunking 설정
없이 쓴다(`guardrail-server/serve.py`). BERT 계열 토큰 분류 모델은 대개 **512
토큰**이 상한이라, 긴 텍스트를 통째로 보내면 에러가 나거나 **앞부분만 처리되고
조용히 끝난다**. 그리고 이 클라이언트는 실패를 삼키고 regex-only 로 진행하므로,
문서 뒷부분의 이름·주소가 **마스킹되지 않은 채** 저장·전송된다.

사용자가 문서를 붙여넣는 입력이 PII 를 담을 확률이 가장 높다는 점에서 가장 나쁜
조합이었다. 그래서 클라이언트가 문자 단위로 잘라 보내고 오프셋을 되돌려 합친다
— 서버를 재배포하지 않아도 medi-back 배포만으로 닫힌다.

경계에서 이름이 두 조각으로 갈리면 양쪽 다 문맥을 잃어 **아예 탐지되지 않으므로**
청크를 겹쳐 보낸다(overlap). 겹침으로 생기는 중복 스팬은 `gate._apply_spans` 가
이미 정리하지만, 여기서도 같은 라벨의 인접/중복 스팬은 병합해서 넘긴다.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import os
import threading
import time as _time
from collections import OrderedDict
from concurrent.futures import CancelledError
from functools import lru_cache

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 결과 캐시 — 같은 텍스트를 턴마다 재검사하는 낭비 제거(2026-08-14 안정선 강화).
#
# 한 턴에서 NER 은 2~3회 불린다: ① at-rest(입력 저장 전) ② egress(LLM 콜마다
# 히스토리의 human 메시지 재검사 — 백스톱). 텍스트가 같으면 결과도 같은데
# 매번 왕복했고, DGX GPU 경합으로 회당 0.5s→2~3s 가 되자 지연이 배수로 붙었다
# (같은 날 인시던트: 팀원 학습 작업 → 전 턴 fail-closed). 완료(complete=True)
# 결과만 content-hash 로 캐시한다 — 안전성 불변(같은 입력, 같은 판정의 재사용).
# TTL 을 두는 이유: NER 서버 모델이 재배포로 바뀌면 판정도 바뀔 수 있다.
# ---------------------------------------------------------------------------
_RESULT_CACHE: "OrderedDict[str, tuple[float, list[dict]]]" = OrderedDict()
_RESULT_CACHE_MAX = 512
_RESULT_CACHE_TTL_S = 600.0
_result_lock = threading.Lock()


def _cache_get(key: str):
    with _result_lock:
        item = _RESULT_CACHE.get(key)
        if item is None:
            return None
        at, spans = item
        if _time.monotonic() - at > _RESULT_CACHE_TTL_S:
            _RESULT_CACHE.pop(key, None)
            return None
        _RESULT_CACHE.move_to_end(key)
        # 호출부(gate)가 스팬 dict 를 만질 수 있으므로 복사본을 준다.
        return copy.deepcopy(spans)


def _cache_put(key: str, spans: list[dict]) -> None:
    with _result_lock:
        _RESULT_CACHE[key] = (_time.monotonic(), copy.deepcopy(spans))
        _RESULT_CACHE.move_to_end(key)
        while len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)


def reset_result_cache() -> None:
    """테스트 격리·서버 모델 교체 직후 강제 무효화."""
    with _result_lock:
        _RESULT_CACHE.clear()


def _base_url() -> str:
    return (os.getenv("PII_NER_API_URL") or "").rstrip("/")


def _api_key() -> str:
    return os.getenv("PII_NER_API_KEY") or ""


def _timeout_s() -> float:
    try:
        return float((os.getenv("PII_NER_TIMEOUT_S") or "").strip() or "3")
    except ValueError:
        return 3.0


def is_available() -> bool:
    """URL·키 둘 다 설정돼 있으면 True(미설정이면 regex-only)."""
    return bool(_base_url() and _api_key())


@lru_cache(maxsize=1)
def _client():
    import httpx

    return httpx.Client(timeout=_timeout_s())


def _chunk_chars_raw() -> int:
    """설정값 원본 — 0 이면 '클라이언트 청킹 끔'(서버가 처리)."""
    try:
        return max(0, int((os.getenv("PII_NER_CHUNK_CHARS") or "").strip() or "600"))
    except ValueError:
        return 600


def _chunk_chars() -> int:
    """청크 크기(문자). 모델 상한 512 토큰을 한국어 최악 비율로 잡아 보수적으로."""
    return max(200, _chunk_chars_raw() or 600)


def _chunk_overlap() -> int:
    """청크 겹침(문자). 경계에 걸친 이름·주소가 어느 한쪽에는 온전히 들어가도록."""
    try:
        return max(0, int((os.getenv("PII_NER_CHUNK_OVERLAP") or "").strip() or "100"))
    except ValueError:
        return 100


def _max_parallel() -> int:
    """청크 동시 요청 수.

    4 → **2** 로 하향(2026-08-04 DGX 회신 A-1 합의). 8/4 호스트 다운의 확정 원인이
    GB10 통합메모리(121GB) 고갈이었고, NER 추론 부하가 활성화 메모리를 밀어올린
    것이 방아쇠였다. 동시 요청 수가 곧 동시 활성화 메모리라 여기가 직접 레버다.
    """
    try:
        return max(1, int((os.getenv("PII_NER_MAX_PARALLEL") or "").strip() or "2"))
    except ValueError:
        return 2


def _total_budget_s() -> float:
    """긴 입력 전체 스캔에 허용할 **벽시계 예산**(초, 0=무제한).

    NER 은 DGX 공용 GPU(검색 리랭커·intent·writer 와 같은 장비)라 처리량이
    부하에 따라 3~4배까지 흔들린다(실측 2026-08-04: 같은 18,000자 입력이
    9.3초 → 33.4초). 청크 수에 비례하는 구조라 예산이 없으면 **채팅 입구
    지연이 사실상 무제한**이 된다(36,000자에서 45~100초 관측).

    그래서 개별 청크 타임아웃과 별개로 전체 예산을 둔다. 예산을 넘기면 남은
    청크를 포기하고 진행하되, 그 구간이 미마스킹이라는 사실을 경고로 남긴다
    — 조용히 넘기지 않는 것이 요점(같은 날 감사 C-5 와 같은 원칙).

    서버측 윈도잉 배포(2026-08-04) 후 왕복이 1회가 되면서 이 값은 **통짜 요청의
    타임아웃**으로도 쓰인다. 실측 36,754자 = 7.0초라 8초로는 부하 변동에 여유가
    없어 15초로 올렸다 — 넘으면 차단(fail-closed)이라 여유가 곧 가용성이다.

    30초(2026-09-14): 입력 상한을 150,000자로 올리면서 상향. NER 교체(8/14
    KoELECTRA) 후 실측은 150,000자 1.8s·300,000자 3.2s 로 여유가 크지만,
    공유 GPU 경합 시 3~4배 변동을 감안한 값이다.
    """
    try:
        return max(0.0, float((os.getenv("PII_NER_TOTAL_BUDGET_S") or "").strip() or "30"))
    except ValueError:
        return 30.0


# 서버 기능 탐지 캐시 — (판정, 만료시각). 배포 후 env 를 따로 만지지 않아도
# 새 서버로 바뀌면 자동으로 통짜 전송으로 넘어간다.
_CAP: dict = {"long_input": None, "at": 0.0}
_CAP_TTL_S = 300.0


def _server_handles_long_input() -> bool:
    """서버가 스스로 윈도잉+배치를 하는가(`/health.long_input`).

    True 면 클라이언트가 자를 이유가 없다 — 통째로 1회 보내는 편이 항상 빠르다
    (왕복 N→1). 구 서버는 이 키가 없으므로 False → 종전대로 클라이언트가 자른다.
    판정 실패도 False(보수적: 자르는 쪽이 안전).
    """
    import time as _t

    now = _t.monotonic()
    if _CAP["long_input"] is not None and now < _CAP["at"]:
        return bool(_CAP["long_input"])
    val = False
    try:

        r = _client().get(f"{_base_url()}/health",
                          headers={"X-API-Key": _api_key()})
        r.raise_for_status()
        val = bool((r.json() or {}).get("long_input"))
    except Exception as e:  # noqa: BLE001 — 탐지 실패는 구 서버로 간주
        _log.debug("pii_ner 기능 탐지 실패(클라이언트 청킹 유지): %s", type(e).__name__)
    _CAP.update({"long_input": val, "at": now + _CAP_TTL_S})
    _log.info("pii_ner 서버 긴입력 처리: %s", "서버측(통짜 전송)" if val else "클라이언트 청킹")
    return val


def reset_capability_cache() -> None:
    """테스트·배포 직후 재탐지용."""
    _CAP.update({"long_input": None, "at": 0.0})


def _bounds(n: int, size: int, overlap: int) -> list[tuple[int, int]]:
    """[(start, end), ...] — 겹치는 청크 경계."""
    if n <= size:
        return [(0, n)]
    step = max(1, size - overlap)
    out: list[tuple[int, int]] = []
    i = 0
    while i < n:
        out.append((i, min(i + size, n)))
        if i + size >= n:
            break
        i += step
    return out


def _post_chunk(text: str, start: int, end: int,
                timeout: float | None = None) -> list[dict]:
    """청크 1개 요청 → 원문 기준 오프셋으로 보정한 스팬. 실패 시 예외를 올린다.

    `timeout` 은 **통짜 전송**(서버 윈도잉) 때 쓴다. `PII_NER_TIMEOUT_S`(3초)는
    작은 청크 1개 기준으로 잡은 값이라, 입력 전체를 한 요청에 보내면 그대로
    터진다 — 실측 2026-08-04: 서버 배포 직후 18,000자·36,000자가 ReadTimeout
    으로 **전부 차단**됐다(서버는 3.9초에 정상 처리 중이었다).
    """
    resp = _client().post(
        f"{_base_url()}/detect",
        json={"text": text[start:end]},
        headers={"X-API-Key": _api_key()},
        **({"timeout": timeout} if timeout is not None else {}),
    )
    resp.raise_for_status()
    data = resp.json()
    ents = data.get("entities") if isinstance(data, dict) else None
    if not isinstance(ents, list):
        return []
    out: list[dict] = []
    for e in ents:
        if not isinstance(e, dict):
            continue
        try:
            s, t = int(e["start"]) + start, int(e["end"]) + start
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= s < t <= len(text)):
            continue
        out.append({**e, "start": s, "end": t, "text": text[s:t]})
    return out


def _merge(spans: list[dict], text: str) -> list[dict]:
    """같은 라벨의 겹침·인접 스팬 병합(청크 겹침으로 생긴 중복·조각 정리).

    score 는 **최댓값**을 남긴다 — 조각 중 하나라도 확신이 높으면 그 스팬은
    마스킹돼야 한다(gate 가 라벨별 최소 score 로 거른다).
    """
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: (s["start"], s["end"]))
    merged: list[dict] = []
    for s in spans:
        prev = merged[-1] if merged else None
        if (prev is not None
                and s.get("label") == prev.get("label")
                and s["start"] <= prev["end"]):
            prev["end"] = max(prev["end"], s["end"])
            prev["text"] = text[prev["start"]:prev["end"]]
            a, b = prev.get("score"), s.get("score")
            if b is not None:
                prev["score"] = b if a is None else max(a, b)
            continue
        merged.append(dict(s))
    return merged


def detect(text: str) -> list[dict]:
    """PII 스팬 리스트만 반환(하위호환). 완전성이 필요하면 `detect_spans`."""
    return detect_spans(text)[0]


def detect_spans(text: str) -> tuple[list[dict], bool]:
    """(스팬, **전 구간 스캔 완료 여부**).

    두 번째 값이 요점이다. False 면 입력의 일부가 문맥 PII 검사를 받지 못했다는
    뜻 — 그 구간의 이름·주소는 마스킹되지 않는다. 호출자(`gate`)가 이걸 보고
    **차단할지** 정한다(fail-open 금지, 2026-08-04).

    긴 입력은 겹치는 청크로 나눠 보내고 오프셋을 원문 기준으로 되돌려 합친다
    (모듈 docstring 참고). 서버가 윈도잉을 지원하면 통짜로 1회 보낸다.
    """
    if not text:
        return [], True
    if not is_available():
        # 서비스 미설정 = 문맥 PII 검사 자체가 없음 → 완료 아님.
        return [], False

    # 결과 캐시 — at-rest 에서 검사한 텍스트를 egress 백스톱이 매 LLM 콜마다
    # 재검사하는 구조라, 히트 시 왕복이 통째로 사라진다(턴당 2~3회 → 1회).
    cache_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True

    import httpx

    # 서버가 윈도잉을 하면 자르지 않는다 — 왕복 1회가 항상 유리하다.
    # (`PII_NER_CHUNK_CHARS=0` 으로도 강제 가능 — 탐지 우회용.)
    if _chunk_chars_raw() == 0 or _server_handles_long_input():
        bounds = [(0, len(text))]
    else:
        bounds = _bounds(len(text), _chunk_chars(), _chunk_overlap())

    # 단일 청크(대다수 질의 + 서버 윈도잉 시 통짜) — 스레드풀 없이 그대로.
    # 통짜 전송이면 요청 1건이 입력 전체를 처리하므로 청크용 3초 타임아웃으로는
    # 부족하다 → **전체 스캔 예산**을 타임아웃으로 쓴다(둘 다 "PII 검사에 쓸
    # 최대 시간"이라는 같은 의미다).
    if len(bounds) == 1:
        whole = bounds[0] == (0, len(text)) and len(text) > _chunk_chars()
        to = max(_timeout_s(), _total_budget_s()) if whole else None
        # 타임아웃 1회 재시도(2026-08-14) — DGX 공유 GPU 의 지연 스파이크가
        # fail-closed(턴 차단)로 직결되는 것 완화. 재시도는 짧은 입력(단일
        # 청크)만 — 긴 입력은 예산 상한이 이미 지연을 보호한다.
        for attempt in (1, 2):
            try:
                spans = _merge(_post_chunk(text, *bounds[0], timeout=to), text)
                _cache_put(cache_key, spans)
                return spans, True
            except httpx.TimeoutException as e:
                if attempt == 1 and not whole:
                    _log.info("pii_ner 타임아웃 — 1회 재시도")
                    continue
                _log.warning("pii_ner detect 실패: %s", type(e).__name__)
                return [], False
            except (httpx.HTTPError, ValueError) as e:
                _log.warning("pii_ner detect 실패: %s", type(e).__name__)
                return [], False

    import time
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeout, wait

    budget = _total_budget_s()
    deadline = (time.monotonic() + budget) if budget else None

    spans: list[dict] = []
    failed = 0
    pool = ThreadPoolExecutor(max_workers=min(_max_parallel(), len(bounds)))
    try:
        futures = [pool.submit(_post_chunk, text, s, e) for s, e in bounds]
        if deadline is not None:
            wait(futures, timeout=budget)
        for f in futures:
            if deadline is not None and not f.done():
                f.cancel()          # 아직 시작 안 한 청크는 취소된다
                failed += 1
                continue
            try:
                spans.extend(f.result(timeout=0 if deadline is not None else None))
            except (httpx.HTTPError, ValueError, _FTimeout, CancelledError) as e:
                failed += 1
                _log.debug("pii_ner 청크 실패: %s", type(e).__name__)
    finally:
        # 예산 초과 시 남은 작업을 기다리지 않고 반환한다(입구 지연 상한 유지).
        pool.shutdown(wait=False, cancel_futures=True)

    if failed:
        # 일부만 실패해도 그 구간의 이름·주소는 마스킹되지 않는다 — 반드시 보이게.
        _log.warning(
            "pii_ner 청크 %d/%d 미완료 — 해당 구간 문맥 PII 미마스킹(regex 만 적용). "
            "입력 %d자, 예산 %.1fs. 상시화되면 입력 상한(CHAT_MAX_INPUT_CHARS)을 "
            "낮추거나 NER 처리량을 늘려야 한다.",
            failed, len(bounds), len(text), budget)
    else:
        _log.debug("pii_ner %d청크 처리(%d자) → 스팬 %d", len(bounds), len(text), len(spans))
    merged = _merge(spans, text)
    if failed == 0:
        _cache_put(cache_key, merged)
    return merged, failed == 0
