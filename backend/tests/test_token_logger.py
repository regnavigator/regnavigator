"""TokenUsageLogger 단위 테스트.

LLM 응답 mock에 usage 박고 callback 발동 → events 테이블에 row 박혔는지 확인.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "medi.db"))
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    from src import persistence as P
    P.get_events_repo.cache_clear()
    P.get_users_repo.cache_clear()
    P.get_reports_repo.cache_clear()
    P.get_blob_store.cache_clear()
    P.get_feedback_repo.cache_clear()
    yield
    P.get_events_repo.cache_clear()
    P.get_users_repo.cache_clear()
    P.get_reports_repo.cache_clear()
    P.get_blob_store.cache_clear()
    P.get_feedback_repo.cache_clear()


def test_normalize_model_strips_provider_prefix():
    from src.observability.token_logger import _normalize_model
    assert _normalize_model("anthropic:claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert _normalize_model("openai:gpt-4o") == "gpt-4o"
    assert _normalize_model("claude-haiku-4-5") == "claude-haiku-4-5"
    assert _normalize_model("") == ""


def test_estimate_cost_known_model():
    from src.observability.token_logger import _estimate_cost
    cost = _estimate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    # 0.003 * 1 + 0.015 * 0.5 = 0.003 + 0.0075 = 0.0105
    assert cost == pytest.approx(0.0105)


def test_estimate_cost_unknown_model_returns_zero():
    from src.observability.token_logger import _estimate_cost
    assert _estimate_cost("unknown-model", 100, 100) == 0.0


def test_token_logger_emits_event_from_llm_output(monkeypatch):
    from src.observability.token_logger import TokenUsageLogger
    from src.persistence import get_events_repo

    # mock ensure_config — 실 langgraph runtime 없이 user_id/thread_id 박음
    from langchain_core.runnables import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "ensure_config", lambda *a, **kw: {
        "configurable": {
            "thread_id": "t-1",
            "user_id": "u-1",
            "run_id": "r-1",
        }
    })

    response = SimpleNamespace(
        llm_output={
            "model_name": "claude-sonnet-4-6",
            "token_usage": {"prompt_tokens": 200, "completion_tokens": 100},
        },
        generations=[],
    )

    logger = TokenUsageLogger()
    logger.on_llm_end(response)

    events = get_events_repo().list_for_user("u-1")
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "llm_call"
    assert e.thread_id == "t-1"
    assert e.run_id == "r-1"
    assert e.input_tokens == 200
    assert e.output_tokens == 100
    # 0.003 * 0.2 + 0.015 * 0.1 = 0.0006 + 0.0015 = 0.0021
    assert e.cost_usd == pytest.approx(0.0021)
    payload = json.loads(e.payload_json)
    assert payload["model"] == "claude-sonnet-4-6"


def test_token_logger_ctx_fallback_outside_langgraph(monkeypatch):
    """자체 chat_loop 경로 — ensure_config 가 빈 값이어도 생성자 컨텍스트로 귀속.

    회귀 방어(2026-07-13 실사용 테스트 발견): 콜백 시점 ensure_config() 가
    langgraph run 밖에선 {} 라 llm_call 이 전부 NULL 귀속 → 쿼터 무력화됐다.
    """
    from src.observability.token_logger import TokenUsageLogger
    from src.persistence import get_events_repo

    from langchain_core.runnables import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "ensure_config", lambda *a, **kw: {})

    # 스트리밍 집계 shape — usage 는 generations[0][0].message.usage_metadata 에만.
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": 150, "output_tokens": 50},
        response_metadata={"model_name": "claude-haiku-4-5", "stop_reason": "end_turn"},
    )
    response = SimpleNamespace(
        llm_output=None,
        generations=[[SimpleNamespace(generation_info=None, message=msg)]],
    )

    logger = TokenUsageLogger(thread_id="t-loop", user_id="u-loop")
    logger.on_llm_end(response)

    events = get_events_repo().list_for_user("u-loop")
    assert len(events) == 1
    e = events[0]
    assert e.thread_id == "t-loop"
    assert e.input_tokens == 150 and e.output_tokens == 50


def test_token_logger_uses_parent_thread_id(monkeypatch):
    """deep 그래프가 별도 thread에서 돌면 parent_thread_id를 chat thread로 인식."""
    from src.observability.token_logger import TokenUsageLogger
    from src.persistence import get_events_repo

    from langchain_core.runnables import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "ensure_config", lambda *a, **kw: {
        "configurable": {
            "thread_id": "deep-thread-Y",
            "parent_thread_id": "chat-thread-X",
            "user_id": "u-1",
        }
    })

    response = SimpleNamespace(
        llm_output={
            "model_name": "claude-haiku-4-5",
            "token_usage": {"prompt_tokens": 50, "completion_tokens": 25},
        },
        generations=[],
    )
    TokenUsageLogger().on_llm_end(response)

    events = get_events_repo().list_for_user("u-1")
    assert len(events) == 1
    assert events[0].thread_id == "chat-thread-X"   # chat thread로 묶임


def test_usage_miss_is_counted_and_warned(monkeypatch, caplog):
    """usage 미확보는 조용히 넘기지 않는다 — 2026-08-04 감사 C-5.

    사고: 파싱 실패도 usage 미발견도 전부 침묵이라, langchain 응답 스키마가 바뀌면
    llm_call 이벤트가 아예 안 박히고 그 위의 QuotaMiddleware 한도·비용 집계가
    조용히 0 에 수렴했다. 발견 경로 자체가 없었다.
    """
    import logging

    import src.observability.token_logger as tl
    from src.observability.token_logger import TokenUsageLogger, usage_miss_stats

    from langchain_core.runnables import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "ensure_config", lambda *a, **kw: {"configurable": {}})
    # 첫 발생은 무조건 찍히므로 카운터를 초기 상태로 되돌린다.
    monkeypatch.setattr(tl, "_usage_misses", 0)
    monkeypatch.setattr(tl, "_usage_calls", 0)
    monkeypatch.setattr(tl, "_last_miss_log_at", 0.0)

    before = usage_miss_stats()["misses"]
    with caplog.at_level(logging.WARNING, logger="src.observability.token_logger"):
        TokenUsageLogger().on_llm_end(SimpleNamespace(llm_output={}, generations=[]))

    after = usage_miss_stats()
    assert after["misses"] == before + 1
    assert after["calls"] >= 1
    assert any("usage 누락" in r.getMessage() for r in caplog.records), \
        "누락이 로그로 드러나야 한다"


def test_usage_miss_warning_is_rate_limited(monkeypatch, caplog):
    """정상 사유(스트리밍 중단)로도 발생하므로 매번 찍으면 노이즈 — 주기 제한."""
    import logging

    import src.observability.token_logger as tl
    from src.observability.token_logger import TokenUsageLogger

    from langchain_core.runnables import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "ensure_config", lambda *a, **kw: {"configurable": {}})
    monkeypatch.setattr(tl, "_usage_misses", 0)
    monkeypatch.setattr(tl, "_usage_calls", 0)
    monkeypatch.setattr(tl, "_last_miss_log_at", 0.0)
    monkeypatch.setattr(tl, "_MISS_LOG_INTERVAL_S", 3600.0)

    logger = TokenUsageLogger()
    with caplog.at_level(logging.WARNING, logger="src.observability.token_logger"):
        for _ in range(5):
            logger.on_llm_end(SimpleNamespace(llm_output={}, generations=[]))

    warns = [r for r in caplog.records if "usage 누락" in r.getMessage()]
    assert len(warns) == 1, f"주기 내 1회만 찍혀야 하는데 {len(warns)}회"
    assert tl._usage_misses == 5, "로그는 억제해도 카운터는 전부 세야 한다"


def test_token_logger_silent_when_no_usage(monkeypatch):
    """usage metadata 없으면 emit 안 함 (silent)."""
    from src.observability.token_logger import TokenUsageLogger
    from src.persistence import get_events_repo

    from langchain_core.runnables import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "ensure_config", lambda *a, **kw: {
        "configurable": {"user_id": "u-2"}
    })

    response = SimpleNamespace(llm_output={}, generations=[])
    TokenUsageLogger().on_llm_end(response)

    events = get_events_repo().list_for_user("u-2")
    assert len(events) == 0


def test_token_logger_does_not_break_on_exception(monkeypatch):
    """events_repo가 던져도 사용자 흐름 깨지면 안 됨."""
    from src.observability.token_logger import TokenUsageLogger

    def broken_emit(*a, **kw):
        raise RuntimeError("db down")
    import src.observability.token_logger as tl
    monkeypatch.setattr(tl, "get_events_repo", lambda: SimpleNamespace(emit=broken_emit))

    from langchain_core.runnables import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "ensure_config", lambda *a, **kw: {
        "configurable": {"user_id": "u-3"}
    })

    response = SimpleNamespace(
        llm_output={
            "model_name": "claude-sonnet-4-6",
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
        generations=[],
    )
    # 예외 던지지 않아야 함
    TokenUsageLogger().on_llm_end(response)


# ---------------------------------------------------------------------------
# _resolve_user_id — fast(SDK runs) 토큰 귀속 (회귀: user_id=NULL → 조회 0)
# ---------------------------------------------------------------------------
def test_resolve_user_id_priority_and_auth_user():
    from src.observability.token_logger import _resolve_user_id
    from types import SimpleNamespace

    # 1) 명시 user_id 최우선 (deep_runner 경로)
    assert _resolve_user_id({"user_id": "u-explicit",
                             "langgraph_auth_user": SimpleNamespace(identity="other")}) == "u-explicit"

    # 2) fast: langgraph_auth_user 객체(.identity)
    assert _resolve_user_id({"langgraph_auth_user": SimpleNamespace(identity="u-auth")}) == "u-auth"

    # 3) langgraph_auth_user 가 dict 형태여도 해석
    assert _resolve_user_id({"langgraph_auth_user": {"identity": "u-dict"}}) == "u-dict"

    # 4) anonymous/빈값 → None (집계 오염 방지)
    assert _resolve_user_id({"user_id": "anonymous"}) is None
    assert _resolve_user_id({"langgraph_auth_user": SimpleNamespace(identity="anonymous")}) is None
    assert _resolve_user_id({}) is None
