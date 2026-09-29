"""공지 메일 — 수신자 해석 · 브랜드 HTML 템플릿 · 예약 발송 큐.

`/admin/notify` 라우트와 예약 스케줄러가 **같은 경로**를 쓰도록 도메인 로직을
여기 모았다(라우트에만 있으면 예약 발송이 조용히 다른 규칙으로 나간다).

예약 저장은 `settings_repo` KV(`admin.scheduled_notices`) 에 JSON 배열.
전용 테이블을 안 만든 이유: 건수가 수십 규모고, 쓰기 주체가 admin 라우트와
스케줄러 루프뿐이며 **워커가 1개**(CLAUDE.md §7)라 경합이 없다. 규모가 커지면
전용 테이블로 승격할 것 — 그때 `_load`/`_save` 만 바꾸면 된다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

_log = logging.getLogger(__name__)

_STORE_KEY = "admin.scheduled_notices"

# 브랜드 팔레트 — medi-front `src/styles/globals.css` 와 동기(Sage #0F6B4A 계열).
# 이메일 클라이언트는 CSS 변수·외부 스타일시트를 대부분 무시하므로 **인라인 값**으로
# 박는다. 프런트 토큰이 바뀌면 여기도 같이 바꿔야 한다(자동 동기 없음).
BRAND = {
    "primary": "#0F6B4A",
    "primary_container": "#0A553B",
    "on_primary": "#FFFFFF",
    "primary_fixed": "#DCEAE3",
    "surface": "#FFFFFF",
    "page": "#F4F7F5",
    "on_surface": "#12211B",
    "on_surface_variant": "#5A6B63",
    "outline": "#DBE4DF",
}

from src.config import env_nonempty as _env_nonempty

APP_URL = _env_nonempty("APP_URL").rstrip("/")


# ---------------------------------------------------------------------------
# 수신자 해석
# ---------------------------------------------------------------------------

AUDIENCES = ("all", "admins", "whitelisted", "beta_testers")


def resolve_recipients(to: Any) -> list[str]:
    """`to` → 이메일 목록(중복 제거, 순서 보존).

    - list: 명시 주소(관리 화면에서 체크한 사람들)
    - "all": 비활성 제외 전체 회원 · "admins": 관리자
    - "whitelisted": 화이트리스트로 허용된 **가입 회원**
    - "beta_testers": 화이트리스트 항목 전체(미가입 초대자 포함, @도메인 제외)

    프리셋은 **발송 시점에** 해석된다 — 예약 공지는 예약 후 추가된 테스터에게도
    나간다(초대 공지의 의도). 특정 명단으로 고정하려면 list 로 넘길 것.
    """
    from src.persistence import get_users_repo

    if isinstance(to, list):
        emails = [str(e).strip() for e in to if str(e).strip()]
    elif to == "beta_testers":
        from src.persistence.whitelist_repo import get_whitelist_repo

        raw = (os.getenv("BETA_WHITELIST_EMAILS") or "").strip()
        entries = {e.strip().lower() for e in raw.split(",") if e.strip()}
        entries |= get_whitelist_repo().entries()
        emails = sorted(e for e in entries if "@" in e and not e.startswith("@"))
    else:
        # 전수 페이지네이션 — 종전 list_all(limit=1000) 단발은 회원 1,000명 초과
        # 시 수신자가 경고 없이 잘렸다(2026-08-11 발견).
        _all = []
        _off = 0
        while True:
            _page = get_users_repo().list_all(limit=1000, offset=_off)
            _all.extend(_page)
            if len(_page) < 1000:
                break
            _off += 1000
        users = [u for u in _all
                 if u.email and not getattr(u, "deleted_at", None)]
        if to == "admins":
            users = [u for u in users if u.is_admin]
        elif to == "whitelisted":
            # 종전엔 `routes.admin._whitelist_classifier` 를 import 해
            # `notices → routes.admin → notices` 순환이었다(2026-09-10 해소).
            from src.whitelist import classifier

            _, classify = classifier()
            users = [u for u in users if classify(u.email)[1] is not None]
        emails = [u.email for u in users]

    seen: set[str] = set()
    out: list[str] = []
    for e in emails:
        k = e.lower()
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def honors_notice_optout(to: Any) -> bool:
    """수신거부를 적용할 발송인가. 관리자 대상 운영 공지(`to="admins"`)·개별 지정
    발송(주소 목록)은 예외 — 장애 고지 같은 운영 필수 연락까지 막으면 안 된다."""
    return to != "admins" and not isinstance(to, list)


def filter_notice_optout(emails: list[str]) -> list[str]:
    """서비스 안내 메일 **수신거부자**를 뺀다(2026-09-10 도입·철회 → 09-14 재도입).

    마케팅 동의(§50 사전동의, `filter_marketing_consented`)와 다른 축이다.
    서비스 고지는 사전동의 없이 보낼 수 있지만, 받는 사람이 그만 받겠다고 하면
    빼준다(§50④ 수신거부 수단). 뉴스레터 푸터가 이 설정을 안내한다.

    가입 회원이 아닌 주소(미가입 초대자 등)는 거부 이력이 없으므로 그대로 둔다.
    """
    from src.persistence import get_users_repo

    optout: set[str] = set()
    try:
        _off = 0
        while True:
            page = get_users_repo().list_all(limit=1000, offset=_off)
            for u in page:
                if u.email and not getattr(u, "notice_email_opt_in", True):
                    optout.add(u.email.lower())
            if len(page) < 1000:
                break
            _off += 1000
    except Exception:  # noqa: BLE001 — 조회 실패로 발송을 막지 않는다
        _log.warning("안내 메일 수신거부 조회 실패 — 필터 미적용", exc_info=True)
        return emails
    return [e for e in emails if e.lower() not in optout]


def filter_marketing_consented(emails: list[str]) -> list[str]:
    """marketing 동의자만 남긴다 — legal_consent **최신** 기록의 scopes 기준.

    수집(OPTIONAL_SCOPES)만 하고 소비처가 0이던 배선 누락 해소(2026-08-11).
    마케팅성 공지(`marketing: true`)에만 적용 — 서비스 고지는 동의 불요(정보통신망법
    §50 영리목적 광고에만 사전동의 요구).
    """
    import json as _json

    from src.persistence import get_events_repo, get_users_repo

    latest_ok: dict[str, bool] = {}
    # list_by_type 은 ts DESC — 사용자별 처음 만난 행이 최신 동의.
    for ev in get_events_repo().list_by_type("legal_consent", limit=100_000):
        uid = ev.user_id
        if not uid or uid in latest_ok:
            continue
        try:
            scopes = _json.loads(ev.payload_json or "{}").get("scopes") or []
        except Exception:  # noqa: BLE001
            scopes = []
        latest_ok[uid] = "marketing" in scopes
    consented: set[str] = set()
    urepo = get_users_repo()
    for uid, ok in latest_ok.items():
        if not ok:
            continue
        try:
            u = urepo.get(uid)
        except Exception:  # noqa: BLE001
            u = None
        if u and u.email:
            consented.add(u.email.lower())
    return [e for e in emails if e.lower() in consented]


# ---------------------------------------------------------------------------
# 브랜드 HTML 템플릿
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"(https?://[^\s<>\"]+)")


def to_plain_text(body_text: str) -> str:
    """마크업 표식(`## `, `- `)을 걷어낸 평문 — text/plain 파트용.

    HTML 을 막아 둔 클라이언트에는 이 버전이 보인다. `##` 가 그대로 노출되면
    작성자가 의도한 '깔끔한 안내문'이 아니라 마크다운 소스처럼 읽힌다.
    """
    out = []
    for line in (body_text or "").split("\n"):
        s = line.strip()
        if s.startswith("## "):
            out.append(f"[ {s[3:].strip()} ]")
        elif s.startswith("- "):
            out.append(f"· {s[2:].strip()}")
        else:
            out.append(line)
    return "\n".join(out)


def _linkify(escaped: str) -> str:
    """escape 된 텍스트의 URL 을 링크로. escape 이후에 호출해야 안전하다."""
    return _URL_RE.sub(
        lambda m: f'<a href="{m.group(1)}" style="color:{BRAND["primary"]};'
                  f'word-break:break-all;">{m.group(1)}</a>',
        escaped,
    )


def render_notice_html(*, subject: str, body_text: str,
                       cta_url: Optional[str] = None,
                       cta_label: Optional[str] = None,
                       footer_note: Optional[str] = None) -> str:
    """평문 본문 → 서비스 테마의 HTML 메일.

    이메일 렌더러는 flex/grid·`<style>`·웹폰트를 신뢰할 수 없다. 그래서 **table
    레이아웃 + 인라인 스타일 + 시스템 폰트 스택**만 쓴다.

    본문 표기(평문으로 써도 읽히는 최소 문법만):
      `## 소제목`  → 구분선 있는 섹션 제목(본문과 확실히 구분)
      `- 항목`     → 불릿 목록
      빈 줄        → 문단 구분 · 문단 안 줄바꿈은 `<br>` 로 보존
      맨 URL       → 자동 링크
    """
    blocks = [b for b in (body_text or "").split("\n\n") if b.strip()]
    parts: list[str] = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        buf: list[str] = []          # 일반 문장 누적
        bullets: list[str] = []      # 불릿 누적

        def _flush_text():
            if buf:
                parts.append(
                    f'<p style="margin:0 0 14px;font-size:15px;line-height:1.75;'
                    f'color:{BRAND["on_surface"]};">'
                    + _linkify("<br>".join(escape(x) for x in buf))
                    + "</p>"
                )
                buf.clear()

        def _flush_bullets():
            if bullets:
                items = "".join(
                    f'<li style="margin:0 0 7px;font-size:15px;line-height:1.7;'
                    f'color:{BRAND["on_surface"]};">{_linkify(escape(b))}</li>'
                    for b in bullets
                )
                parts.append(
                    f'<ul style="margin:0 0 14px;padding-left:20px;">{items}</ul>')
                bullets.clear()

        for raw in lines:
            s = raw.strip()
            if s.startswith("## "):
                _flush_text(); _flush_bullets()
                parts.append(
                    f'<h2 style="margin:26px 0 12px;padding-bottom:7px;'
                    f'border-bottom:1px solid {BRAND["outline"]};'
                    f'font-size:14px;font-weight:700;letter-spacing:.02em;'
                    f'color:{BRAND["primary"]};">{escape(s[3:].strip())}</h2>')
            elif s.startswith("- "):
                _flush_text()
                bullets.append(s[2:].strip())
            else:
                _flush_bullets()
                buf.append(s)
        _flush_text(); _flush_bullets()

    body_html = "".join(parts) or (
        f'<p style="margin:0;font-size:15px;color:{BRAND["on_surface"]};">'
        f'{escape(body_text)}</p>')

    cta = ""
    if cta_url:
        cta = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'style="margin:22px 0 4px;"><tr><td '
            f'style="background:{BRAND["primary"]};border-radius:8px;">'
            f'<a href="{escape(cta_url, quote=True)}" '
            f'style="display:inline-block;padding:11px 22px;font-size:14px;'
            f'font-weight:600;color:{BRAND["on_primary"]};text-decoration:none;">'
            f'{escape(cta_label or "바로가기")}</a></td></tr></table>'
        )

    note = escape(footer_note) if footer_note else (
        "이 메일은 MEDIREG 클로즈 베타 참여자에게 발송된 서비스 안내입니다."
    )

    return f"""\
<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:{BRAND['page']};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{BRAND['page']};padding:28px 12px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="max-width:560px;background:{BRAND['surface']};
                  border:1px solid {BRAND['outline']};border-radius:14px;
                  overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,
                  'Segoe UI','Noto Sans KR',Roboto,'Malgun Gothic',sans-serif;">
      <tr><td style="background:{BRAND['primary']};padding:18px 28px;">
        <span style="font-size:15px;font-weight:700;letter-spacing:.14em;
                     color:{BRAND['on_primary']};">MEDIREG</span>
        <span style="font-size:11.5px;color:{BRAND['primary_fixed']};
                     margin-left:10px;">의료규제 특화 AI 에이전트</span>
      </td></tr>
      <tr><td style="padding:28px 28px 8px;">
        <h1 style="margin:0 0 18px;font-size:19px;line-height:1.4;font-weight:700;
                   color:{BRAND['on_surface']};">{escape(subject)}</h1>
        {body_html}
        {cta}
      </td></tr>
      <tr><td style="padding:18px 28px 24px;">
        <div style="border-top:1px solid {BRAND['outline']};padding-top:14px;
                    font-size:11.5px;line-height:1.7;
                    color:{BRAND['on_surface_variant']};">
          {note}<br>
          문의는 이 메일에 회신해 주세요 ·
          <a href="{APP_URL}" style="color:{BRAND['primary']};
             text-decoration:none;">{APP_URL.replace('https://', '')}</a>
        </div>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


# ---------------------------------------------------------------------------
# 발송
# ---------------------------------------------------------------------------

def send_notice(*, subject: str, body_text: str, emails: list[str],
                body_html: Optional[str] = None,
                template: str = "branded",
                cta_url: Optional[str] = None,
                cta_label: Optional[str] = None,
                reply_to: Optional[str] = None,
                attachments: Optional[list] = None) -> dict:
    """개별 발송(주소 상호 비노출). {sent, failed, smtp_configured} 반환.

    `template="branded"` 면 평문 본문으로 브랜드 HTML 을 만들어 대안 파트로 함께
    보낸다(HTML 차단 클라이언트는 평문을 본다). `body_html` 을 직접 주면 그것을 쓴다.

    `attachments`: `[(filename, bytes|str, mime)]` — 홍보물 PDF 등 동봉용
    (2026-08-19). 종전엔 `send_email` 이 첨부를 지원하는데도 공지 경로가 인자를
    넘기지 않아 **첨부 자체가 불가능**했다. 수신자 수 × 파일 크기만큼 SMTP 트래픽이
    늘어나므로 대용량은 링크를 권장.
    """
    from src.observability.notifications import is_configured, send_email

    html = body_html
    if html is None and template == "branded":
        html = render_notice_html(subject=subject, body_text=body_text,
                                  cta_url=cta_url, cta_label=cta_label)
    # 평문 파트는 표식(`## `·`- `)을 걷어낸 버전 — HTML 차단 클라이언트가
    # 마크다운 소스를 읽게 두지 않는다.
    body_text = to_plain_text(body_text)

    sent = 0
    failed: list[str] = []
    for e in emails:
        try:
            if send_email(to=e, subject=subject, body_text=body_text,
                          body_html=html, reply_to=reply_to,
                          attachments=attachments or None):
                sent += 1
            else:
                failed.append(e)
        except Exception:  # noqa: BLE001 — 개별 실패가 나머지 발송을 막지 않게
            _log.exception("공지 발송 실패: to=%s", e)
            failed.append(e)
    return {"sent": sent, "failed": failed, "smtp_configured": is_configured()}


# ---------------------------------------------------------------------------
# 베타 초대
# ---------------------------------------------------------------------------

# 문구는 2026-08-03 베타 오픈 때 실제로 발송한 공지("[MediReg AI] 베타 서비스를
# 시작합니다", to=beta_testers)를 그대로 이어받는다. 새로 지어내면 서비스명·가입
# 절차가 어긋난다 — 실제로 한 번 어긋났다(가입 절차가 없다고 썼는데 /landing 에서
# 계정을 만들고 비밀번호를 쓴다).
SIGNUP_URL = f"{APP_URL}/landing"
INVITE_SUBJECT = "[MediReg AI] 베타 서비스를 시작합니다"

_INVITE_BODY = f"""MediReg AI 베타 서비스를 시작합니다.

MediReg AI는 의료기기 인허가·규제 업무를 위한 AI 어시스턴트입니다. 법령·시행규칙·고시 원문을 검색해 답변하고, 답변에 근거 조문을 함께 표시합니다.

## 질문 예시
- 2등급 의료기기 제조허가에 필요한 기술문서 항목
- SaMD 변경허가 대상 범위
- 체외진단의료기기 임상적 성능시험 자료의 요건과 면제 조건

## 심층 보고서
주제를 지정하면 근거 자료를 모아 보고서를 작성합니다. 핵심 결론·근거·실무 액션·리스크로 구성되며, 완료되면 Word 파일로 메일에 첨부해 보내드립니다. 작성에는 20분 내외가 걸리며, 그동안 다른 질문을 이어갈 수 있습니다.

## 계정 생성
{SIGNUP_URL}

- 사전등록하신 이메일 주소로만 가입할 수 있습니다.
- 비밀번호를 잊은 경우 로그인 화면에서 이메일로 재설정할 수 있습니다.

## 문의
답변 아래 피드백 버튼 또는 이 메일 회신으로 의견과 오류를 알려주시면 개선에 반영합니다.

답변은 참고 자료입니다. 최종 판단은 법령 원문과 소관 부처 확인을 거쳐 주시기 바랍니다.

MediReg AI 드림"""


# 관리자 수정본(2026-08-28) — app_settings KV. 진실원은 DB(재기동 생존),
# 미설정이면 위 기본 문구. 발송 직전에 읽으므로 저장 즉시 다음 발송에 반영.
_INVITE_TPL_KEY = "invite_template"


def get_invite_template() -> dict:
    """현재 발송될 초대 메일 내용. {subject, body, is_custom, updated_at?, updated_by?}"""
    import json as _json

    from src.persistence.settings_repo import get_settings_repo

    raw = get_settings_repo().get(_INVITE_TPL_KEY)
    if raw:
        try:
            d = _json.loads(raw)
            if str(d.get("subject") or "").strip() and str(d.get("body") or "").strip():
                return {"subject": d["subject"], "body": d["body"], "is_custom": True,
                        "updated_at": d.get("updated_at"), "updated_by": d.get("updated_by")}
        except Exception:  # noqa: BLE001 — 깨진 저장값이면 기본 문구로
            _log.exception("invite_template 파싱 실패 — 기본 문구 사용")
    return {"subject": INVITE_SUBJECT, "body": _INVITE_BODY, "is_custom": False}


def set_invite_template(subject: str, body: str, *, updated_by: Optional[str] = None) -> None:
    import json as _json

    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(_INVITE_TPL_KEY, _json.dumps({
        "subject": subject.strip(), "body": body.strip(),
        "updated_by": updated_by,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False), updated_by=updated_by)


def reset_invite_template(*, updated_by: Optional[str] = None) -> None:
    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(_INVITE_TPL_KEY, None, updated_by=updated_by)


def send_beta_invite(emails: list[str], *, invited_by: Optional[str] = None) -> dict:
    """화이트리스트 신규 등록자에게 초대 메일 발송. {sent, failed, smtp_configured}.

    호출부(admin 라우트)가 **신규 등록된 실제 이메일만** 넘긴다 — 재등록·중복·
    `@도메인` 항목에 다시 보내면 스팸이 된다.
    """
    if invited_by:
        _log.info("베타 초대 발송 %d건 (등록자=%s)", len(emails), invited_by)
    tpl = get_invite_template()
    return send_notice(
        subject=tpl["subject"],
        body_text=tpl["body"],
        emails=emails,
        cta_url=SIGNUP_URL,
        cta_label="계정 만들기",
    )


# ---------------------------------------------------------------------------
# 예약 큐
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_send_at(raw: str) -> datetime:
    """ISO8601 → tz-aware UTC. tz 없으면 **UTC 로 간주**(프런트는 항상 Z 를 붙인다)."""
    s = str(raw).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _load() -> list[dict]:
    from src.persistence.settings_repo import get_settings_repo

    raw = get_settings_repo().get(_STORE_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except ValueError:
        _log.warning("예약 공지 저장값 파싱 실패 — 빈 목록으로 취급")
        return []


def _save(items: list[dict], *, updated_by: Optional[str] = None) -> None:
    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(_STORE_KEY, json.dumps(items, ensure_ascii=False),
                            updated_by=updated_by)


def list_scheduled() -> list[dict]:
    """예약 목록 — 발송 예정 시각 오름차순."""
    return sorted(_load(), key=lambda x: str(x.get("send_at") or ""))


def schedule_notice(*, subject: str, body_text: str, to: Any, send_at: datetime,
                    body_html: Optional[str] = None, template: str = "branded",
                    cta_url: Optional[str] = None, cta_label: Optional[str] = None,
                    reply_to: Optional[str] = None,
                    created_by: Optional[str] = None,
                    marketing: bool = False) -> dict:
    item = {
        "id": f"ntc_{uuid.uuid4().hex[:12]}",
        "marketing": marketing,
        "subject": subject,
        "body": body_text,
        "body_html": body_html,
        "template": template,
        "cta_url": cta_url,
        "cta_label": cta_label,
        "reply_to": reply_to,
        "to": to,
        "send_at": send_at.astimezone(timezone.utc).isoformat(),
        "status": "pending",
        "created_by": created_by,
        "created_at": _now().isoformat(),
        "sent_at": None,
        "result": None,
    }
    items = _load()
    items.append(item)
    _save(items, updated_by=created_by)
    return item


def cancel_scheduled(notice_id: str) -> bool:
    """미발송(pending) 예약 취소. 이미 나간 건은 취소 불가(False)."""
    items = _load()
    for i, it in enumerate(items):
        if it.get("id") == notice_id and it.get("status") == "pending":
            del items[i]
            _save(items)
            return True
    return False


def run_due(*, now: Optional[datetime] = None) -> list[dict]:
    """예정 시각이 지난 pending 공지를 발송하고 결과를 기록한다.

    한 건씩 **발송 직후 저장**한다 — 중간에 프로세스가 죽어도 이미 나간 공지가
    pending 으로 남아 재발송되지 않게(중복 발송이 미발송보다 나쁘다).
    """
    now = now or _now()
    fired: list[dict] = []
    for item in list(_load()):
        if item.get("status") != "pending":
            continue
        try:
            due = parse_send_at(item.get("send_at") or "")
        except ValueError:
            _log.warning("예약 공지 시각 파싱 실패 — 건너뜀: %s", item.get("id"))
            continue
        if due > now:
            continue

        # 먼저 'sending' 으로 못박고 저장 → 크래시해도 재발송 안 됨.
        _update(item["id"], {"status": "sending"})
        emails = resolve_recipients(item.get("to") or "all")
        if item.get("marketing"):
            emails = filter_marketing_consented(emails)
        if honors_notice_optout(item.get("to") or "all"):
            emails = filter_notice_optout(emails)
        if not emails:
            _update(item["id"], {"status": "skipped", "sent_at": now.isoformat(),
                                 "result": {"reason": "수신자 없음"}})
            continue
        res = send_notice(
            subject=item.get("subject") or "",
            body_text=item.get("body") or "",
            emails=emails,
            body_html=item.get("body_html"),
            template=item.get("template") or "branded",
            cta_url=item.get("cta_url"),
            cta_label=item.get("cta_label"),
            reply_to=item.get("reply_to"),
        )
        _update(item["id"], {
            "status": "sent",
            "sent_at": now.isoformat(),
            "result": {"requested": len(emails), **res},
        })
        _log.info("예약 공지 발송: id=%s %s/%s (smtp=%s)", item["id"],
                  res["sent"], len(emails), res["smtp_configured"])
        fired.append({**item, "result": res})
    return fired


def _update(notice_id: str, patch: dict) -> None:
    items = _load()
    for it in items:
        if it.get("id") == notice_id:
            it.update(patch)
            break
    _save(items)
