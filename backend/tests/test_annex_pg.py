"""별표·서식 PG 조회 — article_key 세그먼트 파서 회귀.

Neo4j 에 Attachment 노드가 적재돼 있지 않아(2026-07-10 라이브: 0건) /annex 계열이
전부 miss 였다 → PG fallback(pg_client.{list,fetch}_attachments_pg) 도입.
키 포맷: `{law_id}_{NNNN}{BB}{E|F}_attachment` (NNNN=번호, BB=가지, E=별표/F=서식).
"""
from __future__ import annotations

from src.retrieval.pg_client import parse_annex_num, parse_annex_segment


def test_parse_annex_segment_byl():
    # 의료기기법 시행규칙 별표 1 (등급분류 기준)
    assert parse_annex_segment("009740_000100E_attachment") == (1, 0, "별표")
    # 별표 19의2
    assert parse_annex_segment("006364_001902E_attachment") == (19, 2, "별표")


def test_parse_annex_segment_form():
    # 서식 (F suffix)
    assert parse_annex_segment("009740_000100F_attachment") == (1, 0, "서식")


def test_parse_annex_segment_invalid():
    assert parse_annex_segment("009740_0015001") is None  # 일반 조문 키
    assert parse_annex_segment("") is None
    assert parse_annex_segment("009740_00010XE_attachment") is None


def test_parse_annex_num():
    assert parse_annex_num("19") == (19, 0)
    assert parse_annex_num("19의2") == (19, 2)
    assert parse_annex_num(" 1 ") == (1, 0)
    assert parse_annex_num("별표") is None
    assert parse_annex_num("") is None
