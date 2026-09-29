"""주간 이용 보고서 메일 (2026-09-21).

운영자 요청: "실사용자의 사용 통계를 1주일 단위로 보고서로 작성해 스케줄링, admin 메일로.
추가된 피드백도 함께. 요약(LLM) 불필요. HTML 과 파일 두 가지로."

- 대상 주 = 직전 끝난 주(월~일, KST). 수치는 `usage_weekly` 저장본(없으면 그 자리에서 저장).
- **실사용 기준** — 관리자·테스트 계정과 스크립트 트래픽 제외(`account_class`). 내부 몫은 참고 한 줄.
- 본문은 규칙 기반 문장·표뿐(LLM 없음 — 숫자를 옮기다 틀릴 위험을 만들지 않는다).
- 메일 = HTML 본문 + 첨부 3개: 같은 보고서 `.html`(보관·인쇄), 주간 지표 `.csv`, 자유 의견 `.csv`.
- 이번 주 업데이트 = **보고 노트**(`src/report_notes.py`, 관리자 전용) 중 그 주 날짜·포함(include) 상태인 것
  (2026-09-21 운영자: "관리자만 보는 노트에만 올리고, 포함 토글된 것만 보고 레터에"). 사용자 공지(/updates)와
  분리. 노트는 기능 배포 때 개발 쪽이 올리고 운영자가 포함/해제한다 — 커밋 로그를 요약(LLM)하지 않는다.
- 피드백 목록은 자유 의견(@feedback)만 — 평가·인용 신고·PII 오탐 신고는 건수 지표로만.
- 발송: 매주 지정 요일·시각(기본 월 09시, KST) 이후 첫 점검 때 1회.
  설정은 관리자 화면에서 조정(app_settings `weekly_report_config` — env 는 기본값, 저장값이 우선).
  보낸 주는 app_settings `weekly_report_sent:<월요일>` 에 기록 → 재시작·재배포가 겹쳐도 중복 없음.
  놓친 주를 몰아서 보내지 않는다(직전 주만).
"""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

_log = logging.getLogger(__name__)

SENT_PREFIX = "weekly_report_sent:"
TREND_WEEKS = 8

# 보고서 핵심 지표(순서 = 표시 순서). 나머지는 CSV 에 전부 들어간다.
HEAD_METRICS = ["active_users", "returning_users", "new_users", "questions", "threads",
                "reports", "documents", "doc_fills", "feedback", "citation_reports", "cost_usd"]


# ── 설정 ────────────────────────────────────────────────────────────────────
# 우선순위: 관리자 화면 저장값(app_settings `weekly_report_config`) > env > 기본값.
# 저장값은 준 항목만 덮는다(예: 시각만 바꾸면 수신자는 env 그대로).

CONFIG_KEY = "weekly_report_config"
WEEKDAYS = "월화수목금토일"


def _env_config() -> dict:
    def _int(name, default, lo, hi):
        try:
            return max(lo, min(hi, int((os.getenv(name) or str(default)).strip())))
        except ValueError:
            return default
    from src.config import env_nonempty
    raw_to = env_nonempty("WEEKLY_REPORT_TO")
    return {
        "enabled": (os.getenv("WEEKLY_REPORT_ENABLED") or "1").strip().lower()
        not in ("0", "false", "no", "off"),
        "to": [e.strip() for e in raw_to.split(",") if e.strip()],
        "weekday": _int("WEEKLY_REPORT_SEND_WEEKDAY", 0, 0, 6),   # 0=월
        "hour": _int("WEEKLY_REPORT_SEND_HOUR", 9, 0, 23),
    }


def _saved_config() -> dict:
    try:
        raw = _settings().get(CONFIG_KEY)
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001 — 설정 조회 실패가 발송을 막으면 안 됨(env 로 동작, 로그는 남김)
        _log.warning("weekly_report 설정 조회 실패 — env 기본값 사용", exc_info=True)
        return {}


def config() -> dict:
    """유효 설정 + 항목별 출처("admin"|"env") + 마지막 변경자."""
    env, saved = _env_config(), _saved_config()
    out, source = {}, {}
    for k in ("enabled", "to", "weekday", "hour"):
        if saved.get(k) is not None:
            out[k], source[k] = saved[k], "admin"
        else:
            out[k], source[k] = env[k], "env"
    return {**out, "source": source, "updated_by": saved.get("updated_by"),
            "updated_at": saved.get("updated_at")}


_EMAIL_RE = __import__("re").compile(r"^[^@\s]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def admin_email_options() -> list[str]:
    """수신자 추천 목록 = 관리자 메일(env·루트·is_admin 계정). 2026-09-21 부터 수신자는 관리자 화면에서
    임의 주소를 추가·삭제할 수 있다(운영자 요청) — 이 목록은 빠른 선택용 제안일 뿐 제한이 아니다."""
    from src.persistence import get_users_repo
    from src.whitelist import admin_emails

    opts = {e.lower() for e in admin_emails()}
    try:
        opts |= {u.email.lower() for u in get_users_repo().list_all(limit=100000)
                 if u.is_admin and u.email}
    except Exception:  # noqa: BLE001 — 사용자 조회 실패 시 env 관리자만(로그는 남김)
        _log.warning("관리자 계정 조회 실패", exc_info=True)
    return sorted(opts)


def save_config(patch: dict, *, by: Optional[str]) -> dict:
    """관리자 화면 저장. patch 키: enabled·to·weekday·hour. None 값 = 그 항목을 env 로 되돌림.
    잘못된 값은 ValueError(라우트가 422)."""
    saved = _saved_config()
    for k, v in patch.items():
        if k not in ("enabled", "to", "weekday", "hour"):
            continue
        if v is None:
            saved.pop(k, None)
            continue
        if k == "enabled":
            saved[k] = bool(v)
        elif k == "to":
            addrs = [str(a).strip().lower() for a in (v if isinstance(v, list) else [v]) if str(a).strip()]
            if not addrs:
                raise ValueError("수신자를 한 명 이상 입력하세요")
            if len(addrs) > 20:
                raise ValueError("수신자는 최대 20명")
            bad = [a for a in addrs if not _EMAIL_RE.match(a)]
            if bad:
                raise ValueError(f"메일 주소 형식이 올바르지 않습니다: {', '.join(bad)}")
            saved[k] = sorted(set(addrs))
        elif k == "weekday":
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 6:
                raise ValueError("weekday 는 0(월)~6(일)")
            saved[k] = v
        elif k == "hour":
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 23:
                raise ValueError("hour 는 0~23")
            saved[k] = v
    saved["updated_by"] = by
    saved["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _settings().set(CONFIG_KEY, json.dumps(saved, ensure_ascii=False), updated_by=by)
    return config()


def reset_config(*, by: Optional[str]) -> dict:
    _settings().set(CONFIG_KEY, None, updated_by=by)
    return config()


def enabled() -> bool:
    return bool(config()["enabled"])


def recipients() -> list[str]:
    return list(config()["to"])


def send_hour() -> int:
    return int(config()["hour"])


def send_weekday() -> int:
    return int(config()["weekday"])


# ── 수집 ────────────────────────────────────────────────────────────────────

def _week_snapshot(ws: date) -> dict:
    from src.usage_weekly import load_snapshot, snapshot_week

    snap = load_snapshot(ws)
    return snap if snap is not None else snapshot_week(ws, by="weekly_report")


def _user_label(u) -> str:
    if u is None:
        return "(알 수 없음)"
    name = u.display_name or u.admin_memo
    return f"{name} <{u.email}>" if name else (u.email or u.id)


def _payload(ev) -> dict:
    try:
        return json.loads(ev.payload_json or "{}")
    except ValueError:
        return {}


def collect(ws: date) -> dict:
    """주 `ws`(월요일) 보고서 데이터. 저장 부작용: 해당 주·추이 주의 스냅샷이 없으면 만든다."""
    from src import account_class
    from src.account_class import is_internal_thread
    from src.persistence import get_events_repo, get_users_repo
    from src.usage_weekly import METRICS, launch_week, week_bounds

    since, until = week_bounds(ws)
    internal = account_class.internal_user_ids()
    users = {u.id: u for u in get_users_repo().list_all(limit=100000)}

    def real(uid, tid) -> bool:
        return bool(uid) and uid not in internal and not is_internal_thread(tid or "", uid)

    cur = _week_snapshot(ws)
    prev = _week_snapshot(ws - timedelta(days=7))
    # 추이는 베타 오픈 주부터(통계 화면과 같은 기준 — 오픈 전 주는 개발·테스트 기간)
    first = launch_week()
    trend = [cur, prev] + [_week_snapshot(ws - timedelta(days=7 * i))
                           for i in range(2, TREND_WEEKS)
                           if ws - timedelta(days=7 * i) >= first]
    trend = [w for w in trend if date.fromisoformat(w["week_start"]) >= first] or [cur]

    # 사용자별 활동·신규 가입자 명단은 싣지 않는다(2026-09-21 운영자: "TMI·개인정보") —
    # 보고서는 집계 수치와 피드백만. 개인 단위 조회는 관리자 화면(이용 조회)에서.

    # 피드백 = **자유 의견(@feedback)만**(2026-09-21 운영자: "개인정보 오탐 신고는 제거, 자유 의견만").
    # 👍👎·인용 신고·PII 오탐 신고는 핵심 지표 건수로만 남고 목록엔 싣지 않는다. 내부 몫은 건수만.
    feedback: list[dict] = []
    internal_feedback = 0
    for e in get_events_repo().list_by_type("user_feedback", since=since, until=until, limit=2000):
        if not real(e.user_id, e.thread_id):
            internal_feedback += 1
            continue
        feedback.append({"ts": e.ts, "user": _user_label(users.get(e.user_id)),
                         "content": _payload(e).get("comment") or "", "thread_id": e.thread_id})
    feedback.sort(key=lambda f: f["ts"] or "")

    # 이번 주 업데이트 — 보고 노트(관리자 전용) 중 날짜가 이 주(KST)이고 '포함'인 것.
    from src.announcements import FEATURES
    from src.report_notes import list_notes

    updates = list_notes(since=ws.isoformat(), until=(ws + timedelta(days=6)).isoformat(),
                         include_only=True)
    order = {f: i for i, f in enumerate(FEATURES)}
    updates.sort(key=lambda n: (order.get(n.get("feature") or "", len(order)),
                                str(n.get("date") or "")))

    return {
        "week_start": ws.isoformat(),
        "week_end": (ws + timedelta(days=6)).isoformat(),
        "updates": updates,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metrics": METRICS,
        "cur": cur, "prev": prev, "trend": trend,
        "feedback": feedback, "internal_feedback": internal_feedback,
    }


def week_iso(utc_iso_z: str) -> str:
    return datetime.fromisoformat(utc_iso_z.replace("Z", "+00:00")).isoformat()


# ── 렌더 ────────────────────────────────────────────────────────────────────

_C = {"ink": "#1a1916", "sub": "#5a5850", "line": "#e2e0d8", "bg": "#f7f6f2", "card": "#ffffff",
      "real": "#2a78d6", "up": "#047857", "down": "#b42318", "brand": "#0f6b4a"}


def _fmt(v, kind: str) -> str:
    v = v or 0
    return f"${v:,.2f}" if kind == "usd" else f"{int(v):,}"


def _delta_html(cur: float, prev: float, kind: str) -> str:
    diff = (cur or 0) - (prev or 0)
    if diff == 0:
        return f'<span style="color:{_C["sub"]}">변화 없음</span>'
    color = _C["up"] if diff > 0 else _C["down"]
    sign = "+" if diff > 0 else "−"
    amount = _fmt(abs(diff), kind)
    pct = f" ({sign}{abs(diff) / prev * 100:.0f}%)" if prev else ""
    return f'<span style="color:{color};font-weight:600">{sign}{amount}</span><span style="color:{_C["sub"]}">{pct}</span>'


def _md(d: str) -> str:
    y, m, dd = d.split("-")
    wd = "월화수목금토일"[date(int(y), int(m), int(dd)).weekday()]
    return f"{int(m)}/{int(dd)}({wd})"


def render_html(data: dict) -> str:
    from src.notices import APP_URL

    e = html.escape
    mdef = {m["key"]: m for m in data["metrics"]}
    cur, prev = data["cur"]["scopes"], data["prev"]["scopes"]
    period = f'{_md(data["week_start"])} ~ {_md(data["week_end"])}'
    td = f'padding:8px 10px;border-top:1px solid {_C["line"]};font-size:13px;color:{_C["ink"]}'
    th = f'padding:8px 10px;text-align:left;font-size:12px;color:{_C["sub"]};font-weight:600;background:{_C["bg"]}'
    h2 = f'margin:28px 0 8px;font-size:15px;color:{_C["ink"]}'

    rows = "".join(
        f'<tr><td style="{td}">{e(mdef[k]["label"])}</td>'
        f'<td style="{td};text-align:right;font-weight:600">{_fmt(cur["real"].get(k), mdef[k]["kind"])}</td>'
        f'<td style="{td};text-align:right;color:{_C["sub"]}">{_fmt(prev["real"].get(k), mdef[k]["kind"])}</td>'
        f'<td style="{td};text-align:right">{_delta_html(cur["real"].get(k, 0), prev["real"].get(k, 0), mdef[k]["kind"])}</td></tr>'
        for k in HEAD_METRICS if k in mdef)

    trend = list(reversed(data["trend"]))  # 오래된 주부터
    mx = max([w["scopes"]["real"].get("active_users", 0) for w in trend] + [1])
    trend_rows = ""
    for w in trend:
        a = w["scopes"]["real"].get("active_users", 0)
        q = w["scopes"]["real"].get("questions", 0)
        pct = max(1, round(a / mx * 100)) if a else 0
        bar = (f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>'
               f'<td width="{pct}%" style="background:{_C["real"]};height:10px;border-radius:0 3px 3px 0;font-size:0">&nbsp;</td>'
               f'<td style="font-size:0">&nbsp;</td></tr></table>') if pct else ""
        bold = "font-weight:600;" if w["week_start"] == data["week_start"] else ""
        trend_rows += (f'<tr><td style="{td};{bold}white-space:nowrap">{_md(w["week_start"])}~</td>'
                       f'<td style="{td};width:55%">{bar}</td>'
                       f'<td style="{td};text-align:right;{bold}">{a}</td>'
                       f'<td style="{td};text-align:right;color:{_C["sub"]}">{q}</td></tr>')

    ups = data.get("updates") or []
    if ups:
        blocks = ""
        for n in ups:
            badge = (f'<span style="display:inline-block;margin-right:6px;padding:1px 6px;border-radius:4px;'
                     f'background:{_C["bg"]};font-size:11px;color:{_C["sub"]}">{e(n["feature"])}</span>'
                     if n.get("feature") else "")
            items = "".join(f'<li style="margin:2px 0">{e(str(i))}</li>' for i in (n.get("items") or []))
            blocks += (f'<div style="padding:10px 12px;border-top:1px solid {_C["line"]}">'
                       f'<div style="font-size:13.5px;font-weight:600;color:{_C["ink"]}">{badge}{e(n.get("title") or "")}'
                       f'<span style="margin-left:6px;font-size:11.5px;font-weight:400;color:{_C["sub"]}">'
                       f'{e(_md(str(n.get("date"))[:10]) if n.get("date") else "")}</span></div>'
                       f'<ul style="margin:6px 0 0;padding-left:18px;font-size:12.5px;color:{_C["ink"]}">{items}</ul></div>')
        updates_html = (f'<div style="border:1px solid {_C["line"]};border-top:0;background:{_C["card"]}">{blocks}</div>'
                        f'<p style="margin:6px 0 0;font-size:11.5px;color:{_C["sub"]}">관리자 › 보고 노트에서 \'포함\'된 항목 · '
                        f'<a href="{APP_URL}/admin/report-notes" style="color:{_C["real"]};text-decoration:none">보고 노트 열기</a></p>')
    else:
        updates_html = (f'<p style="font-size:13px;color:{_C["sub"]}">이번 주 보고할 업데이트가 없습니다 — '
                        f'관리자 › 보고 노트에서 \'포함\'한 노트가 여기에 실립니다.</p>')

    fb = data["feedback"]
    if fb:
        fb_rows = ""
        for f in fb:
            link = (f'<a href="{APP_URL}/admin/threads?thread={e(f["thread_id"])}" '
                    f'style="color:{_C["real"]};text-decoration:none">대화 보기</a>') if f["thread_id"] else ""
            ts = datetime.fromisoformat((f["ts"] or "").replace("Z", "+00:00")).astimezone(
                _kst()).strftime("%m/%d %H:%M") if f["ts"] else ""
            body = e(f["content"]) if f["content"] else f'<span style="color:{_C["sub"]}">(내용 없음)</span>'
            fb_rows += (f'<tr><td style="{td};white-space:nowrap;color:{_C["sub"]}">{ts}</td>'
                        f'<td style="{td}">{body}<div style="font-size:11.5px;color:{_C["sub"]};margin-top:3px">'
                        f'{e(f["user"])} {("· " + link) if link else ""}</div></td></tr>')
        fb_html = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                   f'style="border:1px solid {_C["line"]};border-collapse:collapse;background:{_C["card"]}">'
                   f'<tr><th style="{th}">시각</th><th style="{th}">의견 · 사용자</th></tr>'
                   f'{fb_rows}</table>')
    else:
        fb_html = f'<p style="font-size:13px;color:{_C["sub"]}">이번 주 들어온 실사용자 자유 의견이 없습니다.</p>'
    fb_summary = (f'실사용자 자유 의견 {len(fb)}건'
                  + (f' · 내부 계정 의견 {data["internal_feedback"]}건 제외' if data["internal_feedback"] else ""))

    iq, rq = cur["internal"].get("questions", 0), cur["real"].get("questions", 0)
    share = f'{iq / (iq + rq) * 100:.0f}%' if (iq + rq) else "—"
    stale = data["cur"].get("stale") or (data["cur"].get("fingerprint") and _stale(data["cur"]))
    notes = [f'질문 기준 내부 트래픽 비중 {share} (내부 {iq}건 · 실사용 {rq}건) — 관리자·테스트 계정과 스크립트(e2e·야간 회귀)']
    if stale:
        notes.append("이 주 집계는 저장 이후 계정 구분이 바뀌었습니다. 관리자 › 통계에서 [다시 계산]하면 수치가 바뀔 수 있습니다.")
    notes_html = "".join(f'<li style="margin:3px 0">{e(n)}</li>' for n in notes)

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MEDIREG AI 주간 이용 보고서 {e(period)}</title></head>
<body style="margin:0;padding:0;background:{_C["bg"]};font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_C["bg"]}"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="680" cellpadding="0" cellspacing="0" style="max-width:680px;width:100%">
<tr><td>
  <p style="margin:0;font-size:12px;color:{_C["brand"]};font-weight:700;letter-spacing:.02em">MEDIREG AI · 주간 이용 보고서</p>
  <h1 style="margin:6px 0 4px;font-size:22px;color:{_C["ink"]}">{e(period)}</h1>
  <p style="margin:0;font-size:12.5px;color:{_C["sub"]}">실사용 기준(관리자·테스트 계정과 스크립트 트래픽 제외) · 한국시간 월~일 · 전주 = {e(_md(data["prev"]["week_start"]))} ~ {e(_md(data["prev"]["week_end"]))}</p>

  <h2 style="{h2}">핵심 지표</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_C["line"]};border-collapse:collapse;background:{_C["card"]}">
    <tr><th style="{th}">지표</th><th style="{th};text-align:right">이번 주</th><th style="{th};text-align:right">전주</th><th style="{th};text-align:right">증감</th></tr>
    {rows}
  </table>
  <p style="margin:6px 0 0;font-size:11.5px;color:{_C["sub"]}">활성 = 질문 1회 이상 · 재방문 = 전주에도 질문 · 비용은 LLM 호출 단가 합(캐시 할인 미반영)</p>

  <h2 style="{h2}">이번 주 업데이트</h2>
  {updates_html}

  <h2 style="{h2}">최근 {len(trend)}주 추이 (실사용)</h2>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_C["line"]};border-collapse:collapse;background:{_C["card"]}">
    <tr><th style="{th}">주</th><th style="{th}">활성 사용자</th><th style="{th};text-align:right">활성</th><th style="{th};text-align:right">질문</th></tr>
    {trend_rows}
  </table>

  <h2 style="{h2}">이번 주 자유 의견</h2>
  <p style="margin:0 0 8px;font-size:12.5px;color:{_C["sub"]}">{e(fb_summary)}</p>
  {fb_html}

  <h2 style="{h2}">참고</h2>
  <ul style="margin:0;padding-left:18px;font-size:12.5px;color:{_C["sub"]}">{notes_html}</ul>

  <p style="margin:28px 0 0;padding-top:12px;border-top:1px solid {_C["line"]};font-size:11.5px;color:{_C["sub"]}">
    매주 {WEEKDAYS[send_weekday()]}요일 {send_hour():02d}:00 자동 발송(관리자 › 통계에서 조정) · 첨부: 이 보고서(.html) · 주간 지표(.csv) · 자유 의견(.csv) ·
    <a href="{APP_URL}/admin/stats" style="color:{_C["real"]};text-decoration:none">관리자 통계 열기</a>
  </p>
</td></tr></table></td></tr></table>
</body></html>"""


def _kst():
    from src.usage_weekly import _tz

    return _tz()


def _stale(snap: dict) -> bool:
    from src import account_class

    return snap.get("fingerprint") != account_class.fingerprint()


def render_text(data: dict) -> str:
    """HTML 차단 클라이언트용 평문."""
    mdef = {m["key"]: m for m in data["metrics"]}
    cur, prev = data["cur"]["scopes"]["real"], data["prev"]["scopes"]["real"]
    lines = [f'MEDIREG AI 주간 이용 보고서 {_md(data["week_start"])} ~ {_md(data["week_end"])} (실사용 기준)', ""]
    for k in HEAD_METRICS:
        if k in mdef:
            lines.append(f'- {mdef[k]["label"]}: {_fmt(cur.get(k), mdef[k]["kind"])} (전주 {_fmt(prev.get(k), mdef[k]["kind"])})')
    ups = data.get("updates") or []
    lines += ["", f"이번 주 업데이트 {len(ups)}건"]
    lines += [f'- [{n.get("feature") or "업데이트"}] {n.get("title")}' for n in ups]
    lines += ["", f'자유 의견 {len(data["feedback"])}건 — 자세한 내용은 HTML 본문·첨부 파일을 보세요.']
    return "\n".join(lines)


def _csv(header: list, rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")   # 엑셀 한글 깨짐 방지 BOM


def render_csvs(data: dict) -> dict[str, bytes]:
    from src.usage_weekly import SCOPES

    label = {"real": "실사용", "internal": "내부", "all": "전체"}
    metrics = data["metrics"]
    usage_rows = [
        [w["week_start"], w["week_end"], label[sc], *[w["scopes"][sc].get(m["key"], 0) for m in metrics]]
        for w in reversed(data["trend"]) for sc in SCOPES]
    fb_rows = [[f["ts"], f["user"], f["content"], f["thread_id"] or ""] for f in data["feedback"]]
    ws = data["week_start"]
    return {
        f"medireg_weekly_usage_{ws}.csv": _csv(["주 시작(월)", "주 끝(일)", "범위", *[m["label"] for m in metrics]], usage_rows),
        f"medireg_weekly_opinions_{ws}.csv": _csv(["시각(UTC)", "사용자", "의견", "대화 ID"], fb_rows),
    }


# ── 발송 ────────────────────────────────────────────────────────────────────

def build(ws: date) -> dict:
    data = collect(ws)
    page = render_html(data)
    period = f'{_md(data["week_start"])}~{_md(data["week_end"])}'
    files = [(f"medireg_weekly_report_{data['week_start']}.html", page.encode("utf-8"), "text/html")]
    files += [(name, body, "text/csv") for name, body in render_csvs(data).items()]
    return {"data": data, "html": page, "text": render_text(data),
            "subject": f"[MEDIREG AI] 주간 이용 보고서 {period}", "attachments": files}


def send(ws: date, *, to: Optional[list[str]] = None) -> dict:
    """보고서를 만들어 보낸다. 성공 여부는 수신자별. SMTP 미설정이면 stub(실발송 아님)."""
    from src.observability.notifications import is_configured, send_email

    b = build(ws)
    targets = to or recipients()
    sent, failed = [], []
    for addr in targets:
        try:
            ok = send_email(to=addr, subject=b["subject"], body_text=b["text"],
                            body_html=b["html"], attachments=b["attachments"])
        except Exception:  # noqa: BLE001 — 한 주소 실패가 나머지를 막지 않게(로그는 남긴다)
            _log.exception("weekly_report 발송 실패 to=%s", addr)
            ok = False
        (sent if ok else failed).append(addr)
    return {"week_start": ws.isoformat(), "sent": sent, "failed": failed,
            "smtp_configured": is_configured(), "subject": b["subject"],
            "feedback": len(b["data"]["feedback"]),
            "attachments": [a[0] for a in b["attachments"]]}


def _settings():
    from src.persistence.settings_repo import get_settings_repo

    return get_settings_repo()


def last_sent(ws: date) -> Optional[dict]:
    raw = _settings().get(SENT_PREFIX + ws.isoformat())
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def due_week(now: Optional[datetime] = None) -> Optional[date]:
    """지금 보내야 할 주(직전 끝난 주) — 월요일 send_hour 이전이거나 이미 보냈으면 None."""
    from src.usage_weekly import current_week_start

    now = (now or datetime.now(timezone.utc)).astimezone(_kst())
    cur = current_week_start(now)
    if now < _scheduled_at(cur):
        return None
    ws = cur - timedelta(days=7)
    return None if last_sent(ws) else ws


def _scheduled_at(week_monday: date) -> datetime:
    """그 주의 발송 예정 시각(설정 요일·시각, KST)."""
    d = week_monday + timedelta(days=send_weekday())
    return datetime(d.year, d.month, d.day, send_hour(), tzinfo=_kst())


def run_due(now: Optional[datetime] = None) -> Optional[dict]:
    """스케줄 루프가 부른다. 보냈으면 결과, 할 일 없으면 None.

    기록은 **한 곳이라도 성공했을 때만** 남긴다 — 전부 실패면 다음 점검에 재시도
    (조용히 '보냄'으로 적으면 영영 안 간다 — 초대 메일 invited_at 규칙과 같은 원칙)."""
    if not enabled():
        return None
    ws = due_week(now)
    if ws is None:
        return None
    result = send(ws)
    if result["sent"]:
        _settings().set(SENT_PREFIX + ws.isoformat(), json.dumps({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "to": result["sent"], "smtp_configured": result["smtp_configured"],
        }, ensure_ascii=False), updated_by="weekly_report")
        _log.info("[weekly_report] %s 발송 → %s", ws, result["sent"])
    else:
        _log.warning("[weekly_report] %s 발송 전부 실패 %s — 다음 점검에 재시도", ws, result["failed"])
    return result


def status(now: Optional[datetime] = None) -> dict:
    from src.observability.notifications import is_configured
    from src.usage_weekly import current_week_start

    now = (now or datetime.now(timezone.utc)).astimezone(_kst())
    cur = current_week_start(now)
    this_week = _scheduled_at(cur)
    prev_ws = cur - timedelta(days=7)
    sent_prev = last_sent(prev_ws)
    nxt = this_week if (now < this_week or not sent_prev) else _scheduled_at(cur + timedelta(days=7))
    cfg = config()
    return {"enabled": cfg["enabled"], "to": cfg["to"], "send_hour_kst": cfg["hour"],
            "send_weekday": cfg["weekday"], "config": cfg,
            "admin_email_options": admin_email_options(),
            "smtp_configured": is_configured(),
            "next_run_at": nxt.isoformat(timespec="minutes"),
            "last_week": {"week_start": prev_ws.isoformat(), "sent": sent_prev}}
