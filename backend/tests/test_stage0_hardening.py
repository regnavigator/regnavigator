"""단계 0 — 손실 중일 수 있던 것 4건의 회귀 고정 (2026-10-02 감사).

각 항목은 "고치기 전 상태"를 재현하면 **실패**해야 한다. 테스트가 결함을 설명한다.
"""

from __future__ import annotations

import logging
import threading

import pytest

# ── 0-3 평가 집계: 라벨 0 질의는 분모에서 빠진다 ─────────────────────────


def test_unlabeled_query_is_excluded_not_zero():
    """라벨 0 질의가 hit@k·precision@k 에 0점으로 들어가면 지표가 바닥에 붙는다.

    감사 실측: 183 중 69(37.7%)가 라벨 0 → 보고된 hit@3 0.54 는 실제 ≈0.87.
    """
    from src.eval.metrics import aggregate, evaluate_query

    labeled = evaluate_query(["a", "b"], ["a"], ks=(1,))
    unlabeled = evaluate_query(["a", "b"], [], ks=(1,))

    assert labeled["hit@1"] == 1.0
    assert unlabeled["hit@1"] is None
    assert unlabeled["precision@1"] is None
    assert unlabeled["mrr"] is None

    agg = aggregate([labeled, unlabeled])
    # 종전: (1.0 + 0.0) / 2 = 0.5 로 과소보고. 지금: 라벨 있는 것만 → 1.0
    assert agg["hit@1"] == 1.0


# ── 0-4 검색 세마포어: 무한 대기 금지 ────────────────────────────────────


def test_search_wait_has_upper_bound(monkeypatch):
    """슬롯이 안 비면 거절한다 — 종전 무한 대기는 스레드풀을 고갈시켰다."""
    from src.retrieval import search_api_client as C

    monkeypatch.setenv("SEARCH_WAIT_TIMEOUT_S", "0.05")
    monkeypatch.setenv("RAG_SEARCH_API_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("RAG_SEARCH_API_KEY", "x")
    # 1슬롯짜리 세마포어를 **이미 점유된 채** 심는다
    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    monkeypatch.setattr(C, "_SEARCH_SEM", sem)
    C._search_cache.clear() if hasattr(C._search_cache, "clear") else None

    with pytest.raises(C.SearchApiError, match="혼잡"):
        C.search_articles("무한 대기 테스트 질의", top_k=1)
    sem.release()


# ── 0-5 PII 게이트: NER 미설정은 조용히 통과하지 않는다 ────────────────────


def test_missing_ner_blocks_under_strict(monkeypatch):
    """키 하나 빠지면 fail-closed 가 fail-open 으로 뒤집히던 것을 막는다."""
    from src.guardrail import gate, ner_client

    monkeypatch.setattr(ner_client, "is_available", lambda: False)
    monkeypatch.setenv("PII_GATE_STRICT", "1")
    monkeypatch.setenv("PII_GATE_ALLOW_NO_NER", "0")

    with pytest.raises(gate.PiiScanIncomplete):
        gate.scrub_input("환자 홍길동 씨의 진료기록")


def test_missing_ner_allowed_only_when_explicit(monkeypatch):
    """dev 는 명시 플래그로만 연다 — 묵시 통과 금지."""
    from src.guardrail import gate, ner_client

    monkeypatch.setattr(ner_client, "is_available", lambda: False)
    monkeypatch.setenv("PII_GATE_STRICT", "1")
    monkeypatch.setenv("PII_GATE_ALLOW_NO_NER", "1")

    out, _ = gate.scrub_input("문의드립니다")
    assert out == "문의드립니다"


def test_readyz_reports_missing_ner_as_down(monkeypatch):
    """`/readyz` 가 미설정을 ok 로 보고하면 운영 알림이 영영 안 간다."""
    from src.routes import health

    monkeypatch.delenv("PII_NER_API_URL", raising=False)
    monkeypatch.delenv("PII_NER_API_KEY", raising=False)
    monkeypatch.setenv("PII_GATE_ALLOW_NO_NER", "0")
    ok, detail = health._check_pii_ner()
    assert ok is False
    assert "미설정" in (detail or "")

    monkeypatch.setenv("PII_GATE_ALLOW_NO_NER", "1")
    ok, _ = health._check_pii_ner()
    assert ok is True


# ── 0-2 로깅: 앱 info 가 실제로 어딘가에 찍힌다 ───────────────────────────


def test_logging_setup_installs_root_handler(monkeypatch):
    """root 핸들러가 없으면 `_log.info` 276곳이 전부 lastResort 로 소멸한다."""
    from src.logging_setup import setup_logging

    root = logging.getLogger()
    saved = root.handlers[:]
    saved_level = root.level
    try:
        root.handlers.clear()
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup_logging()
        assert root.handlers, "root 핸들러가 설치되지 않았다"
        assert root.level == logging.DEBUG
        fmt = root.handlers[0].formatter
        assert fmt is not None and "%(levelname)" in fmt._fmt
    finally:
        root.handlers[:] = saved
        root.setLevel(saved_level)
