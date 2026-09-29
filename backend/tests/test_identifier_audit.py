"""식별자 대조 감사(2026-09-17) — 답변의 서식·별표 번호 ↔ 이번 턴 근거.

실측 회귀: 같은 품목허가 질의에 허가신청서를 제2호·제1호·공란으로 답했고 근거는
매번 제3호서식이었다. grounding 검증률은 평범(0.57~0.63) — 이 감사만 잡는다.
"""
from src.identifier_audit import audit_identifiers

SRC = ("[9] 의료기기법 시행규칙 [별지 제3호서식] 의료기기 제조(수입) 허가신청서\n"
       "[10] 별지 제15호 서식 기술문서 등 심사의뢰서\n"
       "제출자료의 범위는 별표 7 에 따른다. 별표 1의2 참조.")


def test_flags_form_number_absent_from_sources():
    res = audit_identifiers("허가신청서는 별지 제2호서식 [9], 심사의뢰서는 별지 제15호서식 [10].", SRC)
    assert res["unsupported"] == ["별지 제2호서식"]
    assert "별지 제3호서식" in res["source_forms"]      # 검수자가 정답 후보를 바로 본다


def test_spacing_variants_are_same_identifier():
    assert audit_identifiers("별지 제15호서식과 별지  제 3 호 서식", SRC)["unsupported"] == []


def test_sub_number_is_distinct():
    res = audit_identifiers("별표 1의2 와 별표 1 을 본다.", SRC)
    assert res["unsupported"] == ["별표 1"]             # '1의2' 가 있다고 '1' 이 지지되진 않는다


def test_annex_digit_boundary():
    # 근거의 '별표 7' 이 답변의 '별표 70' 을 지지하면 안 된다.
    assert audit_identifiers("별표 70 참조", SRC)["unsupported"] == ["별표 70"]
    assert audit_identifiers("별표 7 참조", SRC)["unsupported"] == []


def test_placeholder_is_reported():
    res = audit_identifiers("허가신청서(별지 제○호서식)를 제출합니다.", SRC)
    assert res["placeholders"] == ["별지 제○호서식"] and res["unsupported"] == []


def test_no_identifiers_returns_none():
    assert audit_identifiers("의료기기법 제6조에 따라 허가를 받아야 합니다.", SRC) is None


def test_queue_signal():
    from src import review_queue as rq

    base = {"citations_used": 3, "verified_rate": 0.9, "truncated": False}
    assert rq.score_turn(base, feedback=[], claim_audit=None, citation_reported=False,
                         identifier_audit={"unsupported": ["별지 제2호서식"], "placeholders": []}
                         ) == ["identifier_mismatch"]
    assert rq.score_turn(base, feedback=[], claim_audit=None, citation_reported=False,
                         identifier_audit={"unsupported": [], "placeholders": []}) == []
