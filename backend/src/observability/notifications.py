"""Notifications — 이메일 알림 (SMTP, 공급자 무관).

백엔드 주도 알림(보고서 완료·토큰 한도 등). **범용 SMTP**(stdlib smtplib)로 구현 —
Gmail SMTP·Resend·SendGrid 등 어떤 SMTP 공급자든 env 설정만으로 동작. SMTP 미설정
(dev)이면 로그만 남기고 성공 반환(graceful — 대화·보고서 흐름을 막지 않음).

회원 가입 이메일 인증은 medi-front NextAuth 가 처리 — 이 모듈은 백엔드 알림 전용.

**설정 두 방식** (EMAIL_SERVER 우선):
1. `EMAIL_SERVER=smtps://user:pass@smtp.resend.com:465` — medi-front(NextAuth·
   nodemailer)가 쓰는 **한 줄 URL**. 같은 값을 그대로 재사용해 시크릿 이중관리 방지.
   `smtps://`=SSL(465), `smtp://`=STARTTLS(587).
2. `SMTP_HOST/PORT(587)/USER/PASS/SSL` — 개별 지정.

공통: `SMTP_FROM`(미설정 시 사용자 계정).
"""

from __future__ import annotations

import logging
import os
from typing import NamedTuple, Optional
from urllib.parse import unquote, urlparse

_log = logging.getLogger(__name__)


class _Conn(NamedTuple):
    host: str
    port: int
    user: str | None
    password: str | None
    ssl: bool


def _conn() -> _Conn | None:
    """SMTP 접속 정보 — EMAIL_SERVER(URL) 우선, 없으면 SMTP_*. 미설정 시 None."""
    url = (os.getenv("EMAIL_SERVER") or "").strip()
    if url:
        u = urlparse(url)
        if not u.hostname:
            _log.warning("EMAIL_SERVER 파싱 실패(호스트 없음) — SMTP_* 로 폴백")
        else:
            # 암묵적 TLS 판정 — scheme(smtps) **또는 포트 465**.
            # ⚠️ 실측 사고(2026-07-25): `smtp://…@smtp.resend.com:465` 처럼
            # scheme 은 smtp 인데 포트가 465 인 URL(NextAuth EMAIL_SERVER 관행)에서
            # ssl=False 로 판정돼 평문 SMTP+STARTTLS 로 접속 → 465 는 핸드셰이크를
            # 즉시 기대하므로 **12초 타임아웃 후 실패**했다. 그 결과 보고서 완료
            # 메일·쿼터 알림이 조용히 전부 미발송(CLAUDE.md 주의 6 의 재발).
            port = u.port or (465 if u.scheme == "smtps" else 587)
            ssl = (u.scheme == "smtps") or port == 465
            return _Conn(u.hostname, port,
                         unquote(u.username) if u.username else None,
                         unquote(u.password) if u.password else None, ssl)
    host = os.getenv("SMTP_HOST")
    if not host:
        return None
    try:
        port = int((os.getenv("SMTP_PORT") or "").strip() or "587")
    except ValueError:
        port = 587
    return _Conn(host, port, os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"),
                 (os.getenv("SMTP_SSL") or "").strip() == "1")

def is_configured() -> bool:
    """SMTP 가 실제로 설정돼 있는가.

    미설정이면 `send_email` 은 **True 를 반환하는 stub** 이다(대화·보고서 흐름을
    막지 않으려는 의도). 그래서 "발송 완료 3/3" 같은 응답이 실제 발송을 뜻하지
    않는다 — 공지처럼 사람이 결과를 믿는 경로는 이 값을 같이 보여줘야 한다.
    """
    return _conn() is not None


# 첨부: (파일명, 내용(str|bytes), MIME) 리스트.
Attachment = tuple[str, "str | bytes", str]


def send_email(*, to: str, subject: str, body_text: str,
               body_html: Optional[str] = None,
               attachments: Optional[list[Attachment]] = None,
               reply_to: Optional[str] = None) -> bool:
    """SMTP 이메일 발송. 미설정(EMAIL_SERVER·SMTP_HOST 둘 다 없음) 시 stub(True)."""
    conn = _conn()
    if conn is None:
        _log.info("send_email STUB (EMAIL_SERVER/SMTP_HOST 미설정): to=%s subject=%r attach=%d",
                  to, subject, len(attachments or []))
        return True
    if not to:
        return False
    import smtplib
    import ssl
    from email.message import EmailMessage

    msg = EmailMessage()
    # 발신자 — SMTP_FROM > **EMAIL_FROM** > (이메일 형태일 때만) 계정 user.
    # ⚠️ 실측(2026-07-25): EMAIL_SERVER/EMAIL_FROM 쌍(medi-front NextAuth 와
    # 공유하는 관행)을 쓰는데 코드가 EMAIL_FROM 을 안 읽어, conn.user 인
    # `resend`(계정명, 이메일 아님)가 From 으로 나가 **501 Bad sender address
    # syntax** 로 거절됐다. user 가 '@' 없는 계정명이면 발신자로 쓰지 않는다.
    _user_as_from = conn.user if (conn.user and "@" in conn.user) else None
    sender = (os.getenv("SMTP_FROM") or os.getenv("EMAIL_FROM")
              or _user_as_from or "no-reply@medi")
    # ⚠️ 실측(2026-08-02): 운영 compose 가 EMAIL_FROM 을 컨테이너로 전달하지 않아
    # 폴백 `no-reply@medi`(도메인 없는 무효 주소)로 나갔고, Resend 가 **550
    # Invalid `from` field** 로 전부 거절했다 — 보고서 완료 메일이 조용히 0통.
    # 폴백을 그대로 두면 같은 사고가 반복되므로, 발신자가 성립하지 않으면
    # **보내지 않고 명시 실패**한다(무엇을 고쳐야 하는지 로그가 말하게).
    if "@" not in sender or "." not in sender.rsplit("@", 1)[-1]:
        _log.error("send_email 중단 — 발신자 주소가 유효하지 않음(%r). "
                   "SMTP_FROM 또는 EMAIL_FROM 을 설정하고, 운영은 "
                   "docker-compose.yml 의 environment 매핑도 확인할 것.", sender)
        return False
    msg["From"] = sender
    msg["To"] = to
    # 회신 주소 — From 은 발송 도메인(noreply@…)이라 답장이 아무도 안 읽는 함정.
    # 공지 본문이 "이 메일로 회신해 달라"고 안내하면 Reply-To 가 **반드시** 있어야 한다.
    _reply = reply_to or os.getenv("NOTICE_REPLY_TO")
    if _reply:
        msg["Reply-To"] = _reply
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    for name, content, mime in (attachments or []):
        maintype, _, subtype = mime.partition("/")
        data = content.encode("utf-8") if isinstance(content, str) else content
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream",
                           filename=name)

    try:
        if conn.ssl:
            with smtplib.SMTP_SSL(conn.host, conn.port, timeout=15,
                                  context=ssl.create_default_context()) as s:
                if conn.user:
                    s.login(conn.user, conn.password or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(conn.host, conn.port, timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                if conn.user:
                    s.login(conn.user, conn.password or "")
                s.send_message(msg)
        _log.info("send_email 발송: to=%s subject=%r attach=%d",
                  to, subject, len(attachments or []))
        return True
    except Exception as e:  # noqa: BLE001 — 발송 실패가 호출 흐름을 막으면 안 됨
        # 원인까지 남긴다 — 구현은 유형명만 찍어(`SMTPServerDisconnected`) 설정
        # 오류(포트/TLS 불일치)를 몇 달간 숨겼다. 배선 오류는 보여야 고쳐진다.
        _log.warning("send_email 실패: %s: %s (to=%s host=%s:%s ssl=%s)",
                     type(e).__name__, str(e)[:120], to,
                     conn.host, conn.port, conn.ssl)
        return False


def notify_quota_reached(*, email: str, daily_used: int, daily_limit: int) -> bool:
    """사용자가 일 토큰 한도에 도달했을 때 호출."""
    return send_email(
        to=email,
        subject="[medi] 오늘 사용량 한도 도달",
        body_text=(
            f"오늘 토큰 사용량이 한도에 도달했습니다 ({daily_used:,} / {daily_limit:,}).\n"
            f"내일 0시(UTC)에 자동으로 초기화됩니다."
        ),
    )


def notify_report_ready(*, email: str, thread_id: str, report_id: str,
                        report_md: Optional[str] = None,
                        title: Optional[str] = None,
                        fmt: Optional[str] = None,
                        is_document: bool = False) -> bool:
    """심층 보고서/서류 초안 완성 시 호출 — 전문을 첨부해 발송(기본 DOCX).

    `is_document`: 서류 초안(kind="doc") — 제목·본문 문구를 서류로(책임 분리
    2026-08-27, "서식은 심층보고서와 다른데 왜 보고서로 묶이냐").
    `fmt`(기본 env `REPORT_ATTACH_FORMAT`, 없으면 docx): docx|md. 변환 불가 시
    .md 로 폴백(발송 자체는 계속). 사이드바 다운로드도 병행.
    """
    fmt = (fmt or os.getenv("REPORT_ATTACH_FORMAT") or "docx").lower()
    attachments: list[Attachment] = []
    kind = "Markdown"
    if report_md:
        from src.reports_convert import ConversionUnavailable, convert
        try:
            data, mime, ext = convert(report_md, fmt)
        except ConversionUnavailable as e:
            _log.warning("보고서 첨부 변환 폴백(.md): %s", e)
            data, mime, ext = report_md.encode("utf-8"), "text/markdown", "md"
        kind = "Word(DOCX)" if ext == "docx" else "Markdown"
        attachments.append((f"medi_report_{report_id}.{ext}", data, mime))

    subj = "[medi] 심층 보고서 준비 완료" + (f" — {title}" if title else "")
    body = (
        f"요청하신 심층 보고서가 준비됐습니다.\n\n"
        f"· 첨부: 보고서 전문({kind})\n"
        f"· 앱 사이드바에서도 열람·다운로드하실 수 있습니다.\n\n"
        f"(report_id: {report_id})"
    )
    return send_email(to=email, subject=subj, body_text=body, attachments=attachments)
