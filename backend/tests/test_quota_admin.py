"""S4 회귀 — 토큰 한도 미들웨어 + admin API.
"""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest


SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "medi.db"))
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    monkeypatch.delenv("AUTH_DEV_BYPASS_USER", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("DEFAULT_DAILY_TOKEN_LIMIT", raising=False)
    monkeypatch.delenv("DEFAULT_MONTHLY_TOKEN_LIMIT", raising=False)
    from src import persistence as P
    for f in (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo):
        f.cache_clear()
    yield
    for f in (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo):
        f.cache_clear()


def _make_token(*, sub="u-1", email="alice@example.com", expires_in=3600):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "email": email, "email_verified": True,
         "iat": now, "exp": now + expires_in},
        SECRET, algorithm="HS256",
    )


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _now_iso() -> str:
    """이벤트 심기용 '지금' — 어느 일 경계(UTC/KST) 기준으로도 항상 오늘.

    종전엔 start_of_today_utc_iso() 로 심었는데, 쿼터 윈도우는 KST 자정이라
    KST 00~09시(UTC 15~24시)에 돌리면 심은 이벤트가 윈도우 밖으로 빠져
    합계가 0 이 됐다(2026-08-08 실측 — 5건 시각 의존 실패).
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _seed_llm_event(*, user_id: str, ts: str,
                    input_tokens: int, output_tokens: int):
    from src.persistence import Event, get_events_repo
    get_events_repo().emit(Event(
        id="", ts=ts, event_type="llm_call",
        user_id=user_id,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=0.0,
    ))


# ---------------------------------------------------------------------------
# effective_limits / usage_summary 단위
# ---------------------------------------------------------------------------
def test_effective_limits_uses_system_defaults_when_no_override(monkeypatch):
    monkeypatch.setenv("DEFAULT_DAILY_TOKEN_LIMIT", "50000")
    monkeypatch.setenv("DEFAULT_MONTHLY_TOKEN_LIMIT", "1000000")
    from src.middleware.quota import effective_limits
    from src.persistence import User
    u = User(id="u-1", email="a@x.com")
    assert effective_limits(u) == (50000, 1000000)


def test_effective_limits_uses_override_when_set():
    from src.middleware.quota import effective_limits
    from src.persistence import User
    u = User(id="u-1", email="a@x.com",
             daily_token_limit_override=200000,
             monthly_token_limit_override=5000000)
    assert effective_limits(u) == (200000, 5000000)


def test_usage_summary_returns_zero_for_unused_user():
    from src.middleware.quota import usage_summary
    s = usage_summary("nobody")
    assert s["daily_total_tokens"] == 0
    assert s["monthly_total_tokens"] == 0


# ---------------------------------------------------------------------------
# /me/usage
# ---------------------------------------------------------------------------
def test_me_usage_requires_auth():
    # NEXTAUTH_SECRET 설정 + no header → 401 from auth middleware
    client = _client()
    res = client.get("/me/usage")
    assert res.status_code == 401


def test_me_usage_returns_user_data():
    client = _client()
    tok = _make_token(sub="u-1", email="alice@example.com")
    # 최초 호출로 user upsert
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})

    # 누적 사용량 시드
    _seed_llm_event(user_id="u-1", ts=_now_iso(),
                    input_tokens=1000, output_tokens=500)

    res = client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    body = res.json()
    assert body["user_id"] == "u-1"
    assert body["usage"]["daily_input_tokens"] == 1000
    assert body["usage"]["daily_total_tokens"] == 1500


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------
def test_admin_routes_require_admin_role(monkeypatch):
    client = _client()
    tok = _make_token(sub="u-1", email="regular@example.com")
    # user 등록 (admin 아님)
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})

    # 비admin → 403
    res = client.get("/admin/users",
                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 403


def test_admin_can_list_users(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    client = _client()
    admin_tok = _make_token(sub="admin-1", email="boss@example.com")
    user_tok = _make_token(sub="u-2", email="alice@example.com")

    # admin과 일반 user 둘 다 등록
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})

    res = client.get("/admin/users",
                     headers={"Authorization": f"Bearer {admin_tok}"})
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    emails = {u["email"] for u in body["users"]}
    assert "boss@example.com" in emails
    assert "alice@example.com" in emails


def test_admin_list_users_q_filters_server_side(monkeypatch):
    """q= 이메일 부분일치 — 프런트가 로드된 페이지만 거르던 것의 서버측 대체."""
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    client = _client()
    admin_tok = _make_token(sub="admin-1", email="boss@example.com")
    user_tok = _make_token(sub="u-2", email="alice@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})

    res = client.get("/admin/users", params={"q": "alice"},
                     headers={"Authorization": f"Bearer {admin_tok}"})
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["users"][0]["email"] == "alice@example.com"

    res = client.get("/admin/users", params={"q": "nobody"},
                     headers={"Authorization": f"Bearer {admin_tok}"})
    assert res.json()["count"] == 0


def test_admin_stats_exclude_admin_traffic(monkeypatch):
    """관리자 트래픽은 통계에서 제외(2026-08-05) — scope=all 로만 포함."""
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    client = _client()
    admin_tok = _make_token(sub="admin-1", email="boss@example.com")
    user_tok = _make_token(sub="u-2", email="alice@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})

    ts = _now_iso()
    _seed_llm_event(user_id="admin-1", ts=ts, input_tokens=500, output_tokens=100)
    _seed_llm_event(user_id="u-2", ts=ts, input_tokens=1000, output_tokens=200)

    # 기본(scope=real): 관리자 콜 제외 — llm_calls 1, active_users 1
    res = client.get("/admin/stats", headers={"Authorization": f"Bearer {admin_tok}"})
    assert res.status_code == 200
    totals = res.json()["totals"]
    assert totals["llm_calls"] == 1
    assert totals["input_tokens"] == 1000

    # scope=all: 관리자 포함 — llm_calls 2
    res = client.get("/admin/stats", params={"scope": "all"},
                     headers={"Authorization": f"Bearer {admin_tok}"})
    assert res.json()["totals"]["llm_calls"] == 2


def test_admin_questions_exclude_admin_traffic(monkeypatch):
    """이용 조회(질문 리스트)도 관리자 질문 제외 — scope=all 로만 포함."""
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    client = _client()
    admin_tok = _make_token(sub="admin-1", email="boss@example.com")
    user_tok = _make_token(sub="u-2", email="alice@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})

    import json as _json

    from src.persistence import Event, get_events_repo
    ts = _now_iso()
    for uid, q in (("admin-1", "관리자 점검 질문"), ("u-2", "실사용자 질문")):
        get_events_repo().emit(Event(
            id="", ts=ts, event_type="user_question", user_id=uid,
            payload_json=_json.dumps({"question": q}),
        ))

    res = client.get("/admin/questions", headers={"Authorization": f"Bearer {admin_tok}"})
    qs = [it["question"] for it in res.json()["items"]]
    assert "실사용자 질문" in qs and "관리자 점검 질문" not in qs

    res = client.get("/admin/questions", params={"scope": "all"},
                     headers={"Authorization": f"Bearer {admin_tok}"})
    qs = [it["question"] for it in res.json()["items"]]
    assert "관리자 점검 질문" in qs


def test_admin_stats_exclude_anonymous_bench_traffic(monkeypatch):
    """익명(user_id 없음) 이벤트 = 벤치·스크립트 트래픽 — scope=real 제외(2026-08-08).

    운영 컨테이너에서 bench_chatloop e2e 를 돌리면 run_chat_turn 직접 호출이라
    user_id=None 으로 llm_call 이 쌓인다. /chat 은 JWT 필수 = 실사용은 항상
    user_id 가 있으므로, 익명은 실사용 지표에서 뺀다. scope=all 은 탈출구.
    """
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    client = _client()
    admin_tok = _make_token(sub="admin-1", email="boss@example.com")
    user_tok = _make_token(sub="u-2", email="alice@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})

    ts = _now_iso()
    _seed_llm_event(user_id=None, ts=ts, input_tokens=700, output_tokens=70)   # 벤치
    _seed_llm_event(user_id="u-2", ts=ts, input_tokens=1000, output_tokens=200)

    res = client.get("/admin/stats", headers={"Authorization": f"Bearer {admin_tok}"})
    totals = res.json()["totals"]
    assert totals["llm_calls"] == 1
    assert totals["input_tokens"] == 1000

    res = client.get("/admin/stats", params={"scope": "all"},
                     headers={"Authorization": f"Bearer {admin_tok}"})
    totals = res.json()["totals"]
    assert totals["llm_calls"] == 2
    assert totals["input_tokens"] == 1700


def test_admin_questions_exclude_anonymous_bench_traffic(monkeypatch):
    """질문 리스트도 익명(벤치) 질문 제외 — scope=all 로만 포함."""
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    client = _client()
    admin_tok = _make_token(sub="admin-1", email="boss@example.com")
    user_tok = _make_token(sub="u-2", email="alice@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})

    import json as _json

    from src.persistence import Event, get_events_repo
    ts = _now_iso()
    for uid, q in ((None, "벤치 테스트 질문"), ("u-2", "실사용자 질문")):
        get_events_repo().emit(Event(
            id="", ts=ts, event_type="user_question", user_id=uid,
            thread_id="bench_abc123" if uid is None else "th_1",
            payload_json=_json.dumps({"question": q}),
        ))

    res = client.get("/admin/questions", headers={"Authorization": f"Bearer {admin_tok}"})
    qs = [it["question"] for it in res.json()["items"]]
    assert "실사용자 질문" in qs and "벤치 테스트 질문" not in qs

    res = client.get("/admin/questions", params={"scope": "all"},
                     headers={"Authorization": f"Bearer {admin_tok}"})
    qs = [it["question"] for it in res.json()["items"]]
    assert "벤치 테스트 질문" in qs


def test_admin_can_update_user_quota(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    client = _client()
    admin_tok = _make_token(sub="admin-1", email="boss@example.com")
    user_tok = _make_token(sub="u-3", email="bob@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})

    res = client.patch(
        "/admin/users/u-3",
        params={"daily_token_limit_override": 500000,
                "monthly_token_limit_override": 10000000},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["effective_daily_limit"] == 500000
    assert body["effective_monthly_limit"] == 10000000


def test_admin_user_usage_endpoint(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    client = _client()
    admin_tok = _make_token(sub="admin-1", email="boss@example.com")
    user_tok = _make_token(sub="u-4", email="charlie@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})

    _seed_llm_event(user_id="u-4", ts=_now_iso(),
                    input_tokens=2000, output_tokens=1000)

    res = client.get(
        "/admin/users/u-4/usage",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["usage"]["daily_total_tokens"] == 3000


# ---------------------------------------------------------------------------
# Quota middleware — 실제 LLM 라우트(/chat·/reports) 기준(2026-09-22: 종전엔 은퇴한
# langgraph `/threads/*/runs` 로 검증해 실경로 차단이 검증되지 않았다)
# ---------------------------------------------------------------------------
def _post_llm_route(client, tok, path):
    """빈 body POST — 쿼터 초과면 미들웨어가 429, 아니면 라우트 검증(422)에서 멈춘다."""
    return client.post(path, json={}, headers={"Authorization": f"Bearer {tok}"})


def test_quota_paths_are_real_routes_only():
    from src.middleware.quota import _is_quota_path

    assert _is_quota_path("/chat", "POST") and _is_quota_path("/reports", "POST")
    assert not _is_quota_path("/threads/x/runs", "POST")   # 은퇴 경로
    assert not _is_quota_path("/threads/x/messages/m/feedback", "POST")
    assert not _is_quota_path("/reports/abc", "GET")

def test_quota_passes_when_under_limit(monkeypatch):
    monkeypatch.setenv("DEFAULT_DAILY_TOKEN_LIMIT", "10000")
    client = _client()
    tok = _make_token(sub="u-q1", email="q1@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})

    _seed_llm_event(user_id="u-q1", ts=_now_iso(),
                    input_tokens=500, output_tokens=200)

    # 실제 LLM 라우트(POST /reports) — 빈 body 라 미들웨어를 통과하면 라우트 검증(422)에서
    # 멈춘다(LLM 호출 없음). 여기서 보는 건 "429 가 아니다" = 쿼터 통과.
    res = _post_llm_route(client, tok, "/reports")
    assert res.status_code == 422


def test_quota_blocks_when_daily_limit_reached(monkeypatch):
    monkeypatch.setenv("DEFAULT_DAILY_TOKEN_LIMIT", "1000")
    client = _client()
    tok = _make_token(sub="u-q2", email="q2@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})

    _seed_llm_event(user_id="u-q2", ts=_now_iso(),
                    input_tokens=800, output_tokens=300)  # 합계 1100 > 1000

    # 채팅·보고서 둘 다 막혀야 한다 — 차단은 미들웨어라 라우트(LLM)까지 가지 않는다.
    res = _post_llm_route(client, tok, "/chat")
    assert res.status_code == 429
    assert _post_llm_route(client, tok, "/reports").status_code == 429
    body = res.json()
    assert body["period"] == "daily"
    assert body["tokens_used"] == 1100
    assert body["tokens_limit"] == 1000
    assert "한도" in body["detail"]


def test_quota_zero_limit_means_unlimited(monkeypatch):
    """limit=0 은 무제한 — 사용량이 아무리 커도 차단하지 않는다(2026-08-19).

    시스템 기본값을 0 으로 두는 건 비권장이지만(사고 상한 소멸), 데모 계정 등
    특정 사용자에게 한도를 완전히 푸는 경로는 필요하다.
    """
    monkeypatch.setenv("DEFAULT_DAILY_TOKEN_LIMIT", "0")
    monkeypatch.setenv("DEFAULT_MONTHLY_TOKEN_LIMIT", "0")
    client = _client()
    tok = _make_token(sub="u-unl", email="unl@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})

    _seed_llm_event(user_id="u-unl", ts=_now_iso(),
                    input_tokens=99_000_000, output_tokens=99_000_000)

    res = _post_llm_route(client, tok, "/reports")
    assert res.status_code == 422  # 쿼터 통과 → 라우트 검증


def test_default_daily_limit_is_effectively_unlimited(monkeypatch):
    """기본 한도는 실사용 p90(79.3만)을 크게 웃돌아야 한다 — 정상 사용 차단 금지."""
    monkeypatch.delenv("DEFAULT_DAILY_TOKEN_LIMIT", raising=False)
    from src.middleware.quota import _system_daily_limit

    assert _system_daily_limit() >= 20_000_000


def test_quota_blocks_emits_event(monkeypatch):
    monkeypatch.setenv("DEFAULT_DAILY_TOKEN_LIMIT", "100")
    client = _client()
    tok = _make_token(sub="u-q3", email="q3@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})

    _seed_llm_event(user_id="u-q3", ts=_now_iso(),
                    input_tokens=200, output_tokens=0)

    _post_llm_route(client, tok, "/chat")

    from src.persistence import get_events_repo
    blocked = get_events_repo().list_for_user("u-q3", event_type="quota_blocked")
    assert len(blocked) == 1


def test_quota_does_not_apply_to_reports_listing(monkeypatch):
    """/threads/{tid}/reports 는 LLM 호출 없으므로 쿼터 무관."""
    monkeypatch.setenv("DEFAULT_DAILY_TOKEN_LIMIT", "100")
    client = _client()
    tok = _make_token(sub="u-q4", email="q4@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})

    _seed_llm_event(user_id="u-q4", ts=_now_iso(),
                    input_tokens=500, output_tokens=500)  # 한도 초과

    # 소유권 검사(2026-08-04)를 통과하도록 본인 thread 로 — 여기서 보는 건 쿼터다.
    from src.persistence.threads_repo import get_threads_repo
    get_threads_repo().ensure_thread("some-tid", user_id="u-q4")

    # reports listing은 통과
    res = client.get("/threads/some-tid/reports",
                     headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200


def test_quota_user_override_overrides_system_default(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.setenv("DEFAULT_DAILY_TOKEN_LIMIT", "100")  # 매우 낮음
    client = _client()
    admin_tok = _make_token(sub="adm", email="boss@example.com")
    user_tok = _make_token(sub="u-q5", email="q5@example.com")
    client.get("/me/usage", headers={"Authorization": f"Bearer {user_tok}"})
    client.get("/me/usage", headers={"Authorization": f"Bearer {admin_tok}"})

    # admin이 한도 1,000,000으로 올려줌
    client.patch(
        "/admin/users/u-q5",
        params={"daily_token_limit_override": 1000000},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )

    # 시드: 시스템 기본(100) 초과지만 사용자 한도(1M) 미만
    _seed_llm_event(user_id="u-q5", ts=_now_iso(),
                    input_tokens=500, output_tokens=200)

    res = _post_llm_route(client, user_tok, "/reports")
    assert res.status_code == 422  # 사용자 override 한도로 쿼터 통과 → 라우트 검증
