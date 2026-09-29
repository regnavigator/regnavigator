"""law.go.kr 외부 링크 빌더 — 조 path / 별표 정책 회귀.

정정(2026-05-22): 조 단위 path(`/{cat}/{명}/제N조`)는 법령·행정규칙·자치법규
모두 law.go.kr 친화 URL이 지원(/행정규칙/○○규정/제1조 동작 확인). 별표 path
(`/별표/{N}`)는 법령만 — admrul/ordin 별표는 전문 링크.

회귀: 3161a08 이 admrul/ordin 조 path 를 잘못 떼고 전문으로 강등했던 것 복구.
"""
from __future__ import annotations

from urllib.parse import unquote


# ── search.py _external_url_for_citation (citation 용) ──────────────────────
def _ext(target_type, *, article_num=None, chunk_type="article",
         article_key=None, title="의료기기법"):
    from src.tools.search import _external_url_for_citation
    payload = {"target_type": target_type, "chunk_type": chunk_type}
    if article_key:
        payload["article_key"] = article_key
    pg_meta = {"law_title": title}
    if article_num:
        pg_meta["article_num"] = article_num
    url = _external_url_for_citation(payload, pg_meta)
    return unquote(url) if url else url


def test_ext_law_article_has_jo_path():
    assert _ext("law", article_num="제24조") == \
        "https://www.law.go.kr/법령/의료기기법/제24조"


def test_ext_admrul_article_has_jo_path():
    """회귀 핵심 — 행정규칙도 /제N조 조 path 붙음(전문 강등 아님)."""
    url = _ext("admrul", article_num="제1조", title="의료기기 시판 후 조사에 관한 규정")
    assert url == "https://www.law.go.kr/행정규칙/의료기기 시판 후 조사에 관한 규정/제1조"


def test_ext_ordin_article_has_jo_path():
    url = _ext("ordin", article_num="제3조", title="○○시 조례")
    assert url == "https://www.law.go.kr/자치법규/○○시 조례/제3조"


def test_ext_law_attachment_has_byl_path():
    url = _ext("law", chunk_type="attachment",
               article_key="006364_byl_007_attachment")
    assert url == "https://www.law.go.kr/법령/의료기기법/별표/7"


def test_ext_admrul_attachment_is_full_text_only():
    """별표는 admrul 에서 path 미지원 → 전문 링크(/별표 없음)."""
    url = _ext("admrul", chunk_type="attachment",
               article_key="x_byl_001_attachment", title="○○규정")
    assert url == "https://www.law.go.kr/행정규칙/○○규정"
    assert "별표" not in url


# ── api.py _build_law_go_kr_url (/article 용) ───────────────────────────────
def _build(target_type, *, article_num=None, article_title=None,
           article_key=None, title="의료기기법"):
    from src.api import _build_law_go_kr_url
    meta = {"target_type": target_type, "law_title": title}
    if article_num:
        meta["article_num"] = article_num
    if article_title:
        meta["article_title"] = article_title
    url = _build_law_go_kr_url(meta, article_key=article_key)
    return unquote(url) if url else url


def test_build_admrul_article_has_jo_path():
    url = _build("admrul", article_num="제1조",
                 title="의료기기 시판 후 조사에 관한 규정")
    assert url == "https://www.law.go.kr/행정규칙/의료기기 시판 후 조사에 관한 규정/제1조"


def test_build_ordin_article_has_jo_path():
    assert _build("ordin", article_num="제5조", title="○○조례") == \
        "https://www.law.go.kr/자치법규/○○조례/제5조"


def test_build_law_article_has_jo_path():
    assert _build("law", article_num="제6조") == \
        "https://www.law.go.kr/법령/의료기기법/제6조"


def test_build_law_attachment_has_byl_path():
    url = _build("law", article_num="별표", article_title="별표 7",
                 article_key="006364_byl_007_attachment")
    assert url == "https://www.law.go.kr/법령/의료기기법/별표/7"


def test_build_admrul_attachment_is_full_text_only():
    url = _build("admrul", article_num="별표", title="○○규정",
                 article_key="x_byl_001_attachment")
    assert url == "https://www.law.go.kr/행정규칙/○○규정"
    assert "별표" not in url
