"""판단 모델 어댑터 — 백엔드 순서·기밀 차단·응답 정리·LLM 폴백 (2026-10-06)."""

from __future__ import annotations

import asyncio

import pytest

from src import judgment as J


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("JUDGE_LOCAL_BASE_URL", "JUDGE_API_URL", "JUDGE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def _q():
    return {"ok": J.Question("답이 쓸 만한가"), "kind": J.Question("종류", choices=["a", "b"])}


def test_coerce_filters_unknown_and_clamps():
    out = J._coerce({"ok": 1.7, "kind": {"a": 0.2, "b": 0.9, "zzz": 1}, "junk": 0.5}, _q())
    assert out == {"ok": 1.0, "kind": {"a": 0.2, "b": 0.9}}
    assert J._coerce({"ok": True}, _q()) == {"ok": 1.0}
    assert J._coerce({"kind": "a"}, _q()) == {}  # 선택지는 dict 여야


def test_order_local_first(monkeypatch):
    monkeypatch.setenv("JUDGE_LOCAL_BASE_URL", "http://local")
    monkeypatch.setenv("JUDGE_API_URL", "http://api")
    monkeypatch.setenv("JUDGE_API_KEY", "k")
    calls = []

    def fake(base, key, state, questions):
        calls.append((base, key))
        return {"ok": 0.8}

    monkeypatch.setattr(J, "_systemone", fake)
    j = asyncio.run(J.judge("상황", _q()))
    assert j.backend == "local" and j.answers == {"ok": 0.8}
    assert calls == [("http://local", "")]


def test_local_failure_falls_to_api(monkeypatch):
    monkeypatch.setenv("JUDGE_LOCAL_BASE_URL", "http://local")
    monkeypatch.setenv("JUDGE_API_URL", "http://api")
    monkeypatch.setenv("JUDGE_API_KEY", "k")

    def fake(base, key, state, questions):
        if "local" in base:
            raise RuntimeError("down")
        return {"ok": 0.3}

    monkeypatch.setattr(J, "_systemone", fake)
    j = asyncio.run(J.judge("상황", _q()))
    assert j.backend == "api" and j.answers["ok"] == 0.3


def test_confidential_never_leaves_premises(monkeypatch):
    """기밀 턴 — 원내가 없으면 상용도 LLM 폴백도 부르지 않는다."""
    monkeypatch.setenv("JUDGE_API_URL", "http://api")
    monkeypatch.setenv("JUDGE_API_KEY", "k")
    called = []
    monkeypatch.setattr(J, "_systemone", lambda *a: called.append("api") or {"ok": 1})

    async def boom(*a, **k):
        called.append("llm"); return {"ok": 1}

    monkeypatch.setattr(J, "_llm_fallback", boom)
    j = asyncio.run(J.judge("상황", _q(), confidential=True))
    assert j.backend == "none" and j.answers == {} and called == []
    assert J.is_available(confidential=True) is False
    monkeypatch.setenv("JUDGE_LOCAL_BASE_URL", "http://local")
    assert J.is_available(confidential=True) is True


def test_llm_fallback_when_nothing_configured(monkeypatch):
    async def fake_llm(state, questions):
        return {"ok": 0.6, "kind": {"a": 0.1, "b": 0.9}}

    monkeypatch.setattr(J, "_llm_fallback", fake_llm)
    j = asyncio.run(J.judge("상황", _q()))
    assert j.backend == "llm" and j.answers["kind"] == {"a": 0.1, "b": 0.9}


def test_empty_inputs_short_circuit(monkeypatch):
    monkeypatch.setattr(J, "_llm_fallback", lambda *a: (_ for _ in ()).throw(AssertionError("called")))
    assert asyncio.run(J.judge("", _q())).backend == "none"
    assert asyncio.run(J.judge("상황", {})).backend == "none"


def test_llm_fallback_parses_prefilled_json(monkeypatch):
    """`{"answers":` 프리필 뒤 `{…}}` 응답 — workflow.join_prefill 교훈 재사용."""
    class _Res:
        content = ' {"ok": 0.75}}'

    class _LLM:
        async def ainvoke(self, msgs):
            return _Res()

    import src.chat_loop as CL
    monkeypatch.setattr(CL, "aux_model", lambda spec, **k: _LLM())
    out = asyncio.run(J._llm_fallback("상황", {"ok": J.Question("q")}))
    assert out == {"ok": 0.75}


def test_llm_fallback_skips_when_aux_model_none(monkeypatch):
    import src.chat_loop as CL
    monkeypatch.setattr(CL, "aux_model", lambda spec, **k: None)
    assert asyncio.run(J._llm_fallback("상황", {"ok": J.Question("q")})) == {}
