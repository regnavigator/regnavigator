"""적용가능성 판정 — 규칙이 못 잡는 "닮았지만 적용 안 되는" 출처 (2026-10-02).

`source_filter` 는 법령명 문자열만 본다. 그래서 이름만으로는 적용 대상을 알 수
없는 것들을 놓친다 — 「공유재산 및 물품 관리법 시행령」이 카페 질의에 섞이는
식이다(실측). 그 몫을 여기서 받는다.

**커버리지 판정(`coverage.judge_coverage`)과 같은 틀**을 쓴다: 제목 + 발췌 120자만
보내고, 하이쿠 1콜, 8초 타임아웃, 실패하면 아무것도 하지 않는다. 검증 계층이
답변을 막으면 안 된다는 이 저장소의 규율 그대로다.

**판정은 '제외'가 아니라 '지목'이다.** 모델에게 "적용되지 않는 번호"를 받아
호출자가 거른다. 모델이 통째로 침묵하거나 형식을 어기면 아무것도 거르지 않는다 —
실패 방향이 "덜 거름"이어야 한다. 과하게 거르면 답할 근거가 사라진다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

_log = logging.getLogger(__name__)

#: 한 번에 판정할 최대 건수 — 커버리지 판정과 같은 상한.
_MAX_ITEMS = 14
#: 한 번에 제외할 수 있는 최대 비율. 넘으면 판정을 통째로 버린다(폭주 방지).
_MAX_DROP_RATIO = 0.6

_PROMPT = """질문에 **적용되지 않는** 근거를 골라내라.

판단 기준은 "내용이 닮았는가"가 아니라 "**이 법령이 질문 상황에 적용되는가**"다.
다음은 닮았어도 적용되지 않는다:
- 적용 대상이 다름 (예: 어린이 기호식품 판매업소 기준 ↔ 일반 카페)
- 규율 사안이 다름 (예: 공유재산 사용허가 ↔ 영업신고)
- 다른 법을 **인용**하느라 같은 용어가 등장했을 뿐인 조문
- 임의 인증·지정 제도 ↔ 의무 신고·허가

확실하지 않으면 **남겨라**. 적용될 여지가 조금이라도 있으면 제외하지 마라.

질문: {question}

근거:
{evidence}

JSON 만 출력:
{{"drop": [번호, ...], "why": {{"번호": "한 줄 사유"}}}}
적용되지 않는 것이 없으면 {{"drop": []}}.
"""


def enabled() -> bool:
    return (os.getenv("APPLICABILITY_JUDGE_DISABLE") or "").strip() != "1"


def _parse(raw: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


async def judge(
    question: str,
    citations: list[dict],
    *,
    timeout_s: float = 8.0,
) -> dict[int, str]:
    """{제외할 number: 사유}. 스킵·실패·폭주면 빈 dict."""
    if not enabled() or not citations:
        return {}
    q = (question or "").strip()
    if len(q) < 12 or " " not in q:
        return {}

    items = [c for c in citations[:_MAX_ITEMS] if isinstance(c.get("number"), int)]
    if len(items) < 3:          # 근거가 적으면 거를 여유가 없다
        return {}

    lines = []
    for c in items:
        kind = c.get("doc_category") or (
            "웹" if c.get("source_kind") == "web" else "문서")
        snip = (c.get("snippet") or "").replace("\n", " ")[:120]
        lines.append(f"[{c['number']}] {c.get('title', '')} · {kind} — {snip}")

    try:
        from langchain_core.messages import HumanMessage

        from src.config import settings
        from src.chat_loop import aux_model

        model = aux_model(settings.subagent_model, max_tokens=400)
        if model is None:
            return {}  # 기밀 턴 + 원내 없음 — 판정 생략(인용 그대로)
        resp = await asyncio.wait_for(
            model.ainvoke([HumanMessage(content=_PROMPT.format(
                question=q[:500], evidence="\n".join(lines)))]),
            timeout_s,
        )
    except Exception as e:  # noqa: BLE001 — 판정 실패가 답변을 막으면 안 된다
        _log.info("적용가능성 판정 스킵(%s)", type(e).__name__)
        return {}

    content = resp.content
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    data = _parse(str(content or ""))
    if not data:
        return {}

    valid = {c["number"] for c in items}
    why = data.get("why") if isinstance(data.get("why"), dict) else {}
    out: dict[int, str] = {}
    for n in (data.get("drop") or []):
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if n in valid:
            out[n] = str(why.get(str(n)) or why.get(n) or "적용 대상 아님")[:80]

    # 폭주 방지 — 모델이 "다 빼라"고 하면 그건 판정이 아니라 고장이다.
    if len(out) > len(items) * _MAX_DROP_RATIO:
        _log.warning("적용가능성 판정 과다 제외(%d/%d) — 통째로 버림",
                     len(out), len(items))
        return {}
    return out


def judge_sync(question: str, citations: list[dict], *,
               timeout_s: float = 8.0) -> dict[int, str]:
    """`judge()` 의 동기 래퍼 — `asyncio.to_thread` 안에서 쓰라고 있다.

    검색 도구(`_tool_qdrant`)는 워커 스레드에서 돌아 `await` 를 쓸 수 없다. 그
    스레드에는 실행 중인 루프가 없으므로 전용 루프를 열어 돌린다. 혹시 루프가
    돌고 있는 곳에서 잘못 불리면 **아무것도 거르지 않고** 물러난다 — 이 판정은
    있으면 좋은 것이지 없으면 안 되는 것이 아니다.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass              # 정상 경로 — 루프 없음
    else:
        _log.debug("judge_sync 가 이벤트 루프 안에서 불렸다 — 스킵")
        return {}
    try:
        return asyncio.run(judge(question, citations, timeout_s=timeout_s))
    except Exception:  # noqa: BLE001
        _log.info("적용가능성 판정 스킵(sync)")
        return {}
