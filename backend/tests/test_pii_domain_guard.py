"""NER 도메인 어휘 오탐 가드 — 규제 용어가 이름/주소로 마스킹되지 않아야."""
from __future__ import annotations

import pytest

from src.guardrail.gate import _apply_spans


def test_domain_terms_not_masked():
    # 실측 오탐(2026-07-21): "비대면진료"→ADDRESS, "유권해석"→NAME
    text = "비대면진료 판례, 유권해석 알려줘"
    spans = [
        {"start": 0, "end": 5, "label": "ADDRESS", "text": "비대면진료"},
        {"start": 10, "end": 14, "label": "PERSON", "text": "유권해석"},
    ]
    out, cats = _apply_spans(text, spans)
    assert out == text          # 도메인 어휘는 그대로
    assert cats == []


def test_real_name_still_masked():
    text = "홍길동 님의 처방 관련 문의"
    spans = [{"start": 0, "end": 3, "label": "PERSON", "text": "홍길동"}]
    out, cats = _apply_spans(text, spans)
    assert out.startswith("[이름]")
    assert "이름" in cats


def test_numeric_name_guard_still_works():
    text = "제2026-15호 고시 관련"
    spans = [{"start": 0, "end": 9, "label": "PERSON", "text": "제2026-15호"}]
    out, _ = _apply_spans(text, spans)
    assert out == text


# ── 구조적 오탐 가드(2026-07-26) — 어휘 나열이 아니라 "PII 일 수 없는 모양" ──
# 계기: 사용자가 "ㄴㄴ괜찮" 입력 → "[주소]ㄴ괜찮" 으로 저장됨(실측 재현).
# 어휘 스토플리스트는 새 오탐마다 단어를 추가해야 해 확장되지 않는다.

def test_jamo_only_span_not_masked():
    """자모(ㄴㄴ·ㅋㅋ·ㄱㅅ)는 이름·주소일 수 없다 — 축약 리액션 보호."""
    text = "ㄴㄴ괜찮"
    spans = [{"start": 0, "end": 1, "label": "ADDRESS", "text": "ㄴ"}]
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == []


def test_single_char_span_not_masked():
    """한 글자는 한국어 이름·주소의 최소 단위 미만."""
    text = "보고서 다 됐어?"
    spans = [{"start": 3, "end": 5, "label": "ADDRESS", "text": " 다"}]
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == []


def test_bracket_fragment_span_not_masked():
    """토큰 경계 오인식 파편 — 실측: 'B2B' 걸친 '병원(B2' → ADDRESS."""
    text = "소프트웨어를 병원(B2B)에 판매하려 할 때"
    spans = [{"start": 7, "end": 12, "label": "ADDRESS", "text": "병원(B2"}]
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == []


def test_non_maskable_span_must_not_suppress_real_pii():
    """★프라이버시 회귀(2026-07-26 실측): 마스킹 대상이 아닌 스팬(PREFIX)이
    겹침 처리에서 자리를 차지해 **진짜 주소가 통째로 미마스킹**됐다.

    'PREFIX(" 님")' 가 'ADDRESS("님 서울특별시 …")' 와 겹쳐 주소를 밀어냄.
    → 화이트리스트 필터를 겹침 제거보다 **먼저** 적용해야 한다."""
    text = "김영희 님 서울특별시 강남구 테헤란로 152 거주"
    spans = [
        {"start": 0, "end": 3, "label": "NAME", "text": "김영희"},
        {"start": 3, "end": 5, "label": "PREFIX", "text": " 님"},      # 마스킹 대상 아님
        {"start": 4, "end": 26, "label": "ADDRESS", "text": "님 서울특별시 강남구 테헤란로 152"},
    ]
    out, cats = _apply_spans(text, spans)
    assert "[이름]" in out and "[주소]" in out, out
    assert "서울특별시" not in out, f"주소가 새고 있음: {out}"
    assert cats == ["이름", "주소"]


def test_overlap_prefers_longer_span():
    """같은 시작이면 긴 스팬 우선 — 부분 마스킹으로 PII 꼬리가 남지 않게."""
    text = "서울특별시 강남구 테헤란로 152 에 있습니다"
    spans = [
        {"start": 0, "end": 5, "label": "ADDRESS", "text": "서울특별시"},
        {"start": 0, "end": 20, "label": "ADDRESS", "text": "서울특별시 강남구 테헤란로 152"},
    ]
    out, _ = _apply_spans(text, spans)
    assert "강남구" not in out and "테헤란로" not in out, out


# ── 신뢰도 임계값(2026-08-01) — 형태로 못 거르는 오탐의 유일한 레버 ──
# DGX 회신: '현행'은 모델이 2글자 스팬으로 **직접** 뱉어 스팬 확장 차단이 무효.
# 진짜 이름과 모양이 같아 휴리스틱 불가 → score 로 거른다.
def test_low_score_name_skipped_when_threshold_set(monkeypatch):
    monkeypatch.setenv("PII_NER_MIN_SCORE_NAME", "0.9")
    text = "할 때 현행 규제에서 어떤 부분이"
    spans = [{"start": 3, "end": 5, "label": "NAME", "text": "현행", "score": 0.55}]
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == []


def test_high_score_name_still_masked_with_threshold(monkeypatch):
    """임계값을 켜도 신뢰도 높은 진짜 이름은 마스킹돼야 한다."""
    monkeypatch.setenv("PII_NER_MIN_SCORE_NAME", "0.9")
    text = "환자 홍길동 씨의 처방"
    spans = [{"start": 3, "end": 6, "label": "NAME", "text": "홍길동", "score": 0.97}]
    out, cats = _apply_spans(text, spans)
    assert "[이름]" in out and cats == ["이름"]


def test_threshold_off_by_default_preserves_behavior(monkeypatch):
    """★기본은 꺼짐 — env 없으면 종전대로 전부 마스킹(회귀 방지)."""
    monkeypatch.delenv("PII_NER_MIN_SCORE_NAME", raising=False)
    monkeypatch.delenv("PII_NER_MIN_SCORE", raising=False)
    text = "환자 홍길동 씨"
    spans = [{"start": 3, "end": 6, "label": "NAME", "text": "홍길동", "score": 0.41}]
    out, _ = _apply_spans(text, spans)
    assert "[이름]" in out


def test_missing_score_field_is_not_filtered(monkeypatch):
    """구버전 서버(score 없음) 호환 — score 가 없으면 임계값을 적용하지 않는다.
    (배포 순서상 medi-back 이 먼저 올라가도 마스킹이 죽지 않아야 한다)"""
    monkeypatch.setenv("PII_NER_MIN_SCORE_NAME", "0.9")
    text = "환자 홍길동 씨"
    spans = [{"start": 3, "end": 6, "label": "NAME", "text": "홍길동"}]  # score 없음
    out, _ = _apply_spans(text, spans)
    assert "[이름]" in out


def test_address_threshold_independent(monkeypatch):
    """이름·주소 임계값은 독립 — 이름만 올려도 주소는 영향 없음."""
    monkeypatch.setenv("PII_NER_MIN_SCORE_NAME", "0.99")
    monkeypatch.delenv("PII_NER_MIN_SCORE_ADDRESS", raising=False)
    monkeypatch.delenv("PII_NER_MIN_SCORE", raising=False)
    text = "서울특별시 강남구 테헤란로 152"
    spans = [{"start": 0, "end": 17, "label": "ADDRESS",
              "text": "서울특별시 강남구 테헤란로", "score": 0.5}]
    out, _ = _apply_spans(text, spans)
    assert "[주소]" in out


# ── 조사 변형 스토플리스트(2026-08-02) — 신뢰도로 분리 불가한 잔여 오탐 ──
# 실측: '서류가' score 0.7296 이 진짜 이름 최저값('한소희' 0.729)과 **겹친다**.
# 형태로도 진짜 이름과 구분되지 않아, 이 잔여분은 어휘로 거를 수밖에 없다.
# 다만 활용형을 일일이 등재하지 않도록 **조사를 떼어 원형으로 대조**한다.
@pytest.mark.parametrize("span", [
    "서류가", "서류를", "서류는", "서류로", "제재를", "제재의", "규정된",
    "현행", "절차가", "요건은", "허가를", "심사에서",
])
def test_domain_term_with_particle_not_masked(span):
    text = f"규제 문의: {span} 어떻게 되나요"
    i = text.index(span)
    spans = [{"start": i, "end": i + len(span), "label": "NAME",
              "text": span, "score": 0.95}]   # 고신뢰여도 어휘면 제외
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == [], out


@pytest.mark.parametrize("name", ["홍길동", "김영희", "박민수", "이지은", "최영수"])
def test_real_names_survive_particle_stoplist(name):
    """★스토플리스트 조사 절단이 진짜 이름을 삼키면 안 된다."""
    text = f"환자 {name} 씨"
    spans = [{"start": 3, "end": 3 + len(name), "label": "NAME",
              "text": name, "score": 0.9}]
    out, _ = _apply_spans(text, spans)
    assert "[이름]" in out, out


def test_particle_strip_prefers_longer_particle():
    """'으로'가 '로'에 선점되면 원형 복원이 어긋난다 — 긴 조사부터 매칭."""
    from src.guardrail.gate import _stoplisted
    assert _stoplisted("서류으로") is True
    assert _stoplisted("서류로") is True


# ── 임계값 철회(2026-08-02) — 켜면 진짜 이름이 샌다 ────────────────
# DGX 애드혹 실측: '우리 병원 간호사 한소희'→0.5235, '담당 약사 이서연입니다'→0.4834.
# 진짜 이름 0.48~0.92 / 오탐 0.54~0.90('저희' 0.8997) 로 **분포가 겹쳐** 판별력이 없다.
# 임계값을 켜면 오탐 이득 없이 PII 만 샌다 → 기본 OFF 를 계약으로 고정한다.
def test_low_score_real_name_masked_when_threshold_off(monkeypatch):
    monkeypatch.delenv("PII_NER_MIN_SCORE_NAME", raising=False)
    monkeypatch.delenv("PII_NER_MIN_SCORE", raising=False)
    text = "우리 병원 간호사 한소희"
    spans = [{"start": 9, "end": 12, "label": "NAME",
              "text": "한소희", "score": 0.5235}]   # 실측 저score 진짜 이름
    out, _ = _apply_spans(text, spans)
    assert "[이름]" in out, f"저score 진짜 이름이 샌다: {out}"


@pytest.mark.parametrize("pron", ["저희", "우리", "본인", "당사", "귀사"])
def test_pronoun_not_masked_even_at_high_score(pron):
    """대명사는 고신뢰여도 이름이 아니다 — 실측 '저희' NAME 0.8997.
    (신뢰도로는 못 거르는 오탐 = 임계값 무용의 반대편 증거)"""
    text = f"{pron} 병원 도입 절차"
    spans = [{"start": 0, "end": len(pron), "label": "NAME",
              "text": pron, "score": 0.90}]
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == [], out


# ── 짧은 ASCII 오탐 (2026-08-03 베타 첫날 실측) ──────────────────
def test_short_ascii_greeting_not_masked():
    """`hi` 만 입력했는데 NAME 0.4991 로 잡혀 전체가 [이름] 이 됐다.

    사용자는 인사만 했는데 "개인정보가 포함되어 필터됐다"는 답을 받았다.
    """
    spans = [{"start": 0, "end": 2, "label": "NAME", "text": "hi", "score": 0.4991}]
    out, cats = _apply_spans("hi", spans)
    assert out == "hi"
    assert cats == []


@pytest.mark.parametrize("token", ["hi", "ok", "hm", "yo", "no", "a", "u"])
def test_two_char_ascii_never_masked(token):
    spans = [{"start": 0, "end": len(token), "label": "NAME", "text": token}]
    out, _ = _apply_spans(token, spans)
    assert out == token


@pytest.mark.parametrize("name", ["Kim", "Lee", "홍길동", "김구", "John"])
def test_real_names_still_masked(name):
    """가드가 진짜 이름을 놓치면 안 된다 — 3자 이상 로마자·한글은 그대로 마스킹."""
    spans = [{"start": 0, "end": len(name), "label": "NAME", "text": name}]
    out, cats = _apply_spans(name, spans)
    assert out == "[이름]", f"{name} 이 마스킹되지 않았다"
    assert cats == ["이름"]


# ── 조건 어미 술어 오탐 (2026-08-07 베타 실측) ──────────────────
# "너 토큰 한도가 얼마야? 대화가 길어지면 힘든가?" 에서 ' 대화가 길어지면' 이
# ADDRESS 0.671 — 용언 '-면' 을 행정구역 '면' 으로 혼동. score 분포 역전
# (진짜 주소 '음성군 대소면' 0.503)이라 임계값 불가 → 형태 가드.
@pytest.mark.parametrize("span_text,sentence", [
    (" 대화가 길어지면", "너 토큰 한도가 얼마야? 대화가 길어지면 힘든가?"),
    ("기간이 길어지면", "허가 기간이 길어지면 어떻게 되나요"),
    ("심사가 지연되면", "심사가 지연되면 불이익이 있나요"),
    ("서류를 제출하면", "서류를 제출하면 언제 결과가 나오나요"),
    ("허가를 받으려면", "허가를 받으려면 뭐가 필요한가요"),
])
def test_predicate_ending_span_not_masked(span_text, sentence):
    i = sentence.index(span_text)
    spans = [{"start": i, "end": i + len(span_text), "label": "ADDRESS",
              "text": span_text, "score": 0.671}]
    out, cats = _apply_spans(sentence, spans)
    assert out == sentence and cats == [], out


@pytest.mark.parametrize("addr", [
    "경기도 광주시 오포면 신현리",   # 행정구역 접미 어절 동반
    "충북 음성군 대소면 대풍리",
    "용인군 수지면",                 # '지면' 으로 끝나지만 앞 어절이 '군'
    "오포면 신현리 45-2",            # 숫자 동반
    "수지면",                        # 단독 1어절 — 가드 미적용
])
def test_real_myeon_addresses_still_masked(addr):
    """★조건 어미 가드가 진짜 '면' 주소를 삼키면 안 된다(누락 0 원칙)."""
    text = f"거주지는 {addr} 입니다"
    i = text.index(addr)
    spans = [{"start": i, "end": i + len(addr), "label": "ADDRESS",
              "text": addr, "score": 0.5}]
    out, _ = _apply_spans(text, spans)
    assert "[주소]" in out, f"진짜 주소가 새고 있음: {out}"


def test_short_ascii_inside_sentence_not_masked():
    text = "hi 의료기기 허가 절차 알려줘"
    spans = [{"start": 0, "end": 2, "label": "NAME", "text": "hi"}]
    out, cats = _apply_spans(text, spans)
    assert out == text
    assert cats == []


# ── 제도·행위 한자어 접미 가드(2026-08-10) ──────────────────────────────────
# 계기(사용자 실측): "신의료기술평가 통합운영 제도의 자세한 내용은?" 에서
# '통합운영'이 NAME 0.6611 로 마스킹 → 질문 핵심어가 [이름] 으로 사라졌다.
# 같은 배치 진짜 이름은 0.7709~0.9421 이지만, 과거 실측(서류가 0.7296 vs
# 한소희 0.729)처럼 분포가 겹치는 사례가 있어 score 가 아니라 형태로 막는다.

def test_institutional_compound_not_masked():
    text = "신의료기술평가 통합운영 제도의 자세한 내용은?"
    spans = [{"start": 8, "end": 12, "label": "NAME", "score": 0.6611,
              "text": "통합운영"}]
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == []


@pytest.mark.parametrize("term", [
    "품질관리", "위탁운영", "사후평가", "적합성심사", "변경허가",
    "통합심사", "위해성관리", "전문위원회", "임상시험기관",
])
def test_unlisted_compounds_also_guarded(term):
    """스토플리스트에 없는 조어도 접미만으로 걸린다(확장성이 요점)."""
    text = f"{term} 절차 알려줘"
    spans = [{"start": 0, "end": len(term), "label": "NAME", "score": 0.7,
              "text": term}]
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == []


def test_institutional_guard_survives_particle():
    """모델이 조사를 스팬에 포함해 뱉어도('통합운영을') 동일하게 걸린다."""
    text = "통합운영을 어떻게 하나요?"
    spans = [{"start": 0, "end": 5, "label": "NAME", "score": 0.7,
              "text": "통합운영을"}]
    out, cats = _apply_spans(text, spans)
    assert out == text and cats == []


@pytest.mark.parametrize("name", ["김영희", "박민수", "이수현", "홍길동", "남궁민수"])
def test_real_names_unaffected_by_institutional_guard(name):
    """누락 0 원칙 — 진짜 이름은 이 접미로 끝나지 않는다."""
    text = f"{name} 환자 문의"
    spans = [{"start": 0, "end": len(name), "label": "NAME", "score": 0.8,
              "text": name}]
    out, cats = _apply_spans(text, spans)
    assert out.startswith("[이름]") and cats == ["이름"]


def test_multiword_address_not_skipped_by_institutional_guard():
    """다어절 주소는 이 가드 대상이 아니다 — '…로 의료기관'이 통째로 새면 안 된다."""
    text = "서울특별시 강남구 테헤란로 의료기관 문의"
    spans = [{"start": 0, "end": 20, "label": "ADDRESS", "score": 0.9,
              "text": "서울특별시 강남구 테헤란로 의료기관"}]
    out, cats = _apply_spans(text, spans)
    assert out.startswith("[주소]") and cats == ["주소"]
