"""관찰 추천 — 무엇을 담아야 하고 **왜 그런지** (2026-10-02).

실사용 요청: "등록 추천기능도 있으면 좋겠음. 추천 대상에 대해서는 왜 해당 규제를
관찰 목록에 넣어야 하는지를 알려주면 좋겠음."

후보가 20~30건씩 나오면 제목만 보고 고르기 어렵다. 그렇다고 **자동으로 담으면
안 된다** — 관찰 목록이 오염되면 알람이 쓰레기가 되고 사용자는 알람을 끈다.
그래서 **추천 + 사유**까지만 하고 선택은 사람이 한다.

판정 기준은 "질의와 관련 있는가"가 아니라 **"이 조문이 바뀌면 실무가 바뀌는가"**다.
목적·정의 조항은 관련은 있어도 개정을 추적할 가치가 낮다.

`coverage.judge_coverage` 와 같은 틀: 제목 + 발췌, 하이쿠 1콜, 타임아웃, 실패하면
**아무것도 추천하지 않는다**(없는 추천을 지어내는 것보다 낫다).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

_log = logging.getLogger(__name__)

#: 한 번에 판정할 최대 후보 — 넘으면 점수 상위부터 자른다.
MAX_CANDIDATES = 30
#: 추천 상한 — 다 추천하면 추천이 아니다.
MAX_PICKS = 8

_PROMPT = """규제 모니터링 대상에 **담을 만한 조문**을 고르고, 각각 왜 담아야 하는지 한 줄로 적어라.

모니터링 대상: {subject}

판단 기준은 "질의와 관련 있는가"가 아니라 **"이 조문이 개정되면 실무가 바뀌는가"**다.

담을 만한 것:
- 신고·허가·등록 **의무**와 그 요건을 직접 정하는 조문
- 시설·표시·보관 등 **세부 기준**(시행규칙·고시 — 자주 바뀐다)
- 위반 시 **벌칙·과태료·행정처분**
- 제출 **서식**을 지정하는 조문

담지 않을 것:
- 목적·정의 조항(바뀌어도 실무가 거의 안 바뀐다)
- 다른 업종·다른 대상에 적용되는 조문
- 일회성 경과규정

사유는 **구체적으로** 쓴다. "관련 있음" 같은 말은 쓰지 마라 —
"시설기준이 바뀌면 영업장 개조가 필요" 처럼 **무엇이 바뀌면 무엇을 해야 하는지**를 적어라.
최대 {max_picks}건. 담을 만한 것이 없으면 빈 배열.

후보:
{items}

JSON 만 출력한다. 설명·머리말을 붙이지 마라.
{{"picks": [{{"key": "조문키", "why": "한 줄 사유"}}]}}
"""

#: 어시스턴트 프리필 — 모델이 "먼저 자료를 확인하겠습니다" 같은 대화체 서두를
#: 뱉고 끝나는 일이 있었다(2026-10-02 실측). 응답 첫 글자를 고정해 막는다.
_PREFILL = '{"picks":'



def enabled() -> bool:
    return (os.getenv("MONITOR_RECOMMEND_DISABLE") or "").strip() != "1"


def _parse(raw: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


async def recommend(
    subject: str,
    candidates: list[dict],
    *,
    timeout_s: float = 12.0,
    model=None,
) -> dict[str, str]:
    """{article_key: 사유}. 스킵·실패하면 빈 dict.

    `candidates` 는 `/watch/suggest` 의 항목 — `article_key`·`title`·`citation`.
    """
    if not enabled() or not candidates:
        return {}
    subj = (subject or "").strip()
    if len(subj) < 2:
        return {}

    items = candidates[:MAX_CANDIDATES]
    lines = []
    for c in items:
        cit = c.get("citation") or {}
        snip = str(cit.get("snippet") or "").replace("\n", " ")[:180]
        lines.append(f"- {c.get('article_key')} | {c.get('title') or ''} | {snip}")

    try:
        from langchain_core.messages import AIMessage, HumanMessage

        from src.config import settings
        from src.models import build_chat_model

        llm = model or build_chat_model(settings.subagent_model, max_tokens=1600)
        msgs = [HumanMessage(content=_PROMPT.format(
            subject=subj[:200], max_picks=MAX_PICKS, items="\n".join(lines)))]
        if model is None:
            msgs.append(AIMessage(content=_PREFILL))
        res = await asyncio.wait_for(llm.ainvoke(msgs), timeout_s)
    except Exception as e:  # noqa: BLE001 — 추천 실패가 패널을 막으면 안 된다
        _log.info("관찰 추천 스킵(%s)", type(e).__name__)
        return {}

    content = res.content
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    text = str(content or "")
    # 프리필을 쓰면 응답이 그 뒤부터 이어진다 — 앞을 되돌려 붙인다(`workflow.join_prefill`
    # 의 교훈: `{` 로 시작한다고 완전한 JSON 이 아니다).
    if model is None:
        from src.workflow import join_prefill

        text = join_prefill(_PREFILL, text)
    data = _parse(text)
    if not data:
        _log.info("관찰 추천 — JSON 파싱 실패(응답 %d자)", len(text))
        return {}

    valid = {str(c.get("article_key")) for c in items}
    out: dict[str, str] = {}
    for p in (data.get("picks") or [])[:MAX_PICKS]:
        if not isinstance(p, dict):
            continue
        k = str(p.get("key") or "").strip()
        why = str(p.get("why") or "").strip()
        # 모델이 없는 키를 지어내면 버린다(환각 방어).
        if k in valid and why and k not in out:
            out[k] = why[:160]
    return out
