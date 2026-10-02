"""인용 grounding 검증 — claim ↔ source 근거 문장(supporting_quote) 추출 + substring 검증.

보고서(`report_pipeline`)와 채팅(`middleware/grounding_gate`)이 공유. LLM 1콜(배치, haiku)로
각 `[n]` claim 을 직접 뒷받침하는 원문 문장을 추출하고, 그 문장이 source(text)에 실제로
있는지 substring 으로 확인해 `verified`·`supporting_quote` 를 부착한다. 법령 도메인의
미스어트리뷰션·환각 차단용.

- `ground_citations(body, citations)` : citation 에 `text`(원문)가 이미 있는 경우(보고서).
- `ground_answer(body, citations)`    : `text` 없는 채팅 citation 에 PG full_text 를 붙여 검증.
"""

from __future__ import annotations

import json
import logging
import os
import re

_log = logging.getLogger(__name__)

_GROUND_TEXT_CAP = 1500


def _llm_cfg() -> dict:
    """grounding/audit LLM 호출 config — FE 필터 태그.

    (2026-08-05) 토큰 로거는 여기서 붙이지 않는다. `build_chat_model()` 이 모든
    모델에 부착하므로 중복이다. 종전엔 여기서 `TokenUsageLogger()` 를 **무인자로**
    붙여, 이 경로 호출이 events 에 남기는 하되 `user_id` 가 전부 NULL 이었다
    (실측 2026-08-05: 3일치 llm_call 의 15%). 귀속은 ambient 컨텍스트가 맡는다.
    """
    return {"tags": ["report_writer_internal"]}


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _claim_for(body: str, n: int) -> str:
    """본문에서 `[n]` 이 달린 문장(대략) 추출 — claim 컨텍스트."""
    idx = body.find(f"[{n}]")
    if idx < 0:
        return ""
    starts = [body.rfind(b, 0, idx) for b in ("\n", "다. ", ". ")]
    start = max([s for s in starts if s >= 0] or [0])
    start = start + 1 if start > 0 else 0
    ends = [body.find(b, idx) for b in ("다.", ". ", "\n")]
    ends = [e for e in ends if e >= 0]
    end = (min(ends) + 2) if ends else len(body)
    return body[start:end].strip()


_GROUND_PROMPT = (
    "각 항목의 claim 을 *직접 뒷받침하는 문장* 을 source 에서 글자 그대로 "
    "복사해 추출합니다. source 에 claim 을 직접 뒷받침하는 문장이 없으면 "
    "quote 를 \"NONE\" 으로 둡니다. JSON 배열만 출력:\n"
    "[{\"n\": <번호>, \"quote\": \"원문 그대로 또는 NONE\"}]\n\n항목:\n"
)


async def ground_citations(body: str, citations: list[dict], *, model=None) -> list[dict]:
    """각 used citation 의 claim ↔ source(text) 근거 문장 추출 + substring 검증.

    `text` 가 있는 citation 만 대상. citation 에 `supporting_quote`(검증된 원문 span)·
    `verified`(bool) 부착. `text` 없는 citation 은 **원본 그대로**(채팅 web 등 안전).
    LLM 1콜(배치). 실패 시 원본 그대로.
    """
    targets = [(c["number"], c) for c in citations
               if c.get("text") and isinstance(c.get("number"), int)]
    if not targets:
        return citations
    items = []
    for n, c in targets:
        claim = _claim_for(body, n)
        if claim:
            items.append({"n": n, "claim": claim[:300],
                          "source": (c["text"] or "")[:_GROUND_TEXT_CAP]})
    if not items:
        return citations
    llm = model
    if llm is None:
        from src.chat_loop import aux_model  # 기밀 턴이면 원내/생략(2026-10-03)
        llm = aux_model(
            os.getenv("GROUND_MODEL")
            or os.getenv("REPORT_GROUND_MODEL")
            or os.getenv("SUBAGENT_MODEL")
            or "anthropic:claude-haiku-4-5-20251001",
            max_tokens=1200,
        )
        if llm is None:
            # 기밀 턴 + 원내 없음 — 검증 생략. verified 를 True 로 찍지 않는다
            # (검증 안 한 것을 검증됐다고 하면 안 된다). 인용은 그대로 둔다.
            return citations
    quotes: dict[int, str] = {}
    try:
        # grounding JSON 은 사용자 답변 아님 — 태그로 FE 토큰 스트림 필터.
        res = await llm.ainvoke(
            _GROUND_PROMPT + json.dumps(items, ensure_ascii=False),
            _llm_cfg())
        raw = getattr(res, "content", "") or ""
        if isinstance(raw, list):
            raw = "".join(p.get("text", "") for p in raw if isinstance(p, dict))
        i, j = raw.find("["), raw.rfind("]")
        arr = json.loads(raw[i:j + 1]) if i != -1 and j != -1 else []
        for it in arr:
            if isinstance(it, dict) and isinstance(it.get("n"), int):
                quotes[it["n"]] = str(it.get("quote") or "")
    except Exception as e:  # noqa: BLE001
        _log.warning("grounding 검증 실패(%s) — quote 미부착", e)
        return citations

    verified_n = 0
    out = []
    for c in citations:
        n = c.get("number")
        # text 없는 citation(=대상 아님)은 손대지 않음.
        if not (c.get("text") and isinstance(n, int)):
            out.append(c)
            continue
        nc = dict(c)
        q = quotes.get(n, "").strip()
        src = c.get("text") or ""
        if q and q != "NONE" and _norm_ws(q) in _norm_ws(src):
            nc["supporting_quote"] = q
            nc["verified"] = True
            verified_n += 1
        else:
            # NONE(근거 없음) 또는 환각(원문에 없는 quote) → 미검증 표시.
            nc["verified"] = False
        out.append(nc)
    _log.info("grounding: verified %d/%d", verified_n, len(targets))
    return out


def _article_key_from_citation(c: dict) -> str | None:
    """RAG citation id(`cite_doc_{article_key}`)에서 article_key 추출."""
    cid = c.get("id") or ""
    if cid.startswith("cite_doc_"):
        return cid[len("cite_doc_"):]
    return None


async def _attach_source_text(citations: list[dict]) -> list[dict]:
    """채팅 RAG citation 에 source full_text 를 붙인다(검증용, in-memory).

    채팅 citation 은 FE 표시용 snippet(≤300)만 있고 full_text 가 없으므로, 검색
    API `/articles/bodies` 로 인용된 article_key 들만 배치 fetch 해 `text` 를
    채운다(서버가 PG full_text→색인 폴백→<br/> 정제까지 처리). 이미 `text` 있으면
    그대로. web citation(`cite_web_`)·미발견은 손대지 않음.
    """
    need = {}
    for c in citations:
        if c.get("text"):
            continue
        ak = _article_key_from_citation(c)
        if ak:
            need[ak] = c
    if not need:
        return citations
    try:
        import asyncio

        from src.retrieval.search_api_client import fetch_bodies
        bodies = await asyncio.to_thread(fetch_bodies, list(need.keys()))
    except Exception as e:  # noqa: BLE001
        _log.info("grounding source text fetch 실패(no-op): %s", e)
        return citations
    out = []
    for c in citations:
        ak = _article_key_from_citation(c)
        ft = (bodies.get(ak) or {}).get("full_text") if ak else None
        if ft and not c.get("text"):
            nc = dict(c)
            nc["text"] = ft[:_GROUND_TEXT_CAP]
            out.append(nc)
        else:
            out.append(c)
    return out


async def ground_answer(body: str, citations: list[dict], *, model=None) -> list[dict]:
    """채팅 답변용 — RAG citation 에 source full_text 를 붙인 뒤 grounding 검증."""
    enriched = await _attach_source_text(citations)
    return await ground_citations(body, enriched, model=model)


# ---------------------------------------------------------------------------
# 무인용 사실 audit (factual-verification-design Phase 1) — grounding(인용) 과 별개.
# check-worthy 정량·특정 사실이 source 에 지지되나 판정. 사용자 비노출, 측정용.
# ---------------------------------------------------------------------------
# 출처는 넉넉히, 답변은 적당히 — 종전 공통 6000자는 출처(검색 원문 수만 자)를
# 대부분 잘라내 "출처에 실제로 있는 사실"까지 unverified 로 판정했다(2026-08-13
# 운영 실측: unsupported 43% 중 다수가 이 절단 탓으로 추정). Haiku 측정 패스라
# 토큰 여유 있음 — 출처 24k자(≈1만 토큰)로 상향.
_AUDIT_SRC_CAP = 24000
_AUDIT_BODY_CAP = 8000
_AUDIT_VERDICTS = ("supported", "contradicted", "unverified")

_AUDIT_PROMPT = (
    "아래 [답변]에서 **검증 대상 사실**만 뽑아 [출처] 기준으로 판정한다.\n"
    "검증 대상 = 조문/고시 번호, 수수료·금액, 기한·일수·유효기간, 날짜, 판례 사건번호, "
    "수치 요건(예: N일 이내, N% 이상) 등 틀리면 실무 피해가 큰 정량·특정 사실.\n"
    "제외 = 이미 [n] 로 인용된 문장, '확인 필요/대략/일반적으로' 등 hedge 문장, 일반 "
    "절차·상식·해석/추론 문장.\n"
    "각 사실의 verdict = supported(출처가 명시적으로 지지) / contradicted(출처와 어긋남) "
    "/ unverified(출처에 근거 없음).\n"
    "JSON 배열만 출력: "
    '[{"claim":"<사실 한 조각>","verdict":"supported|contradicted|unverified"}]\n'
    "검증 대상이 없으면 [] 만 출력.\n"
)


def _parse_audit(raw: str) -> list[dict]:
    """audit LLM 출력 → [{claim, verdict}] (verdict 화이트리스트만)."""
    if isinstance(raw, list):
        raw = "".join(p.get("text", "") for p in raw if isinstance(p, dict))
    try:
        i, j = raw.find("["), raw.rfind("]")
        arr = json.loads(raw[i:j + 1]) if i != -1 and j != -1 else []
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[dict] = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        verdict = str(it.get("verdict") or "").strip().lower()
        claim = str(it.get("claim") or "").strip()
        if claim and verdict in _AUDIT_VERDICTS:
            out.append({"claim": claim[:200], "verdict": verdict})
    return out


async def audit_uncited_claims(body: str, haystack: str, *, model=None) -> list[dict]:
    """무인용 check-worthy 사실을 source(haystack)에 대해 판정(별도 패스, Haiku 1콜).

    반환 [{claim, verdict}] — verdict ∈ supported|contradicted|unverified.
    비차단·best-effort(실패·빈 입력 시 []). grounding(인용 검증)과 독립.
    출력 JSON 이 스트림에 새지 않도록 report_writer_internal 태그 부착.
    """
    if not (body and body.strip() and haystack and haystack.strip()):
        return []
    llm = model
    if llm is None:
        from src.chat_loop import aux_model  # 기밀 턴이면 원내/생략(2026-10-03)
        llm = aux_model(
            os.getenv("GROUND_MODEL")
            or os.getenv("SUBAGENT_MODEL")
            or "anthropic:claude-haiku-4-5-20251001",
            max_tokens=1200,
        )
        if llm is None:
            return []  # 기밀 턴 + 원내 없음 — 감사 생략(측정 채널일 뿐)
    prompt = (
        _AUDIT_PROMPT
        + "\n[출처]\n" + haystack[:_AUDIT_SRC_CAP]
        + "\n\n[답변]\n" + body[:_AUDIT_BODY_CAP]
    )
    try:
        res = await llm.ainvoke(prompt, _llm_cfg())
    except Exception as e:  # noqa: BLE001 — 감사 실패가 답변을 막으면 안 됨
        _log.info("claim audit 실패(no-op): %s", e)
        return []
    return _parse_audit(getattr(res, "content", "") or "")
