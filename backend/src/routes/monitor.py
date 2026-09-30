"""고객사별 규제 모니터링 — 배송 설정 CRUD · 미리보기 · 수동 발송.

담당 변호사가 고객사(=북마크 폴더)별로 수신자와 주기를 등록하면, 주기 루프가
개정·폐지를 감지해 리포트를 보낸다. 전부 user 스코프다.

⚠️ 라우트 async 규약 — 수집·발송은 동기(PG·SMTP)이므로 `def` 로 선언해 스레드풀에
맡긴다. 이벤트 루프에서 직접 돌리면 SSE 스트리밍과 보고서 잡이 함께 멈춘다.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from src.persistence import (
    MonitorTarget, get_bookmarks_repo, get_monitor_targets_repo, parse_recipients,
)
from src.persistence.monitor_targets_repo import CADENCES

_log = logging.getLogger(__name__)

router = APIRouter()


def _require_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(user_id)


def _owned_or_404(user_id: str, target_id: str) -> MonitorTarget:
    t = get_monitor_targets_repo().get(user_id, target_id)
    if t is None:
        raise HTTPException(status_code=404, detail="monitor target not found")
    return t


def _with_schedule(t: MonitorTarget) -> dict:
    from src.monitor_report import next_run_at

    d = t.as_dict()
    d["next_run_at"] = next_run_at(t)
    return d


def _validated(body: dict, *, partial_from: Optional[MonitorTarget] = None) -> dict:
    """입력 검증 — 한국어 422. partial_from 이 있으면 미지정 필드는 기존값 유지."""
    base = partial_from

    folder = body.get("folder", base.folder if base else None)
    if not folder or not str(folder).strip():
        raise HTTPException(status_code=422, detail="folder(고객사 폴더명) 필요")

    raw_recipients = body.get("recipients", base.recipients if base else None)
    recipients = parse_recipients(raw_recipients)
    if not recipients:
        raise HTTPException(status_code=422, detail="유효한 수신 이메일이 1개 이상 필요합니다")

    cadence = str(body.get("cadence", base.cadence if base else "weekly"))
    if cadence not in CADENCES:
        raise HTTPException(status_code=422, detail=f"cadence 는 {CADENCES} 중 하나")

    def _int(key, default, lo, hi):
        try:
            v = int(body.get(key, default))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{key} 는 정수여야 합니다") from None
        if not (lo <= v <= hi):
            raise HTTPException(status_code=422, detail=f"{key} 범위는 {lo}~{hi}")
        return v

    return {
        "folder": str(folder).strip(),
        "label": (str(body["label"]).strip() if body.get("label")
                  else (base.label if base else None)),
        "recipients": ",".join(recipients),
        "cadence": cadence,
        "send_weekday": _int("send_weekday", base.send_weekday if base else 0, 0, 6),
        "send_hour": _int("send_hour", base.send_hour if base else 9, 0, 23),
        "enabled": 1 if body.get("enabled", bool(base.enabled) if base else True) else 0,
    }


@router.get("/monitor/targets")
def list_targets(request: Request):
    """내 고객사 모니터링 설정 목록 + 각 폴더의 관찰 건수."""
    user_id = _require_user(request)
    targets = get_monitor_targets_repo().list_for_user(user_id)
    bms = get_bookmarks_repo().list_for_user(user_id, limit=500)
    counts: dict[str, int] = {}
    for b in bms:
        key = getattr(b, "folder", None) or ""
        counts[key] = counts.get(key, 0) + 1
    out = []
    for t in targets:
        d = _with_schedule(t)
        d["watched"] = counts.get(t.folder, 0)
        out.append(d)
    return {"targets": out, "folders": sorted(k for k in counts if k)}


@router.post("/monitor/targets", status_code=201)
async def create_target(request: Request):
    """고객사 배송 설정 생성. 같은 folder 재등록은 갱신(멱등)."""
    user_id = _require_user(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be JSON object")
    fields = _validated(body)
    repo = get_monitor_targets_repo()
    tid = repo.upsert(MonitorTarget(id="", user_id=user_id, **fields))
    return _with_schedule(_owned_or_404(user_id, tid))


@router.patch("/monitor/targets/{target_id}")
async def update_target(target_id: str, request: Request):
    """부분 수정 — 지정한 필드만 바꾼다."""
    user_id = _require_user(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="body must be JSON object")
    cur = _owned_or_404(user_id, target_id)
    fields = _validated(body, partial_from=cur)
    repo = get_monitor_targets_repo()
    repo.upsert(MonitorTarget(id=cur.id, user_id=user_id,
                              last_sent_at=cur.last_sent_at,
                              created_at=cur.created_at, **fields))
    return _with_schedule(_owned_or_404(user_id, target_id))


@router.delete("/monitor/targets/{target_id}", status_code=204)
def delete_target(target_id: str, request: Request):
    user_id = _require_user(request)
    _owned_or_404(user_id, target_id)
    get_monitor_targets_repo().delete(user_id, target_id)
    return None


@router.get("/monitor/targets/{target_id}/preview")
def preview_target(target_id: str, request: Request):
    """지금 시점 리포트 미리보기 — 발송하지 않는다(영업 시연·검수용)."""
    from src.monitor_report import build

    user_id = _require_user(request)
    t = _owned_or_404(user_id, target_id)
    b = build(t)
    return {"subject": b["subject"], "html": b["html"], "text": b["text"],
            "changes": b["data"]["changes"], "counts": b["data"]["counts"],
            "watched": b["data"]["watched"],
            "degraded": b["data"].get("degraded", False),
            "check_status": b["data"].get("check_status"),
            "generated_at": b["data"]["generated_at"]}


@router.post("/monitor/targets/{target_id}/send")
async def send_target(target_id: str, request: Request):
    """수동 발송. body: { to?: [email], force?: bool }.

    `force=true` 면 변경 0건이어도 보낸다(시연용). 수동 발송은 주기 판정을 건드리지
    않는다 — `last_sent_at` 을 갱신하지 않으므로 정기 발송은 예정대로 나간다.
    """
    import asyncio

    from src.monitor_report import send as send_report

    user_id = _require_user(request)
    t = _owned_or_404(user_id, target_id)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — body 없는 호출 허용
        body = {}
    to = parse_recipients(body.get("to")) if isinstance(body, dict) else []
    force = bool(body.get("force")) if isinstance(body, dict) else False
    return await asyncio.to_thread(send_report, t, to=to or None, force=force)
