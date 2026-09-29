"""의도 게이트 — 인사/재촉(무검색) vs 규제 질문(검색 강제) 라우팅.

발화 유형 taxonomy(supervisor v7)의 intent 레이어 회귀:
  A 인사·B 범위밖·C 물음없음 → 검색 강제 안 함 / D 규제 질문 → 강제.
3턴 라우팅 버그(2026-07-21): "ㅎㅇ"→"오늘 날씨"→"대답하라고"가 규제 답변으로
날조되던 문제. turn 1 "ㅎㅇ"이 ㅎ 전역 strip 으로 "ㅇ"이 돼 인사 인식이 깨졌고,
turn 3 "대답하라고"가 검색 강제로 들어가 환각을 유발했다.
"""
from __future__ import annotations

import pytest

from src.guardrail.intent import _looks_offtopic, should_search


# ── A 인사(정확 일치) ────────────────────────────────────────────────
@pytest.mark.parametrize("text", ["안녕", "안녕하세요", "ㅎㅇ", "하이", "hi",
                                  "고마워", "감사합니다", "ㄳ", "ok", "넵"])
def test_greeting_is_offtopic(text):
    assert _looks_offtopic(text) is True


def test_hi_slang_not_broken_by_laughter_strip():
    """'ㅎㅇ'(하이) — 과거 ㅎ 전역 제거로 'ㅇ'이 돼 인사 인식이 깨졌음(turn 1 버그)."""
    assert _looks_offtopic("ㅎㅇ") is True
    assert _looks_offtopic("ㅎㅇ!") is True


# ── 웃음 정규화 ──────────────────────────────────────────────────────
@pytest.mark.parametrize("text", ["ㅋㅋㅋ", "ㅎㅎ", "안녕ㅋㅋ", "감사합니다ㅎㅎ"])
def test_trailing_laughter_normalized(text):
    assert _looks_offtopic(text) is True


# ── C 물음 없는 재촉·필러 ────────────────────────────────────────────
@pytest.mark.parametrize("text", ["대답해", "대답하라고", "빨리", "계속",
                                  "그래서", "재답변", "말해봐", "ㄱㄱ"])
def test_no_question_filler_skips_forced_search(text):
    """재촉·필러는 검색 강제 안 함 — 모델이 맥락에 진짜 질문이 있을 때만
    스스로 검색하고 없으면 되묻는다(주제 날조 차단)."""
    assert _looks_offtopic(text) is True
    assert should_search(text) is False


# ── B/D: 실제 질문은 스킵 대상 아님 ──────────────────────────────────
@pytest.mark.parametrize("text", [
    "오늘 서울 날씨는?",           # B 범위 밖 — 분류기가 판정
    "의료기기 광고 규제 알려줘",    # D 규제
    "좋아 그럼 처벌은?",           # 인사 선두지만 규제 질문 — 오판 금지
    "규제",                        # 모호 단독어 — ask_clarify 대상(검색은 함)
])
def test_real_question_not_short_circuited(text):
    assert _looks_offtopic(text) is False


def test_blank_is_offtopic():
    assert _looks_offtopic("") is True
    assert _looks_offtopic("   ") is True


# ── E 서비스·시각 메타 질문(supervisor v14) — 판정 주체는 분류기 ─────
@pytest.mark.parametrize("text", [
    "너 누구야", "누구세요", "너 이름 뭐야", "네 이름은?", "당신 정체가 뭐야",
    "무슨 모델이야", "넌 뭐하는 애야",
    "지금 몇시야", "현재 시각 알려줘", "오늘 며칠이야", "오늘 무슨 요일이야",
])
def test_meta_question_routed_to_classifier_not_local_rules(text, monkeypatch):
    """메타 질문은 medi-back 로컬 규칙이 아니라 **분류기**가 거른다.

    한때 여기에 정규식 레이어를 뒀으나(2026-07-25) 라이브 0.8B 실측에서 분류기가
    10건 중 9건을 이미 맞혔고 정규식이 놓친 "넌 뭐하는 애야"까지 맞혀 제거했다.
    판정 레이어가 둘이면 갈라진다 — 여기서는 "로컬 단축(_looks_offtopic)에
    걸리지 않고 분류기까지 도달하는지"만 고정한다.
    """
    assert _looks_offtopic(text) is False  # 로컬 단축 대상 아님 → 분류기로 감

    seen: list[str] = []

    def _fake(t, ctx=None):
        seen.append(t)
        return False  # 분류기: 검색 불필요

    monkeypatch.setattr("src.guardrail.intent_client.classify", _fake)
    assert should_search(text) is False
    assert seen == [text]


def test_classifier_unavailable_falls_back_to_search(monkeypatch):
    """분류기 미설정/실패 시 메타 질문도 검색이 강제된다 — **의도된 안전 기본값**.

    무검색이 기본이면 규제 질문이 근거 없이 답변된다(환각). 메타 질문에 검색이
    한 번 도는 낭비가 그 반대보다 훨씬 싸다. supervisor E 분기는 검색 결과가
    붙어 있어도 쓰지 말고 즉답하라고 지시하므로 답변 품질은 유지된다.
    """
    monkeypatch.setattr(
        "src.guardrail.intent_client.classify", lambda t, ctx=None: None)
    assert should_search("지금 몇시야") is True


# ── 인사 로컬 차단(2026-08-01) — 분류기 이전에 막는다 ──────────────
# 사용자 지적: "ㅎㅇ만 해도 tavily·vector 검색이 되면 어떡함, 그 전에 차단해야지"
# 구조적 이유: 분류기 시스템 프롬프트가 "직전 대화가 규제 주제면 후속도 '예'" 라
# 지시 → 규제 대화 도중 인사에 '예'. 분류기 다운 시 폴백도 '검색'.
# 순수 인사는 답할 내용이 없어 **차단해도 환각 위험 0** 이라 로컬 차단이 안전하다.
@pytest.mark.parametrize("text", [
    "ㅎㅇ", "ㅎㅇ요", "ㅎㅇㅎㅇ", "ㅎㅇ!!", "안뇽", "하이요",
    "굿모닝", "좋은아침", "안녕안녕", "안녕하세요",
    "수고하셨습니다", "수고했어요", "감사드립니다", "고맙습니다",
    "알겠습니다", "확인했어요", "오케이요", "넵넵", "ㅇㅇ", "ㄱㅅ",
])
def test_greeting_blocked_before_classifier(text, monkeypatch):
    """인사 변형은 **분류기를 호출하지 않고** 로컬에서 차단된다.

    분류기가 '예'(검색 필요)라고 해도 무시돼야 한다 — 맥락이 규제일 때 분류기가
    인사를 후속 질문으로 오판하는 실측 케이스."""
    called = []

    def _boom(t, ctx=None):
        called.append(t)
        return True  # 분류기가 '검색 필요'라고 우겨도

    monkeypatch.setattr("src.guardrail.intent_client.classify", _boom)
    assert should_search(text, "의료기기 광고 규제 알려줘") is False
    assert called == [], "인사인데 분류기까지 갔다"


@pytest.mark.parametrize("text", [
    "안녕하세요 의료기기 허가 절차 알려주세요",   # 인사 + 진짜 질문
    "ㅎㅇ 광고 규제 뭐야",
    "좋아 그럼 처벌은?",
    "굿모닝 GMP 심사 요건은?",
    "감사한데 추가로 임상 요건은?",
    "확인해야 할 서류가 뭔가요",
    "네 그럼 과태료는요?",
])
def test_greeting_prefix_does_not_block_real_question(text, monkeypatch):
    """★과차단 금지 — 인사로 *시작*할 뿐 실질 질문이면 검색이 살아야 한다.
    (전체 메시지 일치 원칙 — 여기가 깨지면 근거 없는 답변=환각)"""
    monkeypatch.setattr(
        "src.guardrail.intent_client.classify", lambda t, ctx=None: True)
    assert should_search(text, "의료기기 광고 규제 알려줘") is True


def test_greeting_blocked_even_when_classifier_down():
    """분류기 다운 시 폴백은 '검색'(안전 기본값)이지만, 인사는 그 전에 걸러진다."""
    import src.guardrail.intent_client as ic
    orig = ic.classify
    ic.classify = lambda t, ctx=None: None      # 서비스 미가용
    try:
        for t in ("ㅎㅇ요", "굿모닝", "안뇽"):
            assert should_search(t) is False, t
        assert should_search("의료기기 허가 절차는?") is True   # 폴백은 유지
    finally:
        ic.classify = orig
