"""admin 공지 메일 + 사용자 목록의 베타 접근 상태 회귀.

실측 사고(2026-08-02): `/admin/notify` 가 `send_email(body=...)` 로 호출해
TypeError 를 냈고 개별 except 가 그걸 삼켜 **한 통도 안 나가는데 200 OK**
였다. 그래서 여기선 발송 성공 수뿐 아니라 **send_email 에 넘어간 인자**까지
검증한다(스텁 호출 인자 캡처).
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
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    monkeypatch.delenv("AUTH_DEV_BYPASS_USER", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)
    monkeypatch.delenv("BETA_GATE", raising=False)
    from src import persistence as P
    from src.middleware.auth import invalidate_whitelist_cache
    from src.persistence.settings_repo import reset_settings_repo_cache
    from src.persistence.whitelist_repo import reset_whitelist_repo_cache

    caches = (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo)
    for f in caches:
        f.cache_clear()
    reset_whitelist_repo_cache()
    reset_settings_repo_cache()
    invalidate_whitelist_cache()
    yield
    for f in caches:
        f.cache_clear()
    reset_whitelist_repo_cache()
    reset_settings_repo_cache()
    invalidate_whitelist_cache()


def _tok(*, sub: str, email: str) -> str:
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


def _register(client, tok):
    client.get("/me/usage", headers={"Authorization": f"Bearer {tok}"})


def _capture_send(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def _fake(**kwargs):
        calls.append(kwargs)
        return True

    import src.observability.notifications as N
    monkeypatch.setattr(N, "send_email", _fake)
    return calls


def test_notify_sends_with_correct_kwargs(monkeypatch):
    """본문이 body_text 로 전달되고, 발송 수가 수신자 수와 같아야 한다."""
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)
    _register(client, _tok(sub="u-1", email="alice@example.com"))

    res = client.post(
        "/admin/notify",
        json={"subject": "[MEDIREG] 클로즈 베타 시작",
              "body": "안녕하세요. 클로즈 베타를 시작합니다."},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["requested"] == 2
    assert body["sent"] == 2
    assert body["failed"] == []
    assert len(calls) == 2
    assert calls[0]["body_text"].startswith("안녕하세요")
    assert calls[0]["subject"].startswith("[MEDIREG]")


def test_notify_reports_smtp_not_configured(monkeypatch):
    """SMTP 미설정이면 send_email 이 True(stub)여도 응답이 그 사실을 알려야 한다."""
    monkeypatch.delenv("EMAIL_SERVER", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    res = client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b", "to": "admins"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["smtp_configured"] is False
    assert body["sent"] == 1  # stub 이라 성공처럼 보인다 — 그래서 플래그가 필요

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    res2 = client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b", "to": "admins", "dry_run": True},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res2.json()["smtp_configured"] is True


def test_notify_dry_run_does_not_send(monkeypatch):
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)
    _register(client, _tok(sub="u-1", email="alice@example.com"))

    res = client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b", "dry_run": True},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200
    assert res.json()["sent"] == 0
    assert sorted(res.json()["recipients"]) == ["alice@example.com", "boss@example.com"]
    assert calls == []


def test_notify_skips_deactivated_and_dedupes(monkeypatch):
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)
    _register(client, _tok(sub="u-1", email="alice@example.com"))
    client.post("/admin/users/u-1/soft-delete",
                headers={"Authorization": f"Bearer {admin}"})

    res = client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200
    assert res.json()["recipients"] == ["boss@example.com"]

    # 명시 리스트에 중복이 있어도 한 통만.
    calls.clear()
    res = client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b",
              "to": ["x@example.com", "X@example.com"]},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.json()["sent"] == 1


def test_notify_beta_testers_uses_whitelist(monkeypatch):
    """가입 전 초대자에게도 보낼 수 있어야 한다(@도메인 항목은 제외)."""
    monkeypatch.setenv("BETA_WHITELIST_EMAILS",
                       "invited@example.com,@partner.com")
    _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    res = client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b", "to": "beta_testers",
              "dry_run": True},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200
    assert res.json()["recipients"] == ["invited@example.com"]


def test_users_list_exposes_whitelist_status(monkeypatch):
    monkeypatch.setenv("BETA_WHITELIST_EMAILS", "alice@example.com,@partner.com")
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)
    _register(client, _tok(sub="u-1", email="alice@example.com"))
    _register(client, _tok(sub="u-2", email="carol@partner.com"))

    res = client.get("/admin/users", headers={"Authorization": f"Bearer {admin}"})
    assert res.status_code == 200
    body = res.json()
    assert body["gate_active"] is True
    rows = {u["email"]: u for u in body["users"]}
    assert rows["alice@example.com"]["whitelist_source"] == "env"
    assert rows["carol@partner.com"]["whitelist_source"] == "domain:@partner.com"
    assert rows["boss@example.com"]["whitelist_source"] == "admin"
    for r in rows.values():
        assert r["whitelisted"] is True
        assert r["can_access"] is True
        assert r["created_at"]  # 가입일 노출


def test_branded_template_is_attached_as_html(monkeypatch):
    """기본 템플릿이면 평문 + 브랜드 HTML 대안 파트가 함께 나가야 한다."""
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    res = client.post(
        "/admin/notify",
        json={"subject": "클로즈 베타", "body": "첫 문단\n둘째 줄\n\n다음 문단",
              "to": "admins", "cta_url": "https://app.example.com",
              "cta_label": "바로 시작하기"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200, res.text
    html = calls[0]["body_html"]
    assert html and "MEDIREG" in html
    assert "#0F6B4A" in html                      # 브랜드 primary
    assert "첫 문단<br>둘째 줄" in html            # 문단 안 줄바꿈 보존
    assert "바로 시작하기" in html                 # CTA 버튼
    assert calls[0]["body_text"].startswith("첫 문단")   # 평문도 그대로


def test_plain_template_sends_no_html(monkeypatch):
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b", "to": "admins", "template": "plain"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert calls[0]["body_html"] is None


def test_preview_renders_without_sending(monkeypatch):
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    res = client.post(
        "/admin/notify",
        json={"subject": "미리보기", "body": "본문", "preview": True},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200
    assert "<html" in res.json()["html"]
    assert calls == []


def test_notify_explicit_recipient_list(monkeypatch):
    """명단에서 고른 사람에게만 — 목록에 없는 회원에게는 가지 않아야 한다."""
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)
    _register(client, _tok(sub="u-1", email="alice@example.com"))
    _register(client, _tok(sub="u-2", email="bob@example.com"))

    res = client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b", "to": ["alice@example.com"]},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200
    assert res.json()["recipients"] == ["alice@example.com"]
    assert [c["to"] for c in calls] == ["alice@example.com"]


def test_html_escapes_body(monkeypatch):
    """본문의 HTML 특수문자가 마크업으로 새지 않아야 한다."""
    from src.notices import render_notice_html

    html = render_notice_html(subject="<b>제목</b>", body_text="<script>x</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;제목&lt;/b&gt;" in html


def test_schedule_list_and_cancel(monkeypatch):
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    res = client.post(
        "/admin/notify",
        json={"subject": "예약 공지", "body": "본문", "to": "admins",
              "send_at": "2030-01-01T09:00:00Z"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scheduled"] is True
    nid = body["notice"]["id"]
    assert calls == []  # 예약은 즉시 발송하지 않는다

    items = client.get("/admin/notify/scheduled",
                       headers={"Authorization": f"Bearer {admin}"}).json()["items"]
    assert [i["id"] for i in items] == [nid]
    assert items[0]["status"] == "pending"

    assert client.delete(f"/admin/notify/scheduled/{nid}",
                         headers={"Authorization": f"Bearer {admin}"}).status_code == 200
    assert client.delete(f"/admin/notify/scheduled/{nid}",
                         headers={"Authorization": f"Bearer {admin}"}).status_code == 404


def test_scheduled_notice_fires_when_due_and_only_once(monkeypatch):
    """예정 시각이 지나면 발송되고, 다음 주기에 **재발송되지 않아야** 한다."""
    from datetime import datetime, timedelta, timezone

    from src.notices import run_due

    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    client.post(
        "/admin/notify",
        json={"subject": "지난 예약", "body": "본문", "to": "admins",
              "send_at": past},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert calls == []

    fired = run_due()
    assert len(fired) == 1
    assert len(calls) == 1
    assert calls[0]["to"] == "boss@example.com"

    assert run_due() == []          # 두 번 안 나간다
    assert len(calls) == 1

    items = client.get("/admin/notify/scheduled",
                       headers={"Authorization": f"Bearer {admin}"}).json()["items"]
    assert items[0]["status"] == "sent"
    assert items[0]["result"]["sent"] == 1


def test_future_schedule_not_fired(monkeypatch):
    from src.notices import run_due

    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)
    client.post(
        "/admin/notify",
        json={"subject": "미래", "body": "본문", "to": "admins",
              "send_at": "2030-01-01T09:00:00Z"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert run_due() == []
    assert calls == []


def test_soft_delete_does_not_500(monkeypatch):
    """이전 구현은 정의되지 않은 admin_in 참조로 모든 비활성화가 500 이었다."""
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)
    _register(client, _tok(sub="u-1", email="alice@example.com"))

    res = client.post("/admin/users/u-1/soft-delete",
                      headers={"Authorization": f"Bearer {admin}"})
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] is True

    rows = client.get("/admin/users",
                      headers={"Authorization": f"Bearer {admin}"}).json()["users"]
    alice = next(u for u in rows if u["email"] == "alice@example.com")
    assert alice["deleted_at"]
    assert alice["can_access"] is False


def test_notice_sets_reply_to(monkeypatch):
    """From 은 noreply 라 회신 주소가 없으면 답장이 사라진다 — 공지에 Reply-To 필수."""
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b", "to": "admins",
              "reply_to": "admin@example.com"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert calls[0]["reply_to"] == "admin@example.com"


def test_scheduled_notice_keeps_reply_to(monkeypatch):
    """예약 건도 발송 시점에 Reply-To 를 유지해야 한다(저장 → 발화)."""
    from datetime import datetime, timedelta, timezone

    from src.notices import run_due

    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    client.post(
        "/admin/notify",
        json={"subject": "s", "body": "b", "to": "admins", "send_at": past,
              "reply_to": "admin@example.com"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    run_due()
    assert calls[0]["reply_to"] == "admin@example.com"


def test_html_renders_headings_bullets_and_links():
    """`## 소제목`·`- 항목`·맨 URL 이 구조로 렌더돼야 한다(본문과 시각 구분)."""
    from src.notices import BRAND, render_notice_html

    html = render_notice_html(
        subject="s",
        body_text="머리말\n\n## 계정 생성\nhttps://app.example.com/landing\n\n- 첫 항목\n- 둘째 항목",
    )
    assert "<h2" in html and "계정 생성" in html
    assert BRAND["primary"] in html          # 소제목이 브랜드 컬러
    assert html.count("<li") == 2
    assert '<a href="https://app.example.com/landing"' in html


def test_plain_text_strips_markup():
    """HTML 차단 클라이언트에 마크다운 표식이 그대로 새면 안 된다."""
    from src.notices import to_plain_text

    out = to_plain_text("## 계정 생성\n- 항목 하나\n일반 문장")
    assert "##" not in out
    assert "[ 계정 생성 ]" in out
    assert "· 항목 하나" in out
    assert "일반 문장" in out


def test_send_notice_uses_plain_text_body(monkeypatch):
    """발송되는 평문 파트도 표식이 제거된 버전이어야 한다."""
    calls = _capture_send(monkeypatch)
    client = _client()
    admin = _tok(sub="a-1", email="boss@example.com")
    _register(client, admin)

    client.post(
        "/admin/notify",
        json={"subject": "s", "body": "## 소제목\n- 항목", "to": "admins"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert "##" not in calls[0]["body_text"]
    assert "[ 소제목 ]" in calls[0]["body_text"]
