"""사용자가 고른 서식으로 작성 (2026-08-26).

보고서는 자체 검색을 돌기 때문에, 지정이 없으면 사용자가 채팅에서 확인한
서식과 다른 것을 집을 수 있다. 인용/별표 모달의 [이 서식으로 작성]이 보낸
`form_article_key` 를 근거 **맨 앞**에 주입해 (1) writer 가 그 구조로 쓰고
(2) 다운로드 시 pick_form_citation 이 같은 것을 고르게 한다.
"""
from __future__ import annotations

import pytest

from src import report_pipeline as rp
from src.tools.citations import pick_form_citation


def _install(monkeypatch, *, body=None, link=None):
    import src.retrieval.search_api_client as sac
    monkeypatch.setattr(
        sac, "fetch_bodies",
        lambda keys: ({keys[0]: {"title": "의료기기 제조업 허가신청서",
                                 "full_text": body}} if body else {}))
    monkeypatch.setattr(
        "src.tools.citations._download_url_for_attachment",
        lambda payload, meta: link, raising=False)
    monkeypatch.setattr(rp, "_PER_SOURCE_TEXT_CAP", 1500, raising=False)


def test_pinned_asset_built(monkeypatch):
    _install(monkeypatch, body="서식 본문" * 100,
             link="https://www.law.go.kr/LSW/flDownload.do?flSeq=1")
    out = rp.pinned_form_asset("009740_000100F_attachment")
    assert len(out) == 1
    c = out[0]
    assert c["article_key"] == "009740_000100F_attachment"
    assert c["doc_category"] == "법령별표서식"      # 다운로드 선별이 이걸 본다
    assert c["tier"] == "T1"                        # 법령 원문 등급
    assert c["download_url"].endswith("flSeq=1")
    assert 0 < len(c["text"]) <= 1500               # writer 예산 상한 준수


def test_pinned_asset_is_pickable_as_form(monkeypatch):
    """주입분이 다운로드 시 그대로 선택돼야 한 경로로 정합된다."""
    _install(monkeypatch, body="본문",
             link="https://www.law.go.kr/LSW/flDownload.do?flSeq=7")
    pinned = rp.pinned_form_asset("009740_000100F_attachment")
    other = {"article_key": "009740_000100E_attachment",
             "doc_category": "법령별표서식",
             "download_url": "https://www.law.go.kr/LSW/flDownload.do?flSeq=9"}
    picked = pick_form_citation(pinned + [other])
    assert picked["download_url"].endswith("flSeq=7")   # 서식(F) 우선 = 지정분


def test_pinned_asset_empty_inputs(monkeypatch):
    _install(monkeypatch, body="본문", link=None)
    assert rp.pinned_form_asset("") == []
    assert rp.pinned_form_asset(None) == []


def test_pinned_asset_skipped_when_nothing_found(monkeypatch):
    """본문도 링크도 없으면 주입하지 않는다 — 빈 근거로 [1]을 낭비하지 않게."""
    _install(monkeypatch, body=None, link=None)
    assert rp.pinned_form_asset("없는키_000100F_attachment") == []


def test_pinned_asset_link_only(monkeypatch):
    """본문 조회는 실패해도 링크가 있으면 살린다(다운로드는 가능해야)."""
    _install(monkeypatch, body=None,
             link="https://www.law.go.kr/LSW/flDownload.do?flSeq=3")
    out = rp.pinned_form_asset("009740_000100F_attachment")
    assert len(out) == 1 and out[0]["download_url"].endswith("flSeq=3")


@pytest.mark.parametrize("key,ok", [
    ("009740_000100F_attachment", True),
    ("admrul:hira_board:고시:8#0", True),      # 콜론·#·한글 포함 키
    ("a", False),                              # 너무 짧음
    ("bad key!", False),                       # 공백·특수문자
])
def test_route_key_format_guard(key, ok):
    """라우트 형식 가드 — 조회는 잡에서 하되 이상한 값은 여기서 버린다."""
    import re
    assert bool(re.match(r"^[\w:#\-]{4,120}$", key)) is ok
