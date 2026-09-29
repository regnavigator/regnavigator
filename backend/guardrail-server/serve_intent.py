"""Guardrail 의도 분류 서비스 — Qwen3.5-0.8B, "검색 필요?" 이진 판정.

medi-back 입구에서 규제 질의에 법령 검색을 강제할지 결정(환각 차단). 4분류는
0.8B 에 부정확해 **이진(search_needed)** 으로 서빙 — few-shot + 대화 맥락으로
후속 질문도 정확. 실측: 맥락 포함 시 위험한 오탐(규제 후속을 스킵) 제거, ~165ms.

계약: medi-back `docs/contracts/guardrail_intent_service.md`
    POST /classify   (X-API-Key)   { "text": "...", "context": "직전 주제(옵션)" }
    → { "search_needed": bool, "label": "예"|"아니오" }

env: GUARDRAIL_API_KEY/INSTANCE_API_KEY, INTENT_MODEL(기본 Qwen/Qwen3.5-0.8B), INTENT_DEVICE(0)
기동: uvicorn serve_intent:app --host 0.0.0.0 --port 8091
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

_API_KEY = os.getenv("GUARDRAIL_API_KEY") or os.getenv("INSTANCE_API_KEY") or ""
_MODEL = os.getenv("INTENT_MODEL", "Qwen/Qwen3.5-0.8B")
_DEVICE = os.getenv("INTENT_DEVICE", "cuda")

_SYS = (
    "의료 규제 챗봇 게이트. 현재 질문이 의료기기·의약품·법령·허가·규제·절차 "
    "관련이면 '예', 단순 인사·감사·잡담·일상이면 '아니오'. **직전 대화가 규제 "
    "주제면 이어지는 후속 질문도 '예'**. **챗봇 자신(이름·정체·사용법)이나 "
    "현재 날짜·시각을 묻는 것도 '아니오'** — 단, 허가·심사에 걸리는 '기간·"
    "소요시간'을 묻는 것은 규제 질문이라 '예'. 오직 예/아니오."
)
_FEW = [
    ("[직전:없음] 의료기기 광고 규제", "예"),
    ("[직전:없음] 고마워!", "아니오"),
    ("[직전:없음] 오늘 날씨 어때?", "아니오"),
    ("[직전:의료기기 광고 사전심의] 그럼 처벌은?", "예"),
    ("[직전:없음] 안녕", "아니오"),
    # 메타 질문(챗봇 자신·현재 시점) — 실측 2026-07-25: '현재 시각 알려줘'가
    # '예'로 새어 법령 검색이 강제됐다(나머지 메타 9건은 이미 정확).
    ("[직전:없음] 현재 시각 알려줘", "아니오"),
    ("[직전:없음] 너 이름 뭐야", "아니오"),
    # ★대조쌍 — 위 '시각' 예시가 소요기간 질문까지 '아니오'로 끌고 가지 않도록
    # 경계를 고정한다(이쪽이 무너지면 규제 질문이 무검색 → 환각).
    ("[직전:없음] 의료기기 허가 몇 시간 걸려?", "예"),
]

app = FastAPI(title="guardrail-intent")
_tok = None
_model = None


def _load():
    global _tok, _model
    if _model is None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        _tok = AutoTokenizer.from_pretrained(_MODEL)
        _model = AutoModelForCausalLM.from_pretrained(
            _MODEL, dtype=torch.bfloat16).to(_DEVICE).eval()
    return _tok, _model


class _Req(BaseModel):
    text: str
    context: str | None = None


def _classify(text: str, context: str | None) -> str:
    import torch

    tok, model = _load()
    msgs = [{"role": "system", "content": _SYS}]
    for q, a in _FEW:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": f"[직전:{context or '없음'}] {text}"})
    p = tok.apply_chat_template(
        msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    ids = tok(p, return_tensors="pt").to(_DEVICE)
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=4, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][ids.input_ids.shape[1]:], skip_special_tokens=True).strip()


def _auth(k):
    if _API_KEY and k != _API_KEY:
        raise HTTPException(status_code=403, detail="invalid X-API-Key")


@app.post("/classify")
def classify(req: _Req, x_api_key: str | None = Header(None, alias="X-API-Key")):
    _auth(x_api_key)
    ans = _classify(req.text, req.context)
    return {"search_needed": ans.startswith("예"), "label": ans[:8]}


@app.get("/health")
def health(x_api_key: str | None = Header(None, alias="X-API-Key")):
    _auth(x_api_key)
    lbl = _classify("의료기기 허가 절차", None)  # 로드 보장 + 스모크
    return {"status": "ok", "model": _MODEL, "smoke": lbl[:8]}
