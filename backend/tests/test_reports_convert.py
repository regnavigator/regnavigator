"""보고서 포맷 변환 — md(원본) → docx, 폴백."""
from __future__ import annotations

import pytest

from src.reports_convert import (
    DOCX_MIME,
    ConversionUnavailable,
    _preprocess_md,
    convert,
    is_available,
    md_to_docx,
)


# ── _preprocess_md 단위 회귀 (2026-07-10 리뷰 발견 3건) ──────────────────

def test_preprocess_setext_heading_preserved():
    """앞줄이 텍스트인 `---` 는 setext H2 — `***` 로 바꾸면 헤딩 파괴 +
    리터럴 노출. 빈 줄 뒤 `---` 만 hr 로 치환."""
    md = "Section Title\n---\n\n본문\n\n---\n\n다음"
    out = _preprocess_md(md)
    assert "Section Title\n---" in out          # setext 보존
    assert "\n\n***\n\n다음" in out              # 진짜 hr 만 치환


def test_preprocess_date_lines_not_listified():
    """'2026. 7. 1.' 같은 날짜 연속행을 ordered list 로 오인해 빈 줄을 넣으면
    3중 번호목록으로 변조된다 — bullet 에만 빈 줄 삽입."""
    md = "시행일은 다음과 같습니다.\n2026. 7. 1. 시행 예정입니다."
    assert _preprocess_md(md) == md


def test_preprocess_bullet_after_sentence_gets_blank_line():
    md = "다음 행위는 금지됩니다.\n*   허위 광고. [1]\n*   과대 광고. [2]"
    out = _preprocess_md(md)
    assert "금지됩니다.\n\n*   허위" in out
    # 리스트 항목 사이엔 삽입 X
    assert "[1]\n*   과대" in out


def test_preprocess_code_fence_untouched():
    md = "본문\n\n```\nstep one\n- flag: value\n---\nresult\n```\n"
    assert _preprocess_md(md) == md

_MD = "# 제목\n\n## 개요\n본문 **굵게** 인용 [1]\n\n1. 첫째\n   - 중첩\n2. 둘째\n"


def test_md_passthrough():
    data, mime, ext = convert(_MD, "md")
    assert data == _MD.encode("utf-8")
    assert ext == "md" and mime == "text/markdown"


def test_unknown_format_raises():
    with pytest.raises(ConversionUnavailable):
        convert(_MD, "hwpx")


def test_empty_body_raises():
    with pytest.raises(ConversionUnavailable):
        md_to_docx("")


@pytest.mark.skipif(not is_available(), reason="pandoc 미설치")
def test_docx_is_real_zip_package():
    data, mime, ext = convert(_MD, "docx")
    assert ext == "docx" and mime == DOCX_MIME
    assert data[:2] == b"PK"  # docx = zip 패키지
    assert len(data) > 1000


@pytest.mark.skipif(not is_available(), reason="pandoc 미설치")
def test_docx_with_horizontal_rule_and_disclaimer():
    """가로 구분선(`---`) 회귀 — pandoc 이 `---` 를 YAML 메타데이터 블록 시작으로
    해석해 exitcode 64 로 죽던 버그. 시스템이 붙이는 법적 고지(DISCLAIMER_REPORT)가
    `---` 로 시작해 사실상 모든 실보고서에서 재현됐다(2026-07-10 테스트베드 발견).
    """
    from src.legal import DISCLAIMER_REPORT

    md = "# 보고서\n\n본문 [1]\n" + DISCLAIMER_REPORT
    data, mime, ext = convert(md, "docx")
    assert ext == "docx" and mime == DOCX_MIME
    assert data[:2] == b"PK"


@pytest.mark.skipif(not is_available(), reason="pandoc 미설치")
def test_docx_references_not_mangled_into_table():
    """References 회귀(2026-07-10 실사고) — `---` 구분선 사이의 참고+References
    블록을 pandoc 이 multiline table 로 해석해 1열 표 안에 '## References'·
    '- [1] ...' 가 생 텍스트로 들어갔다. 표 0개 + References 는 헤딩으로."""
    import io

    docx = pytest.importorskip("docx")
    md = (
        "# 보고서\n\n본문 [1]\n\n---\n"
        "**참고**: 본 보고서는 제공된 자료에 기반합니다.\n\n"
        "## References\n\n"
        "- [1] 의료기기법 제25조 (https://www.law.go.kr/법령/의료기기법/제25조)\n"
        "- [2] 의료기기법 제52조 (https://www.law.go.kr/법령/의료기기법/제52조)\n"
        "\n---\n\n## 법적 고지\n\n본 보고서는 참고 자료입니다.\n"
    )
    d = docx.Document(io.BytesIO(convert(md, "docx")[0]))
    assert len(d.tables) == 0, "References 블록이 표로 뭉개짐"
    texts = [p.text for p in d.paragraphs]
    heads = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    assert "References" in heads
    assert any("의료기기법 제25조" in t for t in texts)
    assert not any(t.strip().startswith("- [") for t in texts), "리스트가 리터럴로 남음"


@pytest.mark.skipif(not is_available(), reason="pandoc 미설치")
def test_docx_list_right_after_sentence():
    """빈 줄 없이 문장 직후 시작하는 리스트(writer 흔한 패턴) — pandoc 은 빈 줄
    없인 리스트로 안 보고 문단에 `* 항목` 리터럴로 이어붙였다. 전처리로 정상 리스트."""
    import io

    docx = pytest.importorskip("docx")
    md = (
        "### 1. 형사 처벌\n"
        "다음 행위를 한 자는 처벌됩니다.\n"
        "*   **위반 행위**: 제24조 위반. [2]\n"
        "*   **양벌 규정**: 법인도 벌금형. [3]\n"
    )
    d = docx.Document(io.BytesIO(convert(md, "docx")[0]))
    body = "\n".join(p.text for p in d.paragraphs)
    assert " * " not in body and "* 위반" not in body, "리스트가 문단에 뭉개짐"
    assert any(p.text.startswith("위반 행위") for p in d.paragraphs)


@pytest.mark.skipif(not is_available(), reason="pandoc 미설치")
def test_docx_preserves_structure():
    """헤더·굵게·인용 마커·번호목록(numPr) 보존."""
    import io

    docx = pytest.importorskip("docx")
    d = docx.Document(io.BytesIO(convert(_MD, "docx")[0]))
    heads = [p.style.name for p in d.paragraphs if p.style.name.startswith("Heading")]
    assert "Heading 1" in heads and "Heading 2" in heads
    assert any(r.bold for p in d.paragraphs for r in p.runs)
    assert any("[1]" in p.text for p in d.paragraphs)
    assert "<w:numPr>" in d.element.xml  # 진짜 번호목록


def test_notify_falls_back_to_md_when_convert_fails(monkeypatch):
    """변환 불가 시 .md 로 폴백 — 발송 자체는 계속(보고서 흐름 무영향)."""
    from unittest.mock import patch

    import src.observability.notifications as N

    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_SERVER", raising=False)  # 실 .env 누출 격리(hermetic)
    with patch("src.reports_convert.md_to_docx",
               side_effect=ConversionUnavailable("pandoc 없음")):
        assert N.notify_report_ready(email="a@b.com", thread_id="t",
                                     report_id="r1", report_md=_MD) is True
