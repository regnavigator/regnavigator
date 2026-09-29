"""법령 본문 정규화 골든 테스트 — 2026-08-04 감사 H-20.

`src/text/normalize.py` 는 303줄짜리 정규식 파이프라인(11단계)인데 테스트가
**0건**이었다. 이 코드는 사용자가 보는 조문 본문을 직접 만들고, 주석에 이미
*"먼저 줄바꿈하지 않으면 헤더 제거가 본문을 통째 삭제"*(`normalize.py:261-266`)
라는 실패 모드가 기록돼 있다 — 규제 상담에서 조문 본문이 소리 없이 잘리는 건
가장 나쁜 종류의 버그다.

여기서 고정하는 것:
  ① **본문은 절대 사라지지 않는다** — 단계 순서가 바뀌면 제일 먼저 깨진다.
  ② 단계별 골든 입출력(항·호 분리, 제로패딩, <br>, 개정태그).
  ③ 멱등성 — 두 번 돌려도 같은 결과(중간 단계가 서로를 되먹이지 않는다).
"""
from __future__ import annotations

import pytest

from src.text.normalize import normalize_law_text as norm


_ARTICLE_KW = dict(law_title="의료기기법", article_num="제25조",
                   article_title="광고의 심의")


# ── ① 본문 보존 (회귀의 핵심) ───────────────────────────────────────────────
def test_inline_hang_article_keeps_body():
    """한 줄에 헤더+본문이 다 들어와도 본문이 남아야 한다.

    `_HANG_RE` 줄바꿈(1.5단계)을 헤더 제거(2단계)보다 **먼저** 돌리는 이유.
    순서를 뒤집으면 `_ARTICLE_HEADER_RE` 의 greedy `\\(.+\\)$` 가 줄 전체를
    헤더로 오인해 본문이 통째로 사라진다.
    """
    out = norm(
        "제25조(광고의 심의) ① 광고하려는 자는 심의를 받아야 한다. "
        "② 제1항에도 불구하고 예외로 한다.",
        **_ARTICLE_KW,
    )
    assert "심의를 받아야 한다" in out, "본문이 사라졌다"
    assert "제1항에도 불구하고" in out
    assert out == ("① 광고하려는 자는 심의를 받아야 한다.\n\n"
                   "② 제1항에도 불구하고 예외로 한다.")


def test_header_dedup_does_not_eat_body():
    out = norm("의료기기법 제25조(광고의 심의)\n① 본문입니다.", **_ARTICLE_KW)
    assert out == "① 본문입니다."


def test_long_body_survives_normalization():
    """긴 실전형 본문 — 어느 단계도 내용을 통으로 날리지 않는다."""
    body = (
        "제6조(제조업의 허가) ① 의료기기를 제조하려는 자는 식품의약품안전처장의 "
        "허가를 받아야 한다. <개정 2020. 1. 1.> "
        "② 제1항에 따른 허가를 받으려는 자는 다음 각 호의 서류를 갖추어야 한다. "
        "1. 시설 명세서 2. 품질관리 기준서"
    )
    out = norm(body, law_title="의료기기법", article_num="제6조",
               article_title="제조업의 허가")
    for must in ("식품의약품안전처장", "시설 명세서", "품질관리 기준서",
                 "다음 각 호의 서류"):
        assert must in out, f"{must!r} 가 사라졌다"


# ── ② 단계별 골든 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("제025조 제003항 제01호", "제25조 제3항 제1호"),          # 5단계 제로패딩
    ("[판시사항]<br/>내용<br />[참조조문]",                     # 1.1단계 <br>
     "[판시사항]\n\n내용\n\n[참조조문]"),
    ("다음 각 호와 같다. 1. 첫째 2. 둘째",                      # 7단계 호 번호
     "다음 각 호와 같다.\n1. 첫째 2. 둘째"),
    ("① 항목 <개정 2020. 1. 1.> ② 다음 항",                    # 8단계 개정 태그
     "① 항목 <개정 2020. 1. 1.>\n\n② 다음 항"),
])
def test_stage_goldens(raw, expected):
    assert norm(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\n\n", "﻿"])
def test_empty_like_input_returns_empty_string(raw):
    """None/빈 입력이 예외나 'None' 문자열로 새지 않는다."""
    assert norm(raw) == ""


def test_crlf_and_bom_are_cleaned():
    assert norm("﻿가나다\r\n라마바") == "가나다\n라마바"


def test_strip_leading_header_false_keeps_title():
    """/annex(별표)는 본문 자체가 제목으로 시작해도 정상 — 지우면 안 된다."""
    out = norm("[별표 1] 시설기준\n내용", strip_leading_header=False)
    assert out.startswith("[별표 1] 시설기준")


def test_excess_blank_lines_collapse():
    assert norm("가\n\n\n\n나") == "가\n\n나"


# ── ③ 멱등성 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,kw", [
    ("제25조(광고의 심의) ① 광고하려는 자는 심의를 받아야 한다. ② 예외로 한다.",
     _ARTICLE_KW),
    ("의료기기법 제25조(광고의 심의)\n① 본문.", _ARTICLE_KW),
    ("① 항목 <개정 2020. 1. 1.> ② 다음 항", {}),
    ("[별표 1] 시설기준\n내용", {"strip_leading_header": False}),
])
def test_normalization_is_idempotent(raw, kw):
    """두 번 돌려도 같아야 한다 — 단계들이 서로의 출력을 되먹이면 여기서 깨진다."""
    once = norm(raw, **kw)
    assert norm(once, **kw) == once
