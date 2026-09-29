"""doc_kinds 단일 진실원 가드 (2026-08-25).

사고: admrul_attach 편입(8/24) 때 **툴 스키마 enum 만** 갱신되고 chat 검증
화이트리스트·보고서 커버리지 게이트는 빠졌다. 모델이 그 종별을 요청하면
필터에서 탈락 → None(기본 검색) 폴백 → 급여기준 코퍼스가 조용히 미검색.
`guide`(7/24 편입)도 커버리지 게이트에선 같은 이유로 죽어 있었다.

이 테스트는 세 지점이 갈라지는 순간 실패한다.
"""
from __future__ import annotations

from src.chat_loop import TOOL_SPECS
from src.coverage import ALLOWED_KINDS
from src.tools.search import (
    ALLOWED_DOC_KINDS,
    DOC_KIND_LABELS,
    sanitize_doc_kinds,
)


def _schema_enum() -> list[str]:
    for spec in TOOL_SPECS:
        fn = spec.get("function") or {}
        if fn.get("name") == "qdrant_search":
            return (fn["parameters"]["properties"]["doc_kinds"]
                    ["items"]["enum"])
    raise AssertionError("qdrant_search 툴 스펙 없음")


def test_tool_schema_enum_matches_whitelist():
    """LLM 에게 제시하는 종별 == 서버가 통과시키는 종별."""
    assert set(_schema_enum()) == set(ALLOWED_DOC_KINDS)


def test_coverage_gate_shares_whitelist():
    """보고서 커버리지 게이트도 같은 집합(따로 들고 있으면 드리프트)."""
    assert set(ALLOWED_KINDS) == set(ALLOWED_DOC_KINDS)


def test_known_kinds_present():
    """편입된 코퍼스가 빠지지 않았는지 — 회귀 대상 명시."""
    for kind in ("law", "admrul", "ordin", "prec", "expc",
                 "guide", "admrul_attach"):
        assert kind in ALLOWED_DOC_KINDS, f"{kind} 누락"
        assert kind in DOC_KIND_LABELS, f"{kind} 라벨 누락"


def test_sanitize_keeps_valid_drops_unknown():
    assert sanitize_doc_kinds(["admrul_attach"]) == ["admrul_attach"]
    assert sanitize_doc_kinds(["law", "guide"]) == ["law", "guide"]
    assert sanitize_doc_kinds(["없는종별"]) is None
    assert sanitize_doc_kinds([]) is None
    assert sanitize_doc_kinds(None) is None
    # 비문자열·중복 방어
    assert sanitize_doc_kinds(["law", "law", 3, None]) == ["law"]


def test_labels_used_for_step_label():
    """화면 라벨도 같은 사전에서 — '법령 벡터 검색'으로 오표기되던 것 방지."""
    assert DOC_KIND_LABELS["admrul_attach"] == "행정규칙 첨부"
