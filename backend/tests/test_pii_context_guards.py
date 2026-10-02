"""PII 문맥 보정 2종(2026-08-16) — 도로명 꼬리 확장 · 자기소개 이름 마스킹.

KoELECTRA modu-ner 의 알려진 한계 보정:
① 도로명이 AF 라벨로 나와 주소가 시·군·구까지만 마스킹 → [주소] 스팬 우측
   도로명+번지 꼬리 흡수.
② 희귀 이름 미탐('최다온입니다'·'독고영재'→TM) → 자기소개 정형 문맥에서
   성씨 게이트 결정적 마스킹.
둘 다 **오탐이 더 큰 사고**였던 도메인이므로(제도 용어 마스킹 인시던트),
네거티브 케이스를 포지티브만큼 촘촘히 고정한다.
"""
from __future__ import annotations

from src.guardrail.gate import (
    _apply_spans,
    _contextual_name_scrub,
    _extend_address_end,
    scrub_input,
)


# ── ① 도로명 꼬리 확장 ────────────────────────────────────────────────────

def test_address_span_extends_over_road_and_number():
    text = "서울 성동구 성수이로 113-1 3층에 사무실이 있어요"
    spans = [{"start": 0, "end": 6, "label": "LC", "text": "서울 성동구"}]
    out, cats = _apply_spans(text, spans)
    assert "[주소]에 사무실이 있어요" == out
    assert cats == ["주소"]


def test_address_span_ending_in_road_extends_number_only():
    text = "대구 중구 테헤란로 123, 4층 방문 예정"
    spans = [{"start": 0, "end": 10, "label": "LC", "text": "대구 중구 테헤란로"}]
    out, _ = _apply_spans(text, spans)
    assert out == "[주소] 방문 예정"


def test_address_not_extended_over_legal_text():
    """주소 스팬 뒤가 법령 문구면 확장 금지 — 규제 콘텐츠 보호."""
    text = "서울 강남구 의료기기법 시행규칙 별표 3 확인"
    spans = [{"start": 0, "end": 6, "label": "LC", "text": "서울 강남구"}]
    out, _ = _apply_spans(text, spans)
    assert out == "[주소] 의료기기법 시행규칙 별표 3 확인"


def test_road_particle_alone_never_masked():
    """'회의로 5명' 류 — 주소 스팬이 없으면 도로명 규칙은 발동하지 않는다."""
    text = "회의로 5명이 모여 GMP 심사로 3건을 처리"
    out, cats = _apply_spans(text, [])
    assert out == text and cats == []


def test_extend_address_end_helper():
    text = "서울 성동구 왕십리로 222 한양대"
    assert _extend_address_end(text, 6, "서울 성동구") == len("서울 성동구 왕십리로 222")


# ── ② 자기소개 이름 마스킹 (성씨 게이트) ─────────────────────────────────

def test_intro_rare_name_masked():
    out, cats = _contextual_name_scrub("안녕하세요 최다온입니다. 임상 문의드려요")
    assert out.startswith("안녕하세요 [이름]입니다")
    assert cats == ["이름"]


def test_intro_compound_surname_masked():
    out, _ = _contextual_name_scrub("저는 독고영재입니다")
    assert out == "저는 [이름]입니다"


def test_intro_name_with_rago_masked():
    out, _ = _contextual_name_scrub("김지원이라고 합니다"[:0] + "저는 김지원이라고 합니다")
    assert out == "저는 [이름]이라고 합니다"


def test_intro_role_nouns_not_masked():
    for s in ("저는 의사입니다", "저는 한국인입니다", "저는 신입입니다",
              "저는 최선입니다", "저는 고객입니다", "저는 간호사입니다"):
        out, cats = _contextual_name_scrub(s)
        assert out == s, s
        assert cats == []


def test_intro_domain_terms_not_masked():
    """도메인 스토플리스트 공유 — '유예'·'서류' 류가 자기소개 위치라도 보호."""
    out, _ = _contextual_name_scrub("저는 유예입니다")
    assert out == "저는 유예입니다"


def test_intro_non_surname_start_not_masked():
    out, _ = _contextual_name_scrub("저는 통합운영입니다")
    assert out == "저는 통합운영입니다"


def test_intro_collect_terms():
    collect: list = []
    _contextual_name_scrub("저는 최다온입니다", collect)
    assert collect == [{"term": "최다온", "placeholder": "[이름]"}]


def test_intro_idempotent_on_placeholder():
    out1, _ = _contextual_name_scrub("저는 최다온입니다")
    out2, cats2 = _contextual_name_scrub(out1)
    assert out2 == out1 and cats2 == []


def test_scrub_input_dev_path_masks_intro_name(monkeypatch):
    """NER 미설정(dev)에서도 자기소개 이름은 결정적으로 잡힌다."""
    from src.guardrail import ner_client
    monkeypatch.setattr(ner_client, "is_available", lambda: False)
    out, cats = scrub_input("저는 남궁민수입니다. 2등급 인증 절차 알려주세요")
    assert out.startswith("저는 [이름]입니다")
    assert "이름" in cats


# ── ③ 차량번호 오탐 — 사건번호 보호 (2026-10-02) ──────────────────────────
#
# `\d{2,3}[가-힣]\s?\d{4}` 는 `2008도6829` 의 **뒤쪽 9글자**(`008도6829`)에
# 그대로 걸린다. 법률 도구에서 사건번호가 `[차량번호]` 로 마스킹되면 판례를
# 특정할 수 없어 답변이 무너진다 — 조문 변동 대조를 검증하다 실측으로 잡았다.
# 선행 숫자 금지(`(?<!\d)`)로 갈리므로, 양쪽을 다 고정한다.

def test_court_case_numbers_are_not_masked_as_plates():
    """대법원 사건번호는 마스킹되지 않는다."""
    for case in ("2008도6829", "2020다12345", "대법원 2008도6829 판결"):
        out = scrub_input(case)[0]
        assert "[차량번호]" not in out, f"{case} 가 차량번호로 오탐됨 → {out}"


def test_real_license_plates_are_still_masked():
    """실제 번호판은 그대로 잡힌다 — 오탐을 고치며 미탐을 만들지 않는다."""
    for plate in ("12가3456", "123가4567", "서울 12가3456"):
        out = scrub_input(plate)[0]
        assert "[차량번호]" in out, f"{plate} 가 마스킹되지 않음 → {out}"
