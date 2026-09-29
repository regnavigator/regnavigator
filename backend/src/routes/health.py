"""운영 헬스체크 — liveness(`/healthz`) vs readiness(`/readyz`).

상용 운영: 로드밸런서·모니터가 의존성 상태를 알아야 한다. `/healthz` 는 프로세스
생존만(=liveness, 항상 200), `/readyz` 는 외부 의존(PG·검색API·Neo4j)을
짧은 타임아웃으로 병렬 probe 해 **무엇이 죽었는지** 보고한다(critical 다운 시 503).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()

_PROBE_TIMEOUT_S = float((os.getenv("READYZ_PROBE_TIMEOUT_S") or "").strip() or "4")


def _check_pg():
    from src.retrieval.pg_client import _get_pool
    pool = _get_pool()
    if pool is None:
        return False, "pool=None (PG_* env 미설정 또는 psycopg 미설치)"
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return True, None


def _check_search_api():
    # RAG 검색은 openlaw-etl /search API 로 위임 — 로컬 임베딩/Qdrant 없음.
    from src.retrieval.search_api_client import ping
    return ping()


def _check_neo4j():
    from src.retrieval.neo4j_client import _get_driver
    driver = _get_driver()
    if driver is None:
        return False, "driver=None (NEO4J_* env 미설정)"
    driver.verify_connectivity()
    return True, None


def _http_health(url: str | None, key: str | None, what: str):
    """DGX 서비스 `/health` GET — 미설정이면 '비활성'(다운 아님)."""
    if not url:
        return True, f"{what} 미설정(폴백 동작)"
    import httpx

    timeout = float((os.getenv("READYZ_PROBE_TIMEOUT_S") or "").strip() or "4")
    r = httpx.get(f"{url.rstrip('/')}/health",
                  headers={"X-API-Key": key or ""}, timeout=timeout)
    r.raise_for_status()
    return True, None


def _check_pii_ner():
    # 다운 → regex-only 폴백(구조적 PII 는 계속 마스킹, 이름·주소만 미탐).
    #
    # /health 핑이 아니라 **실추론**(/detect)을 잰다(2026-08-14): DGX GPU 경합으로
    # 추론이 0.5s→2~3s 로 굶주려 fail-closed 로 전 턴이 차단됐는데, /health 는
    # 15ms 로 멀쩡해 readyz·알림 어디에도 안 보였다. 임계(READYZ_NER_SLOW_S)
    # 초과 = degraded 로 보고해 운영 알림(dedup)이 나가게 한다.
    url = os.getenv("PII_NER_API_URL")
    key = os.getenv("PII_NER_API_KEY")
    if not url or not key:
        return True, "PII NER 미설정(폴백 동작)"
    import httpx

    timeout = float((os.getenv("READYZ_PROBE_TIMEOUT_S") or "").strip() or "4")
    try:
        slow_s = float((os.getenv("READYZ_NER_SLOW_S") or "").strip() or "2.5")
    except ValueError:
        slow_s = 2.5
    t0 = time.perf_counter()
    r = httpx.post(f"{url.rstrip('/')}/detect", json={"text": "홍길동입니다"},
                   headers={"X-API-Key": key}, timeout=timeout)
    r.raise_for_status()
    took = time.perf_counter() - t0
    if took > slow_s:
        return False, (f"추론 지연 {took:.1f}s(임계 {slow_s:.1f}s) — DGX GPU 경합"
                       f"(학습·대형 작업) 의심. 채팅 입구 지연·타임아웃 위험")
    return True, None


def _check_intent():
    # 다운 → 인사말 휴리스틱 폴백(규제면 검색강제 = 안전 기본값).
    return _http_health(os.getenv("INTENT_API_URL"), os.getenv("INTENT_API_KEY"),
                        "의도 분류")


def _check_report_writer():
    """로컬 27B(vLLM) — 다운 시 보고서만 영향(Sonnet 폴백 또는 실패). 채팅 무관."""
    base = os.getenv("REPORT_WRITER_BASE_URL")
    if not base:
        return True, "로컬 writer 미설정(Sonnet 사용)"
    import httpx

    timeout = float((os.getenv("READYZ_PROBE_TIMEOUT_S") or "").strip() or "4")
    r = httpx.get(f"{base.rstrip('/')}/models", timeout=timeout)
    r.raise_for_status()
    return True, None


def _check_doc_fill():
    """서식 기입 온프레미스 모델(원문 처리) — 결과는 기입 경로의 서킷 브레이커에도 반영된다."""
    from src.doc_fill import probe_onprem

    return probe_onprem()


# (name, fn, critical) — critical=True 면 다운 시 전체 readiness 실패(503).
# DGX 가드레일·writer 는 **non-critical**: 다운해도 graceful degradation 으로 대화는
# 계속된다(품질만 저하). 하지만 **보이게** 해야 운영자가 복구한다(SPOF 수용의 전제).
_PROBES = [
    ("postgres", _check_pg, True),            # 인용 원문(/article)·pinned grounding
    ("search_api", _check_search_api, True),  # RAG 검색(openlaw-etl /search)
    ("neo4j", _check_neo4j, False),           # 그래프·즉답만 영향
    ("pii_ner", _check_pii_ner, False),       # 다운 → regex-only(이름·주소 미탐)
    ("intent", _check_intent, False),         # 다운 → 휴리스틱(검색강제 기본값)
    ("report_writer", _check_report_writer, False),  # 다운 → 보고서만 영향
    ("doc_fill", _check_doc_fill, False),     # 다운 → 작성 도우미 503·개인정보 칸 미기입
]


async def _run_probe(name, fn, critical) -> tuple[str, dict]:
    t0 = time.perf_counter()
    try:
        ok, detail = await asyncio.wait_for(
            asyncio.to_thread(fn), timeout=_PROBE_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        ok, detail = False, f"timeout >{_PROBE_TIMEOUT_S}s"
    except Exception as e:  # noqa: BLE001
        # /readyz 는 공개 — 예외 문자열엔 DSN·내부 IP 가 실릴 수 있다.
        # 응답엔 유형명만, 상세는 서버 로그로.
        logging.getLogger(__name__).warning("readyz probe %s down: %s", name, e)
        ok, detail = False, type(e).__name__
    entry = {
        "status": "ok" if ok else "down",
        "critical": critical,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
    }
    if not ok and detail:
        entry["detail"] = detail
    return name, entry


@router.get("/readyz")
async def readyz():
    """의존성 readiness — critical(PG·검색API) 다운 시 503.

    응답: { status: "ok"|"degraded", checks: { dep: {status, critical, latency_ms, detail?} } }
    로드밸런서·모니터가 503 을 보고 트래픽 제외/알림. 병렬 probe + 짧은 타임아웃.
    """
    results = dict(await asyncio.gather(
        *[_run_probe(n, f, c) for n, f, c in _PROBES]
    ))
    down_critical = [
        k for k, v in results.items() if v["critical"] and v["status"] != "ok"
    ]
    status = "ok" if not down_critical else "degraded"

    # 운영 알림 — dedup 으로 폴링 스팸 방지. 비차단.
    #  · critical 다운 → critical 알림(503).
    #  · 가드레일 다운 → warning 알림. 대화는 계속되나 **PII NER 다운은 이름·주소가
    #    마스킹 안 됨 = 컴플라이언스 리스크** → 조용히 넘기지 않는다(SPOF 수용의 전제).
    degraded_guard = [
        k for k, v in results.items()
        if not v["critical"] and v["status"] != "ok" and k in ("pii_ner", "intent")
    ]
    if down_critical or degraded_guard:
        from src.observability.alerts import send_ops_alert

        def _note(dep: str) -> str:
            return ("PII 이름·주소 마스킹 저하(regex-only) — 컴플라이언스 확인"
                    if dep == "pii_ner" else "의도 분류 폴백(검색강제 기본값)")

        # probe 는 gather 로 병렬인데 알림만 순차 await 였다 — 의존성 수만큼 응답이
        # 늘어난다(LB 가 /readyz 를 짧은 주기로 때리면 누적). 같이 병렬로.
        alerts = [
            asyncio.to_thread(
                send_ops_alert,
                f"의존성 다운: {dep}",
                str(results[dep].get("detail") or ""),
                severity="critical",
                dedup_key=f"dep_down:{dep}",
            )
            for dep in down_critical
        ] + [
            asyncio.to_thread(
                send_ops_alert,
                f"가드레일 저하: {dep}",
                f"{_note(dep)}. {results[dep].get('detail') or ''}",
                severity="warning",
                dedup_key=f"guard_down:{dep}",
            )
            for dep in degraded_guard
        ]
        await asyncio.gather(*alerts, return_exceptions=True)

    # 단일 인스턴스 락 상태 — held(정상) | skipped(dev) | unavailable(PG 미확인)
    # | conflict(warn 모드로 **다중 실행 중**). conflict 는 조용히 넘기면 안 되는
    # 상태라 운영이 /readyz 에서 바로 보게 노출한다(감사 C-4).
    from src import single_instance

    return JSONResponse(
        {"status": status, "checks": results,
         "single_instance": single_instance.state()},
        status_code=200 if not down_critical else 503,
    )


@router.get("/legal")
def legal_notice():
    """법적 고지 정본 — 프런트가 **상시 노출**(푸터/배너)용으로 가져간다(인증 X).

    응답: { version, disclaimer_short, disclaimer_report, key_points[], docs{} }
    `version` 이 바뀌면 프런트가 재동의를 받을 수 있다. 정본: `src/legal.py`.
    """
    from src.legal import LEGAL_NOTICE

    return JSONResponse(LEGAL_NOTICE)


@router.get("/legal/{doc}")
def legal_document(doc: str):
    """약관·개인정보처리방침 **정본**(markdown) — 프런트가 이걸 렌더한다(인증 X).

    `doc` = `terms` | `privacy`. 정본은 `docs/legal/{doc}.md` 하나뿐이다 — 프런트가
    별도 페이지에 본문을 하드코딩하면 두 벌이 되어 실제 동작과 어긋난다(실제로
    §3 보유기간·§5 이전받는 자가 어긋나 있었다).
    """
    import pathlib

    from src.legal import LEGAL_VERSION

    if doc not in ("terms", "privacy"):
        raise HTTPException(status_code=404, detail="terms|privacy 만 지원")
    p = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "legal" / f"{doc}.md")
    if not p.exists():
        raise HTTPException(status_code=500, detail=f"정본 문서 없음: {doc}.md")
    return JSONResponse({"doc": doc, "version": LEGAL_VERSION,
                         "format": "markdown", "content": p.read_text(encoding="utf-8")})


@router.get("/load")
def load_status():
    """서버 부하 스냅샷 — 사용자 혼잡/점검 표시용(인증 X · 프런트 폴링).

    응답: { status, search:{...}, reports:{active, paused, message?, writer_up},
            maintenance:{active, message?, since?}, features:{reports:{paused,message,since}} }

    reports.paused = 운영자 토글(기능 단위 일시 중단, 2026-09-07) — POST /reports 503.
    reports.writer_up = writer(DGX vLLM) 프로브(30s 캐시) — False 면 토글 없이도
    프런트가 "보고서 지연/불가" 경고. None 은 로컬 writer 미설정.
    프런트가 폴링해 '원활/혼잡' 배지 + **점검 중 화면**을 띄운다(점검은 로그인 전에도
    노출돼야 하므로 공개 /load 에 실음).
    """
    from src.maintenance import feature_paused, public_features, public_status
    from src.observability.load import snapshot
    from src.writer_status import writer_reachable

    snap = snapshot()
    snap["maintenance"] = public_status()
    snap["features"] = public_features()
    paused, msg = feature_paused("reports")
    snap["reports"] = {**(snap.get("reports") or {}), "paused": paused,
                       "message": msg or None, "writer_up": writer_reachable()}
    return JSONResponse(snap)
