"""기능 조합(composition) 스키마 — 정규화·검증의 단일 진실원 (2026-10-02).

조합은 **기능(function) 들의 순서 + 단계별 입력·파일·기밀**이다. 저장 형태는 그대로
장기 목표인 **직무(task)** 의 저장 형태가 된다 — task 는 "이 객체에 이름을 붙여 다른
테이블에 넣는 것"으로 끝나야 하므로, 여기서 단계 하나가 자족적이어야 한다.

```
{"steps": [{"fn": "case_issues",
            "values": {"facts": "…"},
            "files": [{"id": "wff_…", "name": "소장.pdf", "chars": 12043}],
            "confidential": true,
            "done": false}],
 "cursor": 0, "mode": "stepwise"|"auto", "status": "draft"|"running"|"done"}
```

**`fn` 은 검증하지 않는다.** 기능 목록의 진실원은 프런트 레지스트리
(`lib/features/catalog.ts`)다. 여기서 화이트리스트를 복제하면 기능을 추가할 때마다
두 곳이 어긋나고, 어긋난 쪽이 조용히 422 로 떨어진다. 렌더 단계에서 못 찾은 id 를
빼는 쪽이 맞다.

구버전(문자열 배열)도 읽는다 — 1차 구현이 `steps: ["id", …]` 로 저장했다.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

_log = logging.getLogger("workflow")

#: 한 조합의 단계 상한. 길면 중간에 맥락이 흐려지고 사용자가 끝까지 가지 않는다.
MAX_STEPS = 8
#: 단계 하나에 붙일 수 있는 파일 수 — `CHAT_MAX_ATTACHMENTS`(3)와 맞춘다.
MAX_FILES_PER_STEP = 3
MAX_FN_LEN = 64
MAX_VALUE_LEN = 4000

MODES = ("stepwise", "auto")
STATUSES = ("draft", "running", "done")


class WorkflowError(ValueError):
    """조합 스키마 위반 — 라우트가 422 로 바꾼다."""


def _norm_file(v: Any) -> Optional[dict]:
    if not isinstance(v, dict):
        return None
    fid = str(v.get("id") or "").strip()
    name = str(v.get("name") or "").strip()
    if not fid or not name:
        return None
    try:
        chars = int(v.get("chars") or 0)
    except (TypeError, ValueError):
        chars = 0
    return {"id": fid[:64], "name": name[:200], "chars": max(0, chars)}


def _norm_step(v: Any) -> Optional[dict]:
    """단계 하나 정규화. 구버전 문자열도 받는다."""
    if isinstance(v, str):
        fn = v.strip()
        if not fn:
            return None
        return {"fn": fn[:MAX_FN_LEN], "values": {}, "files": [],
                "confidential": False, "done": False}
    if not isinstance(v, dict):
        return None

    fn = str(v.get("fn") or v.get("id") or "").strip()
    if not fn:
        return None
    if len(fn) > MAX_FN_LEN:
        raise WorkflowError("기능 id 가 너무 깁니다")

    values: dict[str, str] = {}
    for k, val in (v.get("values") or {}).items():
        if not isinstance(k, str) or not k.strip():
            continue
        values[k.strip()[:64]] = str(val or "")[:MAX_VALUE_LEN]

    files = [f for f in (_norm_file(f) for f in (v.get("files") or [])) if f]
    if len(files) > MAX_FILES_PER_STEP:
        raise WorkflowError(f"단계당 파일은 {MAX_FILES_PER_STEP}개까지입니다")

    return {
        "fn": fn,
        "values": values,
        "files": files,
        "confidential": bool(v.get("confidential")),
        "done": bool(v.get("done")),
    }


def normalize(raw: Any) -> Optional[dict]:
    """임의 입력 → 정규 조합. 비어 있으면 None(조합 없음).

    `WorkflowError` 는 호출자가 422 로 바꾼다. 형태가 아예 아닌 값(저장된 쓰레기)은
    예외 대신 None — 기능만 조용히 꺼지고 대화는 계속돼야 한다.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None

    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list):
        return None
    if len(raw_steps) > MAX_STEPS:
        raise WorkflowError(f"조합은 최대 {MAX_STEPS}단계까지입니다")

    steps = [st for st in (_norm_step(s) for s in raw_steps) if st]
    if not steps:
        return None

    try:
        cursor = int(raw.get("cursor") or 0)
    except (TypeError, ValueError):
        cursor = 0
    cursor = max(0, min(cursor, len(steps)))

    mode = raw.get("mode")
    mode = mode if mode in MODES else "stepwise"
    status = raw.get("status")
    status = status if status in STATUSES else "draft"

    return {"steps": steps, "cursor": cursor, "mode": mode, "status": status}


def file_ids(wf: Optional[dict]) -> set[str]:
    """조합이 참조하는 모든 첨부 id — 고아 파일 정리에 쓴다."""
    out: set[str] = set()
    for st in (wf or {}).get("steps") or []:
        for f in st.get("files") or []:
            if f.get("id"):
                out.add(str(f["id"]))
    return out


# ── 다음 단계 입력 제안 ────────────────────────────────────────────────────

_SUGGEST_PROMPT = """앞 단계들의 결과를 보고, 다음 작업의 입력값을 채워라.

다음 작업: {title}
채울 항목:
{fields}

앞 단계에서 확인된 내용:
{context}

규칙:
- **앞 단계에서 실제로 확인된 것만** 쓴다. 모르면 그 항목은 빈 문자열로 둔다.
- 사용자가 고칠 수 있는 초안이다 — 확신이 없으면 비워 두는 편이 낫다.
- 각 값은 한 줄, 120자 이내.

JSON 만 출력한다. 설명·머리말을 붙이지 마라.
{{"values": {{"항목키": "값"}}}}
"""

#: 어시스턴트 프리필 — 모델이 "먼저 확인하겠습니다" 같은 서두를 뱉고 끝나는 일이
#: 있었다(관찰 추천에서 실측). 응답 첫 글자를 고정해 막는다.
_SUGGEST_PREFILL = '{"values":'

#: 앞 단계 맥락으로 넘길 분량. 누적분을 통째로 직렬화하면 컨텍스트가 터진다
#: (`report_pipeline` 에 342건·24만 자로 writer 가 3연속 전멸한 이력).
SUGGEST_CONTEXT_CHARS = 6000


def join_prefill(prefill: str, text: str) -> str:
    """어시스턴트 프리필 뒤에 이어진 응답을 완전한 JSON 으로 되돌린다.

    종전엔 "응답이 `{` 로 시작하지 않으면 프리필을 앞에 붙인다"였는데, 프리필이
    `{"values":` 처럼 **값 자리에서 끊기면** 모델은 `{"subject": …}}` 를 돌려준다 —
    `{` 로 시작하므로 프리필을 안 붙였고, 그 결과는 닫는 괄호가 하나 남는 깨진 JSON 이라
    항상 `{}` 가 됐다(2026-10-05 실측: 입력 제안이 전부 비어 있던 원인). 응답이 이미
    프리필로 시작하는 경우(모델이 통째로 되풀이)만 그대로 둔다.
    """
    t = (text or "").lstrip()
    if t.startswith(prefill):
        return t
    return prefill + t


def _parse_values(text: str) -> dict[str, str]:
    import re as _re

    m = _re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    vals = data.get("values") if isinstance(data, dict) else None
    if not isinstance(vals, dict):
        return {}
    return {str(k): str(v or "")[:120] for k, v in vals.items() if str(k).strip()}


async def suggest_values(
    *,
    title: str,
    fields: list[dict],
    context: str,
    timeout_s: float = 12.0,
    model=None,
) -> dict[str, str]:
    """앞 단계 산출 → 다음 단계 입력값 초안. 실패하면 빈 dict(조합은 멈추지 않는다).

    "단계별 모드"의 핵심이다 — 사용자가 매 단계를 처음부터 타이핑하지 않고,
    채워진 초안을 **고치기만** 하면 되도록 한다.
    """
    keys = [str(f.get("key") or "").strip() for f in fields]
    keys = [k for k in keys if k]
    if not keys or not (context or "").strip():
        return {}

    field_lines = "\n".join(
        f"- {f.get('key')}: {f.get('label') or ''}"
        f"{' (' + str(f.get('placeholder')) + ')' if f.get('placeholder') else ''}"
        for f in fields if f.get("key")
    )

    try:
        from langchain_core.messages import AIMessage, HumanMessage

        from src.config import settings
        from src.models import build_chat_model

        llm = model or build_chat_model(settings.subagent_model, max_tokens=700)
        msgs = [HumanMessage(content=_SUGGEST_PROMPT.format(
            title=title[:120], fields=field_lines,
            context=context[:SUGGEST_CONTEXT_CHARS]))]
        if model is None:
            msgs.append(AIMessage(content=_SUGGEST_PREFILL))

        import asyncio as _aio

        res = await _aio.wait_for(llm.ainvoke(msgs), timeout_s)
    except Exception as e:  # noqa: BLE001 — 제안 실패가 조합을 막으면 안 된다
        _log.info("입력 제안 실패(무시): %s", e)
        return {}

    content = getattr(res, "content", None)
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    text = str(content or "")
    if model is None:
        text = join_prefill(_SUGGEST_PREFILL, text)

    vals = _parse_values(text)
    # 모르는 항목을 지어내지 않도록, 요청한 키만 남긴다.
    return {k: v for k, v in vals.items() if k in keys and v}
