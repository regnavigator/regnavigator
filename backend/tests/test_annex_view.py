"""별표·서식 HWP → 뷰어 HTML (2026-09-08)."""
import os

import pytest


def test_non_hwp_rejected_and_sanitize():
    from src.annex_view import AnnexViewError, _inline_css, _sanitize, convert_hwp_bytes, is_hwp5

    assert not is_hwp5(b"PK\x03\x04zip")
    with pytest.raises(AnnexViewError):
        convert_hwp_bytes(b"PK\x03\x04" + b"x" * 300)
    html = _inline_css('<?xml version="1.0"?><!DOCTYPE html><html><head><link rel="stylesheet" href="styles.css"/></head><body>x</body></html>', "p{}")
    assert html.startswith("<html>") and "<style>p{}" in html and "styles.css" not in html
    dirty = '<div onclick="x()">a</div><script>bad()</script><iframe src="u"></iframe>'
    clean = _sanitize(dirty)
    assert "<script" not in clean and "<iframe" not in clean and "onclick" not in clean


def test_convert_real_sample_renders_tables():
    """실제 HWP5 변환(pyhwp) — 종전 샘플(local/_hwp/form3.hwp)은 gitignore 된 로컬 경로라 CI 는 물론
    로컬에도 없어 항상 skip 이었다(2026-09-22). 공개 고시(HIRA 급여기준, 10KB)를 fixture 로 커밋."""
    from src.annex_view import convert_hwp_bytes

    path = os.path.join(os.path.dirname(__file__), "fixtures", "hira_notice_clonazepam.hwp")
    html = convert_hwp_bytes(open(path, "rb").read())
    assert "<table" in html and "<style>" in html
    assert "Clonazepam" in html and "요양급여" in html


def test_route_soft_fail_when_no_link(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import src.annex_view as V
    from src.api import app

    monkeypatch.setenv("ANNEX_VIEW_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(V, "resolve_download_url", lambda k: None)
    client = TestClient(app)
    r = client.get("/annex/view", params={"key": "L_000300F_attachment"})
    # 변환 불가는 200 + html null + reason (2026-09-09: 503 은 콘솔 에러·사유 불명)
    assert r.status_code == 200
    assert r.json()["html"] is None and "링크" in r.json()["reason"]
    assert client.get("/annex/view", params={"key": ""}).status_code == 422


def test_route_serves_cached_html(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import src.annex_view as V
    from src.api import app

    monkeypatch.setenv("ANNEX_VIEW_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(V, "resolve_download_url", lambda k: "https://x/form.hwp")
    monkeypatch.setattr("src.form_fill.fetch_form_bytes", lambda url: b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 300)
    monkeypatch.setattr(V, "convert_hwp_bytes", lambda data: "<html><body><table><tr><td>서식</td></tr></table></body></html>")
    client = TestClient(app)
    r = client.get("/annex/view", params={"key": "L_000300F_attachment"})
    assert r.status_code == 200 and "<table" in r.json()["html"] and r.json()["reason"] is None
    # 캐시 적중 — 변환 함수를 다시 부르지 않는다
    monkeypatch.setattr(V, "convert_hwp_bytes", lambda data: (_ for _ in ()).throw(RuntimeError("no")))
    assert client.get("/annex/view", params={"key": "L_000300F_attachment"}).status_code == 200
