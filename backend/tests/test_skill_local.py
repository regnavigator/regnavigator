"""IRB/DRB 스킬 턴 로컬 라우팅 + 보고서 양보 (2026-08-28).

핵심 불변식:
1. 로컬 다운이면 **상용 폴백 없이** 안내 후 턴 종료 — 유출 정책이 시간대에
   따라 구멍 나지 않는다.
2. 로컬 경로 모델엔 LLM_FALLBACK 이 붙지 않는다(build_models 로컬 분기).
3. 대화형 touch 후 보고서 report_yield 가 대기하고, HOLD 경과 후 풀린다.
"""
from __future__ import annotations

import asyncio
import json

import pytest

BUNDLE = "src/skills/medireg_irb_drb"


# ── llm_priority ──────────────────────────────────────────────────────────

def test_report_yield_noop_without_touch(monkeypatch):
    import src.llm_priority as prio

    monkeypatch.setattr(prio, "_last_touch", 0.0)
    assert asyncio.run(prio.report_yield()) == 0.0


def test_report_yield_waits_then_releases(monkeypatch):
    import src.llm_priority as prio

    monkeypatch.setenv("REPORT_YIELD_HOLD_S", "0.3")
    monkeypatch.setenv("REPORT_YIELD_MAX_S", "5")
    prio.touch()
    waited = asyncio.run(prio.report_yield())
    # HOLD(0.3s) 지나면 자연 해소 — 카운터 누수 없이 시간으로 풀린다.
    assert 0.0 < waited < 3.0
    assert not prio.interactive_recent()


def test_report_yield_max_cap(monkeypatch):
    """대화형이 계속 touch 돼도 상한에서 보고서가 재개된다(기아 방지)."""
    import src.llm_priority as prio

    monkeypatch.setenv("REPORT_YIELD_HOLD_S", "60")
    monkeypatch.setenv("REPORT_YIELD_MAX_S", "1")
    prio.touch()
    waited = asyncio.run(prio.report_yield())
    assert waited < 4.0  # 60s HOLD 인데 1s 상한이 이겼다
    monkeypatch.setattr(prio, "_last_touch", 0.0)  # 다른 테스트 오염 방지


# ── build_models 로컬 분기 — 상용 폴백 미부착 ────────────────────────────

class _StubModel:
    def __init__(self):
        self.bound = []
        self.tools_seen = []
        self.fallbacks_attached = False

    def bind_tools(self, tools, **kw):
        self.bound.append(kw)
        self.tools_seen.append(tools)
        return self

    def with_fallbacks(self, _):
        self.fallbacks_attached = True
        return self


def test_build_models_local_has_no_commercial_fallback(monkeypatch):
    import src.chat_loop as cl
    import src.skill_local as sl

    stub = _StubModel()
    monkeypatch.setattr(sl, "build_model", lambda mid, max_tokens: stub)
    # LLM_FALLBACK 이 설정돼 있어도 로컬 분기엔 절대 붙으면 안 된다.
    monkeypatch.setenv("LLM_FALLBACK", "anthropic:claude-sonnet-4-6")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    normal, forced, forced_web, forced_skill = cl.build_models(
        None, skill_tools=[{"name": "load_skill"}],
        local_skill_model="qwen38-27b")
    assert normal is stub and forced_skill is stub
    assert stub.fallbacks_attached is False
    # forced 바인딩은 qdrant/load_skill 2종만 — tavily 는 로컬 턴에서 제외한다
    # (2026-09-10: 모델만 원내로 옮기고 웹 도구를 열어두면 검색어가 외부로 나가
    #  정책이 반만 선다). forced_web 자리도 None.
    choices = [kw.get("tool_choice") for kw in stub.bound]
    assert {"qdrant_search", "load_skill"} <= set(filter(None, choices))
    assert "tavily_search" not in set(filter(None, choices))
    assert forced_web is None


def test_local_skill_turn_has_no_web_tool(monkeypatch):
    """온프레미스 스킬 턴은 tavily 를 **도구 목록에서부터** 못 본다.

    강제 게이트만 막으면 모델이 자발적으로 호출하는 경로가 남는다 — 도구 자체를
    주지 않아야 닫힌다. 이 보장이 깨지면 "답변을 만드는 AI 는 원내에서만" 이라는
    사용자 고지가 흔들린다(뉴스레터·개인정보처리방침 §5).
    """
    import src.chat_loop as cl
    import src.skill_local as sl

    stub = _StubModel()
    monkeypatch.setattr(sl, "build_model", lambda mid, max_tokens: stub)
    cl.build_models(None, skill_tools=[{"name": "load_skill"}],
                    local_skill_model="qwen38-27b")

    names = []
    for tools in stub.tools_seen:
        for t in tools:
            names.append(t.get("function", {}).get("name") or t.get("name"))
    assert "qdrant_search" in names, "법령 검색(내부)은 남아야 한다"
    assert "tavily_search" not in names, "웹 검색 도구가 로컬 턴에 노출됐다"


def test_commercial_turn_still_has_web_tool(monkeypatch):
    """스킬 턴이 아니면 웹 검색은 그대로 — 차단 범위가 번지지 않았는지."""
    import src.chat_loop as cl

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("LLM_FALLBACK", raising=False)
    _, _, forced_web, _ = cl.build_models("anthropic:claude-haiku-4-5")
    assert forced_web is not None


# ── chat_loop: 로컬 다운 → 안내 후 종료(상용 무호출) ─────────────────────

def _clear_persistence_caches():
    from src import persistence as P

    for f in (P.get_users_repo, P.get_events_repo, P.get_reports_repo,
              P.get_feedback_repo, P.get_report_runs_repo, P.get_blob_store):
        f.cache_clear()


@pytest.fixture()
def threads_repo(tmp_path, monkeypatch):
    import src.persistence.threads_repo as tr

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setattr(tr, "_repo", None)
    _clear_persistence_caches()
    yield tr.get_threads_repo()
    monkeypatch.setattr(tr, "_repo", None)
    _clear_persistence_caches()


def test_local_down_notice_and_no_commercial_call(threads_repo, monkeypatch):
    import src.skill_local as sl
    from src.chat_loop import run_chat_turn

    monkeypatch.setenv("CHAT_GROUNDING_GATE_DISABLE", "1")
    monkeypatch.delenv("PII_NER_API_URL", raising=False)
    monkeypatch.setenv("INTENT_SEARCH_DISABLE", "1")
    monkeypatch.setenv("SKILL_BUNDLE_DIR", BUNDLE)
    monkeypatch.setenv("SKILL_LOCAL_MODEL", "1")
    monkeypatch.setenv("SKILL_LOCAL_BASE_URL", "http://127.0.0.1:9")  # 죽은 주소
    monkeypatch.setattr(sl, "probe", lambda: None)

    async def _run():
        return [ev async for ev in run_chat_turn(
            "t_local1", "IRB 심의 면제 대상인가요?", user_id="u@x")]

    events = asyncio.run(_run())
    done = events[-1]
    assert done["type"] == "done"
    assert "점검" in done["text"]  # 안내문 — 상용 모델 무호출로 즉시 종료

    state = threads_repo.get_state("t_local1")
    assert [m.type for m in state.messages] == ["human", "ai"]
    assert "점검" in state.messages[-1].content


def test_skill_local_disabled_keeps_flow(monkeypatch):
    """스위치 off(기본)면 enabled() False — 기존 흐름 완전 동일 보장의 전제."""
    import src.skill_local as sl

    monkeypatch.delenv("SKILL_LOCAL_MODEL", raising=False)
    monkeypatch.setenv("REPORT_WRITER_BASE_URL", "http://x")
    assert sl.enabled() is False
    monkeypatch.setenv("SKILL_LOCAL_MODEL", "1")
    assert sl.enabled() is True
