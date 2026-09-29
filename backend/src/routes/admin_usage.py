"""관리자 · 주간 이용 통계 (2026-09-21).

- GET  /admin/stats/weekly?weeks=12        최신 주부터. 끝난 주는 저장본(없으면 계산·저장),
                                          이번 주는 실시간(partial). 실사용·내부·전체 3범위.
- POST /admin/stats/weekly/recompute       저장본 재계산 — 계정 라벨을 바꾼 뒤(stale) 쓴다.
                                          body {week_start?: "YYYY-MM-DD"} 없으면 stale 전부.

집계 규칙·저장 형식은 `src/usage_weekly.py`, 계정 구분은 `src/account_class.py`.
동기 DB 호출뿐이라 `def`(스레드풀) — 라우트 async 규약(CLAUDE.md §7).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.middleware.auth import require_admin

router = APIRouter()


def _launch_week() -> date:
    from src.usage_weekly import launch_week

    return launch_week()


@router.get("/admin/stats/weekly")
def admin_stats_weekly(weeks: int = 12, include_prelaunch: bool = False,
                       _admin=Depends(require_admin)):
    from src import account_class
    from src.usage_weekly import METRICS, weekly_series

    earliest = None if include_prelaunch else _launch_week()
    series = weekly_series(weeks, earliest=earliest)
    return {
        "weeks": series,
        "metrics": METRICS,
        "scopes": [
            {"key": "real", "label": "실사용", "desc": "관리자·테스트 계정과 스크립트 트래픽 제외"},
            {"key": "internal", "label": "내부", "desc": "관리자·테스트 계정 + 스크립트(e2e·야간 회귀)"},
            {"key": "all", "label": "전체", "desc": "실사용 + 내부"},
        ],
        "fingerprint": account_class.fingerprint(),
        "timezone_offset_hours": _tz_hours(),
    }


def _tz_hours() -> float:
    from src.usage_weekly import _tz

    return _tz().utcoffset(None).total_seconds() / 3600


class RecomputeIn(BaseModel):
    week_start: Optional[str] = None


@router.post("/admin/stats/weekly/recompute")
def admin_stats_weekly_recompute(body: RecomputeIn, admin=Depends(require_admin)):
    from datetime import timedelta

    from src import account_class
    from src.usage_weekly import current_week_start, load_snapshot, snapshot_week

    by = f"admin:{getattr(admin, 'email', None) or getattr(admin, 'id', '')}"
    cur = current_week_start()
    if body.week_start:
        try:
            ws = date.fromisoformat(body.week_start)
        except ValueError as e:
            raise HTTPException(status_code=422, detail="week_start 는 YYYY-MM-DD") from e
        if ws.weekday() != 0:
            raise HTTPException(status_code=422, detail="week_start 는 월요일이어야 합니다")
        if ws >= cur:
            raise HTTPException(status_code=422, detail="진행 중인 주는 저장하지 않습니다")
        targets = [ws]
    else:
        fp = account_class.fingerprint()
        targets = []
        ws = cur - timedelta(days=7)
        stop = _launch_week()
        while ws >= stop:
            snap = load_snapshot(ws)
            if snap is None or snap.get("fingerprint") != fp:
                targets.append(ws)
            ws -= timedelta(days=7)
    done = [snapshot_week(w, by=by)["week_start"] for w in targets]
    return {"ok": True, "recomputed": done}


# ── 주간 이용 보고서 메일(2026-09-21) — 본체는 src/weekly_report.py ──────────────

def _past_week(raw: Optional[str]) -> date:
    """week_start 파라미터 → 끝난 주의 월요일. 없으면 직전 주."""
    from datetime import timedelta

    from src.usage_weekly import current_week_start

    cur = current_week_start()
    if not raw:
        return cur - timedelta(days=7)
    try:
        ws = date.fromisoformat(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="week_start 는 YYYY-MM-DD") from e
    if ws.weekday() != 0:
        raise HTTPException(status_code=422, detail="week_start 는 월요일이어야 합니다")
    if ws >= cur:
        raise HTTPException(status_code=422, detail="끝난 주만 보고서로 만들 수 있습니다")
    return ws


@router.get("/admin/weekly-report/status")
def admin_weekly_report_status(_admin=Depends(require_admin)):
    from src.weekly_report import status

    return status()


@router.get("/admin/weekly-report/preview")
def admin_weekly_report_preview(week_start: Optional[str] = None,
                                _admin=Depends(require_admin)):
    """발송될 HTML 그대로(첨부 없이). 프런트는 인증 헤더로 받아 새 탭에 띄운다."""
    from fastapi.responses import HTMLResponse

    from src.weekly_report import collect, render_html

    return HTMLResponse(render_html(collect(_past_week(week_start))))


class WeeklyReportSendIn(BaseModel):
    week_start: Optional[str] = None
    to: Optional[str] = None


@router.post("/admin/weekly-report/send")
def admin_weekly_report_send(body: WeeklyReportSendIn, _admin=Depends(require_admin)):
    """지금 보내기(수동) — 예약 발송 기록은 건드리지 않는다(월요일 자동 발송은 그대로 간다).

    `to` 는 등록된 보고서 수신자·관리자 메일 중에서만 — 새 주소는 먼저 수신자로 등록(설정)해야 한다.
    이용 수치·자유 의견이 담긴 메일을 일회성 임의 주소로 내보내는 경로는 두지 않는다.
    """
    from src.weekly_report import admin_email_options, recipients, send

    ws = _past_week(body.week_start)
    to = None
    if body.to:
        allowed = {e.lower() for e in recipients()} | set(admin_email_options())
        if body.to.strip().lower() not in allowed:
            raise HTTPException(status_code=422, detail="보고서 수신자 또는 관리자 메일만 가능합니다")
        to = [body.to.strip()]
    return send(ws, to=to)


class WeeklyReportConfigIn(BaseModel):
    """준 항목만 바꾼다. 값 null = 그 항목을 서버 기본값(env)으로 되돌림. reset=true = 전부 되돌림."""
    enabled: Optional[bool] = None
    to: Optional[list[str]] = None
    weekday: Optional[int] = None
    hour: Optional[int] = None
    reset: bool = False


@router.patch("/admin/weekly-report/config")
def admin_weekly_report_config(body: WeeklyReportConfigIn, admin=Depends(require_admin)):
    """관리자 화면에서 자동 발송 켜기/끄기·수신자·요일·시각 조정 — 재시작 없이 다음 점검부터 반영."""
    from src.weekly_report import reset_config, save_config, status

    by = getattr(admin, "email", None) or getattr(admin, "id", None)
    if body.reset:
        reset_config(by=by)
        return status()
    patch = body.model_dump(exclude_unset=True, exclude={"reset"})
    try:
        save_config(patch, by=by)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return status()



# ── 보고 노트(관리자 전용, 2026-09-21) — 본체는 src/report_notes.py ──────────────

class ReportNoteIn(BaseModel):
    title: str
    items: list[str] = []
    feature: Optional[str] = None
    date: Optional[str] = None
    include: bool = True


class ReportNotePatch(BaseModel):
    title: Optional[str] = None
    items: Optional[list[str]] = None
    feature: Optional[str] = None
    date: Optional[str] = None
    include: Optional[bool] = None


@router.get("/admin/report-notes")
def admin_report_notes(since: Optional[str] = None, until: Optional[str] = None,
                       _admin=Depends(require_admin)):
    from src.announcements import FEATURES
    from src.report_notes import list_notes

    return {"notes": list_notes(since=since, until=until), "features": list(FEATURES)}


@router.post("/admin/report-notes")
def admin_report_note_add(body: ReportNoteIn, admin=Depends(require_admin)):
    from src.report_notes import add

    try:
        return add(title=body.title, items=body.items, feature=body.feature, day=body.date,
                   include=body.include, by=getattr(admin, "email", None))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.patch("/admin/report-notes/{note_id}")
def admin_report_note_update(note_id: str, body: ReportNotePatch, admin=Depends(require_admin)):
    from src.report_notes import update

    try:
        n = update(note_id, by=getattr(admin, "email", None),
                   **body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if n is None:
        raise HTTPException(status_code=404, detail="note not found")
    return n


@router.delete("/admin/report-notes/{note_id}")
def admin_report_note_delete(note_id: str, admin=Depends(require_admin)):
    from src.report_notes import delete

    if not delete(note_id, by=getattr(admin, "email", None)):
        raise HTTPException(status_code=404, detail="note not found")
    return {"ok": True, "id": note_id}
