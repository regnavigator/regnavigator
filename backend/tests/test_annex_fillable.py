"""GET /annex/fillable — 기입 항목 유무 판정(2026-09-08)."""


def test_annex_fillable_distinguishes_form_and_table(monkeypatch):
    from fastapi.testclient import TestClient
    import src.routes.articles as A
    from src.api import app
    import src.retrieval.search_api_client as SC

    A._FILLABLE_CACHE.clear()
    form_text = (
        "별지 제3호서식\n의료기기 제조허가 신청서\n접수번호 |  | 처리기간 | 10일\n"
        "성명 |  | 생년월일 |  \n주소 |  \n제품명 |  \n년   월   일\n"
        "신청인 (서명 또는 인)\n식품의약품안전처장 귀하\n"
    )
    table_text = "별표 7 광고 금지 표현\n1. 거짓·과대 광고\n2. 부작용 부정\n3. 객관적 근거 없는 비교\n"
    bodies = {"L1_3_attachment": {"full_text": form_text}, "L1_7_attachment": {"full_text": table_text}}
    monkeypatch.setattr(SC, "fetch_bodies", lambda keys: {k: bodies.get(k) for k in keys})
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    client = TestClient(app)

    r = client.get("/annex/fillable", params={"key": "L1_3_attachment"})
    assert r.status_code == 200 and r.json()["fillable"] is True and r.json()["field_count"] >= 2
    r = client.get("/annex/fillable", params={"key": "L1_7_attachment"})
    assert r.status_code == 200 and r.json()["fillable"] is False and r.json()["field_count"] == 0
    assert client.get("/annex/fillable", params={"key": ""}).status_code == 422
    # 캐시 — 두 번째 호출은 fetch_bodies 를 안 부른다
    monkeypatch.setattr(SC, "fetch_bodies", lambda keys: (_ for _ in ()).throw(RuntimeError("no")))
    assert client.get("/annex/fillable", params={"key": "L1_3_attachment"}).json()["fillable"] is True
    A._FILLABLE_CACHE.clear()
