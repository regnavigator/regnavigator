"""고객사별 규제 모니터링 리포트 — 수집·렌더·발송.

로펌이 고객사(=`bookmarks.folder`)별로 관심 조문을 모아 두면, 그 폴더의 **폐지·
개정예정·시행일 변경**을 감지해 지정 수신자에게 정기 리포트를 보낸다(2026-10-01).

판정은 `src/amendments.py` 를 그대로 쓴다 — 개인 조회(`GET /bookmarks/amendments`)와
리포트가 어긋나면 안 된다.

설계 메모
- 변경 0건이면 기본적으로 **보내지 않는다**(`MONITOR_REPORT_SEND_ON_NO_CHANGE=1` 로 변경).
  받는 쪽에서 "변화 없음" 메일이 매주 쌓이면 리포트 자체를 안 읽게 된다.
- `last_sent_at` 은 **한 곳이라도 발송에 성공했을 때만** 갱신한다. 전부 실패면
  다음 점검에 재시도한다(weekly_report 와 같은 원칙).
"""

from __future__ import annotations

import csv
import html
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.amendments import KIND_LABELS, detect as detect_amendments
from src.persistence import get_bookmarks_repo, get_monitor_targets_repo, parse_recipients

_log = logging.getLogger(__name__)

_C = {"ink": "#1a1916", "sub": "#5a5850", "line": "#e2e0d8",
      "bg": "#f7f6f2", "card": "#ffffff", "accent": "#0F6B4A", "warn": "#B91C1C"}

#: 종류별 정렬 우선순위 — 폐지가 가장 급하다
_ORDER = {"repealed": 0, "pending": 1, "amended": 2}


def _kst() -> timezone:
    return timezone(timedelta(hours=9))


def _cfg_flag(key: str, default: str = "0") -> bool:
    import os

    return (os.getenv(key) or default).strip() == "1"


# ── 수집 ────────────────────────────────────────────────────────────────────

def collect(target) -> dict:
    """대상 폴더의 북마크를 훑어 변경분을 모은다. 실패해도 예외를 올리지 않는다."""
    bms = get_bookmarks_repo().list_for_user(target.user_id, limit=500)
    scoped = [b for b in bms if (getattr(b, "folder", None) or "") == target.folder]
    changes = detect_amendments(scoped)
    changes.sort(key=lambda c: (_ORDER.get(c.get("kind"), 9), str(c.get("title") or "")))
    counts = {k: sum(1 for c in changes if c.get("kind") == k) for k in KIND_LABELS}
    return {
        "target": target.as_dict(),
        "watched": len(scoped),
        "changes": changes,
        "counts": counts,
        "generated_at": datetime.now(_kst()).isoformat(timespec="minutes"),
    }


# ── 렌더 ────────────────────────────────────────────────────────────────────

def subject_of(data: dict) -> str:
    name = data["target"]["display_name"]
    n = len(data["changes"])
    today = datetime.now(_kst()).strftime("%Y-%m-%d")
    return (f"[규제 모니터링] {name} — 변경 {n}건 ({today})" if n
            else f"[규제 모니터링] {name} — 변경 없음 ({today})")


def _rows_html(changes: list[dict]) -> str:
    if not changes:
        return (f'<tr><td colspan="3" style="padding:14px;color:{_C["sub"]};'
                'text-align:center">감지된 변경이 없습니다.</td></tr>')
    out = []
    for c in changes:
        kind = c.get("kind")
        label = KIND_LABELS.get(kind, kind or "")
        color = _C["warn"] if kind == "repealed" else _C["accent"]
        detail = ""
        if c.get("saved_date"):
            detail = f'저장 시점 시행일 {html.escape(str(c["saved_date"]))}'
        if c.get("current_date"):
            detail += f' → 현재 {html.escape(str(c["current_date"]))}'
        out.append(
            f'<tr>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {_C["line"]};'
            f'white-space:nowrap"><b style="color:{color}">{html.escape(label)}</b></td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {_C["line"]}">'
            f'{html.escape(str(c.get("title") or "(제목 없음)"))}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {_C["line"]};'
            f'color:{_C["sub"]};font-size:12px">{detail}</td>'
            f'</tr>')
    return "".join(out)


def render_html(data: dict) -> str:
    t = data["target"]
    counts = data["counts"]
    chips = " · ".join(f'{KIND_LABELS[k]} {counts.get(k, 0)}건'
                       for k in KIND_LABELS if counts.get(k))
    return f"""<!doctype html><html><body style="margin:0;padding:22px;
background:{_C['bg']};font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;color:{_C['ink']}">
<div style="max-width:680px;margin:0 auto;background:{_C['card']};border:1px solid {_C['line']};
border-radius:8px;overflow:hidden">
  <div style="padding:16px 20px;border-bottom:3px solid {_C['accent']}">
    <div style="font-size:17px;font-weight:700;color:{_C['accent']}">규제 모니터링 리포트</div>
    <div style="font-size:13px;color:{_C['sub']};margin-top:3px">
      {html.escape(t['display_name'])} · 관찰 {data['watched']}건 · {html.escape(data['generated_at'])}</div>
  </div>
  <div style="padding:14px 20px 4px">
    <div style="font-size:13px;color:{_C['sub']}">
      {html.escape(chips) if chips else '이번 주기에는 감지된 변경이 없습니다.'}</div>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:13px;margin:8px 0 4px">
    {_rows_html(data['changes'])}
  </table>
  <div style="padding:12px 20px 18px;font-size:11px;color:{_C['sub']};line-height:1.6;
border-top:1px solid {_C['line']}">
    본 리포트는 저장해 두신 조문의 <b>시행일 변경 · 개정예정 · 폐지</b> 여부를 자동 감지한 것입니다.
    법령 원문과 최종 해석은 담당 변호사에게 확인하십시오.
  </div>
</div></body></html>"""


def render_text(data: dict) -> str:
    t = data["target"]
    lines = [f"규제 모니터링 리포트 — {t['display_name']}",
             f"관찰 {data['watched']}건 · {data['generated_at']}", ""]
    if not data["changes"]:
        lines.append("감지된 변경이 없습니다.")
    for c in data["changes"]:
        bit = f"- [{KIND_LABELS.get(c.get('kind'), '')}] {c.get('title') or '(제목 없음)'}"
        if c.get("saved_date"):
            bit += f" (저장 시점 {c['saved_date']}"
            bit += f" → 현재 {c['current_date']})" if c.get("current_date") else ")"
        lines.append(bit)
    lines += ["", "법령 원문과 최종 해석은 담당 변호사에게 확인하십시오."]
    return "\n".join(lines)


def render_csv(data: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["종류", "제목", "저장 시점 시행일", "현재 시행일", "citation_id"])
    for c in data["changes"]:
        w.writerow([KIND_LABELS.get(c.get("kind"), c.get("kind") or ""),
                    c.get("title") or "", c.get("saved_date") or "",
                    c.get("current_date") or "", c.get("citation_id") or ""])
    return buf.getvalue().encode("utf-8-sig")


def build(target) -> dict:
    data = collect(target)
    stamp = datetime.now(_kst()).strftime("%Y%m%d")
    safe = "".join(ch for ch in data["target"]["display_name"] if ch.isalnum() or ch in "-_")
    return {"data": data, "subject": subject_of(data),
            "html": render_html(data), "text": render_text(data),
            "attachments": [(f"regulatory-monitor_{safe or 'client'}_{stamp}.csv",
                             render_csv(data))]}


# ── 발송 ────────────────────────────────────────────────────────────────────

def send(target, *, to: Optional[list[str]] = None, force: bool = False) -> dict:
    """리포트를 만들어 보낸다. 변경 0건이면 기본 생략(force=True 로 강제).

    SMTP 미설정이면 stub — 실제로 나가지 않는다(`smtp_configured` 로 구분).
    """
    from src.observability.notifications import is_configured, send_email

    b = build(target)
    n = len(b["data"]["changes"])
    if n == 0 and not force and not _cfg_flag("MONITOR_REPORT_SEND_ON_NO_CHANGE"):
        return {"target_id": target.id, "skipped": "no_change", "changes": 0,
                "sent": [], "failed": [], "smtp_configured": is_configured()}

    targets = to or parse_recipients(target.recipients)
    sent, failed = [], []
    for addr in targets:
        try:
            ok = send_email(to=addr, subject=b["subject"], body_text=b["text"],
                            body_html=b["html"], attachments=b["attachments"])
        except Exception:  # noqa: BLE001 — 한 주소 실패가 나머지를 막지 않게
            _log.exception("monitor_report 발송 실패 target=%s to=%s", target.id, addr)
            ok = False
        (sent if ok else failed).append(addr)
    return {"target_id": target.id, "subject": b["subject"], "changes": n,
            "sent": sent, "failed": failed, "smtp_configured": is_configured(),
            "attachments": [a[0] for a in b["attachments"]]}


# ── 스케줄 ──────────────────────────────────────────────────────────────────

def _period_start(target, now: datetime) -> datetime:
    """이번 주기의 발송 예정 시각(KST). now 이후면 '아직 안 됨'."""
    if target.cadence == "monthly":
        return datetime(now.year, now.month, 1, int(target.send_hour), tzinfo=_kst())
    monday = now.date() - timedelta(days=now.weekday())
    d = monday + timedelta(days=int(target.send_weekday) % 7)
    return datetime(d.year, d.month, d.day, int(target.send_hour), tzinfo=_kst())


def _parse_iso(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_due(target, now: Optional[datetime] = None) -> bool:
    """이번 주기 예정 시각이 지났고, 그 시각 이후로 아직 안 보냈으면 True."""
    if not int(target.enabled or 0):
        return False
    now = (now or datetime.now(timezone.utc)).astimezone(_kst())
    sched = _period_start(target, now)
    if now < sched:
        return False
    last = _parse_iso(target.last_sent_at)
    return last is None or last.astimezone(_kst()) < sched


def next_run_at(target, now: Optional[datetime] = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(_kst())
    sched = _period_start(target, now)
    if now < sched and not _parse_iso(target.last_sent_at):
        return sched.isoformat(timespec="minutes")
    if now < sched:
        return sched.isoformat(timespec="minutes")
    if target.cadence == "monthly":
        nxt = (sched.replace(day=28) + timedelta(days=7)).replace(
            day=1, hour=int(target.send_hour))
    else:
        nxt = sched + timedelta(days=7)
    return nxt.isoformat(timespec="minutes")


def run_due(now: Optional[datetime] = None) -> list[dict]:
    """스케줄 루프가 부른다. 발송 대상이 없으면 빈 리스트."""
    repo = get_monitor_targets_repo()
    # 판정과 기록을 **같은 시각**으로 묶는다 — mark_sent 가 실제 현재 시각을 쓰면
    # 주기 경계 근처에서 같은 주기에 두 번 나갈 수 있다(테스트로 확인).
    eff = (now or datetime.now(timezone.utc)).astimezone(_kst())
    results = []
    for t in repo.list_enabled():
        if not is_due(t, eff):
            continue
        try:
            r = send(t)
        except Exception:  # noqa: BLE001 — 한 고객사 실패가 나머지를 막지 않게
            _log.exception("[monitor_report] target=%s 발송 실패", t.id)
            continue
        # 변경 0건으로 생략한 경우에도 '이번 주기는 처리됨'으로 표시해 반복 점검을 막는다.
        if r.get("sent") or r.get("skipped") == "no_change":
            repo.mark_sent(t.id, eff.isoformat(timespec="seconds"))
            _log.info("[monitor_report] %s → %s (변경 %s건)",
                      t.folder, r.get("sent") or r.get("skipped"), r.get("changes"))
        else:
            _log.warning("[monitor_report] %s 발송 전부 실패 %s — 다음 점검에 재시도",
                         t.folder, r.get("failed"))
        results.append(r)
    return results
