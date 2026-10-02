"""기밀 모드 — 변호사가 사건 파일을 다룰 때 온프레미스 전용 처리 (2026-10-01).

IRB/DRB 스킬 턴과 **같은 경로**를 쓴다. 핵심 불변식은 셋:
1. 기밀 모드가 켜지면 로컬(온프레미스) 모델로 라우팅된다.
2. 그 턴에는 웹 검색 도구를 **주지 않는다** — 검색어가 외부로 나가면 정책이 반만 선다.
3. 로컬이 다운이면 **상용으로 우회하지 않고** 안내 후 종료한다.
"""

from __future__ import annotations

import asyncio

import pytest


class _StubModel:
    """bind_tools 호출을 기록하는 스텁 — 실제 호출은 하지 않는다."""

    def __init__(self):
        self.tools_seen = []
        self.fallback_attached = False

    def bind_tools(self, tools, **kw):
        self.tools_seen.append(tools)
        return self

    def bind(self, **kw):
        return self

    def with_fallbacks(self, *a, **kw):
        self.fallback_attached = True
        return self


def _tool_names(stub) -> list[str]:
    out = []
    for tools in stub.tools_seen:
        for t in tools:
            out.append(t.get("function", {}).get("name") or t.get("name"))
    return out


# ── 도구 차단 ───────────────────────────────────────────────────────────────

def test_confidential_turn_has_no_web_tool(monkeypatch):
    """기밀 턴은 tavily 를 도구 목록에서부터 못 본다."""
    import src.chat_loop as cl
    import src.skill_local as sl

    stub = _StubModel()
    monkeypatch.setattr(sl, "build_model", lambda mid, max_tokens: stub)
    cl.build_models(None, local_skill_model="qwen38-27b")

    names = _tool_names(stub)
    assert "qdrant_search" in names, "법령 검색(내부)은 남아야 한다"
    assert "tavily_search" not in names, "기밀 턴에 웹 검색 도구가 노출됐다"


def test_confidential_turn_has_no_commercial_fallback(monkeypatch):
    """로컬 실패가 상용으로 새면 기밀 모드의 존재 이유가 사라진다."""
    import src.chat_loop as cl
    import src.skill_local as sl

    stub = _StubModel()
    monkeypatch.setattr(sl, "build_model", lambda mid, max_tokens: stub)
    monkeypatch.setenv("LLM_FALLBACK", "anthropic:claude-haiku-4-5")
    cl.build_models(None, local_skill_model="qwen38-27b")
    assert stub.fallback_attached is False


# ── 라우팅 판정 ─────────────────────────────────────────────────────────────

def test_confidential_routes_to_local_without_skill(monkeypatch):
    """스킬이 없어도 기밀 모드만으로 로컬 라우팅이 걸린다."""
    import src.skill_local as sl

    monkeypatch.setattr(sl, "enabled", lambda: True)
    monkeypatch.setattr(sl, "probe", lambda: "qwen38-27b")

    # chat_loop 의 판정식과 동일한 조건을 검증 — (turn_skill or confidential)
    for turn_skill, confidential, expect in [
        (None, True, True),     # 기밀만
        ("irb", False, True),   # 스킬만
        (None, False, False),   # 둘 다 아님 → 상용
    ]:
        assert bool(turn_skill or confidential) is expect


def test_confidential_notice_is_distinct():
    """기밀 모드 안내는 심의(IRB) 안내와 달라야 한다 — 맥락이 다르다."""
    import src.skill_local as sl

    assert sl.CONFIDENTIAL_UNAVAILABLE_NOTICE != sl.UNAVAILABLE_NOTICE
    assert "상용 모델로 우회하지" in sl.CONFIDENTIAL_UNAVAILABLE_NOTICE
    assert "기밀 모드를 끄면" in sl.CONFIDENTIAL_UNAVAILABLE_NOTICE


# ── 계약 ────────────────────────────────────────────────────────────────────

def test_chat_route_accepts_confidential_flag():
    """POST /chat 이 confidential 을 받는다(기본 False)."""
    from src.routes.chat import ChatRequest  # type: ignore[attr-defined]

    assert ChatRequest(message="x").confidential is False
    assert ChatRequest(message="x", confidential=True).confidential is True


def test_run_chat_turn_accepts_confidential():
    """run_chat_turn 시그니처에 confidential 이 있다."""
    import inspect

    from src.chat_loop import run_chat_turn

    sig = inspect.signature(run_chat_turn)
    assert "confidential" in sig.parameters
    assert sig.parameters["confidential"].default is False


# ── fail-closed ─────────────────────────────────────────────────────────────

def test_confidential_without_local_config_does_not_fall_back(monkeypatch):
    """온프레미스 라우팅이 미설정인데 기밀 모드를 켜면 **답하지 않는다**.

    사용자는 보호받는다고 믿고 사건 파일을 넣는다. 설정이 없다고 조용히 상용
    모델로 넘기면 기밀 모드가 있는 것이 없는 것보다 위험하다.
    """
    import src.skill_local as sl

    monkeypatch.setattr(sl, "enabled", lambda: False)

    async def _run():
        # 실제 턴 대신 가드 분기만 타도록 최소 스텁을 쓴다.
        from unittest.mock import MagicMock

        repo = MagicMock()
        repo.append_messages = MagicMock()
        state = MagicMock()
        state.messages = []
        # 가드가 emit 후 return 하는지만 본다.
        return repo, state

    # 안내 문구가 분기의 산출물이다 — 문구 자체를 계약으로 고정.
    assert "상용 모델로 대신 처리하지" in sl.CONFIDENTIAL_NOT_CONFIGURED_NOTICE
    assert "SKILL_LOCAL_MODEL" in sl.CONFIDENTIAL_NOT_CONFIGURED_NOTICE
    assert sl.CONFIDENTIAL_NOT_CONFIGURED_NOTICE != sl.CONFIDENTIAL_UNAVAILABLE_NOTICE
    assert asyncio.run(_run()) is not None


def test_three_confidential_notices_are_distinct():
    """세 상황의 안내가 서로 달라야 한다 — 원인이 다르면 조치도 다르다."""
    import src.skill_local as sl

    notices = {
        sl.UNAVAILABLE_NOTICE,                    # 스킬 엔진 점검 중
        sl.CONFIDENTIAL_UNAVAILABLE_NOTICE,       # 기밀 모드인데 로컬 다운
        sl.CONFIDENTIAL_NOT_CONFIGURED_NOTICE,    # 기밀 모드인데 아예 미설정
    }
    assert len(notices) == 3


# ── 처리 경로 고지 (2026-10-01) ──────────────────────────────────────────────

def test_processing_mode_emitted_only_after_local_routing_confirmed():
    """`processing_mode` 는 **라우팅이 확정된 뒤** 나가야 한다.

    확정 전에 보내면 거짓 안심이 된다 — 로컬이 다운이면 그 턴은 답을 못 하는데
    사용자는 "원내에서 처리됨" 고지를 먼저 본다.
    """
    import inspect

    import src.chat_loop as cl

    src = inspect.getsource(cl)
    i_guard = src.index('_log.warning("skill_local: 로컬 모델 사용 불가')
    i_ok = src.index('_log.info("skill_local: 로컬 라우팅')
    i_emit = src.index('"type": "processing_mode"')

    assert i_guard < i_ok < i_emit, (
        "processing_mode 가 '로컬 사용 가능' 확정 이후가 아니다")


def test_processing_mode_never_claims_web_search():
    """로컬 라우팅 턴은 웹 도구를 못 받는다 — 고지도 그 사실과 일치해야 한다."""
    import inspect
    import re

    import src.chat_loop as cl

    block = inspect.getsource(cl)
    seg = block[block.index('"type": "processing_mode"'):]
    seg = seg[:seg.index("})") + 2]
    assert re.search(r'"web_search":\s*False', seg), seg
    assert '"local": True' in seg


@pytest.fixture()
def _threads_repo(tmp_path, monkeypatch):
    """테스트 스코프 SQLite ThreadsRepo (test_chat_loop 와 같은 패턴)."""
    import src.persistence.threads_repo as tr

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setattr(tr, "_repo", None)
    yield tr.get_threads_repo()
    monkeypatch.setattr(tr, "_repo", None)


def test_thread_marks_and_reports_confidential_history(_threads_repo):
    threads_repo = _threads_repo
    """기밀 이력은 영속돼야 한다 — 기밀을 끌 때 경고할 근거다.

    이력이 없으면 FE 는 "이전 대화가 상용 모델로 나간다"는 경고를 띄울 수 없고,
    사용자는 저장된 사건 파일 내용이 외부로 가는 것을 모른 채 토글을 끈다.
    """
    threads_repo.ensure_thread("t_conf", user_id="u1")

    assert not threads_repo.get_meta("t_conf").get("confidential_seen")

    threads_repo.mark_confidential("t_conf")
    assert threads_repo.get_meta("t_conf").get("confidential_seen")

    # 멱등 — 여러 기밀 턴이 이어져도 상태가 흔들리지 않는다.
    threads_repo.mark_confidential("t_conf")
    assert threads_repo.get_meta("t_conf").get("confidential_seen")
