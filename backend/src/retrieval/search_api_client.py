"""openlaw-etl 검색 API 클라이언트 — RAG 랭킹 + grounding 원문.

서버(search-server, DGX)가 dense(KURE) + BM25 + RRF + 리랭커 + 법률종 부스팅 +
조문 GROUP BY 를 전부 처리한다. medi-back 은 이 HTTP 계약만 안다 — 로컬 임베딩·
Qdrant·sparse·리랭커 및 PG/Mongo/Neo4j 직접 결합 없음(thin-client).

계약: openlaw-etl `search-server/API.md` +
      `docs/etl_requests/search_api_citation_enrichment.md`

env:
- RAG_SEARCH_API_URL   : 베이스 URL (예: http://192.0.2.10:8080). 미설정 시 검색 불가.
- RAG_SEARCH_API_KEY   : X-API-Key.
- RAG_SEARCH_TIMEOUT_S : 요청 타임아웃 초 (기본 20 — 리랭커 GPU 콜드 대비).
- RAG_SEARCH_TARGET_TYPES : 기본 종별 CSV. **미설정 시 서버가 지금 서빙하는 종별을 조회해 쓴다**
                            (`available_target_types()`, 2026-10-06) — 그마저 실패하면 코드 기본값.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from functools import lru_cache
from typing import Any

from src.retrieval.cache import _MISS, TTLCache

_log = logging.getLogger(__name__)

# 검색 백프레셔 — 동시 /search 호출을 SEARCH_MAX_CONCURRENCY 개로 제한. 단일 GPU
# 리랭커가 동시요청에 thrash(초선형 지연)하는 걸 방지. 동기 툴이 스레드풀에서
# 도므로 threading 세마포어(모든 검색 스레드가 공유). 캐시 히트는 슬롯 안 씀.
_SEARCH_SEM: threading.BoundedSemaphore | None = None
_SEARCH_SEM_LOCK = threading.Lock()


def _search_wait_timeout_s() -> float:
    """세마포어 대기 상한(초). 기본 30 — 리랭커 한 건이 수 초라 2슬롯이면 넉넉하다."""
    try:
        return float((os.getenv("SEARCH_WAIT_TIMEOUT_S") or "").strip() or "30")
    except ValueError:
        return 30.0


def _search_semaphore() -> threading.BoundedSemaphore:
    global _SEARCH_SEM
    if _SEARCH_SEM is None:
        with _SEARCH_SEM_LOCK:
            if _SEARCH_SEM is None:
                n = max(1, int((os.getenv("SEARCH_MAX_CONCURRENCY") or "").strip() or "2"))
                _SEARCH_SEM = threading.BoundedSemaphore(n)
    return _SEARCH_SEM

# 검색 결과 캐시 — 법령 코퍼스는 안정적이라 같은 질의 재사용 안전.
_search_cache = TTLCache(
    maxsize=int((os.getenv("SEARCH_CACHE_SIZE") or "").strip() or "512"),
    ttl_s=float((os.getenv("SEARCH_CACHE_TTL_S") or "").strip() or "3600"),
)


def _base_url() -> str:
    return (os.getenv("RAG_SEARCH_API_URL") or "").rstrip("/")


def _api_key() -> str:
    return os.getenv("RAG_SEARCH_API_KEY") or ""


def _timeout_s() -> float:
    try:
        return float((os.getenv("RAG_SEARCH_TIMEOUT_S") or "").strip() or "20")
    except ValueError:
        return 20.0


def is_available() -> bool:
    """URL·키 둘 다 설정돼 있으면 True."""
    return bool(_base_url() and _api_key())


def _normalize_query(q: str) -> str:
    """캐시 키용 정규화 — 앞뒤/연속 공백 정리 + 소문자. 의미(조사·어순)는 보존."""
    return re.sub(r"\s+", " ", q.strip()).lower()


def keepalive() -> bool:
    """리랭커 웜 유지 — 최소 검색으로 GPU 태움(캐시 우회). best-effort.

    idle 후 첫 사용자가 콜드(~7.5s) 맞는 걸 방지(웜 ~2.8s). lifespan 배경 태스크가
    주기 호출(SEARCH_KEEPALIVE_S). 캐시를 안 타 매번 실제 리랭커를 돌린다.
    """
    if not is_available():
        return False
    try:
        _post("/search", {"query": "의료기기 허가", "top_k": 1})
        return True
    except SearchApiError:
        return False


@lru_cache(maxsize=1)
def _client():
    """httpx 클라이언트 — lazy init(프로세스당 1회)."""
    import httpx

    return httpx.Client(timeout=_timeout_s())


class SearchApiError(RuntimeError):
    """검색 API 호출 실패 — 호출자(run_qdrant)가 SearchError 로 변환."""


def _post(path: str, payload: dict) -> Any:
    if not is_available():
        raise SearchApiError(
            "검색 API 미설정 (RAG_SEARCH_API_URL / RAG_SEARCH_API_KEY)."
        )
    import httpx

    url = f"{_base_url()}{path}"
    try:
        resp = _client().post(
            url, json=payload, headers={"X-API-Key": _api_key()}
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200] if e.response is not None else ""
        raise SearchApiError(f"검색 API {e.response.status_code}: {body}") from e
    except httpx.HTTPError as e:
        raise SearchApiError(f"검색 API 연결 실패: {type(e).__name__}") from e


def search_articles(
    query: str, *, top_k: int = 8, target_types: list[str] | None = None,
    include_pending: bool | None = None,
) -> list[dict]:
    """자연어 질의 → 랭킹된 조문 리스트(article 단위 GROUP BY, 서버 랭킹).

    반환 각 항목 필드: article_key·law_id·mst_id·law_title·article_num·
    article_title·law_tier·target_type·chunk_type·attachment_subtype·
    attachment_link·article_url·score·enforcement_date·promulgation_date·
    is_current·effective_status·enforced·department·snippet
    (+ include_pending 시 version_status·supersedes_article_key).
    실패 시 SearchApiError.

    include_pending: 같은 조문의 **시행예정본을 현행 hit 바로 뒤에 동반**
    (openlaw-etl RFC LAW_VERSION_CURRENT_VS_PENDING R3, 2026-08-16 회신).
    top_k 외 추가분이라 현행 결과 수는 줄지 않는다. 예정본 키는 `_ef{YYYYMMDD}`
    접미가 붙고 `article_url` 은 null(무버전 링크는 현행을 가리켜 오도).
    None 이면 env `SEARCH_INCLUDE_PENDING`(기본 1) — 서버 미배포·구 스키마에선
    서버가 조용히 생략하므로 켠 채로 안전하다.
    """
    if include_pending is None:
        include_pending = (
            os.getenv("SEARCH_INCLUDE_PENDING", "1").strip() != "0")
    body: dict[str, Any] = {"query": query, "top_k": top_k}
    tts = target_types or _default_target_types()
    if tts:
        body["target_types"] = tts
    if include_pending:
        body["include_pending"] = True

    # 정규화 캐시 키 — 공백·대소문자 차이는 같은 질의로(적중률↑, 검색 스킵).
    # 조사·어순은 건드리지 않음(법률 의미 보존).
    # ⚠️ include_pending 은 키에 포함 — 같은 질의라도 응답 집합이 다르다.
    cache_key = (_normalize_query(query), top_k, tuple(tts) if tts else None,
                 bool(include_pending))
    cached = _search_cache.get(cache_key)
    if cached is not _MISS:
        return cached

    # 백프레셔 — GPU thrash 방지(캐시 미스만 슬롯 점유) + 부하 추적(혼잡 표시).
    from src.observability import load

    sem = _search_semaphore()
    if not sem.acquire(blocking=False):
        # 대기에 **상한**을 건다(2026-10-02). 종전 `sem.acquire()` 는 무한 대기였고
        # 그 대기가 `asyncio.to_thread` 스레드를 붙잡는다 — 캐시 미스가 몰리면
        # 스레드풀(기본 cpu+4)이 검색 대기로 고갈돼 **DB·SMTP·PII 까지 포함한 전
        # 요청이 같이 멈춘다**. 못 기다리면 명시적으로 거절한다(503 로 번역됨).
        load.search_wait(1)  # 만석 → 대기 시작(사용자에 혼잡 표시)
        try:
            if not sem.acquire(timeout=_search_wait_timeout_s()):
                raise SearchApiError(
                    "검색 서버가 혼잡해 잠시 기다렸지만 차례가 오지 않았습니다. "
                    "잠시 후 다시 시도해 주세요.")
        finally:
            load.search_wait(-1)
    load.search_active(1)
    try:
        hits = _post("/search", body)
    finally:
        load.search_active(-1)
        sem.release()
    if not isinstance(hits, list):
        # 200 OK 인데 내용물이 배열이 아닌 케이스. 2026-07-25 실측 5회+ 의 원인은
        # 서버 내부 오류가 아니라 **혼합 target_types(law+guide) 응답이 kind별
        # dict** 였던 것 — 같은 날 서버가 "200 이면 언제나 평탄 list"(dict 는
        # response_shape:"sections" opt-in)로 고쳐 배포했다
        # (openlaw-etl SEARCH_200_MALFORMED_PAYLOAD.md §5).
        # 이 가드는 계약 백스톱으로 남긴다 — 재발 시 payload 앞 150자가 증거가
        # 된다. 이 메시지는 로그·step 용이며 사용자 향 문구는 도구 래퍼가 일반화.
        raise SearchApiError(
            f"검색 API 응답 형식 오류(list 아님): {repr(hits)[:150]}")
    # 항목 무결성 가드 — list 여도 내용물이 불량이면(비 dict, article_key 없음)
    # 다운스트림이 크래시(h.get)하거나 정체불명 citation 이 생긴다. article_key 는
    # 인용 identity·grounding·pinned 의 앵커라 없으면 그 항목은 쓸 수 없다.
    clean = [h for h in hits
             if isinstance(h, dict) and h.get("article_key")]
    if len(clean) != len(hits):
        bad = [h for h in hits
               if not (isinstance(h, dict) and h.get("article_key"))]
        _log.warning(
            "search API 응답 %d건 중 %d건 스키마 불량 — 폐기 (예: %s)",
            len(hits), len(bad), repr(bad[:2])[:200])
        if not clean:
            # 전건 불량 = 형식 오류와 동급 — 조용한 빈손 대신 명시 실패
            # (호출자 재시도·충분성 게이트가 정상 동작하도록).
            raise SearchApiError(
                f"검색 API 응답 전건 스키마 불량: {repr(hits)[:150]}")
        # 일부만 불량 = 흔들리는 순간의 산물일 수 있음 — 이번 응답은 캐시하지
        # 않는다(불량 섞인 결과가 1시간 재사용되는 오염 방지).
        return clean
    if hits:  # 빈 결과는 캐시 안 함(코퍼스 갱신 시 회복).
        _search_cache.set(cache_key, hits)
    return hits


# 검색 API `/articles/bodies` 의 요청당 키 상한(서버 pydantic 검증값).
# ⚠️ 넘기면 **422 로 전건 실패** — 21개를 보내면 20개가 오는 게 아니라 0개가 온다.
_BODIES_MAX_KEYS = 20


def fetch_bodies(article_keys: list[str]) -> dict[str, dict]:
    """article_key 배치 → 원문(grounding·보고서·pinned 용). best-effort — 실패 시 {}.

    반환: {article_key: {full_text, article_num, law_title, article_title}}.
    서버가 PG full_text 우선 → 색인 폴백 → <br/> 정제까지 처리.

    ⚠️ 실측 사고(2026-08-02): 서버 상한 20 을 모른 채 전량(24·37건)을 한 번에
    보내 **422 → {} → 조용히 원문 없음**이 됐다. 보고서는 조문 원문 대신 스니펫만
    보고 쓰였고, grounding 은 대조할 본문이 없어 인용 검증이 통과하지 못했다.
    로그는 `fetch_bodies 실패(무시)` 한 줄뿐이라 몇 달 눈에 안 띌 수 있었다.
    그래서 여기서 **청크로 쪼갠다** — 한 청크가 실패해도 나머지는 살린다.
    """
    keys = [k for k in dict.fromkeys(article_keys) if k]
    if not keys:
        return {}
    merged: dict[str, dict] = {}
    for i in range(0, len(keys), _BODIES_MAX_KEYS):
        chunk = keys[i:i + _BODIES_MAX_KEYS]
        try:
            out = _post("/articles/bodies", {"article_keys": chunk})
            if isinstance(out, dict):
                merged.update(out)
        except SearchApiError as e:
            _log.warning("fetch_bodies 청크 실패(무시): %d~%d/%d: %s",
                         i, i + len(chunk), len(keys), e)
    return merged


def ping() -> tuple[bool, str | None]:
    """readiness probe — GET /search/health. (ok, detail|None)."""
    if not is_available():
        return False, "RAG_SEARCH_API_URL/KEY 미설정"
    import httpx

    try:
        r = _client().get(
            f"{_base_url()}/search/health", headers={"X-API-Key": _api_key()}
        )
        r.raise_for_status()
        return True, None
    except httpx.HTTPError as e:
        return False, f"{type(e).__name__}"


# 기본 검색 종별 — 법령류 + 판례(prec)·법령해석례(expc). 검색 서버 RRF+리랭커가 법령을
# 우선 랭킹하므로 조문 질의 희석 낮음(실측: 판례 포함해도 top-k 다수가 법령).
# **코드 기본값은 폴백일 뿐이다**(2026-10-06): 서버가 지금 서빙하는 종별을 조회해 쓴다.
_DEFAULT_TARGET_TYPES = ["law", "admrul", "ordin", "prec", "expc"]

#: law 엔진(최상위 Qdrant 컬렉션)이 함께 색인하는 종별 — 서버 `SearchRequest.target_types`
#: 설명·`SearchHitOut.target_type` 어휘. health 에 별도 키가 없어 law 엔진이 살아 있으면
#: 이 다섯이 전부 있다고 본다(ETL 이 5종을 한 컬렉션에 넣는다).
_LAW_ENGINE_TYPES = ["law", "admrul", "ordin", "prec", "expc"]
#: DocChunk 서브엔진 — health 에 **같은 이름의 키**로 상태가 온다.
_DOC_ENGINE_TYPES = ["guide", "admrul_attach", "addendum"]

_TT_CACHE: dict[str, Any] = {"at": 0.0, "value": None}
_TT_TTL_S = 600.0


def _probe_target_types() -> list[str] | None:
    """`GET /search/health` 로 **지금 서빙 중인** 종별을 알아낸다.

    law 엔진은 최상위 `qdrant_points>0`·`reranker_loaded`. DocChunk 엔진은 같은 이름의
    하위 dict 에 `qdrant_points>0` 이면 서빙 중(bm25 는 지연 로드라 보지 않는다).
    실패·형태 불일치면 None(호출자가 폴백).
    """
    if not is_available():
        return None
    import httpx

    try:
        r = _client().get(f"{_base_url()}/search/health",
                          headers={"X-API-Key": _api_key()})
        r.raise_for_status()
        h = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(h, dict) or not int(h.get("qdrant_points") or 0):
        return None
    out = list(_LAW_ENGINE_TYPES)
    for t in _DOC_ENGINE_TYPES:
        sub = h.get(t)
        if isinstance(sub, dict) and int(sub.get("qdrant_points") or 0) > 0 \
                and sub.get("reranker_loaded"):
            out.append(t)
    return out


def available_target_types(*, refresh: bool = False) -> list[str]:
    """서버가 지금 서빙하는 종별(10분 캐시). 조회 실패면 코드 기본값.

    `RAG_SEARCH_TARGET_TYPES` 가 있으면 그것이 최우선(운영자가 일부러 좁힌 것).
    """
    import time as _t

    raw = (os.getenv("RAG_SEARCH_TARGET_TYPES") or "").strip()
    if raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    now = _t.monotonic()
    if not refresh and _TT_CACHE["value"] and now - _TT_CACHE["at"] < _TT_TTL_S:
        return list(_TT_CACHE["value"])
    probed = _probe_target_types()
    if probed:
        _TT_CACHE.update(at=now, value=probed)
        return list(probed)
    return list(_TT_CACHE["value"] or _DEFAULT_TARGET_TYPES)


def _default_target_types() -> list[str] | None:
    """검색 기본 종별 — 서빙 중인 종별 중 **검색 기본에 넣는 것**(law 엔진 5종).

    DocChunk 엔진(guide·admrul_attach·addendum)은 서빙 중이어도 기본에 넣지 않는다 —
    LLM 이 `doc_kinds` 로 고를 때만(가이드라인 질의 등). 기본에 섞으면 조문 질의가 희석된다.
    """
    avail = available_target_types()
    base = [t for t in _LAW_ENGINE_TYPES if t in avail]
    return base or list(_DEFAULT_TARGET_TYPES)


def amendment_status(law_ids: list[str]) -> dict[str, str]:
    """`POST /openlaw/amendment-status` — law_id → current·repealed·pending… (2026-10-06).

    "현행본 미보유" 고지(`legal.pending_only_laws`)는 턴의 인용 상태로 판정하는데, 이 API 는
    법령 단위의 **서버 판정**을 준다. 판정 전 법령은 응답에 없다. 실패하면 빈 dict.
    """
    ids = [str(x).strip() for x in dict.fromkeys(law_ids or []) if str(x).strip()]
    if not ids or not is_available():
        return {}
    try:
        out = _post("/openlaw/amendment-status", {"law_ids": ids[:200]})
    except SearchApiError as e:
        _log.info("amendment-status 실패(무시): %s", e)
        return {}
    st = out.get("status") if isinstance(out, dict) else None
    return {str(k): str(v) for k, v in (st or {}).items()} if isinstance(st, dict) else {}
