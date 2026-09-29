"""mongo_client 본문 추출 — 항/호/목 중첩 평탄화 회귀.

법령 조문은 조문 → 항 → 호 → 목 중첩. 기존 _extract_law_body 가 항내용만
긁어 호("다음 각 호의 사항")가 빠지던 회귀(의료기기법 제24조) 방지.
"""
from __future__ import annotations

from src.retrieval.mongo_client import _extract_law_body, _flatten_clauses


def test_flatten_hang_ho_mok():
    hangs = [
        {"항내용": "① 다음 각 호의 사항을 적어서는 아니 된다",
         "호": [
             {"호내용": "1. 거짓 효능"},
             {"호내용": "2. 과장 광고",
              "목": [{"목내용": "가. 세부 가목"}]},
         ]},
        {"항내용": "② 다른 항"},
    ]
    out = _flatten_clauses(hangs)
    assert out == [
        "① 다음 각 호의 사항을 적어서는 아니 된다",
        "1. 거짓 효능",
        "2. 과장 광고",
        "가. 세부 가목",
        "② 다른 항",
    ]


def test_extract_law_body_includes_ho():
    raw = {
        "법령": {"조문": {"조문단위": [
            {"조문번호": "24", "조문제목": "기재 및 광고의 금지 등",
             "조문내용": "제24조(기재 및 광고의 금지 등)",
             "항": [
                 {"항내용": "① ... 다음 각 호의 사항을 ... 아니 된다",
                  "호": [{"호내용": "1. 거짓·과대 효능"},
                         {"호내용": "2. 오인 우려 표시"}]},
             ]},
        ]}}
    }
    body = _extract_law_body(raw, "제24조")
    assert body is not None
    # 항내용 + 호내용 모두 포함(이전엔 호 빠짐)
    assert "각 호의 사항" in body
    assert "1. 거짓·과대 효능" in body
    assert "2. 오인 우려 표시" in body


def test_extract_law_body_no_hang_still_works():
    """항 없는 단순 조문 — 회귀 없이 동작."""
    raw = {"법령": {"조문": {"조문단위": [
        {"조문번호": "1", "조문제목": "목적", "조문내용": "이 법은 ..."},
    ]}}}
    body = _extract_law_body(raw, "제1조")
    assert body and "이 법은" in body


def test_extract_law_body_skips_section_header_unit():
    """절 시작 조문 회귀(의료기기법 제15조) — 장·절 헤더 유닛(조문여부="전문")은
    다음 조와 같은 조문번호를 갖고 배열상 앞에 온다. 첫 매칭 반환이던 기존
    로직이 본문 대신 "제2절 수입업"만 돌려줬음."""
    raw = {"법령": {"조문": {"조문단위": [
        {"조문번호": "15", "조문여부": "전문",
         "조문내용": "                          제2절 수입업"},
        {"조문번호": "15", "조문여부": "조문", "조문제목": "수입업허가 등",
         "조문내용": "제15조(수입업허가 등)",
         "항": [{"항내용": "① 의료기기의 수입을 업으로 하려는 자는 ..."}]},
    ]}}}
    body = _extract_law_body(raw, "제15조")
    assert body is not None
    assert "수입업허가" in body
    assert "① 의료기기의 수입" in body
    assert "제2절" not in body


def test_extract_law_body_branch_number():
    """제N조의M — M은 조문번호가 아니라 조문가지번호 필드. 미반영 시
    제15조의2 요청이 항상 miss(또는 제15조와 오매칭)."""
    raw = {"법령": {"조문": {"조문단위": [
        {"조문번호": "15", "조문여부": "조문", "조문제목": "수입업허가 등",
         "조문내용": "제15조(수입업허가 등)"},
        {"조문번호": "15", "조문가지번호": "2", "조문여부": "조문",
         "조문제목": "희소ㆍ긴급도입 필요 의료기기",
         "조문내용": "제15조의2(희소ㆍ긴급도입 필요 의료기기)"},
    ]}}}
    body = _extract_law_body(raw, "제15조의2")
    assert body is not None and "희소" in body
    # 가지 없는 제15조도 여전히 정확히 매칭
    body15 = _extract_law_body(raw, "제15조")
    assert body15 is not None and "수입업허가" in body15 and "희소" not in body15


def test_flatten_empty_or_none():
    assert _flatten_clauses(None) == []
    assert _flatten_clauses([]) == []
    assert _flatten_clauses("문자열") == []  # 스칼라 루트는 무시(list/dict만 노드)
    # 단, 리스트 안의 스칼라 항목은 텍스트로 수집
    assert _flatten_clauses(["직접 문자열"]) == ["직접 문자열"]
