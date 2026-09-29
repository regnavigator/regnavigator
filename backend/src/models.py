"""모델 선택 — provider 직접 생성 (ADR-0001 Phase 5: `init_chat_model` 폐기).

`langchain.chat_models.init_chat_model`(langchain 메타 소속) 대신 provider
클래스를 직접 생성 — 목표 의존 셋(langchain-core + langchain-anthropic)만
사용한다. openai 는 [writer-vllm] extras(lazy import).

전 코드의 모델 생성은 `build_chat_model(spec)` 한 곳으로 수렴:
chat_loop(대화·요약) · grounding · report_pipeline(분해) · routes/chat(auto-title).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

_log = logging.getLogger(__name__)


def split_model_spec(spec: str) -> tuple[str, str]:
    """"provider:model" → (provider, model). prefix 없으면 anthropic."""
    if ":" in spec:
        p, n = spec.split(":", 1)
        return p.strip().lower(), n.strip()
    return "anthropic", spec.strip()


def provider_credential_ok(provider: str) -> bool:
    """아는 provider 는 키 유무 사전 확인(부팅/폴백 크래시 방지), 모르면 통과."""
    required = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
    if required is None:
        return True
    return bool((os.getenv(required) or "").strip())


def _usage_callbacks() -> list:
    """모든 모델에 토큰 로거를 부착 — 계측을 호출부 책임에서 뗀다.

    (2026-08-05) 종전엔 호출부가 `config={"callbacks": [...]}` 로 붙였다. 그래서
    붙이는 걸 잊은 세 곳(coverage 판정·auto-title·대화 압축 요약)의 토큰이
    `events` 에 **한 줄도 안 남았고**, 그 위의 일일 쿼터가 그만큼 과소계상됐다.
    모델을 만들면 로거가 따라 나오게 해서 잊을 수 없게 한다.

    귀속(user/thread)은 로거가 ambient 컨텍스트에서 읽는다 — usage_context.
    중복 부착은 run_id 단위 dedupe 가 막는다 — token_logger._claim_llm_run.
    """
    if os.getenv("DISABLE_TOKEN_LOGGER") == "1":
        return []
    try:
        from src.observability.token_logger import TokenUsageLogger

        return [TokenUsageLogger()]
    except Exception:  # noqa: BLE001 — 관측 배선 실패가 모델 생성을 막으면 안 됨
        return []


def build_chat_model(
    spec: str,
    *,
    temperature: float = 0,
    max_tokens: Optional[int] = None,
    max_retries: Optional[int] = None,
    rate_limiter=None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: Optional[float] = None,
    extra_body: Optional[dict] = None,
):
    """"provider:model" spec → chat model 인스턴스 (직접 생성).

    rate_limiter 미지정 시 전역 client-side limiter(`src.llm_limits`) 공유 —
    프로세스 내 모든 모델 호출이 같은 버킷으로 집계 캡.

    `base_url`(openai provider 전용): **온프레미스 OpenAI 호환 서버**를 가리킨다
    (2026-08-26). 직접 ChatOpenAI 를 만들면 토큰 로거가 안 붙어 그 호출의 사용량이
    통째로 사라진다(tests/test_usage_accounting.py 가 금지) — 여기로 통과시킨다.
    """
    provider, name = split_model_spec(spec)
    callbacks = _usage_callbacks()
    if max_retries is None:
        try:
            max_retries = int((os.getenv("MODEL_RETRY_MAX") or "").strip() or "2")
        except ValueError:
            max_retries = 2
    if rate_limiter is None:
        from src.llm_limits import global_rate_limiter

        rate_limiter = global_rate_limiter()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kw = dict(model=name, temperature=temperature,
                  max_retries=max_retries, rate_limiter=rate_limiter,
                  callbacks=callbacks)
        if max_tokens is not None:
            kw["max_tokens"] = max_tokens
        return ChatAnthropic(**kw)
    if provider == "openai":
        from langchain_openai import ChatOpenAI  # [writer-vllm] extras

        kw = dict(model=name, temperature=temperature,
                  max_retries=max_retries, rate_limiter=rate_limiter,
                  callbacks=callbacks)
        if max_tokens is not None:
            kw["max_tokens"] = max_tokens
        if base_url:
            kw["base_url"] = base_url
            # 온프레미스는 키 검증이 없는 게 보통 — 미지정 시 자리표.
            kw["api_key"] = api_key or "EMPTY"
        if timeout is not None:
            kw["timeout"] = timeout
        if extra_body:
            kw["extra_body"] = extra_body
        return ChatOpenAI(**kw)
    raise ValueError(f"미지원 provider: {provider!r} (anthropic|openai)")


def _build(name: str, fallback_name: Optional[str]):
    m = build_chat_model(name)
    if fallback_name and provider_credential_ok(split_model_spec(fallback_name)[0]):
        try:
            m = m.with_fallbacks([build_chat_model(fallback_name)])
        except Exception as e:  # noqa: BLE001 — 폴백 구성 실패가 흐름 막으면 안 됨
            _log.warning("fallback(%s) 구성 실패 — 폴백 비활성: %s", fallback_name, e)
    return m


def primary_model(model_name: Optional[str] = None, fallback: Optional[str] = None):
    """기본 대화 모델 — 인자 > env(`LLM_MODEL`) > 기본값."""
    name = model_name or os.environ.get("LLM_MODEL") or "anthropic:claude-sonnet-4-6"
    fb = fallback if fallback is not None else os.getenv("LLM_FALLBACK")
    return _build(name, fb)


def cheap_model_spec() -> str:
    """가벼운 작업(요약·grounding·분해·제목) 기본 스펙."""
    return os.getenv("SUBAGENT_MODEL") or "anthropic:claude-haiku-4-5-20251001"


def _detect_served_model(base_url: str) -> Optional[str]:
    """vLLM `/models` 로 서빙 중인 모델 id 자동 감지 — REPORT_WRITER_MODEL 미설정용.

    DGX 에서 서빙 모델을 교체(Qwen↔gemma)할 때 env 를 같이 안 바꾸면 모델명
    불일치(404)로 보고서가 전멸하던 문제 — 단일 모델 서빙(vLLM 관례)이면 첫
    항목 id 를 그대로 쓴다. 실패 시 None(호출부가 종전 기본값 폴백).
    """
    try:
        import httpx
        r = httpx.get(
            base_url.rstrip("/") + "/models", timeout=5.0,
            headers={"Authorization":
                     f"Bearer {os.getenv('REPORT_WRITER_API_KEY') or 'EMPTY'}"},
        )
        data = (r.json() or {}).get("data") or []
        mid = str((data[0] or {}).get("id") or "") if data else ""
        if mid:
            _log.info("report writer 모델 자동 감지: %s (%s)", mid, base_url)
            return mid
    except Exception as e:  # noqa: BLE001 — 감지 실패는 기본값 폴백
        _log.info("writer 모델 자동 감지 실패(%s) — 기본값 사용", e)
    return None


def report_writer_model():
    """deep 보고서 writer 전용 모델.

    `REPORT_WRITER_BASE_URL` 설정 시 로컬 vLLM(OpenAI 호환, 예 DGX Qwen3.5-27B)로
    합성. 미설정 시 `primary_model()` 폴백(하위호환).

    ⚠️ Qwen3.5 는 thinking 모드가 기본 ON — 보고서 본문에 사고과정이 새므로
    `enable_thinking=false`(chat_template_kwargs)를 반드시 전달한다.
    """
    base_url = (os.getenv("REPORT_WRITER_BASE_URL") or "").strip()
    if not base_url:
        return primary_model()
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:  # base 의존에서 제외됨(ADR-0001 Phase 0)
        raise ImportError(
            "REPORT_WRITER_BASE_URL 이 설정됐지만 langchain-openai 미설치 — "
            'pip install ".[writer-vllm]" (또는 prod extras) 후 재시도'
        ) from e

    # 기본 1800s — 정책(2026-07-24): writer 는 초장기 허용, 챗 즉각성이 우선.
    # DGX 에서 writer vLLM 점유를 낮추면(--max-num-seqs 등) 생성이 더 느려지므로
    # 클라이언트 타임아웃을 넉넉히.
    try:
        timeout_s = float((os.getenv("REPORT_WRITER_TIMEOUT_S") or "").strip() or "1800")
    except ValueError:
        timeout_s = 1800.0
    try:
        max_tokens = int((os.getenv("REPORT_WRITER_MAX_TOKENS") or "").strip() or "8000")
    except ValueError:
        max_tokens = 8000
    # ⚠️ 실측 사고(2026-08-02): langchain-openai 의 `stream_chunk_timeout` 기본값이
    # **120초**라, writer 가 거대한 입력을 prefill 하는 동안(첫 토큰 전 침묵)
    # `REPORT_WRITER_TIMEOUT_S=1800` 과 무관하게 StreamChunkTimeoutError 로 죽었다
    # (보고서 e2e status=failed). httpx read timeout 과 달리 keepalive 로는 리셋되지
    # 않는 **콘텐츠 침묵** 타이머라, 느린 GPU·긴 프롬프트에서 반드시 걸린다.
    try:
        chunk_timeout_s = float(
            os.getenv("REPORT_WRITER_STREAM_CHUNK_TIMEOUT_S") or "900")
    except ValueError:
        chunk_timeout_s = 900.0
    return ChatOpenAI(
        # 우선순위: 명시 env > /models 자동 감지 > 종전 기본값(하위호환).
        model=(os.getenv("REPORT_WRITER_MODEL")
               or _detect_served_model(base_url)
               or "Qwen3.5-27B-FP8"),
        base_url=base_url,
        api_key=os.getenv("REPORT_WRITER_API_KEY") or "EMPTY",
        temperature=0,
        timeout=timeout_s,
        stream_chunk_timeout=chunk_timeout_s,   # 0/None 이면 비활성(무한 대기)
        max_retries=1,
        max_tokens=max_tokens,  # 심층 보고서 — 넉넉히(배경 시간 무관)
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
