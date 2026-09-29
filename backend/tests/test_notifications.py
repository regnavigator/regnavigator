"""이메일 알림(SMTP) — stub 폴백 + 발송 + 첨부."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.observability import notifications as N


@pytest.fixture(autouse=True)
def _isolate_email_env(monkeypatch):
    """EMAIL_SERVER 격리(hermetic) — 다른 테스트가 scripts 를 import 하며
    load_dotenv() 로 실 .env 를 프로세스에 로드하면, SMTP_* 만 설정하는 아래
    테스트들이 EMAIL_SERVER 우선순위에 오염된다. setenv 하는 테스트는 이 delenv
    뒤에 자기 값을 넣으므로 영향 없음."""
    monkeypatch.delenv("EMAIL_SERVER", raising=False)


def test_stub_when_smtp_unset(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_SERVER", raising=False)
    # SMTP 미설정 → 로그만, True(대화/보고서 흐름 안 막음)
    assert N.send_email(to="a@b.com", subject="t", body_text="x") is True


# ── EMAIL_SERVER (medi-front NextAuth 와 공유하는 한 줄 URL) ──────────
def test_email_server_url_parsed(monkeypatch):
    """smtps://user:pass@host:465 → SSL·포트·자격증명 파싱."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("EMAIL_SERVER", "smtps://resend:re_abc123@smtp.resend.com:465")
    c = N._conn()
    assert c.host == "smtp.resend.com" and c.port == 465 and c.ssl is True
    assert c.user == "resend" and c.password == "re_abc123"


def test_email_server_smtp_scheme_is_starttls(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("EMAIL_SERVER", "smtp://u:p@mail.example.com")
    c = N._conn()
    assert c.ssl is False and c.port == 587   # 기본 587 STARTTLS


def test_email_server_port_465_implies_implicit_tls(monkeypatch):
    """★회귀(2026-07-25 실측 사고): scheme 은 smtp 인데 **포트가 465** 인 URL.

    `smtp://resend:…@smtp.resend.com:465` (NextAuth EMAIL_SERVER 관행) 에서
    구현은 ssl=False 로 판정해 평문 SMTP+STARTTLS 로 접속했고, 465 는 즉시 TLS
    핸드셰이크를 기대하므로 12초 타임아웃 후 실패 → **보고서 완료 메일·쿼터
    알림이 조용히 전부 미발송**. 포트 465 면 암묵적 TLS 로 판정해야 한다."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("EMAIL_SERVER", "smtp://resend:re_x@smtp.resend.com:465")
    c = N._conn()
    assert c.port == 465
    assert c.ssl is True, "465 인데 STARTTLS 경로로 가면 발송이 타임아웃한다"


def test_email_server_port_587_stays_starttls(monkeypatch):
    """587 은 그대로 STARTTLS — 465 규칙이 다른 포트를 오염시키지 않는지."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("EMAIL_SERVER", "smtp://u:p@mail.example.com:587")
    c = N._conn()
    assert c.port == 587 and c.ssl is False


def test_from_uses_email_from_not_account_user(monkeypatch):
    """★회귀(2026-07-25 실측): From 이 계정명으로 나가 501 로 거절됐다.

    `smtp://resend:…@…` 는 user 가 `resend`(이메일 아님)인데 구현이
    `SMTP_FROM or conn.user` 만 봐서 From: resend → **501 Bad sender address
    syntax**. EMAIL_FROM(EMAIL_SERVER 와 짝) 을 읽어야 한다."""
    sent = {}

    class _FakeSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent["from"] = msg["From"]

    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.setenv("EMAIL_SERVER", "smtp://resend:re_x@smtp.resend.com:465")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")
    import smtplib
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)

    assert N.send_email(to="a@b.com", subject="t", body_text="x") is True
    assert sent["from"] == "noreply@example.com"
    assert sent["from"] != "resend"


def test_email_server_urlencoded_password(monkeypatch):
    """비밀번호에 @ · : 가 있으면 %XX 인코딩 — 디코드해야 로그인 성공."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("EMAIL_SERVER", "smtps://user%40x.com:p%40ss%3A1@h.com:465")
    c = N._conn()
    assert c.user == "user@x.com" and c.password == "p@ss:1"


def test_email_server_takes_precedence_over_smtp_vars(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "ignored.example.com")
    monkeypatch.setenv("EMAIL_SERVER", "smtps://u:p@wins.example.com:465")
    assert N._conn().host == "wins.example.com"


def test_smtp_vars_used_when_no_email_server(monkeypatch):
    monkeypatch.delenv("EMAIL_SERVER", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    c = N._conn()
    assert c.host == "smtp.gmail.com" and c.port == 587 and c.ssl is False


def test_send_no_recipient_false(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.x")
    assert N.send_email(to="", subject="t", body_text="x") is False


class _FakeSMTP:
    last = {}

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def starttls(self, **k):
        pass

    def login(self, u, p):
        _FakeSMTP.last["login"] = u

    def send_message(self, msg):
        _FakeSMTP.last["msg"] = msg


def test_notify_report_ready_attaches_md(monkeypatch):
    """fmt='md' 명시 시 .md 첨부(기본은 docx — 아래 별도 테스트)."""
    monkeypatch.setenv("SMTP_HOST", "smtp.x")
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASS", "p")
    monkeypatch.setenv("SMTP_FROM", "f@x.com")
    _FakeSMTP.last = {}
    with patch("smtplib.SMTP", _FakeSMTP):
        ok = N.notify_report_ready(email="doc@med.kr", thread_id="t1",
                                   report_id="rpt_1", report_md="# 보고서\n본문",
                                   title="의료기기 광고", fmt="md")
    assert ok is True
    assert _FakeSMTP.last["login"] == "u"
    msg = _FakeSMTP.last["msg"]
    assert "의료기기 광고" in msg["Subject"]
    assert msg["To"] == "doc@med.kr"
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["medi_report_rpt_1.md"]


def test_notify_report_ready_defaults_to_docx(monkeypatch):
    """기본 첨부 포맷 = DOCX(REPORT_ATTACH_FORMAT). 진짜 zip 패키지여야."""
    from src.reports_convert import is_available
    if not is_available():
        import pytest
        pytest.skip("pandoc 미설치")
    monkeypatch.setenv("SMTP_HOST", "smtp.x")
    monkeypatch.setenv("SMTP_FROM", "f@x.com")   # 발신자 가드 — 없으면 발송 거부
    monkeypatch.delenv("REPORT_ATTACH_FORMAT", raising=False)
    _FakeSMTP.last = {}
    with patch("smtplib.SMTP", _FakeSMTP):
        N.notify_report_ready(email="a@b.com", thread_id="t", report_id="rpt_2",
                              report_md="# 제목\n\n## 개요\n본문 [1]")
    (att,) = list(_FakeSMTP.last["msg"].iter_attachments())
    assert att.get_filename() == "medi_report_rpt_2.docx"
    assert att.get_payload(decode=True)[:2] == b"PK"


def test_send_failure_returns_false(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.x")

    def _boom(*a, **k):
        raise OSError("connection refused")

    with patch("smtplib.SMTP", _boom):
        assert N.send_email(to="a@b.com", subject="t", body_text="x") is False


def test_report_email_no_attachment_when_no_body(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.x")
    monkeypatch.setenv("SMTP_FROM", "f@x.com")   # 발신자 가드 — 없으면 발송 거부
    _FakeSMTP.last = {}
    with patch("smtplib.SMTP", _FakeSMTP):
        N.notify_report_ready(email="a@b.com", thread_id="t", report_id="rpt_2")
    names = list(_FakeSMTP.last["msg"].iter_attachments())
    assert names == []  # 본문 없으면 첨부 없이 알림만


# ── 보고서 완료 배선(report_runner._send_report_email) ──────────────
# (구 src/app.py 는 ADR-0001 Phase 5 컷오버로 삭제 — report_runner 로 이관)
def test_report_runner_imports_asyncio_for_report_email():
    """회귀: 보고서 잡이 `asyncio.to_thread(_send_report_email, …)` 를 쓰므로
    report_runner 모듈에 asyncio 가 import 돼 있어야 한다. 누락 시 best-effort
    except 가 NameError 를 삼켜 **이메일만 조용히 미발송**(e2e 로만 발견됨)."""
    import src.report_runner as rr
    assert hasattr(rr, "asyncio")


def test_send_report_email_attaches_blob_body(monkeypatch):
    """blob 에서 전문(.md)을 읽어 notify_report_ready 에 첨부로 넘기는지."""
    import src.report_runner as rr

    class _Meta:
        blob_uri = "blob://x"
        title = "의료기기 광고"

    sent = {}
    monkeypatch.setattr("src.persistence.get_reports_repo",
                        lambda: type("R", (), {"get": staticmethod(lambda rid: _Meta())})())
    monkeypatch.setattr("src.persistence.get_blob_store",
                        lambda: type("B", (), {"get": staticmethod(lambda uri: "# 보고서\n본문")})())
    monkeypatch.setattr("src.observability.notifications.notify_report_ready",
                        lambda **kw: sent.update(kw) or True)

    rr._send_report_email("doc@med.kr", "t1", "rpt_9")
    assert sent["email"] == "doc@med.kr"
    assert sent["report_md"] == "# 보고서\n본문"
    assert sent["title"] == "의료기기 광고"


# ── 발신자 가드 (2026-08-02 회귀) ─────────────────────────────────
def test_send_email_refuses_invalid_sender(monkeypatch, caplog):
    """발신자 미설정 시 550 을 맞는 대신 보내지 않고 명시 실패."""
    import src.observability.notifications as N

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "resend")      # '@' 없는 계정명
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    monkeypatch.delenv("EMAIL_SERVER", raising=False)

    sent = []
    monkeypatch.setattr(N, "_conn", lambda: N._Conn("smtp.example.com", 587,
                                                    "resend", "pw", False))
    with caplog.at_level("ERROR"):
        ok = N.send_email(to="a@b.com", subject="s", body_text="b")
    assert ok is False
    assert sent == []
    assert "발신자" in caplog.text


def test_send_email_accepts_email_from(monkeypatch):
    """EMAIL_FROM 만 있어도 발신자로 성립한다(운영 관행)."""
    import src.observability.notifications as N

    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.setattr(N, "_conn", lambda: N._Conn("smtp.example.com", 587,
                                                    "resend", "pw", False))
    captured = {}

    class _FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, msg): captured["from"] = msg["From"]

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    assert N.send_email(to="a@b.com", subject="s", body_text="b") is True
    assert captured["from"] == "noreply@example.com"


def test_reply_to_falls_back_to_env(monkeypatch):
    """reply_to 미지정 시 NOTICE_REPLY_TO 를 쓴다."""
    import smtplib

    import src.observability.notifications as N

    monkeypatch.setenv("SMTP_FROM", "noreply@x.com")
    monkeypatch.setenv("NOTICE_REPLY_TO", "admin@example.com")
    monkeypatch.setattr(N, "_conn", lambda: N._Conn("smtp.x", 587, "u", "p", False))
    got = {}

    class _F:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, msg): got["reply"] = msg["Reply-To"]

    monkeypatch.setattr(smtplib, "SMTP", _F)
    assert N.send_email(to="a@b.com", subject="s", body_text="b") is True
    assert got["reply"] == "admin@example.com"


def test_display_name_sender_passes_guard(monkeypatch):
    """`MEDIREG AI <noreply@example.com>` 형식(2026-09-14 운영 기본값)이 발신자
    가드에 걸리지 않고 From 헤더로 그대로 나간다 — 받은편지함에 noreply 대신 서비스명."""
    from src.observability import notifications as N

    monkeypatch.setenv("EMAIL_SERVER", "smtps://resend:key@smtp.resend.com:465")
    monkeypatch.setenv("SMTP_FROM", "MEDIREG AI <noreply@example.com>")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")
    sent = {}

    class _SMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a): pass
        def starttls(self, *a, **k): pass
        def send_message(self, msg): sent["from"] = msg["From"]

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP_SSL", _SMTP)
    monkeypatch.setattr(smtplib, "SMTP", _SMTP)
    assert N.send_email(to="a@b.com", subject="s", body_text="t") is True
    assert sent["from"] == "MEDIREG AI <noreply@example.com>"
