"""무인용 사실 audit — 파싱·지표 순수 함수 검증(Phase 1).

LLM 호출부는 제외(라이브) — JSON 파싱(`_parse_audit`)과 지표(`claim_groundedness`)만.
"""

from src.grounding import _parse_audit
from src.eval.metrics import claim_groundedness


def test_parse_audit_basic():
    raw = (
        '설명... [{"claim":"수수료 30만원","verdict":"contradicted"},'
        '{"claim":"제19조","verdict":"supported"},'
        '{"claim":"14일 이내","verdict":"unverified"}] 끝'
    )
    out = _parse_audit(raw)
    assert len(out) == 3
    assert out[0] == {"claim": "수수료 30만원", "verdict": "contradicted"}
    assert {o["verdict"] for o in out} == {"contradicted", "supported", "unverified"}


def test_parse_audit_rejects_bad_verdict_and_empty():
    raw = '[{"claim":"x","verdict":"maybe"},{"claim":"","verdict":"supported"}]'
    assert _parse_audit(raw) == []  # 화이트리스트 밖 + 빈 claim 제거


def test_parse_audit_malformed_returns_empty():
    assert _parse_audit("JSON 아님") == []
    assert _parse_audit("") == []


def test_parse_audit_handles_block_list_content():
    """Anthropic content 가 block list 로 와도 처리."""
    raw = [{"type": "text", "text": '[{"claim":"1577-1255","verdict":"supported"}]'}]
    out = _parse_audit(raw)
    assert out == [{"claim": "1577-1255", "verdict": "supported"}]


def test_claim_groundedness_rates():
    audited = [
        {"claim": "a", "verdict": "supported"},
        {"claim": "b", "verdict": "supported"},
        {"claim": "c", "verdict": "contradicted"},
        {"claim": "d", "verdict": "unverified"},
    ]
    m = claim_groundedness(audited)
    assert m["total"] == 4 and m["supported"] == 2
    assert m["supported_rate"] == 0.5
    assert m["unsupported_rate"] == 0.5  # (1 contradicted + 1 unverified)/4


def test_claim_groundedness_empty():
    m = claim_groundedness([])
    assert m["total"] == 0 and m["supported_rate"] is None
