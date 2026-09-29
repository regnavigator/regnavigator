"""PII 라벨링 문맥 팝오버(2026-09-21) — 가린 질문의 앞뒤를 보여준다(원문은 저장되지 않음).

운영자: "필터된 단어만 보고는 알 수 없는 경우가 있다 — 주변 원문을 팝오버로".
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from src.guardrail import pii_terms
from src.persistence import get_users_repo
from src.persistence.threads_repo import get_threads_repo

SECRET = "test-secret-pii-context-0123456789"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@medireg.test")
    get_users_repo().upsert(id="u-boss", email="boss@medireg.test")
    pii_terms.invalidate_cache()
    from src.api import app

    now = int(time.time())
    tok = pyjwt.encode({"sub": "u-boss", "email": "boss@medireg.test", "email_verified": True,
                        "iat": now, "exp": now + 600}, SECRET, algorithm="HS256")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


def _thread(tid: str, text: str):
    repo = get_threads_repo()
    repo.ensure_thread(tid, user_id="u-doc")
    repo.append_messages(tid, [HumanMessage(content=text, id=f"h_{tid}"),
                               AIMessage(content="답변", id=f"a_{tid}")])


def test_context_shows_masked_neighborhood_across_threads(client):
    t1, t2 = "t_" + "a" * 32, "t_" + "b" * 32
    _thread(t1, "의료기관 [이름] 규정에 따라 IRB 와 DRB 를 함께 운영하는 경우 심의 절차가 궁금합니다")
    _thread(t2, "[이름] 과 [이름] 을 비교하면?")
    pii_terms.observe_many([{"term": "통합운영", "placeholder": "[이름]"}], thread_id=t1)
    pii_terms.observe_many([{"term": "통합운영", "placeholder": "[이름]"}], thread_id=t2)

    r = client.get("/admin/pii-terms/context", params={"term": "통합운영"}).json()
    assert r["placeholder"] == "[이름]" and r["threads_known"] == 2
    by = {c["thread_id"]: c for c in r["contexts"]}
    assert by[t1]["before"].endswith("의료기관 ") and by[t1]["mark"] == "[이름]"
    assert by[t1]["after"].startswith(" 규정에 따라") and by[t1]["same_kind"] == 1
    assert by[t2]["same_kind"] == 2                        # 어느 자리인지 특정 불가 → 화면이 안내
    assert "통합운영" not in by[t1]["before"] + by[t1]["after"]   # 원문 복원이 아니다


def test_context_counts_deleted_threads_and_404(client):
    pii_terms.observe_many([{"term": "홍길동", "placeholder": "[이름]"}], thread_id="t_" + "c" * 32)
    r = client.get("/admin/pii-terms/context", params={"term": "홍길동"}).json()
    assert r["contexts"] == [] and r["missing_threads"] == 1
    assert client.get("/admin/pii-terms/context", params={"term": "없는말"}).status_code == 404


def test_threads_list_keeps_latest_five():
    for i in range(7):
        pii_terms.observe_many([{"term": "영상분석", "placeholder": "[이름]"}],
                               thread_id=f"t_{i:032x}")
    e = pii_terms._load()["terms"]["영상분석"]
    assert len(e["threads"]) == 5 and e["threads"][0] == f"t_{6:032x}"
    assert e["thread_id"] == f"t_{0:032x}"                  # 최초 관측은 하위호환으로 유지


# ── 정확한 가림 자리(2026-09-21 — "다 똑같은 문맥이면 구분을 어떻게 하냐") ──────────

REF_ORIG = "참고문헌: Nielsen, M. M., Soetekouw, R. H., 연락처 010-1234-5678 Horton, J. 끝"
REF_MASK = "참고문헌: [이름], M. M., [이름], R. H., 연락처 [전화번호] [이름], J. 끝"


def test_locate_finds_each_terms_own_slot():
    r = pii_terms.locate(REF_ORIG, REF_MASK, ["Nielsen", "Soetekouw", "Horton"])
    assert r["Nielsen"][0]["before"].endswith("참고문헌: ")
    assert r["Soetekouw"][0]["before"].endswith("[이름], M. M., ")
    assert r["Horton"][0]["before"].endswith("[전화번호] ")           # 수집 밖 치환은 건너뛰고 재동기화
    for v in r.values():
        assert "Nielsen" not in v[0]["before"] + v[0]["after"]      # 가린 글 기준 — 원문 단어 없음
        assert "010-1234" not in v[0]["before"] + v[0]["after"]


def test_locate_stops_rather_than_guess_on_misalignment():
    assert pii_terms.locate("완전히 다른 글", "[이름] 은 누구", ["홍길동"]) == {}


def test_observe_with_original_stores_exact_samples_and_context_uses_them(client):
    tid = "t_" + "d" * 32
    _thread(tid, REF_MASK)
    spans = [{"term": t, "placeholder": "[이름]"} for t in ("Nielsen", "Soetekouw", "Horton")]
    pii_terms.observe_many(spans, thread_id=tid, message_id=f"h_{tid}",
                           original=REF_ORIG, masked=REF_MASK)
    a = client.get("/admin/pii-terms/context", params={"term": "Soetekouw"}).json()
    b = client.get("/admin/pii-terms/context", params={"term": "Horton"}).json()
    assert a["contexts"][0]["exact"] is True and b["contexts"][0]["exact"] is True
    assert a["contexts"][0]["before"] != b["contexts"][0]["before"]   # 단어마다 다른 자리
    raw = pii_terms._load()["terms"]["Soetekouw"]
    assert "Soetekouw" not in str(raw["samples"])                  # 저장본에도 원문 없음


def test_legacy_entries_show_siblings_from_same_question(client):
    tid = "t_" + "e" * 32
    _thread(tid, REF_MASK)
    for t in ("Nielsen", "Soetekouw", "Horton"):                    # 옛 방식(원문 없이) 수집
        pii_terms.observe_many([{"term": t, "placeholder": "[이름]"}], thread_id=tid)
    r = client.get("/admin/pii-terms/context", params={"term": "Nielsen"}).json()
    assert r["contexts"][0]["exact"] is False and r["contexts"][0]["same_kind"] == 3
    assert set(r["siblings"]) == {"Soetekouw", "Horton"}
