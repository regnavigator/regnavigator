"""서식 → 즉시 기입 문서(form_intake) 회귀 (2026-08-27).

[이 서식으로 작성]이 심층 보고서 파이프라인을 타던 걸 끊어낸 경로다. 여기가
조용히 망가지면 사용자는 다시 "서식을 눌렀는데 보고서가 돈다"를 겪는다.
관보 서식 본문은 표가 박스문자로 평탄화돼 오므로, 그 모양을 그대로 픽스처로 둔다.
"""

from src.form_intake import (
    _BASELINE_FIELDS,
    build_skeleton,
    fields_from_text,
    intake,
)

# 의료기기법 시행규칙 [별지 제1호서식] 본문의 실제 모양(발췌).
FORM_TEXT = """■ 의료기기법 시행규칙 [별지 제1호서식] <개정 2025. 4. 1.>

                의료기기 제조(수입)업 허가신청서

────────┬────┬──────────────────┬────────────
 접수번호  │접수일   │발급일    │처리기간  25일
────────┴────┴──────────────────┴────────────
───────┬───────────────────────┬─────────────
 신청인  │성명(한글)              │(한자)
 (대표자) ├───────────────────────┴─────────────
        │법인등록번호 또는 주민등록번호
───────┴─────────────────────────────────────
 제조(수입) │명칭(상호)
        │소재지
 품질책임자 │성명            │주민등록번호
        │자격 구분
 첨부서류  │뒤쪽 참조
 수수료   │144,000원
"""


def test_fields_come_from_the_form_itself():
    """LLM 없이 서식 본문만으로 기입 항목이 나온다."""
    fields = fields_from_text(FORM_TEXT)
    assert "성명(한글)" in fields
    assert "소재지" in fields
    # 접속사 `또는` 의 `는` 을 조사로 오인해 탈락시키면 안 된다.
    assert "법인등록번호 또는 주민등록번호" in fields


def test_office_only_cells_are_not_fields():
    """접수번호·발급일·처리기간은 관청 기입란 — 민원인 칸으로 띄우면 안 된다."""
    fields = fields_from_text(FORM_TEXT)
    for noise in ("접수번호", "접수일", "발급일", "처리기간 25일"):
        assert noise not in fields


def test_stops_before_submission_guidance():
    """첨부서류·수수료 뒤는 제출 안내지 기입란이 아니다."""
    fields = fields_from_text(FORM_TEXT)
    assert not any("뒤쪽" in f or "144,000" in f for f in fields)


def test_skeleton_uses_the_shared_marker_contract():
    """`[확인 필요: X]` — doc_fill·/documents/fill·원본 서식 기입이 보는 계약.
    이게 바뀌면 하위 경로가 전부 조용히 빈손이 된다."""
    body = build_skeleton("서식명", ["성명", "주소"])
    assert "[확인 필요: 성명]" in body
    assert "[확인 필요: 주소]" in body

    from src.doc_fill import extract_unfilled_fields

    assert extract_unfilled_fields(body) == ["성명", "주소"]


def test_intake_never_returns_empty():
    """라벨을 하나도 못 뽑아도 화면은 떠야 한다 — 빈 문서는 사용자에게
    '아무 일도 안 일어남'으로 보인다."""
    fields, body = intake("알 수 없는 서식", "")
    assert fields == _BASELINE_FIELDS
    assert "[확인 필요:" in body


def test_partial_export_keeps_unfilled_markers():
    """다 안 채워도 내보낼 수 있어야 한다(2026-08-27 사용자 요구).

    미기입 칸은 **비우는 게 아니라** `[확인 필요: X]` 표시로 남긴다 — 빈칸으로
    내보내면 검토자가 '작성 안 한 칸'과 '원래 빈 칸'을 구분하지 못한다.
    내보내기를 막는 게이트가 생기면 여기서 걸린다.
    """
    from src.doc_fill import apply_filled_values

    fields, body = intake("서식", "", form_path=None)
    out = apply_filled_values(body, {fields[0]: "홍길동"})
    assert "홍길동" in out
    for f in fields[1:]:
        assert f"[확인 필요: {f}]" in out
    # 하나도 안 채운 상태도 그대로 통과한다(빈 서식 내보내기).
    assert apply_filled_values(body, {}) == body
