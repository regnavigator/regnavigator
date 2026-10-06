"""판단 모델 어댑터 — 상황(state) + 타입 지정 질문 → 보정 확률 (2026-10-06).

`Vibe_Coding_Agent_Master_Prompt.docx` 의 "JEV" 를 선별 적용한 것. Jev(TypeSafe)는 문장을
생성하지 않고 **boolean / 선택지 질문에 확률로 답하는** 판단 모델이다(위키독스
`wikidocs.net/432835`). 추론 LLM 과 경쟁이 아니라 보완 — "LLM 을 부를지"를 먼저 싸게 판정한다.

백엔드 순서(있는 것부터):
  ① 원내  `JUDGE_LOCAL_BASE_URL` — Ollama ≥0.35 `/v1/systemone`(Kev-4B 등 오픈 GGUF)
  ② 상용  `JUDGE_API_URL` + `JUDGE_API_KEY` — TypeSafe `/v1/systemone`
  ③ 폴백  `aux_model()` 로 LLM 에게 JSON 으로 묻는다(인터페이스만 같고 보정 성질은 다르다 — 책 14부)
기밀 턴은 ①만(`aux_model` 정책과 같은 규칙 — 상용·외부로 내용이 나가면 안 된다).

**임계값은 측정 뒤에 켠다.** 지금은 호출자가 결과를 events(`judgment`) 로 적재만 하고 동작은
휴리스틱을 유지한다(감사 M3: 미측정 상수로 켜지 않는다). 책 사례 — "확신하고 틀린 1건이
게이트를 통과" — 를 그대로 재현할 수 있다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

_log = logging.getLogger("judgment")

#: state 상한 — Jev 32k 토큰 중 질문 몫을 뺀 안전치. 원내 4B 는 더 작다.
STATE_MAX_CHARS = 6000


@dataclass
class Question:
    """boolean(`choices` 없음) 또는 선택지 하나."""
    text: str
    choices: Optional[list[str]] = None


@dataclass
class Judgment:
    #: 질문 키 → 확률(boolean) 또는 {선택지: 확률}
    answers: dict[str, float | dict[str, float]] = field(default_factory=dict)
    backend: str = "none"  # local | api | llm | none


def _local_url() -> str:
    return (os.getenv("JUDGE_LOCAL_BASE_URL") or "").rstrip("/")


def _api_url() -> str:
    return (os.getenv("JUDGE_API_URL") or "").rstrip("/")


def _api_key() -> str:
    return (os.getenv("JUDGE_API_KEY") or "").strip()


def _timeout_s() -> float:
    try:
        return float((os.getenv("JUDGE_TIMEOUT_S") or "").strip() or "2")
    except ValueError:
        return 2.0


def is_available(*, confidential: bool = False) -> bool:
    if _local_url():
        return True
    if confidential:
        return False
    return bool(_api_url() and _api_key())


def _systemone(base: str, key: str, state: str, questions: dict[str, Question]) -> dict:
    """`POST {base}/v1/systemone` — TypeSafe·Ollama 공통 형태.

    `{"state": str, "questions": {key: {"text", "choices"?}}}` → `{"answers": {key: p | {c: p}}}`.
    """
    import httpx

    payload = {
        "state": state[-STATE_MAX_CHARS:],
        "questions": {
            k: ({"text": q.text, "choices": q.choices} if q.choices else {"text": q.text})
            for k, q in questions.items()
        },
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with httpx.Client(timeout=_timeout_s()) as c:
        r = c.post(f"{base}/v1/systemone", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data.get("answers") if isinstance(data, dict) else {}


def _coerce(raw: dict, questions: dict[str, Question]) -> dict[str, float | dict[str, float]]:
    """응답을 질문 키·타입에 맞춰 정리 — 모르는 키·범위 밖 값은 버린다."""
    out: dict[str, float | dict[str, float]] = {}
    for k, q in questions.items():
        v = (raw or {}).get(k)
        if q.choices:
            if not isinstance(v, dict):
                continue
            probs = {c: float(v[c]) for c in q.choices if isinstance(v.get(c), (int, float))}
            if probs:
                out[k] = {c: max(0.0, min(1.0, p)) for c, p in probs.items()}
        else:
            if isinstance(v, bool):
                v = 1.0 if v else 0.0
            if isinstance(v, (int, float)):
                out[k] = max(0.0, min(1.0, float(v)))
    return out


_LLM_PROMPT = """다음 상황을 읽고 각 질문에 **확률(0~1)** 로만 답하라. 설명 없이 JSON 만.

[상황]
{state}

[질문]
{questions}

출력 형식: {{"answers": {{"질문키": 0.0~1.0 또는 {{"선택지": 0.0~1.0}}}}}}
"""


async def _llm_fallback(state: str, questions: dict[str, Question]) -> dict:
    from langchain_core.messages import AIMessage, HumanMessage

    from src.chat_loop import aux_model
    from src.config import settings
    from src.workflow import join_prefill

    llm = aux_model(settings.subagent_model, max_tokens=400)
    if llm is None:
        return {}
    qtext = "\n".join(
        f"- {k}: {q.text}" + (f" (선택지: {', '.join(q.choices)})" if q.choices else " (예/아니오)")
        for k, q in questions.items()
    )
    prefill = '{"answers":'
    res = await llm.ainvoke([
        HumanMessage(content=_LLM_PROMPT.format(state=state[-STATE_MAX_CHARS:], questions=qtext)),
        AIMessage(content=prefill),
    ])
    content = getattr(res, "content", "")
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    text = join_prefill(prefill, str(content or ""))
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {}
    return data.get("answers") if isinstance(data, dict) else {}


async def judge(
    state: str,
    questions: dict[str, Question],
    *,
    confidential: bool = False,
) -> Judgment:
    """판정. 실패하면 빈 Judgment(backend="none") — 호출자는 휴리스틱으로 계속한다."""
    if not questions or not (state or "").strip():
        return Judgment()
    import asyncio

    local = _local_url()
    if local:
        try:
            raw = await asyncio.to_thread(_systemone, local, "", state, questions)
            ans = _coerce(raw, questions)
            if ans:
                return Judgment(answers=ans, backend="local")
        except Exception as e:  # noqa: BLE001 — 판정 실패가 작업을 막으면 안 된다
            _log.info("판단 모델(원내) 실패(무시): %s", e)
    if confidential:
        # 기밀 턴 — 원내가 없거나 실패하면 여기서 끝. 상용·LLM 폴백으로 내용이 나가면 안 된다.
        return Judgment()
    api, key = _api_url(), _api_key()
    if api and key:
        try:
            raw = await asyncio.to_thread(_systemone, api, key, state, questions)
            ans = _coerce(raw, questions)
            if ans:
                return Judgment(answers=ans, backend="api")
        except Exception as e:  # noqa: BLE001
            _log.info("판단 모델(상용) 실패(무시): %s", e)
    try:
        ans = _coerce(await _llm_fallback(state, questions), questions)
        if ans:
            return Judgment(answers=ans, backend="llm")
    except Exception as e:  # noqa: BLE001
        _log.info("판단 LLM 폴백 실패(무시): %s", e)
    return Judgment()
