"""뉴스레터(2026-09-22) — 관리 화면에서 작성·수정·미리보기·수신자 선택·발송·발송 이력.

종전엔 뉴스레터마다 `local/04_공지메일/send_newsletter_*.py` 스크립트를 새로 만들어
`/admin/notify` 에 HTML 을 넘겼다(개발자만 보낼 수 있었고, 누구에게 나갔는지는 터미널
출력으로만 남았다). 이제 '메일 발신' 권한을 가진 관리자가 화면에서 한다.

저장(app_settings KV — 공지 예약·업데이트 내역과 같은 패턴, 워커 1개라 경합 없음):
- `newsletters.index`       메타 목록(최신순) — 목록 화면이 본문을 안 읽게
- `newsletter:{id}`         본문(HTML·평문)
- `newsletter_sends:{id}`   발송 이력 — 회차별 수신자·결과(성공/실패/제외 사유)

수신 자격(발송 시점에 서버가 다시 판정 — 화면의 비활성 표시는 안내일 뿐):
- 탈퇴(비활성) 계정 → 제외
- 서비스 안내 메일 수신거부(`notice_email_opt_in=False`) → 제외(§50④ 수신거부)
- 광고성(`marketing=True`) 뉴스레터는 마케팅 수신 동의자만(§50 사전동의).
  미가입 초대자는 동의 기록이 없으므로 광고성이면 제외.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Optional

_log = logging.getLogger(__name__)

_INDEX_KEY = "newsletters.index"
_BODY_KEY = "newsletter:{id}"
_SENDS_KEY = "newsletter_sends:{id}"

SUBJECT_MAX = 200
HTML_MAX = 1_000_000          # 1MB — 메일 본문으로는 이미 과함(수신 서버가 자른다)
TEXT_MAX = 100_000
MAX_NEWSLETTERS = 300
AD_PREFIX = "(광고)"          # 정보통신망법 §50④ — 광고성 정보는 제목 앞에 표기

REASON_LABELS = {
    "deleted": "탈퇴·비활성 계정",
    "notice_optout": "안내 메일 수신 거부",
    "no_marketing_consent": "마케팅 수신 미동의",
    "unknown": "수신자 목록에 없는 주소",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo():
    from src.persistence.settings_repo import get_settings_repo

    return get_settings_repo()


def _get_json(key: str, default):
    raw = _repo().get(key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        _log.warning("뉴스레터 저장값 파싱 실패: %s", key)
        return default


def _set_json(key: str, value, *, by: Optional[str]) -> None:
    _repo().set(key, json.dumps(value, ensure_ascii=False), updated_by=by)


# ---------------------------------------------------------------------------
# HTML → 평문(text/plain 파트)
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
              "table", "section", "article", "header", "footer", "hr"}
    _SKIP = {"style", "script", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0
        self._href: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("· ")
        if tag == "a":
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.out.append("\n")
        if tag == "a" and self._href and self._href.startswith("http"):
            self.out.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html or "")
        p.close()
    except Exception:  # noqa: BLE001 — 깨진 HTML 이어도 평문은 최대한 뽑는다
        pass
    text = "".join(p.out).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# ---------------------------------------------------------------------------
# 작성·수정
# ---------------------------------------------------------------------------

def _clean(payload: dict) -> dict:
    subject = str(payload.get("subject") or "").strip()
    body_html = str(payload.get("body_html") or "")
    body_text = str(payload.get("body_text") or "").strip()
    if not subject:
        raise ValueError("제목이 필요합니다.")
    if len(subject) > SUBJECT_MAX:
        raise ValueError(f"제목은 {SUBJECT_MAX}자 이하")
    if len(body_html) > HTML_MAX:
        raise ValueError(f"HTML 이 너무 큽니다({len(body_html):,}자 > {HTML_MAX:,}자)")
    if len(body_text) > TEXT_MAX:
        raise ValueError(f"평문 본문은 {TEXT_MAX:,}자 이하")
    if not body_html.strip() and not body_text:
        raise ValueError("HTML 또는 평문 본문 중 하나는 필요합니다.")
    return {
        "subject": subject,
        "body_html": body_html if body_html.strip() else "",
        "body_text": body_text,
        "marketing": bool(payload.get("marketing")),
        "reply_to": (str(payload.get("reply_to") or "").strip() or None),
        "source_filename": (str(payload.get("source_filename") or "").strip()[:200] or None),
    }


def _meta(item: dict) -> dict:
    keys = ("id", "subject", "marketing", "created_by", "created_at", "updated_by",
            "updated_at", "last_sent_at", "sent_count", "send_runs", "source_filename")
    return {k: item.get(k) for k in keys}


def list_newsletters() -> list[dict]:
    idx = _get_json(_INDEX_KEY, [])
    return [m for m in idx if isinstance(m, dict)]


def get_newsletter(nid: str) -> Optional[dict]:
    item = _get_json(_BODY_KEY.format(id=nid), None)
    return item if isinstance(item, dict) else None


def _write(item: dict, *, by: Optional[str]) -> None:
    _set_json(_BODY_KEY.format(id=item["id"]), item, by=by)
    idx = [m for m in list_newsletters() if m.get("id") != item["id"]]
    idx.insert(0, _meta(item))
    idx.sort(key=lambda m: str(m.get("updated_at") or ""), reverse=True)
    _set_json(_INDEX_KEY, idx[:MAX_NEWSLETTERS], by=by)


def create_newsletter(payload: dict, *, by: Optional[str]) -> dict:
    data = _clean(payload)
    now = _now()
    item = {"id": f"nl_{uuid.uuid4().hex[:12]}", **data,
            "created_by": by, "created_at": now, "updated_by": by, "updated_at": now,
            "last_sent_at": None, "sent_count": 0, "send_runs": 0}
    _write(item, by=by)
    return item


def update_newsletter(nid: str, payload: dict, *, by: Optional[str]) -> Optional[dict]:
    item = get_newsletter(nid)
    if not item:
        return None
    item.update(_clean({**item, **payload}))
    item["updated_by"] = by
    item["updated_at"] = _now()
    _write(item, by=by)
    return item


def delete_newsletter(nid: str, *, by: Optional[str]) -> bool:
    """이미 발송한 뉴스레터는 지우지 않는다 — 누구에게 나갔는지가 기록으로 남아야 한다."""
    item = get_newsletter(nid)
    if not item:
        return False
    if item.get("send_runs"):
        raise ValueError("발송 이력이 있는 뉴스레터는 삭제할 수 없습니다.")
    _repo().set(_BODY_KEY.format(id=nid), None, updated_by=by)
    _set_json(_INDEX_KEY, [m for m in list_newsletters() if m.get("id") != nid], by=by)
    return True


def rendered_html(item: dict) -> str:
    """발송될 HTML — 직접 넣은 HTML 이 있으면 그대로, 없으면 평문으로 브랜드 템플릿."""
    if (item.get("body_html") or "").strip():
        return item["body_html"]
    from src.notices import render_notice_html

    return render_notice_html(subject=item.get("subject") or "",
                              body_text=item.get("body_text") or "")


def plain_text(item: dict) -> str:
    return (item.get("body_text") or "").strip() or html_to_text(item.get("body_html") or "")


def sender_info(reply_to: Optional[str] = None) -> dict:
    """미리보기용 발신자·회신 주소 — 실제 발송 경로(`send_email`)와 같은 우선순위."""
    frm = (os.getenv("SMTP_FROM") or os.getenv("EMAIL_FROM") or "").strip() or None
    return {"from": frm, "reply_to": (reply_to or os.getenv("NOTICE_REPLY_TO") or None)}


def send_subject(item: dict) -> str:
    s = item.get("subject") or ""
    if item.get("marketing") and not s.lstrip().startswith(AD_PREFIX):
        s = f"{AD_PREFIX} {s}"
    return s


# ---------------------------------------------------------------------------
# 수신자
# ---------------------------------------------------------------------------

def recipient_catalog(*, marketing: bool, nid: Optional[str] = None) -> list[dict]:
    """발송 후보 전체 + 수신 자격. 회원(탈퇴 포함 표시) + 미가입 베타 초대자.

    테스트 계정(계정 구분 '테스트')은 후보에서 뺀다 — 발송 대상이 아니다(운영자 요청 2026-09-22).

    행: {email, user_id, member, display_name, affiliation, account_class, is_internal,
         notice_opt_in, marketing_opt_in, eligible, reason, reason_label, received_at}
    """
    from src import account_class as _ac
    from src.notices import filter_marketing_consented
    from src.persistence import get_users_repo

    users = []
    off = 0
    while True:
        page = get_users_repo().list_all(limit=1000, offset=off)
        users.extend(page)
        if len(page) < 1000:
            break
        off += 1000
    users = [u for u in users if u.email]
    mk = {e.lower() for e in filter_marketing_consented([u.email for u in users])}
    cut = _ac.launch_cutoff()
    emails_admin = _ac._admin_emails()
    listed = _ac.beta_listed_checker()
    received = received_map(nid) if nid else {}

    rows: list[dict] = []
    seen: set[str] = set()
    for u in users:
        e = u.email
        k = e.lower()
        if k in seen:
            continue
        seen.add(k)
        cls, _src = _ac.classify(u, cut=cut, admin_emails=emails_admin, beta_listed=listed)
        if cls == _ac.TEST:
            continue
        notice_ok = bool(getattr(u, "notice_email_opt_in", True))
        mk_ok = k in mk
        reason = None
        if getattr(u, "deleted_at", None):
            reason = "deleted"
        elif not notice_ok:
            reason = "notice_optout"
        elif marketing and not mk_ok:
            reason = "no_marketing_consent"
        rows.append({
            "email": e, "user_id": u.id, "member": True,
            "display_name": getattr(u, "display_name", None),
            "affiliation": getattr(u, "affiliation", None),
            "admin_memo": getattr(u, "admin_memo", None),
            "account_class": cls, "account_class_label": _ac.LABELS[cls],
            "is_internal": cls != _ac.USER,
            "notice_opt_in": notice_ok, "marketing_opt_in": mk_ok,
            "eligible": reason is None, "reason": reason,
            "reason_label": REASON_LABELS.get(reason) if reason else None,
            "received_at": received.get(k),
        })

    # 미가입 베타 초대자(화이트리스트 개별 주소) — 초대 공지 대상과 같은 규칙.
    from src.notices import resolve_recipients

    for e in resolve_recipients("beta_testers"):
        k = e.lower()
        if k in seen:
            continue
        seen.add(k)
        reason = "no_marketing_consent" if marketing else None
        rows.append({
            "email": e, "user_id": None, "member": False,
            "display_name": None, "affiliation": None, "admin_memo": None,
            "account_class": None, "account_class_label": "미가입 초대자",
            "is_internal": False,
            "notice_opt_in": True, "marketing_opt_in": False,
            "eligible": reason is None, "reason": reason,
            "reason_label": REASON_LABELS.get(reason) if reason else None,
            "received_at": received.get(k),
        })
    rows.sort(key=lambda r: (not r["eligible"], not r["member"], r["email"].lower()))
    return rows


# ---------------------------------------------------------------------------
# 발송·이력
# ---------------------------------------------------------------------------

def list_sends(nid: str) -> list[dict]:
    runs = _get_json(_SENDS_KEY.format(id=nid), [])
    return [r for r in runs if isinstance(r, dict)]


def received_map(nid: str) -> dict[str, str]:
    """email(lower) → 최초 성공 수신 시각(테스트 발송 제외)."""
    out: dict[str, str] = {}
    for run in sorted(list_sends(nid), key=lambda r: str(r.get("at") or "")):
        if run.get("test"):
            continue
        for r in run.get("recipients") or []:
            if r.get("ok"):
                out.setdefault(str(r.get("email") or "").lower(), run.get("at"))
    return out


def send_newsletter(nid: str, *, emails: list[str], by: Optional[str],
                    test_to: Optional[str] = None) -> dict:
    """발송 1회 — 자격을 **서버에서 다시** 판정하고, 회차 기록을 남긴다.

    test_to 가 있으면 그 주소 1통만(자격 판정·수신 기록 제외, 이력엔 test 로 남김).
    동기 SMTP(수신자 수 × 최대 15초) — 라우트가 스레드풀에서 부른다.
    """
    from src.notices import send_notice

    item = get_newsletter(nid)
    if not item:
        raise LookupError("newsletter not found")

    skipped: list[dict] = []
    if test_to:
        targets = [test_to]
    else:
        catalog = {r["email"].lower(): r for r in
                   recipient_catalog(marketing=bool(item.get("marketing")))}
        targets, seen = [], set()
        for e in emails:
            e = str(e).strip()
            k = e.lower()
            if not e or k in seen:
                continue
            seen.add(k)
            row = catalog.get(k)
            if row is None:
                skipped.append({"email": e, "reason": "unknown",
                                "reason_label": REASON_LABELS["unknown"]})
            elif not row["eligible"]:
                skipped.append({"email": row["email"], "reason": row["reason"],
                                "reason_label": row["reason_label"]})
            else:
                targets.append(row["email"])
        if not targets:
            raise ValueError("보낼 수 있는 수신자가 없습니다"
                             + (f" — 제외 {len(skipped)}명" if skipped else ""))

    subject = send_subject(item)
    if test_to:
        subject = f"[테스트] {subject}"
    res = send_notice(subject=subject, body_text=plain_text(item), emails=targets,
                      body_html=rendered_html(item), template="plain",
                      reply_to=item.get("reply_to"))
    failed = {e.lower() for e in res.get("failed") or []}
    now = _now()
    run = {
        "id": f"nls_{uuid.uuid4().hex[:10]}",
        "at": now, "by": by, "test": bool(test_to), "subject": subject,
        "marketing": bool(item.get("marketing")),
        "requested": len(targets), "sent": res.get("sent", 0),
        "failed": len(failed), "smtp_configured": res.get("smtp_configured"),
        "recipients": [{"email": e, "ok": e.lower() not in failed} for e in targets],
        "skipped": skipped,
    }
    runs = list_sends(nid)
    runs.insert(0, run)
    _set_json(_SENDS_KEY.format(id=nid), runs, by=by)
    if not test_to:
        item["last_sent_at"] = now
        item["send_runs"] = int(item.get("send_runs") or 0) + 1
        item["sent_count"] = len(received_map(nid))
        # updated_at 은 '내용 수정' 시각 — 발송은 바꾸지 않되 목록 정렬엔 반영되게 index 만 갱신
        _write(item, by=by)
    return run


def summary_for(nid: str) -> dict[str, Any]:
    item = get_newsletter(nid)
    if not item:
        return {}
    return {**item, "sends": list_sends(nid)}
