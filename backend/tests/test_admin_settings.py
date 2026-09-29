"""admin 설정 API — 베타 화이트리스트(DB) 관리 + 시스템 설정 조회.

게이트 규칙: env(BETA_WHITELIST_EMAILS) ∪ DB(beta_whitelist), ADMIN_EMAILS
항상 허용, 둘 다 비면 전면 허용. DB 변경은 캐시 무효화로 즉시 반영.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest

SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "adm.db"))
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)
    monkeypatch.delenv("AUTH_DEV_BYPASS_USER", raising=False)

    from src import maintenance as M
    from src import persistence as P
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
        M.invalidate_cache()

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


def test_db_whitelist_gates_and_invalidates():
    client = _client()
    h = _admin_headers()

    # 게이트 꺼짐(빈 리스트) — 아무나 통과
    r = client.get("/me/usage", headers={"Authorization": f"Bearer {_token(sub='u-a', email='a@x.com')}"})
    assert r.status_code == 200

    # DB 에 항목 추가 → 게이트 켜짐: 목록 밖 403, 목록 안 200
    r = client.post("/admin/whitelist", json={"entry": "vip@x.com"}, headers=h)
    assert r.status_code == 201
    assert client.get("/me/usage", headers={
        "Authorization": f"Bearer {_token(sub='u-v', email='vip@x.com')}"}).status_code == 200
    assert client.get("/me/usage", headers={
        "Authorization": f"Bearer {_token(sub='u-s', email='stranger@x.com')}"}).status_code == 403

    # 도메인 항목
    client.post("/admin/whitelist", json={"entry": "@partner.co.kr"}, headers=h)
    assert client.get("/me/usage", headers={
        "Authorization": f"Bearer {_token(sub='u-d', email='dr@partner.co.kr')}"}).status_code == 200

    # 삭제 → 즉시 차단(캐시 무효화)
    assert client.delete("/admin/whitelist/vip@x.com", headers=h).status_code == 200
    assert client.get("/me/usage", headers={
        "Authorization": f"Bearer {_token(sub='u-v2', email='vip@x.com')}"}).status_code == 403

    # admin 은 항상 허용
    assert client.get("/me/usage", headers=h).status_code == 200


def test_whitelist_admin_endpoints_validation_and_scope():
    client = _client()
    h = _admin_headers()

    # 형식 오류 422
    assert client.post("/admin/whitelist", json={"entry": "not-an-email"}, headers=h).status_code == 422
    # 미존재 삭제 404
    assert client.delete("/admin/whitelist/none@x.com", headers=h).status_code == 404
    # 일반 사용자 접근 차단
    user_h = {"Authorization": f"Bearer {_token(sub='u-n', email='n@x.com')}"}
    assert client.get("/admin/whitelist", headers=user_h).status_code == 403

    # 목록 shape — env/db 출처 구분 + added_by 기록
    client.post("/admin/whitelist", json={"entry": "VIP@X.com"}, headers=h)  # 소문자 정규화
    r = client.get("/admin/whitelist", headers=h)
    body = r.json()
    assert body["gate_active"] is True
    assert body["env_entries"] == []
    assert body["db_entries"][0]["entry"] == "vip@x.com"
    assert body["db_entries"][0]["added_by"] == "boss@example.com"


def test_env_and_db_union(monkeypatch):
    monkeypatch.setenv("BETA_WHITELIST_EMAILS", "env-only@x.com")
    from src.middleware.auth import invalidate_whitelist_cache
    invalidate_whitelist_cache()
    client = _client()
    h = _admin_headers()
    client.post("/admin/whitelist", json={"entry": "db-only@x.com"}, headers=h)

    for email in ("env-only@x.com", "db-only@x.com"):
        assert client.get("/me/usage", headers={
            "Authorization": f"Bearer {_token(sub=email, email=email)}"}).status_code == 200, email
    assert client.get("/me/usage", headers={
        "Authorization": f"Bearer {_token(sub='u-o', email='other@x.com')}"}).status_code == 403


def test_admin_config_masks_secrets():
    client = _client()
    r = client.get("/admin/config", headers=_admin_headers())
    assert r.status_code == 200
    groups = r.json()["groups"]
    auth_items = {i["key"]: i for i in groups["auth"]}
    sec = auth_items["NEXTAUTH_SECRET"]
    assert sec["secret"] is True and sec["is_set"] is True
    assert sec["value"] is None  # 값 절대 미노출
    # 비밀 아닌 키는 값 노출
    llm_items = {i["key"]: i for i in groups["llm"]}
    assert llm_items["LLM_MODEL"]["secret"] is False


def test_admin_stats_and_citation_report():
    """/admin/stats 일별 집계 + POST /feedback/citation 저장·이벤트."""
    client = _client()
    h = _admin_headers()
    user_h = {"Authorization": f"Bearer {_token(sub='u-c', email='c@x.com')}"}

    # 인용 신고는 본인 thread 에만 — 남의 대화에 품질 라벨을 꽂으면 평가셋이
    # 오염된다(2026-08-04 H-6). 여기서 보는 건 집계라 소유자를 맞춰준다.
    from src.persistence.threads_repo import get_threads_repo
    get_threads_repo().ensure_thread("t_stat", user_id="u-c")

    # 인용 신고 → feedback + events 기록
    r = client.post("/feedback/citation", json={
        "thread_id": "t_stat", "message_id": "m1",
        "citation_id": "cite_doc_x", "citation_number": 3,
        "citation_title": "의료기기법 제6조", "reason": "주장과 무관한 조문",
    }, headers=user_h)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.post("/feedback/citation", json={"thread_id": "t"},
                       headers=user_h).status_code == 422

    # llm_call 이벤트 시드 → 통계 집계
    from src.persistence import Event, get_events_repo, start_of_today_utc_iso
    get_events_repo().emit(Event(
        id="", ts=start_of_today_utc_iso(), event_type="llm_call",
        user_id="u-c", input_tokens=100, output_tokens=20, cost_usd=0.001,
    ))

    r = client.get("/admin/stats?days=7", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["totals"]["llm_calls"] >= 1
    assert body["totals"]["citation_reports"] >= 1
    today = body["daily"][0]
    assert today["input_tokens"] >= 100 and today["active_users"] >= 1
    # 일반 사용자는 통계 접근 불가
    assert client.get("/admin/stats", headers=user_h).status_code == 403


def test_report_queue_ahead_tracking():
    from src.report_runner import _job_started_at, queue_ahead

    _job_started_at.clear()
    _job_started_at["rpt_a"] = 1.0
    _job_started_at["rpt_b"] = 2.0
    _job_started_at["rpt_c"] = 3.0
    try:
        assert queue_ahead("rpt_a") == 0
        assert queue_ahead("rpt_c") == 2
        assert queue_ahead("rpt_unknown") is None
    finally:
        _job_started_at.clear()


def test_beta_check_public_endpoint():
    """POST /beta/check — 무인증 공개, boolean 만(목록 미노출), env∪DB 반영."""
    client = _client()
    h = _admin_headers()

    # 게이트 꺼짐 — 아무 이메일이나 allowed
    r = client.post("/beta/check", json={"email": "anyone@x.com"})
    assert r.status_code == 200
    assert r.json() == {"allowed": True, "gate_active": False}

    # DB 항목 추가 → 게이트 켜짐, 목록 밖은 allowed False
    client.post("/admin/whitelist", json={"entry": "vip@x.com"}, headers=h)
    r = client.post("/beta/check", json={"email": "vip@x.com"})
    assert r.json() == {"allowed": True, "gate_active": True}
    r = client.post("/beta/check", json={"email": "stranger@x.com"})
    assert r.json() == {"allowed": False, "gate_active": True}

    # 형식 오류 422, 응답에 목록 자체는 없음
    assert client.post("/beta/check", json={"email": "bad"}).status_code == 422
    assert "entries" not in client.post("/beta/check", json={"email": "vip@x.com"}).json()


def test_maintenance_gate_blocks_users_allows_admin():
    """점검 모드 — 비관리자 API 503, 관리자 통과, 공개 라우트는 계속 열림."""
    client = _client()
    h = _admin_headers()
    user_h = {"Authorization": f"Bearer {_token(sub='u-m', email='m@x.com')}"}

    # 평상시 — 사용자 통과
    assert client.get("/me/usage", headers=user_h).status_code == 200
    assert client.get("/load").json()["maintenance"] == {"active": False}

    # 점검 ON — 관리자만 설정 가능
    assert client.post("/admin/maintenance", json={"active": True},
                       headers=user_h).status_code == 403
    r = client.post("/admin/maintenance",
                    json={"active": True, "message": "4시 갱신 중"}, headers=h)
    assert r.status_code == 200 and r.json()["active"] is True

    # 비관리자 → 503 (+ maintenance 플래그, Retry-After)
    r = client.get("/me/usage", headers=user_h)
    assert r.status_code == 503
    assert r.json()["maintenance"] is True and "4시 갱신 중" in r.json()["detail"]
    assert r.headers.get("Retry-After")

    # 관리자는 계속 통과(해제·확인 가능)
    assert client.get("/me/usage", headers=h).status_code == 200
    assert client.get("/admin/maintenance", headers=h).json()["active"] is True

    # 공개 라우트는 점검 중에도 열림 — 프런트가 상태 폴링·점검화면 표시
    pub = client.get("/load").json()
    assert pub["maintenance"]["active"] is True
    assert "4시 갱신 중" in pub["maintenance"]["message"]
    assert client.get("/healthz").status_code == 200
    assert client.get("/legal").status_code == 200

    # 점검 OFF — 사용자 복귀
    assert client.post("/admin/maintenance", json={"active": False},
                       headers=h).json()["active"] is False
    assert client.get("/me/usage", headers=user_h).status_code == 200
    assert client.get("/load").json()["maintenance"] == {"active": False}


def test_maintenance_daily_schedule_window(monkeypatch):
    """매일 반복 예약 — 창 안/밖 자동 on/off, 자정 넘김, 수동과 독립."""
    from src import maintenance as M

    # 04:00~04:20 예약(KST 기본)
    M.set_schedule(enabled=True, start="4:0", end="04:20", message="갱신 중",
                   updated_by="admin@x.com")
    assert M.get_state()["schedule"]["start"] == "04:00"  # 정규화

    # 창 밖(03:30) → 비활성
    monkeypatch.setattr(M, "_local_minutes", lambda tz: 3 * 60 + 30)
    M.invalidate_cache()
    assert M.is_active() is False

    # 창 안(04:10) → 활성, source=schedule (수동은 off)
    monkeypatch.setattr(M, "_local_minutes", lambda tz: 4 * 60 + 10)
    M.invalidate_cache()
    st = M.get_state()
    assert st["active"] is True and st["source"] == "schedule" and st["manual"] is False
    assert M.public_status()["message"] == "갱신 중"

    # 경계: end(04:20)는 창 밖(반열림 [start,end))
    monkeypatch.setattr(M, "_local_minutes", lambda tz: 4 * 60 + 20)
    M.invalidate_cache()
    assert M.is_active() is False

    # 예약 해제 → 비활성
    M.set_schedule(enabled=False, start="04:00", end="04:20", updated_by="admin@x.com")
    M.invalidate_cache()
    assert M.is_active() is False

    # 자정 넘김 창 23:50~00:10
    M.set_schedule(enabled=True, start="23:50", end="00:10", updated_by="admin@x.com")
    monkeypatch.setattr(M, "_local_minutes", lambda tz: 5)       # 00:05 → 활성
    M.invalidate_cache()
    assert M.is_active() is True
    monkeypatch.setattr(M, "_local_minutes", lambda tz: 12 * 60)  # 12:00 → 비활성
    M.invalidate_cache()
    assert M.is_active() is False
    M.set_schedule(enabled=False, start="23:50", end="00:10", updated_by="admin@x.com")


def test_maintenance_schedule_via_api_blocks_in_window(monkeypatch):
    """예약 API → 창 안이면 비관리자 503, 창 밖이면 통과. 형식 오류 422."""
    from src import maintenance as M

    client = _client()
    h = _admin_headers()
    user_h = {"Authorization": f"Bearer {_token(sub='u-sch', email='sch@x.com')}"}

    r = client.post("/admin/maintenance", json={
        "schedule": {"enabled": True, "start": "04:00", "end": "04:20"},
        "message": "새벽 갱신 중",
    }, headers=h)
    assert r.status_code == 200 and r.json()["schedule"]["enabled"] is True

    # 창 안(04:10) → 비관리자 503, 관리자 통과, /load 노출
    monkeypatch.setattr(M, "_local_minutes", lambda tz: 4 * 60 + 10)
    M.invalidate_cache()
    assert client.get("/me/usage", headers=user_h).status_code == 503
    assert client.get("/me/usage", headers=h).status_code == 200
    pub = client.get("/load").json()["maintenance"]
    assert pub["active"] is True and "새벽 갱신 중" in pub["message"]

    # 창 밖(01:00) → 정상 복귀
    monkeypatch.setattr(M, "_local_minutes", lambda tz: 60)
    M.invalidate_cache()
    assert client.get("/me/usage", headers=user_h).status_code == 200
    assert client.get("/load").json()["maintenance"] == {"active": False}

    # 잘못된 시각 형식 422
    assert client.post("/admin/maintenance", json={
        "schedule": {"enabled": True, "start": "25:00", "end": "04:20"},
    }, headers=h).status_code == 422


def test_maintenance_survives_restart():
    """점검 상태는 app_settings DB — 재기동(캐시·repo 리셋) 후에도 유지."""
    from src import maintenance as M
    from src.persistence.settings_repo import reset_settings_repo_cache

    M.set_state(True, message="정비", updated_by="admin@x.com")
    assert M.is_active() is True
    # 재기동 시뮬 — 프로세스 캐시·팩토리 캐시 날림
    reset_settings_repo_cache()
    M.invalidate_cache()
    assert M.is_active() is True  # DB 에서 재로드
    M.set_state(False, updated_by="admin@x.com")


def test_account_soft_delete_flow(monkeypatch):
    """회원탈퇴 소프트삭제 — 마킹·접근차단·복구, 하드 삭제와 분리."""
    client = _client()
    from src.persistence import get_users_repo

    # 사용자 생성(첫 요청이 upsert)
    tok = _token(sub="u-wd", email="wd@x.com")
    assert client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"}).status_code == 200

    # 탈퇴 → 소프트삭제(행 보존 + deleted_at)
    r = client.post("/me/withdraw", json={"reason": "테스트"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    u = get_users_repo().get("u-wd")
    assert u is not None and u.deleted_at is not None  # 행 보존, 마킹됨

    # 이후 접근은 403(탈퇴 계정) — upsert 가 되살리지 않음
    r = client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert "탈퇴" in r.json()["detail"]

    # 관리자 복구 → 다시 접근 가능
    h = _admin_headers()
    r = client.post("/admin/users/u-wd/restore", headers=h)
    assert r.status_code == 200 and r.json()["restored"] is True
    assert get_users_repo().get("u-wd").deleted_at is None
    assert client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"}).status_code == 200

    # admin 목록에 deleted_at 필드 노출
    users = client.get("/admin/users", headers=h).json()["users"]
    assert any("deleted_at" in u for u in users)

    # 없는 사용자 복구 404
    assert client.post("/admin/users/nope/restore", headers=h).status_code == 404


# ── 화이트리스트 중복 구분(2026-08-01) ──────────────────────────────
# 종전엔 repo.add() 가 반환값이 없어 **이미 있던 항목도 'added' 로 집계**했다.
# 벌크 100건 붙여넣기에 "100건 추가"라고 답해 실제 신규가 몇 건인지 알 수 없었다.
def test_whitelist_add_distinguishes_duplicate():
    client = _client()
    h = _admin_headers()

    r1 = client.post("/admin/whitelist", json={"entry": "dup@x.com"}, headers=h)
    assert r1.status_code == 201
    assert r1.json()["added"] == ["dup@x.com"]
    assert r1.json()["duplicate"] == []

    # 같은 항목 재추가 → 신규 아님
    r2 = client.post("/admin/whitelist", json={"entry": "dup@x.com"}, headers=h)
    assert r2.json()["added"] == []
    assert r2.json()["duplicate"] == ["dup@x.com"]

    # 대소문자·공백 정규화도 같은 항목으로 판정
    r3 = client.post("/admin/whitelist", json={"entry": "  DUP@X.com "}, headers=h)
    assert r3.json()["duplicate"] == ["dup@x.com"]


def test_whitelist_bulk_reports_new_vs_existing():
    """벌크 — 신규/중복이 섞이면 각각 집계돼야 운영자가 실제 반영 수를 안다."""
    client = _client()
    h = _admin_headers()
    client.post("/admin/whitelist", json={"entry": "old@x.com"}, headers=h)

    r = client.post("/admin/whitelist",
                    json={"entries": "old@x.com, new1@x.com, new2@x.com, 쓰레기"},
                    headers=h)
    body = r.json()
    assert sorted(body["added"]) == ["new1@x.com", "new2@x.com"]
    assert body["duplicate"] == ["old@x.com"]
    assert body["invalid"] == ["쓰레기"]


def test_whitelist_add_flags_domain_already_covered():
    """등록된 @도메인이 이미 통과시키는 개별 이메일은 중복 — 추가하지 않고 알린다."""
    client = _client()
    h = _admin_headers()
    client.post("/admin/whitelist", json={"entry": "@corp.com"}, headers=h)

    r = client.post("/admin/whitelist", json={"entry": "kim@corp.com"}, headers=h)
    body = r.json()
    assert body["covered_by_domain"] == ["kim@corp.com"]
    assert body["added"] == []
    # 실제로 이미 통과하는지 확인 — 중복이라는 판정이 맞았는지
    assert client.get("/me/usage", headers={
        "Authorization": f"Bearer {_token(sub='u-c', email='kim@corp.com')}"
    }).status_code == 200


def test_whitelist_add_flags_already_in_env(monkeypatch):
    """.env 로 이미 허용 중인 항목 — DB 에 넣어봐야 무의미하므로 구분해 알린다."""
    monkeypatch.setenv("BETA_WHITELIST_EMAILS", "envuser@x.com")
    from src.middleware.auth import invalidate_whitelist_cache
    invalidate_whitelist_cache()
    client = _client()
    h = _admin_headers()

    r = client.post("/admin/whitelist", json={"entry": "envuser@x.com"}, headers=h)
    body = r.json()
    assert body["already_in_env"] == ["envuser@x.com"]
    assert body["added"] == []


def test_feature_pause_reports_only(monkeypatch):
    """기능 단위 일시 중단(2026-09-07) — 보고서만 503, 채팅 등은 정상, /load 에 노출."""
    monkeypatch.delenv("REPORT_WRITER_BASE_URL", raising=False)
    from src import writer_status as W
    W.invalidate_cache()
    client = _client()
    h = _admin_headers()
    user_h = {"Authorization": f"Bearer {_token(sub='u-f', email='f@x.com')}"}

    pub = client.get("/load").json()
    assert pub["reports"]["paused"] is False and pub["features"] == {}
    assert pub["reports"]["writer_up"] is None  # 로컬 writer 미설정

    # 알 수 없는 기능명 → 422
    r = client.post("/admin/maintenance",
                    json={"features": {"chat": {"paused": True}}}, headers=h)
    assert r.status_code == 422

    # 보고서 일시 중단 ON
    r = client.post("/admin/maintenance",
                    json={"features": {"reports": {"paused": True, "message": "writer 다른 작업 중"}}},
                    headers=h)
    assert r.status_code == 200
    assert r.json()["features"]["reports"]["paused"] is True
    assert r.json()["active"] is False  # 전체 점검은 아님

    # 사용자: 채팅·기타는 정상, 보고서 트리거만 503(+헤더)
    assert client.get("/me/usage", headers=user_h).status_code == 200
    r = client.post("/reports", json={"thread_id": "t_x", "idempotency_key": "rpt_a"},
                    headers=user_h)
    assert r.status_code == 503
    assert "writer 다른 작업 중" in r.json()["detail"]
    assert r.headers.get("X-Feature-Paused") == "reports"

    # 공개 /load 에 노출 — 프런트 배너·버튼 비활성 근거
    pub = client.get("/load").json()
    assert pub["maintenance"] == {"active": False}
    assert pub["reports"]["paused"] is True and "writer 다른 작업 중" in pub["reports"]["message"]
    assert pub["features"]["reports"]["paused"] is True
    st = client.get("/admin/maintenance", headers=h).json()
    assert st["feature_names"] == ["reports"] and "reports" in st["feature_default_messages"]

    # OFF — 기본 문구는 message 미지정 시 적용
    r = client.post("/admin/maintenance",
                    json={"features": {"reports": {"paused": False}}}, headers=h)
    assert r.json()["features"]["reports"]["paused"] is False
    assert client.get("/load").json()["reports"]["paused"] is False
    # 문구는 전체 점검과 같이 유지된다 — 비우면 기본 문구
    r = client.post("/admin/maintenance",
                    json={"features": {"reports": {"paused": True, "message": ""}}}, headers=h)
    pub = client.get("/load").json()
    assert "채팅·검색은 정상" in pub["reports"]["message"]


def test_writer_probe_cached_and_reported(monkeypatch):
    """writer 프로브 — 미도달이면 /load reports.writer_up=False, TTL 안에서는 재프로브 없음."""
    monkeypatch.setenv("REPORT_WRITER_BASE_URL", "http://127.0.0.1:9/v1")  # 닫힌 포트
    monkeypatch.setenv("REPORT_WRITER_PROBE_TTL_S", "60")
    from src import writer_status as W
    W.invalidate_cache()
    calls = {"n": 0}
    import urllib.request as rq

    def _boom(*a, **k):
        calls["n"] += 1
        raise OSError("down")

    monkeypatch.setattr(rq, "urlopen", _boom)
    client = _client()
    assert client.get("/load").json()["reports"]["writer_up"] is False
    assert client.get("/load").json()["reports"]["writer_up"] is False
    assert calls["n"] == 1
    W.invalidate_cache()
