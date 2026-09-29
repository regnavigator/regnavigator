

def test_hidden_note_skipped_in_latest(monkeypatch, tmp_path):
    """노출 금지(2026-08-28) — 숨긴 노트는 기록엔 남고 latest 에서만 빠진다."""
    import src.announcements as A
    from src.persistence.settings_repo import reset_settings_repo_cache

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "a.db"))
    reset_settings_repo_cache(); A.invalidate_cache()
    old = A.publish(title="이전 노트", items=["x"])
    new = A.publish(title="최신 노트", items=["y"])
    assert A.latest()["id"] == new["id"]
    assert A.set_hidden(new["id"], True) is True
    # 2026-09-18 사고: 최신을 숨기면 이전 노트가 latest 로 올라와 옛 노트가 새 팝업으로
    # 되살아났다. 팝업 후보는 가장 최근 발행 1건뿐 — 그게 숨김이면 팝업은 없다.
    assert A.latest() is None
    assert [n["id"] for n in A.list_notes()] == [old["id"]]  # 게시판엔 이전 노트가 그대로
    assert len(A.list_notes(include_hidden=True)) == 2  # 기록은 그대로(사용자 목록에선 제외)
    assert A.set_hidden(new["id"], False) is True  # 재노출
    assert A.latest()["id"] == new["id"]
    reset_settings_repo_cache(); A.invalidate_cache()


def test_list_excludes_hidden_and_searches(monkeypatch, tmp_path):
    """업데이트 내역 게시판(2026-09-02): 숨김 제외 + 키워드 AND 검색."""
    import src.announcements as A
    from src.persistence.settings_repo import reset_settings_repo_cache

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "b.db"))
    reset_settings_repo_cache(); A.invalidate_cache()
    a = A.publish(title="보고서 중단 버튼 추가", items=["진행 카드에 [중단] 버튼"])
    b = A.publish(title="모달 디자인 통일", items=["확인·설정 창 톤 통일", "한국어 줄바꿈"])
    A.set_hidden(b["id"], True)
    ids = [n["id"] for n in A.list_notes()]
    assert ids == [a["id"]]                                   # 숨김 제외
    assert [n["id"] for n in A.list_notes(include_hidden=True)] == [b["id"], a["id"]]
    assert [n["id"] for n in A.list_notes(q="중단")] == [a["id"]]
    assert A.list_notes(q="중단 카드") and A.list_notes(q="중단 없는말") == []  # AND
    assert A.list_notes(q="줄바꿈") == []                     # 숨김은 검색에도 안 잡힘
    reset_settings_repo_cache(); A.invalidate_cache()


def test_announcements_list_is_public_and_admin_list_includes_hidden(monkeypatch, tmp_path):
    """랜딩 게시판이 비로그인으로 읽는다 — 인증 헤더 없이 200. admin 목록은 숨김 포함."""
    import src.announcements as A
    from src.persistence.settings_repo import reset_settings_repo_cache
    from fastapi.testclient import TestClient
    from src.api import app

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "c.db"))
    monkeypatch.setenv("NEXTAUTH_SECRET", "x" * 32)   # 운영 모드 — 무헤더면 보호 라우트 401
    reset_settings_repo_cache(); A.invalidate_cache()
    n = A.publish(title="공개 확인", items=["x"])
    A.set_hidden(n["id"], True)
    client = TestClient(app)
    r = client.get("/announcements?q=공개")
    assert r.status_code == 200 and r.json()["items"] == []  # 공개지만 숨김 제외
    assert client.get("/announcements/latest").status_code == 200
    assert client.get("/admin/announcements").status_code in (401, 403)  # admin 은 보호
    reset_settings_repo_cache(); A.invalidate_cache()


def test_publish_version_field(monkeypatch, tmp_path):
    """버전 표기(2026-09-02) — 선택 필드, 20자 초과 거부, 검색 대상."""
    import pytest
    import src.announcements as A
    from src.persistence.settings_repo import reset_settings_repo_cache

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "d.db"))
    reset_settings_repo_cache(); A.invalidate_cache()
    n = A.publish(title="게시판", items=["x"], version=" v0.8.0 ")
    assert n["version"] == "v0.8.0"
    assert A.publish(title="무버전", items=["x"])["version"] is None
    assert [m["id"] for m in A.list_notes(q="v0.8")] == [n["id"]]
    with pytest.raises(ValueError):
        A.publish(title="t", items=["x"], version="v" * 21)
    reset_settings_repo_cache(); A.invalidate_cache()


def test_publish_feature_field_filter_and_order(monkeypatch, tmp_path):
    """기능 영역(2026-09-07) — 선택 필드, 30자 초과 거부, feature 필터, 탭 순서는 FEATURES 순."""
    import pytest
    import src.announcements as A
    from src.persistence.settings_repo import reset_settings_repo_cache

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "d.db"))
    reset_settings_repo_cache(); A.invalidate_cache()
    a = A.publish(title="서식 채우기", items=["x"], feature=" 서류 작성 ")
    b = A.publish(title="보고서 중단", items=["x"], feature="심층 보고서")
    c = A.publish(title="기타", items=["x"], feature="새 영역")
    hidden = A.publish(title="숨김", items=["x"], feature="검색·답변")
    A.set_hidden(hidden["id"], True)
    assert a["feature"] == "서류 작성"
    assert A.publish(title="무영역", items=["x"])["feature"] is None
    assert [m["id"] for m in A.list_notes(feature="심층 보고서")] == [b["id"]]
    assert [m["id"] for m in A.list_notes(q="서류")] == [a["id"]]
    # FEATURES 순(심층 보고서 < 서류 작성) + 목록 밖 값은 뒤, 숨김은 제외
    assert A.feature_order() == ["심층 보고서", "서류 작성", "새 영역"]
    assert "검색·답변" in A.feature_order(include_hidden=True)
    assert c["feature"] == "새 영역"
    with pytest.raises(ValueError):
        A.publish(title="t", items=["x"], feature="f" * 31)
    reset_settings_repo_cache(); A.invalidate_cache()


def test_last_seen_announcement_pref_roundtrip(monkeypatch, tmp_path):
    """업데이트 팝업 마지막 확인 id 를 서버가 기억(2026-09-07) — /me/prefs GET/PATCH."""
    import time
    import jwt as pyjwt
    from fastapi.testclient import TestClient

    secret = "test-secret-32-bytes-min-padding-for-hs256"
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("NEXTAUTH_SECRET", secret)
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)
    from src import persistence as P
    from src.persistence.settings_repo import reset_settings_repo_cache
    for f in (P.get_users_repo, P.get_events_repo):
        f.cache_clear()
    reset_settings_repo_cache()
    from src.api import app
    client = TestClient(app)
    now = int(time.time())
    tok = pyjwt.encode({"sub": "u-seen", "email": "seen@x.com", "email_verified": True,
                        "iat": now, "exp": now + 600}, secret, algorithm="HS256")
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/me/prefs", headers=h).json()["last_seen_announcement_id"] is None
    r = client.patch("/me/prefs", json={"last_seen_announcement_id": "note_abc"}, headers=h)
    assert r.status_code == 200 and r.json()["last_seen_announcement_id"] == "note_abc"
    assert client.get("/me/prefs", headers=h).json()["last_seen_announcement_id"] == "note_abc"
    # 기존 필드만 보내도 동작, 빈 body 는 422
    assert client.patch("/me/prefs", json={"report_email_opt_in": False}, headers=h).status_code == 200
    assert client.patch("/me/prefs", json={}, headers=h).status_code == 422
    for f in (P.get_users_repo, P.get_events_repo):
        f.cache_clear()
    reset_settings_repo_cache()


def test_popup_flag_is_independent_of_board_visibility(monkeypatch, tmp_path):
    """popup=False 노트는 게시판에는 쌓이고 팝업은 안 뜬다 — 이전 노트로 내려가지도 않는다."""
    import src.announcements as A
    from src.persistence.settings_repo import reset_settings_repo_cache

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "a.db"))
    reset_settings_repo_cache(); A.invalidate_cache()
    old = A.publish(title="팝업 있던 옛 노트", items=["x"])
    quiet = A.publish(title="게시판 전용 노트", items=["y"], popup=False)
    assert A.latest() is None                                  # 옛 노트가 되살아나지 않는다
    assert [n["id"] for n in A.list_notes()] == [quiet["id"], old["id"]]
    assert A.set_popup(quiet["id"], True) is True
    assert A.latest()["id"] == quiet["id"]
    assert A.latest([quiet["id"]]) is None                     # 이미 본 노트면 안 띄움
    assert A.set_popup("nope", False) is False
    reset_settings_repo_cache(); A.invalidate_cache()


def test_admin_patch_popup_and_latest_seen_param(monkeypatch, tmp_path):
    import src.announcements as A
    from src.persistence.settings_repo import reset_settings_repo_cache
    from src.routes.announcements import get_latest_announcement

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "a.db"))
    reset_settings_repo_cache(); A.invalidate_cache()
    n = A.publish(title="노트", items=["x"])
    assert get_latest_announcement(seen="")["announcement"]["id"] == n["id"]
    assert get_latest_announcement(seen=f"zzz, {n['id']}")["announcement"] is None
    A.set_popup(n["id"], False)
    assert get_latest_announcement(seen="")["announcement"] is None
    reset_settings_repo_cache(); A.invalidate_cache()
