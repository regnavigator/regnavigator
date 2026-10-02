"""출처 적합성 필터 — 닮았지만 적용되지 않는 출처 차단 (2026-10-02).

실사용 신고: "카페를 열려면 어떤 신고와 허가가 필요한가요?" 에 「어린이
식생활안전관리 특별법 시행규칙」 별표가 인용됐다. '식품접객업' 용어는 겹치지만
적용 대상이 다르다.

여기서 지키는 것은 "잘 거르는가" 가 아니라 **잘못 거르지 않는가** 다. 과하게
거르면 답할 근거가 사라진다 — 실패 방향은 항상 '덜 거름'이어야 한다.
"""

from __future__ import annotations

from src import source_filter as SF


def _hit(law, *, art="제1조", title="", tt="law", score=1.0, snippet=""):
    return {"article_key": f"k_{law}_{art}", "law_title": law,
            "article_num": art, "article_title": title,
            "target_type": tt, "score": score, "snippet": snippet}


# ── 적용대상 ────────────────────────────────────────────────────────────────

def test_scope_limited_law_dropped_when_query_lacks_that_scope():
    """신고 사례 그 자체 — 카페 질의에 어린이 전용 기준이 들어오면 안 된다."""
    q = "카페를 열려면 어떤 신고와 허가가 필요한가요?"
    h = _hit("어린이 식생활안전관리 특별법 시행규칙", art="별표",
             title="어린이 기호식품 우수판매업소 시설기준")
    assert SF.classify(q, h)


def test_scope_limited_law_kept_when_query_names_that_scope():
    """어린이를 물었으면 어린이 법이 맞다 — 거르면 그게 오류다."""
    q = "어린이 기호식품 우수판매업소 시설기준이 뭔가요?"
    h = _hit("어린이 식생활안전관리 특별법 시행규칙", art="별표",
             title="어린이 기호식품 우수판매업소 시설기준")
    assert SF.classify(q, h) is None


def test_scope_synonym_counts_as_match():
    """'아동'이라 물어도 '어린이' 법은 적용된다 — 글자만 보면 놓친다."""
    h = _hit("어린이 식생활안전관리 특별법", title="어린이 급식")
    assert SF.classify("아동 급식 안전 기준", h) is None


# ── 관할 ────────────────────────────────────────────────────────────────────

def test_ordinance_dropped_without_region():
    q = "카페 휴게음식점 시설기준"
    assert SF.classify(q, _hit("임실군 음식판매자동차 조례", tt="ordin"))


def test_ordinance_kept_when_region_named():
    q = "서울 마포구 카페 휴게음식점 시설기준"
    h = _hit("서울특별시 마포구 식품접객업 시설기준 적용특례에 관한 규칙", tt="ordin")
    assert SF.classify(q, h) is None


def test_region_hint_fires_only_when_many_ordinances_dropped():
    few = [{"reason": "관할 미지정(자치법규)"}] * (SF.ASK_REGION_AT - 1)
    many = [{"reason": "관할 미지정(자치법규)"}] * SF.ASK_REGION_AT
    assert SF.region_hint(few) is None
    assert "되물어라" in (SF.region_hint(many) or "")


# ── 임의 제도 ───────────────────────────────────────────────────────────────

def test_voluntary_scheme_dropped_for_duty_question():
    """의무 절차를 물었는데 임의 인증 서류가 섞이면 필수로 오해한다."""
    q = "카페 영업신고에 필요한 서류가 뭔가요?"
    h = _hit("식품접객업소등 위생등급 지정 및 운영관리 규정", art="별표",
             title="식품안심업소 지정평가표")
    assert SF.classify(q, h)


def test_voluntary_scheme_kept_when_asked_about_it():
    q = "식품안심업소 지정 평가는 어떻게 받나요?"
    h = _hit("식품접객업소등 위생등급 지정 및 운영관리 규정", art="별표",
             title="식품안심업소 지정평가표")
    assert SF.classify(q, h) is None


# ── 점수 ────────────────────────────────────────────────────────────────────

def test_negative_score_dropped():
    """리랭커 점수는 음수가 될 수 있다 — 비율만 쓰면 부호가 뒤집힌다."""
    assert SF.classify("카페 영업신고", _hit("무관법", score=-0.5), max_score=1.0)


def test_relevant_hit_survives_everything():
    q = "카페 휴게음식점 영업신고 시설기준"
    h = _hit("식품위생법 시행규칙", art="제42조", title="영업신고", score=1.0)
    assert SF.classify(q, h, max_score=1.0) is None


# ── 안전장치 ────────────────────────────────────────────────────────────────

def test_min_keep_revives_only_weak_reasons():
    """근거가 모자라면 되살리되, **적용 안 됨 판정은 되살리지 않는다.**

    구현 중 실제로 이 구멍으로 어린이 특별법이 돌아왔다(2026-10-02).
    """
    q = "카페 휴게음식점 시설기준"
    hits = ([_hit(f"{i}군 음식판매자동차 조례", tt="ordin", score=0.5 - i * 0.01)
             for i in range(6)]
            + [_hit("어린이 식생활안전관리 특별법 시행규칙", art="별표",
                    title="어린이 기호식품 우수판매업소 시설기준", score=0.9)])
    kept, dropped = SF.apply(q, hits)

    assert len(kept) >= SF.MIN_KEEP          # 근거 0건이 되지 않는다
    titles = " ".join(h["law_title"] for h in kept)
    assert "어린이" not in titles            # 되살리기로 돌아오면 안 된다
    assert any(d["reason"].startswith("적용대상") for d in dropped)


def test_disable_knob_is_a_full_bypass(monkeypatch):
    monkeypatch.setenv("SOURCE_FILTER_DISABLE", "1")
    hits = [_hit("임실군 조례", tt="ordin")]
    kept, dropped = SF.apply("카페 영업신고", hits)
    assert kept == hits and dropped == []


def test_empty_input_is_safe():
    assert SF.apply("카페", []) == ([], [])


# ── 응답 서두 (2026-10-02) ──────────────────────────────────────────────────

def test_prompt_forbids_search_preamble():
    """"지금까지 확보한 근거를 바탕으로 정리합니다" 류 서두를 금지한다.

    실사용 신고: 모든 답변이 이 문장으로 시작했다. 검색 과정은 화면에 이미
    보이므로, 그걸 문장으로 또 말하면 정작 답이 한 줄 밀린다.
    """
    from src.prompts import supervisor

    p = supervisor.SUPERVISOR_PROMPT
    assert "서두 금지" in p
    assert "지금까지 확보한 근거를 바탕으로 정리합니다" in p   # 금지 예시로 명시
    assert "첫 문장부터" in p
