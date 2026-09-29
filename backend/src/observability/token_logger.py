"""TokenUsageLogger — LangChain CallbackHandler로 모든 LLM 호출 후 token·cost emit.

LangChain의 ChatModel·LLM은 응답 metadata에 usage_metadata(input/output tokens)를
실어 보낸다. 이 callback이 on_llm_end에서 그것을 events 테이블에 박는다.

graph 빌드 시 매 LLM에 등록 — 또는 RunnableConfig에 callbacks=[...]로 inject.
이 프로젝트에서는 src/app.py 의 build_*_graph 함수에서 model.with_config로 묶는다.

cost 계산: 모델별 1K 토큰당 USD 가격 표 — production은 실제 청구서 기반으로
주기적 업데이트 필요. 현 표는 2026년 4월 기준 추정.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackHandler

from src.persistence import Event, get_events_repo

_log = logging.getLogger(__name__)


# ── usage 누락 관측 ────────────────────────────────────────────────────────
# 토큰을 못 뽑으면 llm_call 이벤트가 아예 안 박히고, 그 위에 얹힌 QuotaMiddleware
# 한도와 비용 집계가 **조용히 0 에 수렴**한다. 예전엔 파싱 실패도 usage 미발견도
# 전부 침묵이라 발견 경로가 없었다(2026-08-04 감사). notifications.py 의 교훈과
# 같다 — "배선 오류는 보여야 고쳐진다".
#
# 다만 스트리밍 중단처럼 **정상적인** 미발견도 있어 매번 warning 을 찍으면 노이즈다.
# → 누적 카운터를 두고 첫 발생 + 주기(기본 5분)마다 누락률과 함께 한 번만 찍는다.
_MISS_LOG_INTERVAL_S = float(os.getenv("TOKEN_USAGE_MISS_LOG_INTERVAL_S") or "300")
_usage_calls = 0
_usage_misses = 0
_last_miss_log_at = 0.0


def usage_miss_stats() -> dict:
    """관측용 스냅샷 — (총 on_llm_end 수, usage 누락 수, 누락률)."""
    return {
        "calls": _usage_calls,
        "misses": _usage_misses,
        "miss_ratio": round(_usage_misses / _usage_calls, 4) if _usage_calls else 0.0,
    }


def _note_usage_miss(reason: str, model_name: str = "") -> None:
    """usage 미확보 1건 기록 + 주기적 warning. 예외를 절대 올리지 않는다."""
    global _usage_misses, _last_miss_log_at
    import time as _time

    _usage_misses += 1
    now = _time.monotonic()
    if _usage_misses == 1 or (now - _last_miss_log_at) >= _MISS_LOG_INTERVAL_S:
        _last_miss_log_at = now
        s = usage_miss_stats()
        _log.warning(
            "token usage 누락 — 사유=%s model=%s 누계 %d/%d (%.1f%%). "
            "지속되면 쿼터·비용 집계가 과소계상된다.",
            reason, model_name or "?", s["misses"], s["calls"], s["miss_ratio"] * 100,
        )


# ── 중복 계상 방지 ────────────────────────────────────────────────────────
# 로거를 **모델에 부착**(build_chat_model)하도록 축을 옮기면서, 예전처럼 config
# 의 `callbacks` 로도 한 번 더 붙으면 같은 LLM run 이 두 번 계상된다(langchain 은
# 두 경로를 합쳐 모두 호출한다). 호출부가 실수로 되붙여도 회계가 틀리지 않도록
# **run_id 단위로 1회만** 집계한다 — "잊어도 새지 않는다"의 반대편 보증.
_SEEN_RUNS_MAX = 1024
_seen_runs: "OrderedDict[str, None]" = OrderedDict()
_seen_runs_lock = threading.Lock()


def _claim_llm_run(run_id) -> bool:
    """이 LLM run 을 처음 봤으면 True. run_id 가 없으면(구 콜백) 그냥 통과."""
    if run_id is None:
        return True
    key = str(run_id)
    with _seen_runs_lock:
        if key in _seen_runs:
            return False
        _seen_runs[key] = None
        while len(_seen_runs) > _SEEN_RUNS_MAX:
            _seen_runs.popitem(last=False)
    return True


def reset_run_dedupe() -> None:
    """테스트용."""
    with _seen_runs_lock:
        _seen_runs.clear()


# 모델명 → (input_per_1k_usd, output_per_1k_usd)
# 현 표는 추정치. 실 운영 후 청구서로 보정.
MODEL_PRICES_USD_PER_1K: dict[str, tuple[float, float]] = {
    # Anthropic Claude
    "claude-sonnet-4-6":             (0.003, 0.015),
    "claude-haiku-4-5":              (0.0008, 0.004),
    "claude-haiku-4-5-20251001":     (0.0008, 0.004),
    "claude-opus-4-7":               (0.015, 0.075),

    # OpenAI (LLM_FALLBACK·SUBAGENT_FALLBACK)
    "gpt-4o":                        (0.0025, 0.010),
    "gpt-4o-mini":                   (0.00015, 0.0006),
    "gpt-5.4":                       (0.005, 0.015),       # 추정
    "gpt-5.4-mini":                  (0.0005, 0.002),      # 추정
}


def _normalize_model(model_name: str) -> str:
    """provider prefix 제거: 'anthropic:claude-sonnet-4-6' → 'claude-sonnet-4-6'."""
    if not model_name:
        return ""
    if ":" in model_name:
        return model_name.split(":", 1)[1].strip()
    return model_name.strip()


def _resolve_user_id(configurable: dict) -> Optional[str]:
    """run config에서 사용자 식별자 해석.

    우선순위:
      1) configurable["user_id"] — 명시 주입(백엔드가 그래프를 직접 invoke 시).
      2) configurable["langgraph_auth_user"].identity — langgraph 커스텀 auth
         (src/auth.py)가 인증한 사용자. 프런트 SDK runs(/threads/{}/runs)는
         AuthMiddleware를 안 거치므로 fast 턴은 이 경로로만 귀속 가능.
         (키 출처: langgraph/pregel/main.py — configurable["langgraph_auth_user"])

    "anonymous"/빈값은 실사용자 아님 → None (집계·쿼터 오염 방지).
    """
    uid = configurable.get("user_id")
    if uid and str(uid) not in ("", "anonymous"):
        return str(uid)
    au = configurable.get("langgraph_auth_user")
    if au is not None:
        ident = getattr(au, "identity", None)
        if ident is None and isinstance(au, dict):
            ident = au.get("identity")
        if ident and str(ident) not in ("", "anonymous"):
            return str(ident)
    return None


def _estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    norm = _normalize_model(model_name)
    rates = MODEL_PRICES_USD_PER_1K.get(norm)
    if not rates:
        return 0.0
    input_rate, output_rate = rates
    return (input_tokens / 1000.0) * input_rate + (output_tokens / 1000.0) * output_rate


class TokenUsageLogger(BaseCallbackHandler):
    """LLM 호출마다 events.event_type='llm_call' 한 행 emit.

    user_id·thread_id·run_id는 RunnableConfig.configurable에서 추출.

    **명시 컨텍스트 폴백** (2026-07-13, ADR-0001 실사용 테스트에서 발견):
    콜백 실행 시점의 `ensure_config()` 는 langgraph run 밖(자체 chat_loop 등)에선
    빈 값이라 thread/user 귀속이 전부 NULL 로 새어나갔다(쿼터 무력화). 생성자
    kwargs 로 받은 컨텍스트를 configurable 부재 시 폴백으로 쓴다 — 기존 no-arg
    사용처(TokenLoggerMiddleware)는 동작 불변.
    """

    def __init__(self, *, thread_id: Optional[str] = None,
                 user_id: Optional[str] = None,
                 run_id: Optional[str] = None) -> None:
        super().__init__()
        self._ctx_thread_id = thread_id
        self._ctx_user_id = user_id
        self._ctx_run_id = run_id

    def on_llm_end(self, response: Any, *, run_id=None, parent_run_id=None,
                   tags=None, **kwargs) -> None:
        try:
            if not _claim_llm_run(run_id):
                return
            self._capture(response, kwargs)
        except Exception as e:
            # observability는 실패해도 사용자 흐름 막지 않는다.
            _log.warning("TokenUsageLogger emit failed: %s", e)

    on_chat_model_end = on_llm_end  # ChatModel 경로도 같은 로직

    def _capture(self, response: Any, kwargs: dict) -> None:
        global _usage_calls
        _usage_calls += 1

        # 1) usage 추출 — generations / llm_output / response_metadata 어디든 있을 수 있음
        input_tokens = 0
        output_tokens = 0
        model_name = ""

        # 1a) llm_output (legacy LangChain)
        llm_output = getattr(response, "llm_output", None) or {}
        usage = (llm_output.get("token_usage")
                 or llm_output.get("usage")
                 or {})
        if usage:
            input_tokens = (usage.get("prompt_tokens")
                            or usage.get("input_tokens") or 0)
            output_tokens = (usage.get("completion_tokens")
                             or usage.get("output_tokens") or 0)
        model_name = llm_output.get("model_name") or llm_output.get("model") or ""

        # 1b) response_metadata in generations[0][0]
        if not (input_tokens or output_tokens):
            try:
                gen = response.generations[0][0]
                meta = getattr(gen, "generation_info", None) or {}
                rm = meta.get("response_metadata") or getattr(
                    gen.message, "response_metadata", {}
                ) if hasattr(gen, "message") else {}
                if rm:
                    u = rm.get("usage") or rm.get("token_usage") or {}
                    input_tokens = (u.get("input_tokens") or u.get("prompt_tokens") or 0)
                    output_tokens = (u.get("output_tokens") or u.get("completion_tokens") or 0)
                    model_name = model_name or rm.get("model") or rm.get("model_name") or ""
                # usage_metadata (langchain_anthropic 등)
                if hasattr(gen, "message"):
                    um = getattr(gen.message, "usage_metadata", None) or {}
                    if um and not (input_tokens or output_tokens):
                        input_tokens = um.get("input_tokens", 0)
                        output_tokens = um.get("output_tokens", 0)
            except Exception as e:
                # 응답 스키마가 바뀌면 여기로 떨어진다 — 삼키되 관측은 남긴다.
                _log.debug("usage 파싱 예외(%s)", type(e).__name__)

        # 2) configurable 컨텍스트
        from langchain_core.runnables.config import ensure_config
        try:
            cfg = ensure_config()
            configurable = (cfg or {}).get("configurable") or {}
        except Exception:
            configurable = {}

        # 귀속 우선순위: configurable > 생성자 인자 > **ambient 컨텍스트**.
        # 마지막 폴백이 무결성의 축이다 — 호출부가 아무것도 안 넘겨도 진입점에서
        # 심은 값으로 귀속된다(src/observability/usage_context.py).
        from src.observability import usage_context

        amb = usage_context.current()

        chat_thread_id = (
            configurable.get("parent_thread_id")
            or configurable.get("thread_id")
            or kwargs.get("thread_id")
            or self._ctx_thread_id
            or amb["thread_id"]
        )
        user_id = _resolve_user_id(configurable)
        if not user_id and self._ctx_user_id and str(self._ctx_user_id) not in ("", "anonymous"):
            user_id = str(self._ctx_user_id)
        if not user_id:
            user_id = amb["user_id"]
        run_id_str = (
            str(configurable.get("run_id"))
            if configurable.get("run_id")
            else (self._ctx_run_id or amb["run_id"])
        )

        if not (input_tokens or output_tokens):
            # usage 못 찾음 — 모델이 metadata 미제공 또는 stream 도중 종료.
            # 정상 사유도 있지만 스키마 변경 시엔 쿼터가 조용히 0 이 되므로 계측한다.
            _note_usage_miss("usage_not_found", model_name)
            return

        cost = _estimate_cost(model_name, input_tokens, output_tokens)

        payload = {
            "model": model_name,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
        }

        try:
            get_events_repo().emit(Event(
                id="", ts="",
                event_type="llm_call",
                user_id=user_id,
                thread_id=chat_thread_id,
                run_id=run_id_str,
                payload_json=json.dumps(payload, ensure_ascii=False),
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                cost_usd=round(cost, 6),
            ))
        except Exception as e:
            _log.warning("events.emit failed in TokenUsageLogger: %s", e)
