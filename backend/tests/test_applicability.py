"""적용가능성 판정 — 규칙이 못 잡는 몫 (2026-10-02).

LLM 판정이라 "무엇을 거르는가"는 테스트할 수 없다. 대신 **고장 났을 때 어떻게
되는가**를 고정한다 — 이 계층의 실패는 항상 '덜 거름'이어야 한다.
"""

from __future__ import annotations

import asyncio

from src import applicability as A


def _cits(n):
    return [{"number": i, "title": f"법 {i}", "snippet": "본문", "id": f"c{i}"}
            for i in range(1, n + 1)]


def _run(coro):
    return asyncio.run(coro)


class _Model:
    def __init__(self, text):
        self.text = text

    async def ainvoke(self, _msgs):
        class R:
            content = self.text
        return R()


def _patch(monkeypatch, text):
    # 2026-10-03: applicability 는 이제 `chat_loop.aux_model` 경유(기밀 턴이면
    # 원내/생략). 비기밀 기본 경로는 chat_loop 가 import 한 build_chat_model 을 쓴다.
    monkeypatch.setattr("src.chat_loop.build_chat_model",
                        lambda *a, **k: _Model(text))


def test_drops_named_numbers(monkeypatch):
    _patch(monkeypatch, '{"drop": [2], "why": {"2": "적용 대상 다름"}}')
    out = _run(A.judge("카페를 열려면 무슨 신고가 필요한가요", _cits(5)))
    assert out == {2: "적용 대상 다름"}


def test_malformed_json_drops_nothing(monkeypatch):
    """형식을 어기면 아무것도 거르지 않는다 — 근거를 날리는 것보다 낫다."""
    _patch(monkeypatch, "음... 2번은 좀 아닌 것 같은데요")
    assert _run(A.judge("카페를 열려면 무슨 신고가 필요한가요", _cits(5))) == {}


def test_unknown_numbers_ignored(monkeypatch):
    """목록에 없는 번호를 지목하면 무시한다(환각 방어)."""
    _patch(monkeypatch, '{"drop": [99, 3]}')
    out = _run(A.judge("카페를 열려면 무슨 신고가 필요한가요", _cits(5)))
    assert set(out) == {3}


def test_mass_drop_is_discarded(monkeypatch):
    """'다 빼라'는 판정이 아니라 고장이다 — 통째로 버린다."""
    _patch(monkeypatch, '{"drop": [1,2,3,4,5,6,7,8]}')
    assert _run(A.judge("카페를 열려면 무슨 신고가 필요한가요", _cits(8))) == {}


def test_llm_failure_drops_nothing(monkeypatch):
    class _Boom:
        async def ainvoke(self, _m):
            raise RuntimeError("down")
    monkeypatch.setattr("src.models.build_chat_model", lambda *a, **k: _Boom())
    assert _run(A.judge("카페를 열려면 무슨 신고가 필요한가요", _cits(5))) == {}


def test_skipped_for_short_question(monkeypatch):
    _patch(monkeypatch, '{"drop": [1]}')
    assert _run(A.judge("카페", _cits(5))) == {}


def test_skipped_when_too_few_citations(monkeypatch):
    """근거가 적으면 거를 여유가 없다."""
    _patch(monkeypatch, '{"drop": [1]}')
    assert _run(A.judge("카페를 열려면 무슨 신고가 필요한가요", _cits(2))) == {}


def test_disable_knob(monkeypatch):
    monkeypatch.setenv("APPLICABILITY_JUDGE_DISABLE", "1")
    _patch(monkeypatch, '{"drop": [1]}')
    assert _run(A.judge("카페를 열려면 무슨 신고가 필요한가요", _cits(5))) == {}


def test_judge_sync_refuses_inside_running_loop(monkeypatch):
    """루프 안에서 잘못 불리면 물러난다 — 있으면 좋은 판정이지 필수가 아니다."""
    _patch(monkeypatch, '{"drop": [1]}')

    async def _inner():
        return A.judge_sync("카페를 열려면 무슨 신고가 필요한가요", _cits(5))

    assert asyncio.run(_inner()) == {}
