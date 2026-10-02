"""검색 근거 충분성(커버리지) 게이트 — 3층 하이브리드 (2026-07-21 설계 합의).

1층(근거 0건 → 재검색 1회)은 chat_loop 루프 상단의 규칙.
이 모듈은 2·3층:

  2층 — 명시 종별 규칙(무료): 질문에 근거 종별이 명시(판례·유권해석·고시·조례·
        공고 등)됐는데 수집 근거에 그 종별이 없으면, 그 종별 겨냥 검색을 지시.
        LLM 없음 — 키워드 사전 매칭.
  3층 — LLM 판정(Haiku 1콜): 근거 ≥1건인데 2층 gap 이 없을 때만. 질문을 요소로
        분해해 수집 근거(제목+발췌)와 대조, 미커버 요소를 레인(qdrant/web)+종별
        지정 겨냥 검색으로 반환. 요소 분해가 정확도의 핵심 — "충분한가?" 전체
        판단은 주제 유사성에 앵커링돼 부분 커버를 놓친다.

안전: 판정은 best-effort(실패/타임아웃 → None, 답변을 막지 않음). 겨냥 검색 ≤2,
턴당 1사이클. `COVERAGE_JUDGE_ENABLE=0` 으로 3층만 끌 수 있다(2층은 무료라 상시).

용도 8종(memory/service-use-cases) 반영: R&D·정부과제·공고류는 법령 코퍼스 밖
→ web 레인을 gap-fill 대상에 포함.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

_log = logging.getLogger(__name__)

# qdrant_search 가 받는 종별 — **단일 진실원 재수출**(2026-08-25).
# 종전엔 여기 튜플을 따로 들고 있어 guide(7/24)·admrul_attach(8/24) 편입이
# 반영되지 않았고, 커버리지 게이트가 그 종별을 지목해도 조용히 탈락했다.
from src.tools.search import ALLOWED_DOC_KINDS as ALLOWED_KINDS  # noqa: E402

# citation.doc_category(한글) → 종별 kind. **정본은 citations 쪽**이다 —
# 여기서 손으로 복제했다가 4종(조약·헌재결정례·행정심판례·가이드라인)이 빠진 채
# 드리프트했고, `covered_kinds()` 가 매핑 실패를 조용히 건너뛰는 탓에 가이드라인
# 근거만 있는 턴이 "커버리지 0" 으로 집계됐다(2026-09-10 응집도 점검에서 발견).
from src.tools.citations import KIND_BY_DOC_CATEGORY as _KIND_BY_CATEGORY  # noqa: E402

# 2층 — 질문 속 명시 종별 키워드 사전. (키워드들, kind) — kind "web" 은 tavily 레인.
_EXPLICIT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("판례", "판결"), "prec"),
    (("유권해석", "해석례", "법령해석", "질의회신"), "expc"),
    (("고시", "훈령", "예규", "행정규칙"), "admrul"),
    (("조례", "자치법규"), "ordin"),
    # R&D·정부과제·공고류 — 법령 코퍼스 밖(웹): service-use-cases 5·7
    (("공고", "정부과제", "지원사업", "모집요강", "R&D", "과제 공고"), "web"),
]


def collect_turn_citations(turn_steps: list[dict]) -> list[dict]:
    """이번 턴 steps 에 누적된 citation 을 id 기준 dedupe 해 모음(판정 입력용)."""
    seen: set = set()
    out: list[dict] = []
    for st in turn_steps or []:
        for c in (st.get("citations") or []):
            if not isinstance(c, dict):
                continue
            cid = c.get("id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            out.append(c)
    return out


def covered_kinds(turn_steps: list[dict]) -> set[str]:
    """수집 근거가 커버하는 종별 집합 — {"law","prec",...,"web"}."""
    kinds: set[str] = set()
    for c in collect_turn_citations(turn_steps):
        if c.get("source_kind") == "web":
            kinds.add("web")
            continue
        k = _KIND_BY_CATEGORY.get(c.get("doc_category") or "")
        if k:
            kinds.add(k)
    return kinds


def explicit_gap_searches(question: str, covered: set[str]) -> list[dict]:
    """2층 — 질문이 명시한 종별 중 미커버를 겨냥 검색으로(≤2, 무료)."""
    q = (question or "").strip()
    if not q:
        return []
    out: list[dict] = []
    for keywords, kind in _EXPLICIT_RULES:
        if kind in covered:
            continue
        if not any(k in q for k in keywords):
            continue
        if kind == "web":
            out.append({"lane": "web", "query": q[:100]})
        else:
            out.append({"lane": "qdrant", "query": q[:100], "doc_kinds": [kind]})
        if len(out) >= 2:
            break
    return out


# ── 3층 — LLM 판정 ─────────────────────────────────────────────────────────

_JUDGE_PROMPT = """너는 의료 규제 답변의 "근거 충분성" 심판이다. 답변하지 말고 판정만 하라.

절차:
1. [질문]에 답하려면 어떤 정보가 필요한지 핵심 요소로 분해하라(보통 1~3개).
   도메인 힌트 — 인허가: 등급분류→허가경로→GMP→심사 / 임상: 계획승인(IND)·GCP /
   AI·디지털 의료기기: SaMD 관련 고시 + 식약처 가이드라인(웹) /
   R&D·정부과제: 과제 공고·모집요강은 법령 DB 에 없음(웹에서 찾아야 함).
2. 각 요소가 [수집 근거]로 실질 커버되는지 대조하라. 주제만 겹치는 것은 커버가 아니다
   (예: 질문이 "급여 기준"인데 근거가 "허가 절차"뿐이면 미커버).
3. 핵심 요소가 전부 커버되면 sufficient=true, searches=[].
   미커버 요소가 있으면 sufficient=false 로 하고, 그 요소를 gaps 에, 그 요소를 찾을
   검색을 searches 에 넣어라(최대 2개).

규칙:
- 과잉 금지: 답에 없어도 되는 정보를 요구하지 마라. 정말 필요한 gap 만.
- 상세 욕심 금지: 링크·사건번호·연락처·서식 파일 같은 "더 자세한 정보"는 gap 이
  아니다. gap 은 질문의 핵심 요소가 통째로 미커버일 때만.
- searches[].lane: "qdrant"(법령·행정규칙·판례·가이드라인 등 국내 규제 DB) 또는
  "web"(공고·해외규제 등 웹). qdrant 면 doc_kinds 로 종별 지정 —
  law(법령)/admrul(행정규칙·고시)/ordin(조례)/prec(판례)/expc(법령해석례)/
  guide(식약처 가이드라인·안내서 — 실무 절차·심사기준·제출자료)/
  admrul_attach(행정규칙 첨부 본문 — 급여기준·심사지침 등 별표·첨부에만 있는
  세부 기준. 수가·급여 관련 gap 이면 이걸 지정).
- 출력은 JSON 하나만. 다른 텍스트 금지.

출력 형식:
{{"sufficient": true|false, "gaps": ["미커버 요소"], "searches": [{{"lane": "qdrant", "query": "검색어", "doc_kinds": ["admrul"]}}]}}

[질문]
{question}

[수집 근거]
{evidence}
"""


def _judge_enabled() -> bool:
    return (os.getenv("COVERAGE_JUDGE_ENABLE") or "1").strip() == "1"


def parse_judge_output(text: str) -> Optional[dict]:
    """판정 응답 파싱+검증 — 실패 시 None(best-effort). 코드펜스 허용."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sufficient"), bool):
        return None
    searches: list[dict] = []
    for s in (data.get("searches") or [])[:2]:
        if not isinstance(s, dict):
            continue
        lane = s.get("lane")
        query = (s.get("query") or "").strip()
        if lane not in ("qdrant", "web") or not query:
            continue
        item: dict = {"lane": lane, "query": query[:150]}
        if lane == "qdrant":
            kinds = [k for k in (s.get("doc_kinds") or []) if k in ALLOWED_KINDS]
            if kinds:
                item["doc_kinds"] = kinds
        searches.append(item)
    return {
        "sufficient": data["sufficient"],
        "gaps": [str(g)[:200] for g in (data.get("gaps") or [])[:4]],
        "searches": searches,
    }


async def judge_coverage(
    question: str,
    citations: list[dict],
    *,
    timeout_s: float = 8.0,
) -> Optional[dict]:
    """3층 판정 1콜 — {"sufficient","gaps","searches"} 또는 None(스킵/실패).

    스킵 조건: 노브 off · 근거 0건(1층 소관) · 초단문/단일어 질문(분해할 요소 없음).
    """
    if not _judge_enabled():
        return None
    q = (question or "").strip()
    if len(q) < 12 or " " not in q:
        return None
    if not citations:
        return None

    lines = []
    for c in citations[:12]:
        kind = c.get("doc_category") or ("웹" if c.get("source_kind") == "web" else "문서")
        snip = (c.get("snippet") or "").replace("\n", " ")[:120]
        lines.append(f"[{c.get('number')}] {c.get('title', '')} · {kind} — {snip}")
    prompt = _JUDGE_PROMPT.format(question=q[:500], evidence="\n".join(lines))

    try:
        from langchain_core.messages import HumanMessage

        from src.config import settings
        from src.chat_loop import aux_model

        model = aux_model(settings.subagent_model, max_tokens=500)
        if model is None:
            return None  # 기밀 턴 + 원내 없음 — 심판 생략(근거 보강 없이 진행)
        resp = await asyncio.wait_for(
            model.ainvoke([HumanMessage(content=prompt)]), timeout_s
        )
        content = resp.content
        if isinstance(content, list):  # anthropic 블록 응답 대응
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        verdict = parse_judge_output(str(content))
        if verdict:
            _log.info(
                "coverage judge: sufficient=%s gaps=%s searches=%d",
                verdict["sufficient"], verdict["gaps"], len(verdict["searches"]),
            )
        return verdict
    except Exception as e:  # noqa: BLE001 — 판정 실패가 답변을 막으면 안 됨
        _log.info("coverage judge skipped: %s", e)
        return None
