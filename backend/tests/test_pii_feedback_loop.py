"""PII 마스킹 전수 수집·라벨링·오탐 신고 루프 + 패치노트 공지 (2026-08-13).

구조: 채팅에서 NER 마스킹된 **모든 단어**가 자동 등재(observe_many) →
사용자 신고는 reported 플래그 + **선보고 후조치**(즉시 마스킹 제외) →
관리자가 correct(정탐, 마스킹 유지·복귀)/wrong(오탐, 영구 제외) 라벨.
구조적 PII(주민번호·전화…)는 어느 경로로도 등재·허용 불가.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest

SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "piiF.db"))
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)
    monkeypatch.delenv("AUTH_DEV_BYPASS_USER", raising=False)

    from src import announcements as A
    from src import persistence as P
    from src.guardrail import pii_terms as T
    from src.middleware.auth import invalidate_whitelist_cache
    from src.persistence.settings_repo import reset_settings_repo_cache
    from src.persistence.whitelist_repo import reset_whitelist_repo_cache

    def _reset():
        for f in (P.get_users_repo, P.get_events_repo, P.get_reports_repo,
                  P.get_feedback_repo, P.get_blob_store):
            f.cache_clear()
        reset_whitelist_repo_cache()
        invalidate_whitelist_cache()
        reset_settings_repo_cache()
        T.invalidate_cache()
        A.invalidate_cache()

    _reset()
    yield
    _reset()


def _token(sub="u-1", email="alice@example.com"):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "email": email, "email_verified": True,
         "iat": now, "exp": now + 3600},
        SECRET, algorithm="HS256",
    )


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _admin_headers():
    return {"Authorization": f"Bearer {_token(sub='adm', email='boss@example.com')}"}


def _own_thread(client, headers, tid="t_pii_1"):
    """호출 사용자를 upsert 시킨 뒤 그 소유의 thread 를 만들어 준다."""
    from src.persistence import get_users_repo
    from src.persistence.threads_repo import get_threads_repo

    # /announcements 는 2026-09-02 부터 공개(무인증)라 upsert 가 안 됨 — 보호 라우트로.
    assert client.get("/me/prefs", headers=headers).status_code == 200
    uid = get_users_repo().get_by_email("boss@example.com").id
    get_threads_repo().ensure_thread(tid, user_id=uid)
    return tid


# ---------------------------------------------------------------------------
# 레지스트리 + gate 통합
# ---------------------------------------------------------------------------
def test_observe_collects_all_masked_terms_without_unmasking():
    from src.guardrail import pii_terms
    from src.guardrail.gate import _stoplisted

    n = pii_terms.observe_many(
        [{"term": "판독유예", "placeholder": "[이름]"},
         {"term": "판독유예", "placeholder": "[이름]"},
         {"term": "김영희", "placeholder": "[이름]"},
         {"term": "010-1234-5678", "placeholder": "[이름]"}],  # 구조적 PII → 스킵
        thread_id="t-1")
    assert n == 3  # 전화번호는 조용히 제외

    items = {i["term"]: i for i in pii_terms.list_terms()}
    assert set(items) == {"판독유예", "김영희"}
    assert items["판독유예"]["count"] == 2
    assert items["판독유예"]["status"] == "unlabeled"
    # 자동 수집은 마스킹 동작을 바꾸지 않는다
    assert not _stoplisted("판독유예")
    assert not _stoplisted("김영희")


def test_report_immediately_unmasks_and_correct_label_restores():
    from src.guardrail import pii_terms
    from src.guardrail.gate import _stoplisted

    entry = pii_terms.report("판독유예", placeholder="[이름]", user_id="u-1")
    assert entry["status"] == "reported"
    assert entry["unmasked"] is True
    assert _stoplisted("판독유예")                # 선보고 — 신고 즉시 마스킹 제외
    assert _stoplisted("판독유예를")              # 조사 변형도 동일 규칙

    # 후조치 — correct(진짜 개인정보) 라벨 시 즉시 마스킹 복귀
    pii_terms.label("판독유예", "correct", labeled_by="boss@example.com")
    assert not _stoplisted("판독유예")

    # correct 라벨 단어는 재신고해도 조용히 안 풀린다
    entry = pii_terms.report("판독유예", user_id="u-2")
    assert entry["status"] == "correct"
    assert entry["unmasked"] is False
    assert entry["report_count"] == 2
    assert not _stoplisted("판독유예")


def test_wrong_label_unmasks_and_remove_restores():
    from src.guardrail import pii_terms
    from src.guardrail.gate import _stoplisted

    # 자동 수집분(신고 없음)도 관리자가 wrong 라벨하면 마스킹 제외
    pii_terms.observe_many([{"term": "성능평가유예", "placeholder": "[이름]"}])
    assert not _stoplisted("성능평가유예")
    pii_terms.label("성능평가유예", "wrong", labeled_by="boss@example.com")
    assert _stoplisted("성능평가유예")

    pii_terms.remove("성능평가유예")
    assert not _stoplisted("성능평가유예")        # 철회 즉시 원복


def test_structural_pii_never_allowed():
    from src.guardrail import pii_terms

    with pytest.raises(pii_terms.TermRejected):
        pii_terms.report("010-1234-5678")         # 전화번호 — 신고 거부

    # DB 를 직접 오염시켜도 wrong 라벨 단계가 다시 막는다.
    pii_terms.report("정상용어")
    from src.persistence.settings_repo import get_settings_repo
    import json
    raw = json.loads(get_settings_repo().get("pii_terms"))
    raw["terms"]["950101-1234567"] = dict(raw["terms"]["정상용어"])
    get_settings_repo().set("pii_terms", json.dumps(raw, ensure_ascii=False))
    pii_terms.invalidate_cache()
    with pytest.raises(pii_terms.TermRejected):
        pii_terms.label("950101-1234567", "wrong")


# ---------------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------------
def test_feedback_pii_route_and_admin_labeling():
    client = _client()
    h = _admin_headers()
    tid = _own_thread(client, h)

    from src.guardrail import pii_terms
    # 자동 수집분이 미리 있는 상태(전수 수집)
    pii_terms.observe_many([{"term": "통합운영", "placeholder": "[이름]"},
                            {"term": "이수현", "placeholder": "[이름]"}])

    r = client.post("/feedback/pii", headers=h, json={
        "thread_id": tid, "term": "통합운영", "placeholder": "[이름]"})
    assert r.status_code == 200
    assert r.json()["status"] == "reported"
    assert r.json()["unmasked"] is True           # 선보고 — 즉시 적용

    from src.guardrail.gate import _stoplisted
    assert _stoplisted("통합운영")

    # 구조적 PII 는 신고 단계에서 422
    assert client.post("/feedback/pii", headers=h, json={
        "thread_id": tid, "term": "010-1234-5678"}).status_code == 422

    # 남의 thread 로는 신고 불가(404 — 존재 비노출)
    assert client.post("/feedback/pii", headers={
        "Authorization": f"Bearer {_token(sub='u-x', email='x@x.com')}",
    }, json={"thread_id": tid, "term": "아무말"}).status_code == 404

    # 개선리스트: 전체 2건, 신고분만 필터하면 1건
    assert client.get("/admin/pii-terms", headers=h).json()["count"] == 2
    rep = client.get("/admin/pii-terms?reported_only=true", headers=h).json()
    assert [i["term"] for i in rep["items"]] == ["통합운영"]
    unl = client.get("/admin/pii-terms?status=unlabeled", headers=h).json()
    assert [i["term"] for i in unl["items"]] == ["이수현"]

    # 라벨링: 신고분을 correct(진짜 개인정보) → 즉시 마스킹 복귀
    r = client.post("/admin/pii-terms/통합운영", headers=h,
                    json={"label": "correct"})
    assert r.status_code == 200 and r.json()["unmasked"] is False
    assert not _stoplisted("통합운영")

    # 자동 수집분을 wrong(오탐) → 마스킹 제외
    r = client.post("/admin/pii-terms/이수현", headers=h,
                    json={"label": "wrong"})
    assert r.status_code == 200 and r.json()["unmasked"] is True
    assert _stoplisted("이수현")

    # 잘못된 라벨·미등재 단어
    assert client.post("/admin/pii-terms/통합운영", headers=h,
                       json={"label": "maybe"}).status_code == 422
    assert client.post("/admin/pii-terms/없는말", headers=h,
                       json={"label": "wrong"}).status_code == 404


def test_announcements_publish_and_latest():
    client = _client()
    h = _admin_headers()

    # 발행 전 — null
    r = client.get("/announcements/latest", headers=h)
    assert r.status_code == 200 and r.json()["announcement"] is None

    r = client.post("/admin/announcements", headers=h, json={
        "title": "8월 13일 업데이트",
        "items": ["PII 오탐 신고 기능 추가", "검색 품질 개선"]})
    assert r.status_code == 201
    note_id = r.json()["announcement"]["id"]

    r = client.get("/announcements/latest", headers=h)
    latest = r.json()["announcement"]
    assert latest["id"] == note_id
    assert latest["items"] == ["PII 오탐 신고 기능 추가", "검색 품질 개선"]

    # 두 번째 발행이 latest 가 되고, 목록은 최신순
    r2 = client.post("/admin/announcements", headers=h, json={
        "title": "8월 14일 업데이트", "items": ["보고서 속도 개선"]})
    assert r2.status_code == 201
    assert client.get("/announcements/latest", headers=h).json()[
        "announcement"]["title"] == "8월 14일 업데이트"
    titles = [n["title"] for n in
              client.get("/announcements", headers=h).json()["items"]]
    assert titles == ["8월 14일 업데이트", "8월 13일 업데이트"]

    # 철회하면 이전 노트가 latest 로 복귀
    rid = r2.json()["announcement"]["id"]
    assert client.delete(f"/admin/announcements/{rid}",
                         headers=h).status_code == 200
    assert client.get("/announcements/latest", headers=h).json()[
        "announcement"]["id"] == note_id

    # 검증 — 빈 items 는 422
    assert client.post("/admin/announcements", headers=h, json={
        "title": "x", "items": []}).status_code == 422
