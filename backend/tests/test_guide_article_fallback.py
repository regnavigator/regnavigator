"""법령 외 문서(가이드라인) 원문 조회 — 2026-08-04.

사고: 가이드라인 인용에 '법령정보센터에서 보기' 가 붙던 것을 걷어냈다(법령정보
센터에 없는 문서라 잘못된 링크). 그런데 걷어내고 보니 **원문 접근 경로가 통째로
사라졌다** — `/article` 은 openlaw PG(법령 8종)만 조회해 가이드라인 키는 404 였고,
프런트는 snippet 만 보여줬다. 규제 상담에서 근거 전문을 못 여는 건 치명적이다.

그래서 PG 미적중 시 검색 API `/articles/bodies` 로 폴백한다. 이 파일이 잠그는 것:
  ① 가이드라인 키로 본문이 나온다
  ② 법령 조회 경로는 그대로다(폴백이 정상 경로를 가리지 않는다)
  ③ **없는 원문 링크를 지어내지 않는다** — source_url 이 없으면 external_url=None
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_guide_key_falls_back_to_search_api(monkeypatch):
    import src.routes.articles as ar

    monkeypatch.setattr(ar, "_fetch_body_from_search_api", lambda k: {
        "article_key": k, "target_type": "guide", "law_title": "의료기기 임상시험 안내서",
        "full_text": "본문", "external_url": None,
    })
    # PG 조회는 실패시킨다(가이드라인은 PG 에 없다)
    monkeypatch.setattr(ar, "__name__", ar.__name__)  # no-op, 가독성용

    from src.retrieval import pg_client
    monkeypatch.setattr(pg_client, "fetch_articles", lambda *a, **k: [])
    monkeypatch.setattr(pg_client, "_get_pool", lambda: None)

    out = ar.get_article(key="hffe2e41e6c474eea#8")
    assert out["target_type"] == "guide"
    assert out["full_text"] == "본문"


def test_no_body_still_404(monkeypatch):
    """폴백도 못 찾으면 404 — 조용히 빈 응답을 주지 않는다."""
    import src.routes.articles as ar
    from src.retrieval import pg_client

    monkeypatch.setattr(ar, "_fetch_body_from_search_api", lambda k: None)
    monkeypatch.setattr(pg_client, "fetch_articles", lambda *a, **k: [])
    monkeypatch.setattr(pg_client, "_get_pool", lambda: None)

    with pytest.raises(HTTPException) as e:
        ar.get_article(key="없는키")
    assert e.value.status_code == 404


def test_external_url_is_never_invented(monkeypatch):
    """source_url 이 없으면 external_url 은 None — 법령정보센터 링크 금지."""
    import src.routes.articles as ar
    from src.retrieval import search_api_client as sc

    monkeypatch.setattr(sc, "fetch_bodies", lambda keys: {
        keys[0]: {"full_text": "가이드 본문", "title": "의료기기 안내서",
                  "publisher": "식품의약품안전처", "source_url": None},
    })
    out = ar._fetch_body_from_search_api("g#1")
    assert out is not None
    assert out["external_url"] is None, "없는 원문 링크를 지어냈다"
    assert out["target_type"] == "guide"


def test_external_url_used_when_etl_provides_it(monkeypatch):
    """ETL 이 source_url 을 채우면 그건 그대로 쓴다(향후 대응)."""
    import src.routes.articles as ar
    from src.retrieval import search_api_client as sc

    monkeypatch.setattr(sc, "fetch_bodies", lambda keys: {
        keys[0]: {"full_text": "본문", "title": "안내서",
                  "source_url": "https://mfds.go.kr/docs/1.pdf"},
    })
    assert ar._fetch_body_from_search_api("g#1")["external_url"] == "https://mfds.go.kr/docs/1.pdf"


def test_empty_body_is_not_a_hit(monkeypatch):
    """본문이 비면 폴백 실패로 취급 — 빈 모달을 띄우지 않는다."""
    import src.routes.articles as ar
    from src.retrieval import search_api_client as sc

    monkeypatch.setattr(sc, "fetch_bodies", lambda keys: {keys[0]: {"full_text": "   "}})
    assert ar._fetch_body_from_search_api("g#1") is None
