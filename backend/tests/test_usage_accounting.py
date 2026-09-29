"""LLM 사용량 회계 무결성 — 2026-08-05.

실측으로 드러난 것: `events.llm_call` 3일치 119건 중 58건(36만 토큰, 15%)이
`user_id` NULL 이었고, 그와 별개로 **이벤트가 아예 안 남는** 호출이 셋 있었다
(coverage 판정·auto-title·대화 압축 요약). 셋 다 원인이 같다 — 계측과 귀속이
호출부의 책임이라, 새 호출부가 잊으면 조용히 샜다.

이 파일이 잠그는 것:
  ① 계측 — 모델을 만들면 로거가 따라 나온다(호출부가 잊을 수 없다)
  ② 귀속 — 진입점에서 심은 ambient 컨텍스트로 user/thread 가 붙는다
  ③ 이중 계상 — 콜백이 두 번 붙어도 run_id 단위로 1회만 집계된다
  ④ 회귀 방지 — build_chat_model 을 우회해 provider 를 직접 만들면 실패
  ⑤ 일 경계 — 일일 쿼터의 "하루"는 UTC 가 아니라 사용자 자정
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.observability import usage_context
from src.observability.token_logger import (
    TokenUsageLogger,
    reset_run_dedupe,
    usage_miss_stats,
)


@pytest.fixture(autouse=True)
def _clean_ctx():
    usage_context.clear()
    reset_run_dedupe()
    yield
    usage_context.clear()
    reset_run_dedupe()


# ── ② 귀속 — ambient 컨텍스트 ──────────────────────────────────────────────
class _Resp:
    """usage_metadata 를 실은 최소 LLM 응답(langchain_anthropic 형태)."""

    def __init__(self, i=100, o=20):
        msg = type("M", (), {"usage_metadata": {"input_tokens": i, "output_tokens": o},
                             "response_metadata": {"model": "claude-haiku-4-5"}})()
        gen = type("G", (), {"message": msg, "generation_info": {}})()
        self.generations = [[gen]]
        self.llm_output = {}


def _capture_events(monkeypatch) -> list:
    """emit 된 Event 를 가로채 리스트로."""
    from src.observability import token_logger

    got: list = []
    monkeypatch.setattr(token_logger, "get_events_repo",
                        lambda: type("R", (), {"emit": staticmethod(got.append)})())
    return got


def test_ambient_context_attributes_the_call(monkeypatch):
    """호출부가 아무것도 안 넘겨도 진입점에서 심은 사용자로 귀속된다."""
    got = _capture_events(monkeypatch)
    usage_context.bind(user_id="u-1", thread_id="t-1")

    TokenUsageLogger().on_llm_end(_Resp(), run_id="r1")

    assert len(got) == 1
    assert got[0].user_id == "u-1", "귀속 실패 — 이 토큰은 누구의 한도에도 안 잡힌다"
    assert got[0].thread_id == "t-1"


def test_explicit_args_win_over_ambient(monkeypatch):
    """명시 컨텍스트가 있으면 그쪽이 우선 — 잡이 요청 컨텍스트를 덮어쓴다."""
    got = _capture_events(monkeypatch)
    usage_context.bind(user_id="u-request")

    TokenUsageLogger(user_id="u-job").on_llm_end(_Resp(), run_id="r1")

    assert got[0].user_id == "u-job"


def test_anonymous_is_not_bound():
    """'anonymous'·빈값은 실사용자가 아니다 — 집계 오염 방지."""
    usage_context.bind(user_id="anonymous")
    assert usage_context.current()["user_id"] is None


def test_scope_restores_previous_context():
    usage_context.bind(user_id="u-outer")
    with usage_context.scope(user_id="u-inner"):
        assert usage_context.current()["user_id"] == "u-inner"
    assert usage_context.current()["user_id"] == "u-outer"


def test_context_propagates_into_child_task(monkeypatch):
    """백그라운드 태스크가 값을 물려받아야 보고서 토큰이 귀속된다."""
    import asyncio

    async def _go():
        usage_context.bind(user_id="u-parent")
        return await asyncio.create_task(_child())

    async def _child():
        return usage_context.current()["user_id"]

    assert asyncio.run(_go()) == "u-parent"


# ── ③ 이중 계상 방지 ───────────────────────────────────────────────────────
def test_same_run_is_counted_once_even_with_two_loggers(monkeypatch):
    """모델 부착 + config 부착이 겹쳐도 토큰이 2배가 되면 안 된다."""
    got = _capture_events(monkeypatch)
    usage_context.bind(user_id="u-1")

    for _ in range(3):                       # 콜백 3개가 같은 run 을 보고
        TokenUsageLogger().on_llm_end(_Resp(i=100, o=20), run_id="same-run")

    assert len(got) == 1, f"같은 LLM run 이 {len(got)}번 계상됐다 — 청구·쿼터가 틀린다"
    assert got[0].input_tokens == 100


def test_different_runs_are_all_counted(monkeypatch):
    got = _capture_events(monkeypatch)
    usage_context.bind(user_id="u-1")
    for i in range(3):
        TokenUsageLogger().on_llm_end(_Resp(), run_id=f"run-{i}")
    assert len(got) == 3


# ── ① 계측 — 모델에 로거가 따라 나온다 ─────────────────────────────────────
def test_build_chat_model_attaches_logger(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("DISABLE_TOKEN_LOGGER", raising=False)
    from src.models import build_chat_model

    m = build_chat_model("anthropic:claude-haiku-4-5-20251001")
    assert any(isinstance(c, TokenUsageLogger) for c in (m.callbacks or [])), \
        "모델에 토큰 로거가 안 붙었다 — 이 모델의 호출은 집계에서 사라진다"


def test_disable_flag_is_honored(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("DISABLE_TOKEN_LOGGER", "1")
    from src.models import build_chat_model

    m = build_chat_model("anthropic:claude-haiku-4-5-20251001")
    assert not [c for c in (m.callbacks or []) if isinstance(c, TokenUsageLogger)]


# ── ④ 회귀 방지 — provider 직접 생성 금지 ──────────────────────────────────
_PROVIDER_CLASSES = {"ChatAnthropic", "ChatOpenAI"}
_ALLOWED = {pathlib.Path("src/models.py")}


def _py_files():
    return [p for p in pathlib.Path("src").rglob("*.py")]


def test_no_module_builds_a_provider_model_directly():
    """`build_chat_model()` 만이 모델을 만든다.

    우회하면 로거가 안 붙어 그 호출의 토큰이 통째로 사라진다 — 이번에 발견된
    누락 셋과 정확히 같은 사고다. 새 호출부가 생겨도 여기서 걸린다.
    """
    offenders = []
    for path in _py_files():
        if path in _ALLOWED:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in _PROVIDER_CLASSES:
                offenders.append(f"{path}:{node.lineno} {node.func.id}()")

    assert not offenders, (
        "build_chat_model() 을 우회해 모델을 직접 생성한다 — 토큰 로거가 안 붙는다:\n  "
        + "\n  ".join(offenders))


def test_llm_cfg_helpers_do_not_attach_callbacks():
    """config 로 로거를 되붙이면 이중 부착 — dedupe 가 막지만 애초에 금지."""
    from src.grounding import _llm_cfg as ground_cfg
    from src.report_pipeline import _llm_cfg as report_cfg

    assert "callbacks" not in ground_cfg()
    assert "callbacks" not in report_cfg({"user_id": "u", "thread_id": "t"})


# ── ⑤ 일 경계 ──────────────────────────────────────────────────────────────
def test_daily_window_is_user_midnight_not_utc(monkeypatch):
    """UTC 자정을 쓰면 일일 한도가 KST 오전 9시에 리셋된다.

    ⚠️ 시각 의존 주의: 종전 단언(`local < utc`)은 KST 00~09시(UTC 15~24시)에
    뒤집힌다 — 그 시간대엔 KST 자정(어제 15:00Z)이 UTC 자정(어제 00:00Z)보다
    *늦다*. 기대값을 직접 계산해 하루 중 언제 돌려도 결정적이게 한다.
    """
    from datetime import datetime, timedelta, timezone

    from src.persistence import start_of_today_local_iso, start_of_today_utc_iso

    monkeypatch.setenv("USAGE_DAY_UTC_OFFSET_HOURS", "9")
    local, utc = start_of_today_local_iso(), start_of_today_utc_iso()

    assert local.endswith("Z") and utc.endswith("Z")
    assert local != utc, "일 경계가 여전히 UTC 자정이다"
    now = datetime.now(timezone.utc)
    kst_midnight = (now + timedelta(hours=9)).replace(
        hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=9)
    assert local == kst_midnight.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), \
        "일 경계가 KST 자정이 아니다"


def test_quota_uses_the_local_window():
    """미들웨어가 새 경계를 실제로 쓰는지 — 헬퍼만 고치고 배선을 잊는 사고 방지."""
    src = pathlib.Path("src/middleware/quota.py").read_text(encoding="utf-8")
    assert "start_of_today_local_iso()" in src
    assert "start_of_today_utc_iso()" not in src


def test_offset_env_is_respected(monkeypatch):
    from src.persistence import start_of_today_local_iso

    monkeypatch.setenv("USAGE_DAY_UTC_OFFSET_HOURS", "0")
    from src.persistence import start_of_today_utc_iso

    assert start_of_today_local_iso() == start_of_today_utc_iso()


def test_bad_offset_falls_back_to_kst(monkeypatch):
    monkeypatch.setenv("USAGE_DAY_UTC_OFFSET_HOURS", "정오")
    from src.persistence import start_of_today_local_iso

    assert start_of_today_local_iso().endswith("Z")   # 죽지 않는다


# ── 관측 ───────────────────────────────────────────────────────────────────
def test_usage_miss_is_counted(monkeypatch):
    """usage 를 못 뽑으면 이벤트가 안 박힌다 — 그 사실이 보여야 고쳐진다."""
    got = _capture_events(monkeypatch)
    before = usage_miss_stats()["misses"]

    class _Empty:
        generations = [[type("G", (), {"generation_info": {}})()]]
        llm_output = {}

    TokenUsageLogger().on_llm_end(_Empty(), run_id="r-empty")

    assert got == []
    assert usage_miss_stats()["misses"] == before + 1


# ── 한도값 ─────────────────────────────────────────────────────────────────
def test_default_daily_limit_is_effectively_unlimited(monkeypatch):
    """일일 기본 한도 = 2,000만 (2026-08-19 운영 판단 — 베타 동안 사실상 무제한).

    이력: 1000만(장식) → 200만(2026-08-05, 실측 p95 92만의 2배) → **2000만**.
    지금 이 값의 역할은 배급이 아니라 **폭주·남용 차단기 하나뿐**이다.
    실측 p90 79.3만의 25배·중앙값(15.4만)의 130배라 정상 사용은 어떤 패턴으로도
    걸리지 않고, 무한 루프·키 유출만 하루 손실 ~$33 선에서 끊는다.

    **한도를 없애지 않는 이유**: 차단기가 사라지면 사고 비용에 상한이 없고,
    사용량이 붙어 과금 전략을 도입할 때 계측·차단 경로가 살아 있어야 한다.
    개별 조정은 admin 의 daily_token_limit_override(0=무제한).
    """
    from src.middleware.quota import _system_daily_limit

    monkeypatch.delenv("DEFAULT_DAILY_TOKEN_LIMIT", raising=False)
    assert _system_daily_limit() == 20_000_000


def test_daily_limit_env_overrides(monkeypatch):
    from src.middleware.quota import _system_daily_limit

    monkeypatch.setenv("DEFAULT_DAILY_TOKEN_LIMIT", "2500000")
    assert _system_daily_limit() == 2_500_000
