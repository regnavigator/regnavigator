"""별표 vs 서식 구분 — 기입 버튼이 뜨는 조건 (2026-10-01).

인용이 "별표"(기준표)인지 "서식"(빈 양식)인지에 따라 [이 서식으로 작성] 노출이
갈린다. 검색 API 는 `attachment_subtype` 으로 정확히 알려주는데, 종전에는 그 값을
버리고 제목에 '서식' 글자가 있는지로 추측했다.
"""

from __future__ import annotations


# ── 별표/서식 구분 (2026-10-01) ──────────────────────────────────────────────

def test_citation_carries_attachment_subtype():
    """검색 API 가 아는 "별표/서식" 구분을 인용에 실어 보낸다.

    실사용 신고: `공중위생관리법 시행규칙 별표: 영업신고서` 는 **서식**인데 제목에
    '서식' 글자가 없어, 제목 추측에만 의존하던 FE 가 별표로 보고 [이 서식으로 작성]
    을 숨겼다. 서버가 아는 값을 버리면 안 된다.
    """
    from src.tools.citations import build_citation_from_api_hit

    hit = {
        "article_key": "006358_000100F_attachment",
        "law_id": "006358",
        "law_title": "공중위생관리법 시행규칙",
        "article_num": "별표",
        "article_title": "영업신고서",
        "target_type": "law",
        "chunk_type": "attachment",
        "attachment_subtype": "서식",
        "snippet": "영업신고서 …",
    }
    cit = build_citation_from_api_hit(hit, 1)
    assert cit.get("attachment_subtype") == "서식"
    # 카테고리는 종전 계약 그대로 — FE 의 별표서식 분기가 깨지면 안 된다.
    assert cit.get("doc_category") == "법령별표서식"


def test_citation_omits_subtype_for_plain_article():
    """일반 조문에는 붙지 않는다 — 없는 키가 붙으면 FE 분기가 흔들린다."""
    from src.tools.citations import build_citation_from_api_hit

    cit = build_citation_from_api_hit({
        "article_key": "004097_0025001",
        "law_id": "004097",
        "law_title": "식품위생법 시행령",
        "article_num": "제25조",
        "target_type": "law",
        "chunk_type": "article",
        "attachment_subtype": None,
    }, 1)
    assert "attachment_subtype" not in cit
