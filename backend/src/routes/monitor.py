"""대상별 규제 모니터링 — 배송 설정 CRUD · 미리보기 · 수동 발송.

담당 변호사가 대상(=북마크 폴더)별로 수신자와 주기를 등록하면, 주기 루프가
개정·폐지를 감지해 리포트를 보낸다. 전부 user 스코프다.

⚠️ 라우트 async 규약 — 수집·발송은 동기(PG·SMTP)이므로 `def` 로 선언해 스레드풀에
맡긴다. 이벤트 루프에서 직접 돌리면 SSE 스트리밍과 보고서 잡이 함께 멈춘다.
"""

from __future__ import annotations

import json
import logging
import uuid
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
        raise HTTPException(status_code=422, detail="folder(대상 폴더명) 필요")

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
    """내 규제 모니터링 설정 목록 + 각 폴더의 관찰 건수."""
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
    """대상 배송 설정 생성. 같은 folder 재등록은 갱신(멱등)."""
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


# ══════════════════════════════════════════════════════════════════════════
# 모니터링 스레드 (2026-10-02) — docs/spec/monitor-threads-design.md
#
# 관찰 단위를 북마크 폴더에서 **스레드**로 옮긴다. 대상 하나 = 스레드 하나.
# 그 안에서 대화하고, 자료를 올리고, 관찰 목록을 고치고, 알람을 받고,
# 보고서를 뽑는다. 채팅 스레드를 그대로 쓰므로 엔진은 재사용이다.
# ══════════════════════════════════════════════════════════════════════════

def _own_thread_or_404(user_id: str, thread_id: str) -> dict:
    from src.persistence.threads_repo import get_threads_repo

    meta = get_threads_repo().get_meta(thread_id)
    if not meta:
        raise HTTPException(status_code=404, detail="thread not found")
    owner = str(meta.get("user_id") or "")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="forbidden")
    return meta


@router.post("/monitor/threads")
async def create_monitor_thread(request: Request):
    """모니터링 스레드 생성. body: {"title": str(선택)}"""
    user_id = _require_user(request)
    from src.persistence.threads_repo import get_threads_repo

    # 빈 바디를 허용한다 — 제목 없이 "새 모니터링"으로 시작할 수 있어야 한다.
    try:
        body = await request.json() if await request.body() else {}
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    tid = f"t_{uuid.uuid4().hex}"
    repo = get_threads_repo()
    repo.ensure_thread(tid, user_id=user_id)
    repo.set_kind(tid, "monitor")
    title = str(body.get("title") or "").strip()
    if title:
        try:
            repo.set_title(tid, title[:120])
        except Exception:  # noqa: BLE001 — 제목은 선택
            _log.debug("set_title 실패", exc_info=True)
    _log.info("monitor thread 생성 %s", tid)
    return {"thread_id": tid, "kind": "monitor", "title": title or None}


@router.get("/monitor/threads")
def list_monitor_threads(request: Request):
    """모니터링 스레드 목록 + 관찰 건수 + 미읽음 알람 수."""
    user_id = _require_user(request)
    from src.persistence import get_monitor_alert_repo, get_monitor_watch_repo
    from src.persistence.threads_repo import get_threads_repo

    rows = [t for t in get_threads_repo().list_for_user(user_id, limit=200)
            if (t.get("kind") or "chat") == "monitor"]
    ids = [t["id"] for t in rows]
    unread = get_monitor_alert_repo().unread_counts(ids)
    wrepo = get_monitor_watch_repo()
    out = []
    for t in rows:
        out.append({**t,
                    "watch_count": wrepo.count_for_thread(t["id"]),
                    "unread_alerts": unread.get(t["id"], 0)})
    return {"threads": out}


@router.get("/monitor/threads/{thread_id}/watch")
def list_watch(thread_id: str, request: Request):
    user_id = _require_user(request)
    _own_thread_or_404(user_id, thread_id)
    from src.persistence import get_monitor_watch_repo

    items = get_monitor_watch_repo().list_for_thread(thread_id)
    return {"thread_id": thread_id, "items": [i.as_dict() for i in items]}


@router.post("/monitor/threads/{thread_id}/watch")
async def add_watch(thread_id: str, request: Request):
    """관찰 목록에 조문을 넣는다.

    body: {"citations": [citation, ...], "added_by": "user"|"ai"|"file",
           "reason": str(선택)}

    **자동 추가는 하지 않는다.** 검색 인용은 출처 적합성 필터를 거쳐도 노이즈가
    남는다. 관찰 목록이 오염되면 알람이 쓰레기가 되고, 그러면 알람을 안 보게
    된다. 제안까지만 하고 승인은 사람이 한다 — 이 엔드포인트가 그 승인이다.
    """
    user_id = _require_user(request)
    _own_thread_or_404(user_id, thread_id)
    from src.persistence import get_monitor_watch_repo
    from src.persistence.monitor_watch_repo import ADDED_BY, WatchItem

    body = await request.json()
    cites = body.get("citations") or []
    if not isinstance(cites, list) or not cites:
        raise HTTPException(status_code=422, detail="citations 가 필요합니다")
    added_by = str(body.get("added_by") or "user")
    if added_by not in ADDED_BY:
        added_by = "user"
    reason = str(body.get("reason") or "").strip()[:200] or None

    repo = get_monitor_watch_repo()
    added, skipped = [], []
    for c in cites[:50]:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "")
        ak = cid[len("cite_doc_"):] if cid.startswith("cite_doc_") else ""
        if not ak:
            # 웹 인용 등 조문 키가 없는 것은 관찰할 수 없다 — 조용히 빼지 않고 알린다.
            skipped.append(str(c.get("title") or cid or "(제목 없음)")[:80])
            continue
        repo.add(WatchItem(
            id="", thread_id=thread_id, article_key=ak,
            citation_json=json.dumps(c, ensure_ascii=False)[:8000],
            added_by=added_by, reason=reason))
        added.append(ak)
    return {"ok": True, "added": added, "skipped": skipped,
            "count": repo.count_for_thread(thread_id)}


@router.delete("/monitor/threads/{thread_id}/watch/{article_key}")
def remove_watch(thread_id: str, article_key: str, request: Request):
    user_id = _require_user(request)
    _own_thread_or_404(user_id, thread_id)
    from src.persistence import get_monitor_watch_repo

    repo = get_monitor_watch_repo()
    ok = repo.remove(thread_id, article_key)
    return {"ok": ok, "count": repo.count_for_thread(thread_id)}


@router.post("/monitor/threads/{thread_id}/watch/suggest")
def suggest_watch(thread_id: str, request: Request):
    """이 스레드가 수집한 인용 중 **아직 관찰하지 않는** 조문을 제안한다.

    자동으로 넣지 않는다 — 사용자가 고른다.
    """
    user_id = _require_user(request)
    _own_thread_or_404(user_id, thread_id)
    from src.persistence import get_monitor_watch_repo
    from src.persistence.threads_repo import get_threads_repo

    state = get_threads_repo().get_state(thread_id)
    watching = {w.article_key for w in
                get_monitor_watch_repo().list_for_thread(thread_id)}

    seen: set[str] = set()
    out: list[dict] = []
    for st in (state.steps or []):
        for c in (st.get("citations") or []):
            cid = str(c.get("id") or "")
            if not cid.startswith("cite_doc_"):
                continue            # 웹 인용은 관찰 대상이 아니다
            ak = cid[len("cite_doc_"):]
            if not ak or ak in seen:
                continue
            seen.add(ak)
            out.append({"article_key": ak, "citation": c,
                        "title": c.get("title"),
                        "doc_category": c.get("doc_category"),
                        "already": ak in watching})
    return {"thread_id": thread_id, "suggestions": out[:60],
            "watching": len(watching)}


@router.get("/monitor/alerts")
def list_alerts(request: Request, unread: int = 0, kind: str = "",
                limit: int = 100):
    """전 스레드 알람 모아보기."""
    user_id = _require_user(request)
    from src.persistence import get_monitor_alert_repo
    from src.persistence.threads_repo import get_threads_repo

    tids = [t["id"] for t in get_threads_repo().list_for_user(user_id, limit=200)
            if (t.get("kind") or "chat") == "monitor"]
    titles = {t["id"]: t.get("title") for t in
              get_threads_repo().list_for_user(user_id, limit=200)}
    repo = get_monitor_alert_repo()
    rows = repo.list_for_user(tids, unread_only=bool(unread),
                              kind=(kind or None), limit=min(int(limit), 300))
    return {"alerts": [{**a.as_dict(), "thread_title": titles.get(a.thread_id)}
                       for a in rows],
            "unread_total": sum(repo.unread_counts(tids).values())}


@router.post("/monitor/alerts/{alert_id}/read")
def read_alert(alert_id: str, request: Request):
    _require_user(request)
    from src.persistence import get_monitor_alert_repo

    return {"ok": get_monitor_alert_repo().mark_read(alert_id)}


@router.post("/monitor/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: str, request: Request):
    _require_user(request)
    from src.persistence import get_monitor_alert_repo

    return {"ok": get_monitor_alert_repo().dismiss(alert_id)}


@router.post("/monitor/threads/{thread_id}/detect")
async def detect_now(thread_id: str, request: Request):
    """지금 검사 — 운영·시연용. 주기 루프와 같은 경로를 쓴다."""
    import asyncio as _a

    user_id = _require_user(request)
    _own_thread_or_404(user_id, thread_id)
    from src.monitor_alerts import detect_for_thread

    return await _a.to_thread(detect_for_thread, thread_id)


# ── 수신자 주소록 (2026-10-02) ───────────────────────────────────────────────
#
# 종전 수신자는 쉼표 문자열이라 보낼 때마다 다시 타이핑했다. 오타가 그대로
# 외부로 나간다 — 규제 리포트가 엉뚱한 사람에게 가는 사고다.

@router.get("/contacts")
def search_contacts(request: Request, q: str = "", limit: int = 50):
    user_id = _require_user(request)
    from src.persistence import get_contacts_repo

    rows = get_contacts_repo().search(user_id, q, limit=min(int(limit), 200))
    return {"contacts": [c.as_dict() for c in rows]}


@router.post("/contacts")
async def create_contact(request: Request):
    user_id = _require_user(request)
    from src.persistence import get_contacts_repo
    from src.persistence.contacts_repo import Contact

    body = await request.json()
    email = str(body.get("email") or "").strip()
    try:
        cid = get_contacts_repo().upsert(Contact(
            id="", user_id=user_id, email=email,
            name=(str(body.get("name") or "").strip() or None),
            org=(str(body.get("org") or "").strip() or None)))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "id": cid}


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: str, request: Request):
    user_id = _require_user(request)
    from src.persistence import get_contacts_repo

    return {"ok": get_contacts_repo().delete(user_id, contact_id)}


# ── 스레드별 짧은 보고서 + 선택 발송 ────────────────────────────────────────

@router.post("/monitor/threads/{thread_id}/report")
async def thread_alert_report(thread_id: str, request: Request):
    """그 스레드의 알람을 **짧은 보고서**로 만든다.

    body: {"since": "2026-09-01"(선택)}
    정기 발송과 **별개 경로**다 — 정기는 "일정대로", 이건 "지금 필요해서".
    결과는 문서로 저장돼 의견서와 같은 패널에서 열람·수정·내보내기가 된다.
    """
    import asyncio as _a

    user_id = _require_user(request)
    meta = _own_thread_or_404(user_id, thread_id)
    from src.monitor_report import render_alert_report
    from src.persistence import (get_blob_store, get_monitor_alert_repo,
                                 get_monitor_watch_repo, get_reports_repo)
    from src.persistence.reports_repo import ReportMeta

    body = {}
    try:
        body = await request.json() if await request.body() else {}
    except Exception:  # noqa: BLE001
        body = {}
    since = str(body.get("since") or "").strip() or None

    alerts = get_monitor_alert_repo().list_for_thread(thread_id, since=since)
    watch = get_monitor_watch_repo().list_for_thread(thread_id)
    title = f"{meta.get('title') or '규제 모니터링'} — 변경 보고"
    md = render_alert_report(title=title, alerts=[a.as_dict() for a in alerts],
                             watch_count=len(watch), since=since)

    rid = f"doc_{uuid.uuid4().hex[:16]}"
    blob_uri = await _a.to_thread(get_blob_store().put, f"{rid}.md", md)
    await _a.to_thread(get_reports_repo().create, ReportMeta(
        id=rid, thread_id=thread_id, mode="deep", kind="doc", status="done",
        blob_uri=blob_uri, title=title, summary="규제 변경 보고",
        citations_json="[]", completed_at=None, filled_values="{}"))
    _log.info("monitor report %s (알람 %d건)", rid, len(alerts))
    return {"report_id": rid, "title": title, "alerts": len(alerts)}


@router.post("/monitor/threads/{thread_id}/send")
async def send_thread_report(thread_id: str, request: Request):
    """보고서를 **선택한 수신자**에게 보낸다.

    body: {"report_id": str, "recipients": ["a@b.com", ...]}
    보낸 주소는 주소록에 자동 등록된다 — 보낸 곳은 남아야 다음에 고를 수 있다.
    """
    import asyncio as _a

    user_id = _require_user(request)
    _own_thread_or_404(user_id, thread_id)
    from src.monitor_report import send_markdown_report
    from src.persistence import get_blob_store, get_contacts_repo, get_reports_repo

    body = await request.json()
    rid = str(body.get("report_id") or "").strip()
    recipients = parse_recipients(body.get("recipients"))
    if not rid:
        raise HTTPException(status_code=422, detail="report_id 가 필요합니다")
    if not recipients:
        raise HTTPException(status_code=422,
                            detail="수신자를 1명 이상 선택해 주세요")

    rmeta = get_reports_repo().get(rid)
    if not rmeta or rmeta.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="report not found")
    try:
        md = get_blob_store().get(rmeta.blob_uri) if rmeta.blob_uri else ""
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="report body unavailable")

    ok = await _a.to_thread(send_markdown_report, rmeta.title or "규제 변경 보고",
                            md, recipients)
    if ok:
        await _a.to_thread(get_contacts_repo().touch, user_id, recipients)
    return {"ok": ok, "recipients": recipients}


@router.post("/monitor/threads/{thread_id}/watch/recommend")
async def recommend_watch(thread_id: str, request: Request):
    """후보 중 **담을 만한 것**을 고르고 사유를 돌려준다 (2026-10-02).

    반환: {"picks": {article_key: "왜 담아야 하는지"}}

    **자동으로 담지 않는다.** 추천과 사유까지만 — 관찰 목록이 오염되면 알람이
    쓰레기가 되고, 그러면 사용자가 알람을 끈다.

    기밀 턴이 있던 스레드는 상용 모델로 제목을 보내지 않는다(원내 모델이 없으면
    추천 자체를 건너뛴다).
    """
    user_id = _require_user(request)
    meta = _own_thread_or_404(user_id, thread_id)

    if meta.get("confidential_seen"):
        from src.doc_fill import onprem_fill

        if not onprem_fill():
            # 기밀 대화의 주제를 상용 모델에 보내지 않는다. 조용히 비우지 않고
            # 이유를 돌려줘 FE 가 "추천 불가"로 표시하게 한다.
            return {"picks": {}, "skipped": "confidential"}

    from src.monitor_recommend import recommend

    # 후보는 제안 로직을 그대로 쓴다 — 두 목록이 어긋나면 추천이 엉뚱해진다.
    sug = suggest_watch(thread_id, request)
    cands = [s for s in sug["suggestions"] if not s["already"]]
    if not cands:
        return {"picks": {}}

    subject = str(meta.get("title") or "").strip() or "이 모니터링 대상"
    picks = await recommend(subject, cands)
    _log.info("관찰 추천 %s: 후보 %d → 추천 %d", thread_id, len(cands), len(picks))
    return {"picks": picks}
