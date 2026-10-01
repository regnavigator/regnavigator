"""규제 경로 분해 — "무엇을 → 어디에 → 어떤 서식으로" 를 단계 체크리스트로.

변호사 업무지원 2/4 (2026-10-01). 조사에서 확인된 병목 중 "규제 대응 자문" 을
겨냥한다. 답변 본문을 읽고 단계를 머리로 재구성하는 일을 없애고, **빠뜨린 단계가
눈에 보이게** 한다 — 사고는 몰라서가 아니라 한 단계를 건너뛰어서 난다.

설계
- **추가 LLM 콜을 쓰지 않는다.** 답변을 만드는 모델이 말미에 `<pathway>` 마커로
  JSON 을 붙이고, 여기서 파싱해 본문에서 걷어낸다. `<verdict>`·`<next_steps>` 와
  같은 마커 계약이다(채널 분리 불변식).
- 파싱 실패·형식 불일치는 **조용히 버린다**. 경로가 없다고 답변이 틀린 건 아니다.
- 각 단계의 `cites` 는 본문의 `[n]` 번호다 — FE 가 그대로 인용 칩에 연결한다.

본문에 단계를 섞지 않는 이유는 `<next_steps>` 와 같다: 사용자가 체크하고 추적할
것을 산문에 묻으면 추적이 안 된다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

_log = logging.getLogger(__name__)

_MARKER = re.compile(r"<pathway>\s*(.*?)\s*</pathway>", re.S | re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)

#: 한 경로에 허용하는 최대 단계 — 넘으면 체크리스트가 아니라 문서가 된다.
MAX_STEPS = 12
#: 필드 길이 상한(렌더 깨짐·프롬프트 인젝션 방지)
_MAX_LEN = {"title": 80, "what": 300, "where": 120, "form": 160, "when": 80, "note": 300}


def _clip(v: Any, key: str) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    lim = _MAX_LEN.get(key, 200)
    return s[:lim]


def _cites(v: Any) -> list[int]:
    """인용 번호만 추린다 — 본문 [n] 과 맞물린다. 문자열 "3" 도 허용."""
    out: list[int] = []
    if not isinstance(v, (list, tuple)):
        return out
    for x in v[:10]:
        try:
            n = int(str(x).strip().lstrip("[").rstrip("]"))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 999 and n not in out:
            out.append(n)
    return out


def parse(body: str) -> Optional[list[dict]]:
    """`<pathway>` 마커에서 단계 목록을 꺼낸다. 없거나 깨졌으면 None.

    기대 형태:
        <pathway>
        [{"title": "영업신고", "what": "...", "where": "관할 구청",
          "form": "별지 제37호서식", "when": "영업 시작 전", "cites": [1,2]}]
        </pathway>
    """
    m = _MARKER.search(body or "")
    if not m:
        return None

    raw = _FENCE.sub("", m.group(1).strip())
    try:
        data = json.loads(raw)
    except ValueError:
        _log.warning("pathway 마커 JSON 파싱 실패 — 무시")
        return None

    # {"steps": [...]} 형태도 받아 준다 — 모델이 자주 감싼다.
    if isinstance(data, dict):
        data = data.get("steps") or data.get("pathway")
    if not isinstance(data, list) or not data:
        return None

    steps: list[dict] = []
    for i, item in enumerate(data[:MAX_STEPS], start=1):
        if not isinstance(item, dict):
            continue
        title = _clip(item.get("title") or item.get("step"), "title")
        what = _clip(item.get("what") or item.get("desc"), "what")
        if not title and not what:
            continue
        steps.append({
            "no": i,
            "title": title or f"{i}단계",
            "what": what,
            "where": _clip(item.get("where"), "where"),
            "form": _clip(item.get("form"), "form"),
            "when": _clip(item.get("when") or item.get("deadline"), "when"),
            "note": _clip(item.get("note"), "note"),
            "cites": _cites(item.get("cites") or item.get("citations")),
        })
    return steps or None


def strip_marker(body: str) -> str:
    """영속 본문에서 마커를 걷어낸다 — FE 는 SSE `pathway` 이벤트로 받는다."""
    return _MARKER.sub("", body or "").rstrip()


def summary(steps: list[dict]) -> dict:
    """events 적재용 요약 — 본문·고객 정보는 싣지 않는다."""
    return {
        "steps": len(steps),
        "with_form": sum(1 for s in steps if s.get("form")),
        "with_deadline": sum(1 for s in steps if s.get("when")),
        "uncited": sum(1 for s in steps if not s.get("cites")),
    }
