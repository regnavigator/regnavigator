"""문서 붙여넣기 입력 회귀 — 2026-08-04 사용자 리포트.

사고: 사용자가 문서를 붙여넣자 "텍스트가 길다"며 실패했다. 원인은 모델 컨텍스트가
아니라 `routes/chat.py` 의 `max_length=8000` 이었다(HTTP 422, 영문 Pydantic 메시지).
채팅 모델 컨텍스트는 1M 이고 대화 압축 트리거도 24,000토큰(≈72,000자)이라 8,000자는
파이프라인 여력 대비 지나치게 작았다.

한도만 올리면 **뒤에서 세 가지가 조용히 깨진다** — 이 파일이 그 세 가지를 잠근다:

① PII NER 은 512토큰 상한 모델이다. 통째로 보내면 뒷부분 이름·주소가 미탐되고,
   클라이언트는 실패를 삼켜 regex-only 로 진행한다 → 문서 뒷부분 PII 가 마스킹 없이
   저장·전송된다. 문서 붙여넣기가 PII 확률이 가장 높은 입력이라 최악의 조합.
② 압축이 "컷 지점 없음"으로 포기해, 붙여넣은 문서가 **이후 모든 턴**에 실렸다.
③ 의도 분류기(0.8B)에 문서를 통째로 보내면 타임아웃 → 안전 기본값 폴백으로 판정 무력화.
"""
from __future__ import annotations

import pytest


# ── ① NER 청킹 ─────────────────────────────────────────────────────────────
def test_long_text_is_split_into_overlapping_chunks(monkeypatch):
    """긴 입력은 통째로 안 보낸다 — 각 청크가 모델 상한 아래여야 한다."""
    from src.guardrail import ner_client

    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")
    monkeypatch.setenv("PII_NER_CHUNK_CHARS", "600")
    monkeypatch.setenv("PII_NER_CHUNK_OVERLAP", "100")

    sent: list[str] = []

    def _fake(text, start, end, timeout=None):
        sent.append(text[start:end])
        return []

    monkeypatch.setattr(ner_client, "_post_chunk", _fake)
    ner_client.detect("가" * 5000)

    assert len(sent) > 1, "긴 입력이 분할되지 않았다"
    assert all(len(c) <= 600 for c in sent), "청크가 상한을 넘었다"
    # 겹침 — 경계에 걸친 이름이 어느 한쪽엔 온전히 들어가야 한다.
    assert sum(len(c) for c in sent) > 5000, "겹침 없이 잘렸다"


def test_chunk_offsets_map_back_to_original_text(monkeypatch):
    """청크 로컬 오프셋이 원문 기준으로 복원돼야 엉뚱한 곳이 마스킹되지 않는다."""
    from src.guardrail import ner_client

    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")
    monkeypatch.setenv("PII_NER_CHUNK_CHARS", "1000")
    monkeypatch.setenv("PII_NER_CHUNK_OVERLAP", "0")

    text = ("가" * 1200) + "홍길동" + ("나" * 500)
    name_at = 1200

    class _Resp:
        status_code = 200

        def raise_for_status(self): ...

        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    def _post(url, json=None, headers=None):
        chunk = json["text"]
        i = chunk.find("홍길동")
        return _Resp({"entities": [
            {"start": i, "end": i + 3, "label": "NAME", "score": 0.9}
        ]} if i >= 0 else {"entities": []})

    monkeypatch.setattr(ner_client, "_client", lambda: type("C", (), {"post": staticmethod(_post)})())
    spans = ner_client.detect(text)

    assert spans, "이름 스팬이 사라졌다"
    hit = [s for s in spans if s["label"] == "NAME"][0]
    assert hit["start"] == name_at and hit["end"] == name_at + 3
    assert text[hit["start"]:hit["end"]] == "홍길동", "오프셋 보정 실패 — 엉뚱한 구간"


def test_partial_chunk_failure_is_logged_not_silent(monkeypatch, caplog):
    """일부 청크가 실패하면 그 구간은 미마스킹이다 — 반드시 경고로 드러나야 한다."""
    import logging

    import httpx

    from src.guardrail import ner_client

    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")
    monkeypatch.setenv("PII_NER_CHUNK_CHARS", "500")
    monkeypatch.setenv("PII_NER_CHUNK_OVERLAP", "0")

    calls = {"n": 0}

    def _flaky(text, start, end, timeout=None):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise httpx.ConnectError("boom")
        return []

    monkeypatch.setattr(ner_client, "_post_chunk", _flaky)
    with caplog.at_level(logging.WARNING, logger="src.guardrail.ner_client"):
        ner_client.detect("가" * 3000)

    assert any("미마스킹" in r.getMessage() for r in caplog.records), \
        "청크 실패가 조용히 넘어갔다 — PII 구멍이 보이지 않는다"


def test_short_text_still_single_request(monkeypatch):
    """대다수 질의는 짧다 — 불필요한 분할/스레드풀 오버헤드가 없어야 한다."""
    from src.guardrail import ner_client

    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")

    calls = []
    monkeypatch.setattr(ner_client, "_post_chunk",
                        lambda t, s, e, timeout=None: calls.append((s, e)) or [])
    ner_client.detect("의료기기 광고 사전심의 알려줘")
    assert len(calls) == 1


# ── ② 입력 한도 ─────────────────────────────────────────────────────────────
def test_limit_is_configurable_and_defaults_to_32k(monkeypatch):
    from src.routes.chat import _max_input_chars

    monkeypatch.delenv("CHAT_MAX_INPUT_CHARS", raising=False)
    assert _max_input_chars() == 32000
    monkeypatch.setenv("CHAT_MAX_INPUT_CHARS", "50000")
    assert _max_input_chars() == 50000


@pytest.mark.parametrize("raw", ["", "  ", "notanumber"])
def test_limit_survives_blank_env(monkeypatch, raw):
    """빈 문자열 env 로 터지지 않는다(프로젝트 관용구)."""
    from src.routes.chat import _max_input_chars

    monkeypatch.setenv("CHAT_MAX_INPUT_CHARS", raw)
    assert _max_input_chars() == 32000


def test_oversize_message_error_is_korean_and_actionable():
    """영문 Pydantic 검증 메시지가 그대로 노출되면 사용자가 뭘 해야 할지 모른다."""
    import time

    import jwt as pyjwt
    from fastapi.testclient import TestClient

    from src.api import app

    secret = "test-secret-32-bytes-min-padding-for-hs256"
    now = int(time.time())
    tok = pyjwt.encode({"sub": "u-1", "email": "a@x.com", "iat": now, "exp": now + 3600},
                       secret, algorithm="HS256")

    import os
    os.environ["NEXTAUTH_SECRET"] = secret
    try:
        res = TestClient(app).post(
            "/chat",
            json={"message": "가" * 50000},
            headers={"Authorization": f"Bearer {tok}"},
        )
    finally:
        os.environ.pop("NEXTAUTH_SECRET", None)

    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, str), "detail 이 Pydantic 오류 배열이면 FE 가 못 읽는다"
    assert "너무 깁니다" in detail and "32,000" in detail


# ── ② 압축 — 붙여넣은 문서가 이후 턴에 계속 실리면 안 된다 ──────────────────
def _state(messages, seqs):
    from src.persistence.threads_repo import ThreadState

    return ThreadState(thread_id="t-1", messages=messages, steps=[],
                       selected_law_keys=[], seqs=seqs)


class _Repo:
    def __init__(self):
        self.saved = None

    def set_summary(self, thread_id, summary, upto):
        self.saved = (thread_id, summary, upto)


@pytest.mark.asyncio
async def test_huge_pasted_doc_is_compacted_on_later_turns(monkeypatch):
    """지난 턴의 문서는 요약으로 대체된다.

    예전엔 human 턴 수가 keep(2) 이하면 '컷 지점 없음'으로 포기해, 붙여넣은 문서가
    이후 모든 턴 컨텍스트에 영구히 실렸다.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    import src.chat_loop as cl

    monkeypatch.setenv("CHAT_SUMMARY_TRIGGER_TOKENS", "1000")
    monkeypatch.setenv("CHAT_SUMMARY_KEEP_TURNS", "2")

    async def _fake_summarize(block, prev):
        return "요약: 사용자가 규제 문서를 붙여넣고 검토를 요청함"

    monkeypatch.setattr(cl, "_summarize_text", _fake_summarize)

    doc = "가" * 30000  # 붙여넣은 문서 (지난 턴)
    msgs = [
        HumanMessage(content=doc),
        AIMessage(content="검토했습니다"),
        HumanMessage(content="그럼 광고 심의는요?"),   # 현재 턴
    ]
    repo = _Repo()
    tail, summary = await cl._maybe_compact(repo, _state(msgs, [1, 2, 3]))

    assert summary and "요약" in summary
    assert repo.saved is not None, "요약 컷 지점이 영속되지 않았다"
    joined = "".join(str(getattr(m, "content", "")) for m in tail)
    assert doc not in joined, "붙여넣은 문서가 여전히 컨텍스트에 실린다"
    assert "그럼 광고 심의는요?" in joined, "현재 턴이 사라졌다"


@pytest.mark.asyncio
async def test_current_turn_document_is_never_summarized(monkeypatch):
    """지금 답해야 할 턴의 문서는 원문 유지 — 요약하면 답변 근거가 사라진다."""
    from langchain_core.messages import HumanMessage

    import src.chat_loop as cl

    monkeypatch.setenv("CHAT_SUMMARY_TRIGGER_TOKENS", "1000")

    async def _boom(block, prev):
        raise AssertionError("현재 턴을 요약하려 했다")

    monkeypatch.setattr(cl, "_summarize_text", _boom)

    doc = "가" * 30000
    tail, summary = await cl._maybe_compact(_Repo(), _state([HumanMessage(content=doc)], [1]))

    assert summary is None
    assert "".join(str(getattr(m, "content", "")) for m in tail) == doc


# ── ③ 의도 분류기 입력 축약 ─────────────────────────────────────────────────
def test_intent_input_keeps_head_and_tail(monkeypatch):
    """질문은 문서 앞이나 뒤에 붙는다 — 앞만 남기면 의도를 놓친다."""
    from src.guardrail import intent_client

    monkeypatch.setenv("INTENT_MAX_INPUT_CHARS", "1000")
    text = "아래 문서 검토해줘\n" + ("가" * 30000) + "\n위 내용 관련 규정 알려줘"
    out = intent_client._condense(text)

    assert len(out) < 1100
    assert "아래 문서 검토해줘" in out, "머리(질문)가 잘렸다"
    assert "위 내용 관련 규정 알려줘" in out, "꼬리(질문)가 잘렸다"


def test_short_intent_input_untouched(monkeypatch):
    from src.guardrail import intent_client

    monkeypatch.delenv("INTENT_MAX_INPUT_CHARS", raising=False)
    q = "의료기기 광고 사전심의 절차 알려줘"
    assert intent_client._condense(q) == q


# ── ④ PII 보장 — 스캔이 불완전하면 통과시키지 않는다 ────────────────────────
def test_incomplete_ner_scan_blocks_instead_of_leaking(monkeypatch):
    """이름·주소는 NER 이 유일한 방어선 — 못 덮은 구간이 있으면 차단해야 한다.

    예전엔 경고만 찍고 원문을 통과시켰다(fail-open). 그러면 마스킹 안 된 이름이
    DB 에 저장되고 Anthropic 으로 나간다. 되돌릴 수 없는 유출이다.
    """
    from src.guardrail import gate, ner_client

    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")
    monkeypatch.delenv("PII_GATE_STRICT", raising=False)
    # 스캔 불완전(complete=False)
    monkeypatch.setattr(ner_client, "detect_spans", lambda t: ([], False))

    with pytest.raises(gate.PiiScanIncomplete):
        gate.scrub_input("담당자 홍길동 관련 규정 문의")


def test_strict_off_restores_legacy_fail_open(monkeypatch, caplog):
    """끌 수는 있어야 한다 — 다만 그 선택이 로그로 남아야 한다."""
    import logging

    from src.guardrail import gate, ner_client

    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")
    monkeypatch.setenv("PII_GATE_STRICT", "0")
    monkeypatch.setattr(ner_client, "detect_spans", lambda t: ([], False))

    with caplog.at_level(logging.ERROR, logger="src.guardrail.gate"):
        out, _ = gate.scrub_input("담당자 홍길동")
    assert out  # 통과
    assert any("불완전" in r.getMessage() for r in caplog.records)


def test_at_rest_scrub_does_not_swallow_the_block(monkeypatch):
    """chat_loop 의 광범위 except 가 차단을 삼키면 fail-open 이 부활한다."""
    import src.chat_loop as cl
    from src.guardrail.gate import PiiScanIncomplete

    monkeypatch.delenv("PII_GATE_DISABLE", raising=False)

    def _boom(_t, collect=None):
        raise PiiScanIncomplete("검사 미완료")

    monkeypatch.setattr(cl, "scrub_input", _boom)
    with pytest.raises(PiiScanIncomplete):
        cl._scrub_user_text("담당자 홍길동")


def test_egress_scrub_does_not_swallow_the_block(monkeypatch):
    """egress backstop 도 마찬가지 — 원문이 LLM 으로 나가면 안 된다."""
    from langchain_core.messages import HumanMessage

    import src.chat_loop as cl
    from src.guardrail.gate import PiiScanIncomplete

    monkeypatch.delenv("PII_GATE_DISABLE", raising=False)

    def _boom(_c):
        raise PiiScanIncomplete("검사 미완료")

    monkeypatch.setattr(cl, "_scrub_content", _boom)
    with pytest.raises(PiiScanIncomplete):
        cl._egress_scrub([HumanMessage(content="담당자 홍길동")])
