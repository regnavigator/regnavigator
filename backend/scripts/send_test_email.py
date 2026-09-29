"""SMTP 설정 검증 — 테스트 메일 1통 발송(보고서 첨부 시뮬 포함).

`.env` 의 SMTP_* 를 채운 뒤 이걸 돌려 **실제로 도착하는지** 확인한다. 도착하면
보고서 완료 알림도 그대로 동작한다(같은 `send_email` 경로).

SMTP_HOST 미설정이면 stub(로그만) — "설정이 안 됐다"는 뜻이지 실패가 아니다.

usage:
  python scripts/send_test_email.py you@example.com
  python scripts/send_test_email.py you@example.com --with-attachment
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/send_test_email.py <받는사람@메일>"
              " [--with-attachment]")
        return 1
    to = sys.argv[1]
    attach = "--with-attachment" in sys.argv

    from src.observability.notifications import _conn

    conn = _conn()
    if conn is None:
        print("이메일 미설정 — stub 모드(로그만). 아래 중 하나를 .env 에 넣으세요.\n"
              "  ① medi-front(NextAuth·Resend)와 같은 값 재사용 — 권장:\n"
              "     EMAIL_SERVER=smtps://resend:<RESEND_API_KEY>@smtp.resend.com:465\n"
              "  ② 개별 지정:\n"
              "     SMTP_HOST=smtp.gmail.com  SMTP_PORT=587\n"
              "     SMTP_USER=<계정>  SMTP_PASS=<앱 비밀번호>\n"
              "  공통: SMTP_FROM=<발신주소>  (Resend 는 인증된 도메인만 발신 가능)")
        return 1

    print(f"[smtp] {conn.host}:{conn.port} ssl={conn.ssl} user={conn.user} "
          f"from={os.getenv('SMTP_FROM') or conn.user} → {to}")

    from src.observability.notifications import notify_report_ready, send_email

    if attach:
        md = ("# 테스트 보고서\n\n## 개요\n첨부 변환(DOCX) 확인용입니다 [1].\n\n"
              "## References\n[1] 의료기기법 제25조\n")
        ok = notify_report_ready(email=to, thread_id="test", report_id="rpt_test",
                                 report_md=md, title="SMTP 설정 검증")
        what = "보고서 완료 알림(전문 첨부)"
    else:
        ok = send_email(to=to, subject="[medi] SMTP 설정 검증",
                        body_text="이 메일이 도착했다면 SMTP 설정이 정상입니다.")
        what = "단순 테스트 메일"

    print(f"[smtp] {what} 발송 {'성공 ✓ (받은편지함 확인)' if ok else '실패 ✗ (위 경고 로그 확인)'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
