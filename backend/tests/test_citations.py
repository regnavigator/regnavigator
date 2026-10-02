"""Citation extractor 2종 테스트 — extract_web_citation / extract_rag_citation.

spec: 02_INTERFACE.md §2.2, 06_SKILLS.md M5a / M5b
"""

from __future__ import annotations

from types import SimpleNamespace


from src.tools.search import (
    _publisher_from_url,
    build_citation_from_api_hit,
    extract_rag_citation,
    extract_web_citation,
)


# ---------------------------------------------------------------------------
# extract_web_citation
# ---------------------------------------------------------------------------
def test_extract_web_basic():
    result = {
        "title": "식약처 광고 가이드라인",
        "url": "https://www.mfds.go.kr/path/to/page",
        "content": "광고 시 다음 사항을 표시해야 한다.",
    }
    c = extract_web_citation(result, 1)
    assert c["number"] == 1
    assert c["source_kind"] == "web"
    assert c["title"] == "식약처 광고 가이드라인"
    assert c["url"] == "https://www.mfds.go.kr/path/to/page"
    assert c["publisher"] == "식품의약품안전처"  # 도메인 매핑
    assert c["status"] == "active"
    assert c["snippet"].startswith("광고 시")
    assert c["id"].startswith("cite_web_")


def test_extract_web_same_url_same_id():
    """같은 URL 두 번 추출 시 동일 id."""
    r = {"title": "x", "url": "https://example.com/path", "content": "snippet"}
    c1 = extract_web_citation(r, 1)
    c2 = extract_web_citation(r, 5)
    assert c1["id"] == c2["id"]
    assert c1["number"] == 1
    assert c2["number"] == 5  # number는 순서대로


def test_extract_web_unknown_publisher_returns_none():
    r = {"title": "x", "url": "https://random-blog.tistory.com/123", "content": ""}
    c = extract_web_citation(r, 1)
    assert c["publisher"] is None


# ---------------------------------------------------------------------------
# R1·R2 — verified · doc_category (BACKEND_REQUESTS.md)
# ---------------------------------------------------------------------------
def test_web_verified_true_for_known_publisher():
    r = {"title": "고시", "url": "https://www.mfds.go.kr/x", "content": ""}
    c = extract_web_citation(r, 1)
    assert c["verified"] is True


def test_web_verified_false_for_unknown_publisher():
    r = {"title": "블로그", "url": "https://blog.naver.com/x", "content": ""}
    c = extract_web_citation(r, 1)
    assert c["verified"] is False


def test_web_doc_category_from_law_go_kr():
    r = {"title": "법령", "url": "https://www.law.go.kr/lsInfoP.do?id=...", "content": ""}
    c = extract_web_citation(r, 1)
    assert c.get("doc_category") == "법령"


def test_web_doc_category_omitted_when_unknown():
    r = {"title": "x", "url": "https://example.com", "content": ""}
    c = extract_web_citation(r, 1)
    assert "doc_category" not in c


def test_extract_web_snippet_truncated_at_300():
    long = "a" * 1000
    r = {"title": "x", "url": "https://example.com", "content": long}
    c = extract_web_citation(r, 1)
    assert len(c["snippet"]) == 300


def test_publisher_from_url_table():
    assert _publisher_from_url("https://www.mfds.go.kr/x") == "식품의약품안전처"
    assert _publisher_from_url("https://www.law.go.kr/y") == "법제처"
    assert _publisher_from_url("https://hira.or.kr/z") == "건강보험심사평가원"
    assert _publisher_from_url("https://random.com") is None


def test_extract_web_missing_title_falls_back_to_url():
    r = {"url": "https://example.com/page", "content": ""}
    c = extract_web_citation(r, 1)
    assert c["title"] == "https://example.com/page"


# ---------------------------------------------------------------------------
# extract_rag_citation
# ---------------------------------------------------------------------------
def _point(payload: dict):
    return SimpleNamespace(payload=payload)


def test_extract_rag_active():
    p = _point({
        "chunk_id": "law_med_device_act#0042",
        "title": "의료기기법",
        "publisher": "보건복지부",
        "published_at": "2020-01-01",
        "amended_at": "2024-03-15",
        "doc_id": "law_med_device_act",
        "article": "제45조",
        "page": 32,
        "text": "의료기기 광고는 식약처장의 사전심의를 받아야 한다.",
    })
    c = extract_rag_citation(p, 1)
    assert c["number"] == 1
    assert c["source_kind"] == "doc"
    assert c["title"] == "의료기기법"
    assert c["doc_id"] == "law_med_device_act"
    assert c["article"] == "제45조"
    assert c["page"] == 32
    assert c["date"] == "2024-03-15"  # amended가 우선
    assert c["status"] == "active"
    assert c["id"] == "cite_doc_law_med_device_act#0042"


def test_extract_rag_revoked():
    p = _point({
        "chunk_id": "old#1",
        "title": "구 법령",
        "text": "...",
        "revoked_at": "2023-01-01",
    })
    c = extract_rag_citation(p, 1)
    assert c["status"] == "revoked"


def test_extract_rag_amended_pending():
    p = _point({
        "chunk_id": "x#1",
        "title": "곧 개정",
        "text": "...",
        "amended_pending_until": "2026-12-31",
    })
    c = extract_rag_citation(p, 1)
    assert c["status"] == "amended_pending"


def test_extract_rag_published_when_no_amended():
    p = _point({
        "chunk_id": "x#1",
        "title": "x",
        "text": "x",
        "published_at": "2020-05-01",
    })
    c = extract_rag_citation(p, 1)
    assert c["date"] == "2020-05-01"


def test_extract_rag_dict_input_works_too():
    """payload 속성 없는 dict도 그대로 처리."""
    raw = {"chunk_id": "x#1", "title": "x", "text": "x"}
    c = extract_rag_citation(raw, 1)
    assert c["title"] == "x"
    assert c["id"] == "cite_doc_x#1"


def test_extract_rag_snippet_truncated():
    long = "본문 " * 200
    p = _point({"chunk_id": "x#1", "title": "x", "text": long})
    c = extract_rag_citation(p, 1)
    assert len(c["snippet"]) == 300


# ---------------------------------------------------------------------------
# R1·R2·R4 — RAG citation 확장 (BACKEND_REQUESTS.md)
# ---------------------------------------------------------------------------
def test_rag_verified_default_true():
    p = _point({"chunk_id": "x#1", "title": "법령", "text": "x", "source_kind": "law"})
    c = extract_rag_citation(p, 1)
    assert c["verified"] is True


def test_rag_doc_category_law():
    p = _point({"chunk_id": "x#1", "title": "법", "text": "x", "source_kind": "law"})
    c = extract_rag_citation(p, 1)
    assert c["doc_category"] == "법령"


def test_rag_doc_category_rule_maps_to_법령():
    p = _point({"chunk_id": "x#1", "title": "x", "text": "x", "source_kind": "rule"})
    c = extract_rag_citation(p, 1)
    assert c["doc_category"] == "법령"


def test_rag_doc_category_guideline_maps_to_행정규칙():
    p = _point({"chunk_id": "x#1", "title": "x", "text": "x", "source_kind": "guideline"})
    c = extract_rag_citation(p, 1)
    assert c["doc_category"] == "행정규칙"


def test_rag_doc_category_omitted_for_unknown_source_kind():
    p = _point({"chunk_id": "x#1", "title": "x", "text": "x", "source_kind": "weird"})
    c = extract_rag_citation(p, 1)
    assert "doc_category" not in c


def test_rag_court_extracted_for_case():
    p = _point({
        "chunk_id": "case#1",
        "title": "대법원 2020.8.28. 선고 2017헌가35 판결",
        "text": "x",
        "source_kind": "case",
    })
    c = extract_rag_citation(p, 1)
    assert c["court"] == "대법원"
    assert c["instance"] == 3


def test_rag_court_omitted_for_non_case():
    p = _point({
        "chunk_id": "x#1", "title": "대법원 판례 인용 의료기기법", "text": "x",
        "source_kind": "law",   # 본문에 '대법원' 있어도 source_kind=law이면 추출 안 함
    })
    c = extract_rag_citation(p, 1)
    assert "court" not in c
    assert "instance" not in c


def test_rag_constitutional_court_extracted():
    p = _point({
        "chunk_id": "ccourt#1",
        "title": "헌법재판소 2020헌가35 결정",
        "text": "x",
        "source_kind": "constitutional",
    })
    c = extract_rag_citation(p, 1)
    assert c["court"] == "헌법재판소"
    assert c["instance"] == 3


# ---------------------------------------------------------------------------
# build_citation_from_api_hit (openlaw-etl /search API hit → Citation)
# ---------------------------------------------------------------------------
def _hit(**over):
    h = {
        "article_key": "013476_0022001", "law_id": "013476", "mst_id": "013476",
        "law_title": "의료기기산업 육성 및 혁신의료기기 지원법", "article_num": "제22조",
        "article_title": "허가특례", "target_type": "law", "chunk_type": "article",
        "attachment_subtype": None, "attachment_link": None,
        "article_url": "https://www.law.go.kr/법령/x/제22조",
        "enforcement_date": "2026-07-01", "is_current": True,
        "department": "보건복지부", "snippet": "① 혁신의료기기를 제조하거나 …",
    }
    h.update(over)
    return h


def test_api_hit_citation_basic():
    c = build_citation_from_api_hit(_hit(), 3)
    assert c["id"] == "cite_doc_013476_0022001"
    assert c["number"] == 3
    assert c["source_kind"] == "doc"
    assert "제22조" in c["title"]
    assert c["article"] == "제22조"
    assert c["publisher"] == "보건복지부"
    assert c["date"] == "2026-07-01"
    assert c["url"] == "https://www.law.go.kr/법령/x/제22조"
    assert c["status"] == "active"
    assert c["verified"] is True
    assert c["doc_category"] == "법령"


def test_api_hit_citation_revoked_when_not_current():
    c = build_citation_from_api_hit(_hit(is_current=False), 1)
    assert c["status"] == "revoked"


# amend_status(ETL lawdangle enrich) → citation.status 매핑.
def test_api_hit_amend_status_mapping():
    assert build_citation_from_api_hit(_hit(amend_status="repealed"), 1)["status"] == "revoked"
    assert build_citation_from_api_hit(_hit(amend_status="renamed"), 1)["status"] == "amended_pending"
    # current 는 is_current=False(낡은 payload)여도 active — enrich 가 더 신선.
    assert build_citation_from_api_hit(
        _hit(amend_status="current", is_current=False), 1)["status"] == "active"
    # unknown/미존재 → is_current 폴백 (기존 계약).
    assert build_citation_from_api_hit(_hit(amend_status="unknown"), 1)["status"] == "active"
    assert build_citation_from_api_hit(
        _hit(amend_status=None, is_current=False), 1)["status"] == "revoked"


def test_api_hit_pending_not_revoked():
    """시행예정(pending: 공포·시행일 미도래) — 폐지 오표기 금지.

    시행예정 법령은 ETL 이 is_current 를 null 로 주므로, pending 을 폴백에
    흘리면 revoked 가 된다(lawdangle 0.3.1 이 잡은 오판의 소비층 재발 방지)."""
    c = build_citation_from_api_hit(_hit(amend_status="pending", is_current=None), 1)
    assert c["status"] == "amended_pending"
    assert c["status"] != "revoked"


def test_api_hit_citation_attachment_download_url():
    c = build_citation_from_api_hit(_hit(
        chunk_type="attachment", attachment_subtype="별표",
        attachment_link="https://www.law.go.kr/dl/별표1.hwp",
    ), 1)
    assert c["download_url"] == "https://www.law.go.kr/dl/별표1.hwp"


def test_api_hit_citation_prec_court():
    # 판례 문서형 — 사건명(article_title)에 법원이 있으면 R4 추출.
    c = build_citation_from_api_hit(_hit(
        target_type="prec", law_title="판례", article_num="본문",
        article_title="대법원 2020.8.28. 선고 2017다35 판결",
        chunk_type="article",
    ), 1)
    assert c.get("court") == "대법원"
