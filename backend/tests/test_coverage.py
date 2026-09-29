"""커버리지 게이트(#6) — 2층 규칙·3층 판정 파서."""
from __future__ import annotations

from src.coverage import (
    covered_kinds,
    explicit_gap_searches,
    parse_judge_output,
)


def _steps_with(categories: list[str]) -> list[dict]:
    return [{
        "id": "s1",
        "citations": [
            {"id": f"c{i}", "number": i + 1, "title": f"t{i}",
             "doc_category": cat, "snippet": "..."}
            for i, cat in enumerate(categories)
        ],
    }]


def test_covered_kinds_maps_categories_and_web():
    steps = _steps_with(["법령", "판례"])
    steps[0]["citations"].append(
        {"id": "w1", "number": 9, "source_kind": "web", "title": "web"})
    assert covered_kinds(steps) == {"law", "prec", "web"}


def test_explicit_gap_prec_expc_when_uncovered():
    # "판례, 유권해석" 명시 — 법령만 수집됨 → prec·expc 겨냥 검색 2건
    out = explicit_gap_searches("비대면진료 판례, 유권해석 알려줘", {"law"})
    assert len(out) == 2
    kinds = [s["doc_kinds"][0] for s in out]
    assert set(kinds) == {"prec", "expc"}
    assert all(s["lane"] == "qdrant" for s in out)


def test_explicit_gap_skips_covered_kind():
    out = explicit_gap_searches("비대면진료 판례 알려줘", {"prec"})
    assert out == []


def test_explicit_gap_web_lane_for_gov_project():
    out = explicit_gap_searches("의료기기 정부과제 공고 알려줘", set())
    assert out and out[0]["lane"] == "web"


def test_explicit_gap_no_keyword_no_gap():
    assert explicit_gap_searches("의료기기 광고 사전심의 절차", {"law"}) == []


def test_parse_judge_valid_and_fenced():
    raw = '{"sufficient": false, "gaps": ["급여 기준"], "searches": [{"lane": "qdrant", "query": "요양비 급여 기준", "doc_kinds": ["admrul"]}]}'
    v = parse_judge_output(raw)
    assert v and v["sufficient"] is False
    assert v["searches"][0]["doc_kinds"] == ["admrul"]
    fenced = f"```json\n{raw}\n```"
    assert parse_judge_output(fenced) is not None


def test_parse_judge_invalid_returns_none():
    assert parse_judge_output("죄송합니다, 판단이 어렵습니다.") is None
    assert parse_judge_output('{"nope": 1}') is None
    assert parse_judge_output("") is None


def test_parse_judge_clamps_and_filters():
    raw = (
        '{"sufficient": false, "gaps": [], "searches": ['
        '{"lane": "qdrant", "query": "a", "doc_kinds": ["prec", "bogus"]},'
        '{"lane": "web", "query": "b"},'
        '{"lane": "qdrant", "query": "c"}]}'
    )
    v = parse_judge_output(raw)
    assert v is not None
    assert len(v["searches"]) == 2  # ≤2 클램프
    assert v["searches"][0]["doc_kinds"] == ["prec"]  # bogus 종별 필터


# ── 종별 매핑 드리프트 방지 (2026-09-10 응집도 점검) ──────────────────
# 배경: `coverage._KIND_BY_CATEGORY` 는 `citations._OPENLAW_CATEGORY_BY_TARGET_TYPE`
# 의 역방향인데 **손으로 복제**돼 있었고, 조약·헌재결정례·행정심판례·가이드라인
# 4종이 빠진 채 드리프트했다. `covered_kinds()` 는 매핑 실패를 조용히 건너뛰므로
# (`if k:`) 가이드라인 근거만 있는 턴이 "커버리지 0" 으로 집계돼 불필요한 추가
# 검색을 유발했다. 파생으로 바꿨고, 이 테스트가 되돌아가는 것을 막는다.
def test_kind_by_category_covers_every_source_category():
    from src.coverage import _KIND_BY_CATEGORY
    from src.tools.citations import _OPENLAW_CATEGORY_BY_TARGET_TYPE as FWD

    missing = [c for c in FWD.values() if c not in _KIND_BY_CATEGORY]
    assert not missing, f"역방향 매핑 누락 — 손으로 복제하지 말 것: {missing}"
    # 왕복 일관성: kind -> category -> kind
    for kind, cat in FWD.items():
        assert _KIND_BY_CATEGORY[cat] == kind, f"{cat} 왕복 불일치"


def test_searchable_kinds_are_reachable_from_citations():
    """검색 가능한 종별인데 인용에서 역매핑이 안 되면 영원히 '미커버'로 남는다."""
    from src.coverage import _KIND_BY_CATEGORY
    from src.tools.search import ALLOWED_DOC_KINDS

    reachable = set(_KIND_BY_CATEGORY.values())
    # admrul_attach(행정규칙 첨부)는 표시용 doc_category 가 따로 없어 제외.
    unreachable = ALLOWED_DOC_KINDS - reachable - {"admrul_attach"}
    assert not unreachable, f"인용으로 커버 판정이 불가능한 검색 종별: {unreachable}"


def test_guideline_citation_counts_as_covered():
    """실제 결함 재현 — 식약처 가이드라인 근거가 커버리지에 잡혀야 한다."""
    from src.coverage import covered_kinds

    steps = [{
        "tool_name": "qdrant_search",
        "citations": [{"source_kind": "doc", "doc_category": "가이드라인",
                       "id": "c1", "number": 1}],
    }]
    assert "guide" in covered_kinds(steps)
