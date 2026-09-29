"""시행 상태 노출(2026-08-16) — 모델 컨텍스트 마커 + citation 필드.

배경: 검색 결과가 모델에 `[n] 제목 + 본문` 으로만 실려, **시행 예정·구법 조문을
현행처럼 단정**했다(규제 상담에서 답의 유효성을 뒤집는 오류). 비현행 근거에만
마커를 붙이고, citation 에는 원본 라벨을 실어 FE 가 정확히 배지한다.

핵심 불변식: **미시행(공포됐으나 시행일 미도래) ≠ 폐지**. is_current 폴백이
이 둘을 뭉개면 '시행 예정'이 '폐지'로 표시된다.
"""
from __future__ import annotations

from src.tools.citations import build_citation_from_api_hit
from src.tools.search import _effective_marker, _format_rag_hits


def _hit(**kw) -> dict:
    base = {
        "article_key": "009514_0006001", "law_id": "009514",
        "law_title": "의료기기법", "article_num": "제6조",
        "article_title": "제조업의 허가", "target_type": "law",
        "chunk_type": "article", "snippet": "제조업자는 …", "is_current": True,
    }
    base.update(kw)
    return base


# ── 마커(모델 컨텍스트) ────────────────────────────────────────────────────

def test_current_article_has_no_marker():
    """현행은 무표기 — 매 줄 붙으면 노이즈이고 토큰만 늘어난다."""
    assert _effective_marker(_hit(effective_status="시행중"), {}) == ""
    assert _effective_marker(_hit(), {}) == ""


def test_pending_enforcement_marked_with_date():
    m = _effective_marker(
        _hit(effective_status="미시행", enforcement_date="2026-09-01"), {})
    assert "시행 예정" in m and "2026-09-01" in m and "효력" in m


def test_pending_without_date_still_marked():
    assert "시행 예정" in _effective_marker(_hit(effective_status="미시행"), {})


def test_enforced_false_is_pending_not_repealed():
    """enforced=False 는 '아직 효력 없음' — 폐지로 말하면 안 된다."""
    m = _effective_marker(_hit(enforced=False, enforcement_date="2027-01-01"), {})
    assert "시행 예정" in m and "폐지" not in m


def test_superseded_marked():
    assert _effective_marker(_hit(effective_status="구법"), {}) == "구법(현행 아님)"


def test_unknown_is_current_false_is_hedged_not_repealed():
    """상태 라벨이 없고 is_current 만 False 면 단정하지 않는다."""
    assert _effective_marker(_hit(is_current=False), {}) == "현행 여부 확인 필요"


def test_meta_overrides_payload():
    """pinned 경로는 PG meta 가 진실원 — meta 값이 우선."""
    m = _effective_marker(_hit(effective_status="시행중"),
                          {"effective_status": "구법"})
    assert m == "구법(현행 아님)"


def test_format_rag_hits_appends_marker_only_when_not_current():
    text = _format_rag_hits([
        (1, _hit(), None),
        (2, _hit(article_key="x_2", effective_status="미시행",
                 enforcement_date="2026-09-01"), None),
    ])
    lines = [ln for ln in text.splitlines() if ln.startswith("[")]
    assert "⚠️" not in lines[0]
    assert "⚠️" in lines[1] and "2026-09-01" in lines[1]


# ── citation 필드(FE 배지) ────────────────────────────────────────────────

def test_citation_pending_status_and_labels():
    c = build_citation_from_api_hit(_hit(effective_status="미시행",
                                     enforced=False), number=1)
    assert c["status"] == "amended_pending"      # 폐지(revoked) 아님
    assert c["effective_status"] == "미시행"
    assert c["enforced"] is False


def test_citation_superseded_is_revoked():
    c = build_citation_from_api_hit(_hit(effective_status="구법"), number=1)
    assert c["status"] == "revoked"


def test_citation_current_active():
    c = build_citation_from_api_hit(_hit(effective_status="시행중"), number=1)
    assert c["status"] == "active" and c["effective_status"] == "시행중"


def test_amend_status_still_wins():
    """law.go.kr enrich(폐지 확정)가 있으면 그쪽이 우선 — 기존 계약 유지."""
    c = build_citation_from_api_hit(
        _hit(amend_status="repealed", effective_status="시행중"), number=1)
    assert c["status"] == "revoked"


def test_citation_omits_labels_when_absent():
    c = build_citation_from_api_hit(_hit(), number=1)
    assert "effective_status" not in c and "enforced" not in c
