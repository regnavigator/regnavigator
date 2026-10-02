"""보고서 메타 조회·다운로드 + 본인 사용량."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response

from src.middleware import effective_limits, usage_summary
from src.persistence import (
    Event,
    get_blob_store,
    get_events_repo,
    get_reports_repo,
    get_users_repo,
)
from src.routes._shared import (
    _check_auth,
    _meta_dict,
    assert_report_access,
    assert_thread_access,
)

router = APIRouter()
_log = logging.getLogger(__name__)

# 주제로 인정하지 않는 최소 정제 길이(공백 제거 후 글자 수). "요약", "보고서" 같은
# 알맹이 없는 트리거 문구를 거른다.
_MIN_TOPIC_CHARS = 8


def _assert_report_ready(thread_id: str, prompt: Optional[str]) -> None:
    """심층보고서 진입 허들 — 실질 상담 맥락이 없으면 HTTPException(422).

    두 조건을 모두 통과해야 함:
      ① 실질 주제 — prompt(next_steps 클릭) 또는 직전 human 메시지가 인사/재촉/
         필러가 아니고 최소 길이 이상.
      ② 상담 근거 — thread 에 누적 citation ≥1. 규제 질의는 검색이 강제되므로
         (CLAUDE.md §5) 실제 상담엔 citation 이 쌓인다. 서비스 소개·인사만 오간
         대화는 citation 이 0 이라 여기서 걸린다(빈 보고서 사고의 핵심 신호).

    라우트 진입부에서 동기 호출 — 멱등락/잡 spawn 이전에 빠르게 실패시킨다.
    """
    from src.guardrail.intent import _looks_offtopic
    from src.persistence.threads_repo import get_threads_repo
    from src.report_pipeline import extract_report_context

    state = get_threads_repo().get_state(thread_id).as_tool_state()
    rctx = extract_report_context(state)

    topic = (prompt or "").strip() or (rctx.get("user_query") or "").strip()
    compact = re.sub(r"\s+", "", topic)
    if not topic or _looks_offtopic(topic) or len(compact) < _MIN_TOPIC_CHARS:
        raise HTTPException(
            status_code=422,
            detail="심층보고서를 만들 주제가 없습니다. 먼저 구체적인 규제 "
                   "질문을 남겨 상담을 진행한 뒤 보고서를 요청해주세요.",
        )

    if not rctx.get("accumulated_citations"):
        raise HTTPException(
            status_code=422,
            detail="아직 상담 근거가 없습니다. 규제 사안에 대한 답변(법령·자료 "
                   "인용)을 한 번 이상 받은 뒤 심층보고서를 요청해주세요.",
        )


@router.post("/reports", status_code=202)
async def trigger_report(request: Request, body: dict):
    """보고서 트리거 — ADR-0001 Phase 3 (langgraph `agent_report` 대체 PoC).

    body: {"thread_id": "...", "idempotency_key": "rpt_..."}
    응답: 202 {status:"accepted"} | 200 {status:"completed"|"running"} |
          409 {status:"failed"}(새 idem 키로 재요청) | 422 형식 오류.

    langgraph 경로의 entry_check 와 동일 계약: 인증 필수, `^rpt_` 멱등키,
    report_runs 멱등락. 수락 시 asyncio task 백그라운드 실행(report_runner).
    자체 /chat 루프로 대화한 thread 전제(threads_repo 맥락 상속).
    """
    if (os.getenv("CHAT_LOOP_DISABLE") or "").strip() == "1":
        raise HTTPException(status_code=404, detail="chat loop disabled")

    user_id = getattr(request.state, "user_id", None)
    user_email = getattr(request.state, "user_email", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    from src.routes.privacy import require_consent
    await asyncio.to_thread(require_consent, request)  # 동의 없는 이용 차단(2026-09-23)

    # 기능 단위 일시 중단(2026-09-07): writer 를 다른 작업에 쓰는 동안 "보고서만"
    # 막는다 — 채팅은 정상. 전체 점검(503 전면 차단)과 구분. 관리자도 막힘(실제로
    # writer 가 없으니 예외를 둘 이유가 없다).
    from src.maintenance import feature_paused
    _paused, _pmsg = await asyncio.to_thread(feature_paused, "reports")
    if _paused:
        raise HTTPException(status_code=503, detail=_pmsg,
                            headers={"X-Feature-Paused": "reports"})

    thread_id = str(body.get("thread_id") or "").strip()
    idem = str(body.get("idempotency_key") or "").strip()
    purpose = body.get("purpose")
    if purpose not in (None, "license_strategy", "reg_summary", "change_response",
                       "document_draft"):
        purpose = None  # 미지 값은 기본 보고서로
    # 사용자가 인용/별표 모달에서 고른 서식(2026-08-26) — "검색해서 확인한 그
    # 서식으로 작성"을 성립시킨다. 형식 검증만 하고 조회는 잡에서(라우트 빠르게).
    form_key = str(body.get("form_article_key") or "").strip()
    if form_key and not re.match(r"^[\w:#\-]{4,120}$", form_key):
        form_key = ""
    if not thread_id or not re.match(r"^rpt_[A-Za-z0-9_-]{1,128}$", idem):
        raise HTTPException(
            status_code=422,
            detail="thread_id 와 idempotency_key(^rpt_...) 가 필요합니다.",
        )

    # 소유권 — 남의 thread 대화로 보고서 생성(=맥락 유출) 차단. 존재도 필수
    # (빈 thread 론 보고서 불가). 구경로 @auth.on.threads 스코프 대체.
    from src.routes.chat import _owned_meta_or_404
    _meta = await asyncio.to_thread(_owned_meta_or_404, thread_id, request)

    # 기밀 스레드 게이트(2026-10-03). 보고서 파이프라인은 직전 질문·답변·누적
    # 인용을 decompose(Haiku)·writer 로 보내는데 `confidential` 을 전혀 몰랐다 —
    # 변호사가 기밀 상담 뒤 "심층보고서"를 누르면 **의뢰인 사실관계가 통째로
    # 상용 모델로** 나갔다. writer·decompose 가 원내로 고정될 때까지 막는다.
    if bool((_meta or {}).get("confidential_seen")):
        raise HTTPException(
            status_code=422,
            detail="기밀 모드로 상담한 대화는 심층보고서를 만들 수 없습니다 — "
                   "보고서 생성은 원내 모델로 처리되지 않습니다. 의견서 초안(원내)을 "
                   "이용하거나 새 대화에서 요청해 주세요.")

    # 진입 허들 — 실질 상담 맥락이 있어야만 5~12분 27B 잡을 띄운다. 없으면 즉시
    # 422(멱등락 acquire·잡 spawn 이전). 인사/서비스 소개만 오간 thread 에서 빈
    # 보고서가 생성되던 사고 차단(2026-07-21).
    #
    # 이 핸들러만 `async def` 를 유지한다 — spawn_report_job 이 asyncio.create_task
    # 를 쓰므로 실행 중인 루프가 필요하다. 대신 동기 DB 작업은 전부 to_thread 로
    # 넘긴다. 특히 _assert_report_ready 는 thread 상태 **전체**를 로드해
    # extract_report_context 를 돌리므로 대화가 길수록 무겁다(2026-08-04 C-3).
    await asyncio.to_thread(
        _assert_report_ready, thread_id,
        str(body.get("prompt") or "").strip() or None)

    from src.persistence import get_report_runs_repo
    from src.report_runner import has_capacity, spawn_report_job

    if not has_capacity():
        raise HTTPException(status_code=429, detail="보고서 큐가 가득 찼습니다. 잠시 후 재시도해주세요.")

    # 스레드당 동시 보고서 1개 — 진행 중인데 *다른 키*로 또 트리거하면 차단
    # (같은 키 재시도는 아래 acquire 멱등 경로가 "running" 반환). 중복 잡이
    # 직렬 큐에 쌓여 같은 대화에 보고서가 연달아 생성되던 간섭 제거(2026-07-24).
    # detail 에 코드 문자열 포함 — FE 가 "실패 키 409 → 새 키 재시도" 경로와 구분.
    _running = await asyncio.to_thread(
        get_report_runs_repo().latest_running_for_thread, thread_id)
    if _running and _running.idempotency_key != idem:
        raise HTTPException(
            status_code=409,
            detail="report_in_progress: 이 대화에서 이미 심층 보고서를 생성 중입니다. "
                   "완료 후 다시 시도해주세요.",
        )

    acquired, existing = await asyncio.to_thread(
        lambda: get_report_runs_repo().acquire(
            idempotency_key=idem, thread_id=thread_id, user_id=str(user_id),
            # 주제·목적을 run 에 저장(재설계 2026-07-24) — 대화록 append 대신
            # 러너·재시작 복원이 여기서 읽는다.
            prompt=(str(body.get("prompt") or "").strip() or None),
            purpose=purpose,
        )
    )
    if not acquired:
        # idempotency_key 는 report_runs 의 PRIMARY KEY — **전 사용자 공유
        # 네임스페이스**다. 소유자 확인 없이 기존 run 을 돌려주면 남의 키를 맞힌
        # 사람이 report_id 를 받아간다(조회 소유권 검사와 짝, 2026-08-04 H-3).
        # 다른 조회 라우트(report_run_status·active)는 이미 검사 중이었다.
        if existing and existing.user_id and str(existing.user_id) != str(user_id):
            raise HTTPException(
                status_code=409,
                detail="이미 사용된 idempotency_key 입니다. 새 키로 요청해주세요.",
            )
        st = existing.status if existing else "unknown"
        if st == "completed" and existing and existing.report_id:
            return Response(
                content=json.dumps({
                    "status": "completed", "report_id": existing.report_id,
                }, ensure_ascii=False),
                media_type="application/json", status_code=200,
            )
        if st == "running":
            return Response(
                content=json.dumps({"status": "running"}, ensure_ascii=False),
                media_type="application/json", status_code=200,
            )
        raise HTTPException(
            status_code=409,
            detail="이전 보고서 요청이 실패로 종료됐습니다. 새 idempotency_key 로 다시 요청해주세요.",
        )

    spawn_report_job(
        thread_id=thread_id, user_id=str(user_id),
        idempotency_key=idem, user_email=user_email,
        prompt=(str(body.get("prompt") or "").strip() or None),
        purpose=purpose,
        form_article_key=form_key or None,
    )
    return {"status": "accepted", "idempotency_key": idem, "thread_id": thread_id}


@router.get("/reports/runs/active")
def report_run_active(thread_id: str, request: Request):
    """이 thread 의 진행 중 보고서 run — FE 새로고침 후 진행 UI·폴링 복원용.

    (실측 2026-07-24: 새로고침하면 멱등키가 메모리에만 있어 진행 표시가 통째로
    사라짐 — "진행보기 안 보임" 피드백.) `/reports/runs/{key}` 보다 먼저 선언
    (경로 매칭 순서).
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    from src.persistence import get_report_runs_repo

    run = get_report_runs_repo().latest_running_for_thread(thread_id)
    if not run or (run.user_id and str(run.user_id) != str(user_id)):
        return {"status": "none"}
    out = {
        "status": "running",
        "idempotency_key": run.idempotency_key,
        "started_at": run.started_at,
    }
    from src.report_runner import queue_ahead

    qa = queue_ahead(run.idempotency_key)
    if qa is not None:
        out["queue_ahead"] = qa
    return out


@router.post("/reports/runs/{idempotency_key}/cancel")
async def report_run_cancel(idempotency_key: str, request: Request):
    """진행 중 보고서 중단(2026-09-02) — 진행 카드 [중단] 버튼 전용.

    본인 run + running 상태만. 자유 텍스트(채팅)로는 중단되지 않는다 —
    트리거와 대칭인 명시 버튼 계약(오탐 한 번이 40분 작업을 죽이면 안 됨).
    비용 절감 + 동시성 1 큐 점유 해소가 목적.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    from src.persistence import get_report_runs_repo

    run = await asyncio.to_thread(
        get_report_runs_repo().get, idempotency_key)
    if not run or (run.user_id and str(run.user_id) != str(user_id)):
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "running":
        raise HTTPException(status_code=409,
                            detail=f"중단할 수 없는 상태입니다({run.status}).")
    from src.report_runner import cancel_run

    # task.cancel() 은 이벤트 루프 안에서 — 이 라우트가 async 인 이유.
    if not cancel_run(idempotency_key):
        raise HTTPException(status_code=409, detail="이미 종료된 작업입니다.")
    try:
        import json as _json

        from src.persistence import get_events_repo
        from src.persistence.events_repo import Event as _Ev
        await asyncio.to_thread(get_events_repo().emit, _Ev(
            id="", ts="", event_type="report_cancelled",
            user_id=str(user_id), thread_id=run.thread_id,
            run_id=idempotency_key,
            payload_json=_json.dumps({}, ensure_ascii=False)))
    except Exception:  # noqa: BLE001 — 관측 실패가 취소를 막으면 안 됨
        pass
    return {"ok": True, "status": "cancelled"}


#: 보고서 파이프라인 단계 — `report_runner` 가 발행하는 step 의 tool_name 순서.
#: 사용자에게 "3단계 중 2단계"를 보여주기 위한 것이라, 단계를 늘리면 여기도 고친다.
_REPORT_PHASES: tuple[tuple[str, str], ...] = (
    ("report_decompose", "질문 분해"),
    ("report_gather", "자료 수집"),
    ("report_writer", "본문 작성"),
)


def _run_progress(thread_id: str) -> dict | None:
    """진행 중인 보고서의 현재 단계 — thread steps 에서 추출.

    반환 `{phase, total, label, message?}`. 단계를 못 찾으면 None(초기 몇 초).
    실패는 삼키지 않고 warning — 진행 표시가 조용히 죽으면 사용자는 멈춘 줄 안다.
    """
    try:
        from src.persistence.threads_repo import get_threads_repo

        steps = get_threads_repo().get_state(thread_id).steps or []
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "보고서 진행 단계 조회 실패 thread=%s", thread_id, exc_info=True)
        return None

    order = {name: i for i, (name, _) in enumerate(_REPORT_PHASES)}
    last = None
    for st in steps:
        if str(st.get("tool_name") or "") in order:
            last = st
    if last is None:
        return None
    name = str(last.get("tool_name"))
    out = {
        "phase": order[name] + 1,
        "total": len(_REPORT_PHASES),
        "label": last.get("label") or _REPORT_PHASES[order[name]][1],
    }
    # 새벽 데이터 갱신 대기 등 — 진행이 멈춰 보이는 이유를 설명하는 보조 문구.
    if last.get("status") == "running" and last.get("progress_message"):
        out["message"] = last["progress_message"]
    return out


@router.get("/reports/runs/{idempotency_key}")
def report_run_status(idempotency_key: str, request: Request):
    """보고서 잡 상태 폴링 — POST /reports 수락 후 FE 가 조회."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    from src.persistence import get_report_runs_repo

    run = get_report_runs_repo().get(idempotency_key)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    if run.user_id and str(run.user_id) != str(user_id):
        raise HTTPException(status_code=404, detail="run not found")  # 소유자 외 비노출
    out = {
        "status": run.status,
        "report_id": run.report_id,
        "thread_id": run.thread_id,
        "error": run.error,
    }
    if run.status == "running":
        from src.report_runner import queue_ahead

        qa = queue_ahead(idempotency_key)
        if qa is not None:
            out["queue_ahead"] = qa  # 앞에 N건 — FE "대기 중" 안내
        # 세부 진행(2026-09-10) — 종전엔 FE 가 5초마다 `GET /chat/{tid}/state` 로
        # **스레드 전체(메시지 포함)** 를 받아 라벨 한 줄만 뽑아 썼다. 보고서는
        # 5~40분이라 폴링이 수백 회 돌고, 단일 워커 서버에 불필요한 부하였다.
        # 여기서 바로 준다 — FE 는 이 폴링 하나로 끝난다.
        if qa is None and run.thread_id:
            prog = _run_progress(str(run.thread_id))
            if prog:
                out["progress"] = prog
    return out


@router.get("/threads/{thread_id}/reports")
def list_reports(thread_id: str, request: Request,
                 authorization: Optional[str] = Header(None)):
    _check_auth(authorization)
    assert_thread_access(thread_id, request)
    repo = get_reports_repo()
    rows = repo.list_for_thread(thread_id)
    return {"thread_id": thread_id, "count": len(rows), "reports": [_meta_dict(r) for r in rows]}


@router.get("/reports/{report_id}")
def get_report(report_id: str, request: Request,
               authorization: Optional[str] = Header(None)):
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)
    out = _meta_dict(meta)
    if meta.blob_uri:
        try:
            url = get_blob_store().presigned_url(meta.blob_uri)
            if url:
                out["download_url"] = url
        except Exception as e:  # noqa: BLE001 — 링크 실패가 메타 조회를 막으면 안 됨
            # 조용히 삼키면 FE 에 "다운로드 없음"으로만 보여 원인 추적 불가
            # (2026-08-11 발견) — 최소한 관측은 남긴다.
            logging.getLogger(__name__).warning(
                "presigned_url 실패 report=%s blob=%s: %s",
                report_id, meta.blob_uri, e)
    return out


@router.get("/me/usage")
def me_usage(request: Request):
    """본인 사용량 조회. 인증 필요."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = get_users_repo().get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    d, m = effective_limits(user)
    return {
        "user_id": user.id,
        "email": user.email,
        "is_admin": user.is_admin,
        "effective_daily_limit": d,
        "effective_monthly_limit": m,
        "usage": usage_summary(user.id),
    }


@router.delete("/reports/{report_id}")
def delete_report(report_id: str, request: Request,
                  authorization: Optional[str] = Header(None)):
    """보고서/서류 삭제 (2026-08-27, 사용자 요청) — 소유자만.

    blob(전문)은 best-effort 삭제, 메타 행은 확정 삭제. report_runs 이력은
    남긴다(사용량·관측의 근거 — 사용자 화면에는 안 뜬다).
    """
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)

    if meta.blob_uri:
        try:
            get_blob_store().delete(meta.blob_uri)
        except Exception:  # noqa: BLE001 — 고아 blob 은 보존정책 스윕이 걷는다
            _log.info("report delete: blob 삭제 실패(무시) %s", report_id)
    get_reports_repo().delete(report_id)
    if meta.kind == "doc":
        # run 행은 남기되 지운 서류를 가리키지 않게 — 안 그러면 채팅 턴 대조·
        # "작성 중인 서류" pill·GET /documents 가 없는 서류를 계속 집는다(2026-09-18).
        from src.persistence import get_report_runs_repo
        try:
            get_report_runs_repo().detach_report(report_id)
        except Exception:  # noqa: BLE001 — 삭제 자체는 이미 끝났다
            _log.warning("report delete: run detach 실패 %s", report_id, exc_info=True)
    try:
        get_events_repo().emit(Event(
            id="", ts="", event_type="report_deleted",
            user_id=str(getattr(request.state, "user_id", "") or None),
            thread_id=meta.thread_id, run_id=report_id,
            payload_json=json.dumps({"kind": meta.kind}, ensure_ascii=False)))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "report_id": report_id}


@router.get("/documents")
def list_documents(request: Request, limit: int = 50,
                   authorization: Optional[str] = Header(None)):
    """내가 작성한 서식 목록 — 스레드 무관, 최신순 (2026-09-18, 다시 보기·삭제).

    reports 엔 user_id 가 없어 report_runs(purpose=document_draft) 로 사용자를
    잇는다. 각 항목: id·title·thread_id·created_at·filled_count. 본문·항목 수는
    패널이 열릴 때 따로 받는다(목록은 가볍게).
    """
    _check_auth(authorization)
    from src.persistence import get_report_runs_repo
    user_id = str(getattr(request.state, "user_id", "") or "")
    ids = get_report_runs_repo().document_report_ids_for_user(
        user_id, limit=max(1, min(int(limit), 200)))
    from src.doc_fill import extract_unfilled_fields
    from src.form_docs import document_status
    from src.persistence.threads_repo import get_threads_repo

    repo = get_reports_repo()
    threads = get_threads_repo()
    alive: dict[str, bool] = {}
    titles: dict[str, Optional[str]] = {}
    items = []
    for rid in ids:
        meta = repo.get(rid)
        if not meta or meta.kind != "doc" or meta.status != "done":
            continue
        try:
            filled = json.loads(meta.filled_values or "{}")
        except ValueError:
            filled = {}
        # 전체 항목 수는 본문의 [확인 필요:] 마커에서 센다. 본문을 못 읽으면 0 —
        # 그때 상태는 채운 수만으로 판정(작성 중/미작성).
        fields: list[str] = []
        if meta.blob_uri:
            try:
                fields = extract_unfilled_fields(get_blob_store().get(meta.blob_uri))
            except Exception:  # noqa: BLE001
                _log.info("documents list: 본문 읽기 실패 %s", rid)
        filled_count = (sum(1 for f in fields if f in filled) if fields else len(filled))
        if meta.thread_id not in alive:
            tmeta = threads.get_meta(meta.thread_id)
            alive[meta.thread_id] = bool(tmeta)
            titles[meta.thread_id] = (tmeta or {}).get("title") if tmeta else None
        items.append({"id": meta.id, "title": meta.title,
                      "alias": meta.alias,
                      "thread_id": meta.thread_id,
                      "thread_alive": alive[meta.thread_id],
                      "thread_title": titles.get(meta.thread_id),
                      "created_at": meta.created_at,
                      "field_count": len(fields),
                      "filled_count": filled_count,
                      "status": document_status(len(fields), filled_count),
                      "kept": bool(meta.kept)})
    return {"documents": items}


@router.patch("/documents/{report_id}")
def patch_document(report_id: str, body: dict, request: Request,
                   authorization: Optional[str] = Header(None)):
    """서식 별명 `{alias: str|null}` — 같은 서식을 여러 건 쓸 때 구분용(≤60자, 빈 값=해제).
    원 제목(서식명)은 바뀌지 않는다."""
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta or meta.kind != "doc":
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)
    if "alias" not in (body or {}):
        raise HTTPException(status_code=422, detail="alias 필요")
    alias = re.sub(r"\s+", " ", str(body.get("alias") or "")).strip()
    if len(alias) > 60:
        raise HTTPException(status_code=422, detail="별명은 60자 이내여야 합니다.")
    get_reports_repo().set_alias(report_id, alias or None)
    return {"ok": True, "report_id": report_id, "alias": alias or None}


@router.post("/documents/{report_id}/keep")
def keep_document(report_id: str, body: dict, request: Request,
                  authorization: Optional[str] = Header(None)):
    """서식 보관(스크랩) 토글 `{kept: bool}` — 보관한 서식은 원 대화가 삭제·만료돼도
    남는다. 보관하지 않은 서식은 대화와 함께 지워진다(`form_docs.delete_thread_documents`)."""
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta or meta.kind != "doc":
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)
    kept = bool((body or {}).get("kept", True))
    get_reports_repo().set_kept(report_id, kept)
    return {"ok": True, "report_id": report_id, "kept": kept}


@router.get("/documents/state")
def document_state(request: Request, thread_id: str,
                   authorization: Optional[str] = Header(None)):
    """스레드의 최신 서류 초안 상태 — FE 문서 패널 초기화용 (Phase ③).

    반환: {"report_id": null} (초안 없음) 또는
    {"report_id", "fields", "filled", "remaining"} (본문은 미포함 —
    본문은 `GET /reports/{id}/download?fill=0` 으로 별도 취득).
    """
    _check_auth(authorization)
    assert_thread_access(thread_id, request)
    from src.doc_fill import load_draft_state

    state = load_draft_state(thread_id)
    if not state:
        return {"report_id": None}
    meta = get_reports_repo().get(state["report_id"])
    return {"report_id": state["report_id"], "fields": state["fields"],
            "filled": state["filled"], "remaining": state["remaining"],
            "title": (getattr(meta, "title", None) if meta else None)}


@router.post("/documents/{report_id}/fill")
async def fill_document_field(report_id: str, request: Request,
                              authorization: Optional[str] = Header(None)):
    """서류 초안 항목 AI 작성/기입 (Phase ②, 2026-08-24).

    body: {"field": "항목명" | "*", "hint": "사용자 힌트(선택)",
           "value": "직접 입력값(선택 — 있으면 LLM 없이 그대로 저장)"}
    - value 제공 → 그대로 병합(직접 기입 저장 경로).
    - field="*" → 미기입 전체를 대화 없이 문서 맥락+힌트로 일괄 시도.
    반환: {"filled": {...}, "remaining": [...]} — 날조 금지: 근거 부족 항목은
    안 채워지고 remaining 에 남는다.
    """
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)

    body = await request.json()
    field = str(body.get("field") or "").strip()
    hint = str(body.get("hint") or "").strip()
    value = body.get("value")
    if not field:
        raise HTTPException(status_code=422, detail="field 가 필요합니다")

    from src.doc_fill import (chat_context_for_fill, extract_unfilled_fields,
                              generate_field_value)
    from src.persistence import get_blob_store as _bs

    try:
        doc = _bs().get(meta.blob_uri) if meta.blob_uri else ""
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="document body unavailable")
    fields = extract_unfilled_fields(doc)
    import json as _json
    try:
        filled = _json.loads(meta.filled_values or "{}")
    except ValueError:
        filled = {}

    new_values: dict = {}
    if value is not None and field != "*":
        # 직접 기입 저장 — LLM 미경유(빈 문자열이면 해당 항목 삭제는 v2).
        v = str(value).strip()
        if v:
            new_values[field] = v[:2000]
    else:
        targets = ([f for f in fields if f not in filled]
                   if field == "*" else [field])
        # 근거는 대화에 있다 — 본문(from-form 은 뼈대뿐)만 보면 전부 "근거
        # 부족"이 된다. 저장 대화는 마스킹본이라 어느 모델에든 안전.
        ctx = await asyncio.to_thread(chat_context_for_fill, meta.thread_id)
        for f in targets:
            v = await generate_field_value(doc, f, hint, chat_context=ctx)
            if v:
                new_values[f] = v

    if new_values:
        filled = get_reports_repo().merge_filled_values(report_id, new_values)
    remaining = [f for f in fields if f not in filled]
    return {"filled": new_values, "values": filled, "remaining": remaining}


@router.get("/documents/assist/load")
def assist_load(request: Request,
                authorization: Optional[str] = Header(None)):
    """기입 레인 동시 요청 수 — FE 가 "대기(앞에 요청 있음)" 와 "생성 지연" 을
    구분해 안내하는 근거(2026-08-27). 값은 이 서버 기준(단일 인스턴스)."""
    _check_auth(authorization)
    from src.doc_fill import assist_inflight

    return {"in_flight": assist_inflight()}


@router.post("/documents/{report_id}/chat")
async def document_assist_chat(report_id: str, request: Request,
                               authorization: Optional[str] = Header(None)):
    """서식 작성 도우미 챗 (2026-08-27) — 전용 모달의 한 턴.

    body: {"message": str, "history": str(선택 — 클라이언트가 든 직전 대화)}
    반환: {"reply", "filled"(새 기입), "values"(전체), "remaining", "corrected"}

    설계 근거(실사용 지적 2건):
    - "저장 대화는 PII 마스킹본인데 어떻게 대화로 작성하냐" — 맞는 지적.
      이 창구는 **채팅 스레드 밖**이다: 메시지가 게이트를 거치지 않고
      **온프레미스 모델로 직행**하며, 어디에도 저장하지 않는다(기입값만
      filled_values 로 영속, 관측은 항목명·건수만).
    - "서식 작성은 별도 모달로, FAQ 챗봇처럼" — 도우미가 남은 항목을 안내하고
      "뭘 입력해야 해"에 답한다.

    온프레미스 미설정이면 503 — 원문 개인정보를 상용 모델로 보낼 수는 없다
    (독립 레인 정책). FE 는 직접 입력으로 안내한다.
    """
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)

    from src.doc_fill import assistant_turn, extract_unfilled_fields, onprem_fill

    if not onprem_fill():
        raise HTTPException(
            status_code=503,
            detail="작성 도우미를 지금 사용할 수 없습니다. 항목을 눌러 직접 "
                   "입력해 주세요.")

    body = await request.json()
    message = str(body.get("message") or "").strip()
    history = str(body.get("history") or "").strip()
    # 첨부 문서 텍스트(2026-08-27) — FE 가 /files/extract 로 뽑아 보낸다.
    # 온프레미스 전용 창구라 원문 허용. 상한은 로컬 모델 컨텍스트 보호용.
    attachment_text = str(body.get("attachment_text") or "").strip()[:12000]
    if not message:
        raise HTTPException(status_code=422, detail="message 가 필요합니다")
    if len(message) > 4000:
        raise HTTPException(status_code=422, detail="메시지가 너무 깁니다")

    from src.persistence import get_blob_store as _bs
    try:
        doc = _bs().get(meta.blob_uri) if meta.blob_uri else ""
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="document body unavailable")
    fields = extract_unfilled_fields(doc)
    import json as _json
    try:
        filled = _json.loads(meta.filled_values or "{}")
    except ValueError:
        filled = {}

    reply, values = await assistant_turn(
        meta.title or "서식", fields, filled, message, history,
        attachment_text=attachment_text)
    corrected = sorted(k for k in values if k in filled)
    if values:
        filled = get_reports_repo().merge_filled_values(report_id, values)
        # 관측 — 값(개인정보) 비적재, 항목명·건수만.
        try:
            get_events_repo().emit(Event(
                id="", ts="", event_type="doc_fill",
                user_id=str(getattr(request.state, "user_id", "") or None),
                thread_id=meta.thread_id, run_id=report_id,
                payload_json=_json.dumps({
                    "filled_fields": sorted(values.keys()),
                    "corrected_fields": corrected,
                    "remaining": len([f for f in fields if f not in filled]),
                    "source": "assist_chat",
                }, ensure_ascii=False)))
        except Exception:  # noqa: BLE001
            _log.debug("doc assist event emit failed", exc_info=True)
    remaining = [f for f in fields if f not in filled]
    return {"reply": reply, "filled": values, "values": filled,
            "remaining": remaining, "corrected": corrected}


@router.post("/documents/from-form")
async def create_document_from_form(request: Request,
                                    authorization: Optional[str] = Header(None)):
    """선택한 별표·서식으로 **즉시** 기입 문서를 연다 (2026-08-27).

    body: {"thread_id", "article_key", "title"(선택)}
    반환: `/documents/state` 와 같은 모양 — {"report_id","fields","filled",
    "remaining","title"}.

    왜 별도 경로인가: 종전 [이 서식으로 작성]은 `POST /reports`
    (purpose=document_draft)로 심층 보고서 파이프라인을 돌렸고, 그게 끝나야
    (5~40분) 기입 항목이 화면에 떴다. 사용자가 기대한 건 "서식이 뜨고 그걸
    채우게 안내"다. 항목 목록은 서식 자체에 있으므로 LLM 없이 몇 초면 만든다.
    여기서 만든 문서는 기존 초안과 **같은 마커 계약**(`[확인 필요: X]`)이라
    채팅 기입·항목별 AI 작성·원본 서식 다운로드가 그대로 붙는다.
    """
    _check_auth(authorization)
    body = await request.json()
    thread_id = str(body.get("thread_id") or "").strip()
    article_key = str(body.get("article_key") or "").strip()
    if not thread_id or not article_key:
        raise HTTPException(status_code=422,
                            detail="thread_id·article_key 가 필요합니다")
    if not re.fullmatch(r"[\w:#\-]{4,120}", article_key):
        raise HTTPException(status_code=422, detail="article_key 형식 오류")
    assert_thread_access(thread_id, request)

    from src.form_intake import intake
    from src.report_pipeline import pinned_form_asset

    # 서식 본문·다운로드 링크는 인용 조립 경로를 재사용한다(중복 구현 금지).
    cites = await asyncio.to_thread(pinned_form_asset, article_key)
    if not cites:
        raise HTTPException(
            status_code=404,
            detail="선택한 서식의 본문·원본 링크를 찾지 못했습니다")
    cite = cites[0]
    title = (str(body.get("title") or "").strip()
             or str(cite.get("title") or "서식"))

    # ⚠️ `cite["text"]` 는 writer 주입용으로 잘린 발췌다(1,500자) — 그걸로 항목을
    # 뽑으면 서식 앞머리 몇 칸만 잡힌다(실측 10개 → 3개). 기입란은 서식 전체에
    # 흩어져 있으므로 원문을 다시 받는다.
    form_text = str(cite.get("text") or "")
    try:
        from src.retrieval.search_api_client import fetch_bodies

        full = (await asyncio.to_thread(fetch_bodies, [article_key])
                or {}).get(article_key) or {}
        form_text = str(full.get("full_text") or "") or form_text
    except Exception:  # noqa: BLE001 — 발췌로도 항목 일부는 나온다
        _log.info("from-form: 원문 조회 실패 — 발췌로 진행 key=%s",
                  article_key, exc_info=True)

    # 실파일 라벨이 본문 파싱보다 정확하다 — 받을 수 있으면 받아서 쓴다.
    form_path = None
    tmpdir = None
    if cite.get("download_url"):
        try:
            import tempfile

            from src.form_fill import fetch_form_bytes

            data = await asyncio.to_thread(fetch_form_bytes,
                                           cite["download_url"])
            tmpdir = tempfile.mkdtemp(prefix="form_intake_")
            form_path = os.path.join(tmpdir, "form.hwp")
            with open(form_path, "wb") as fh:
                fh.write(data)
        except Exception:  # noqa: BLE001 — 링크 죽어도 본문 파싱으로 진행
            _log.info("from-form: 원본 서식 내려받기 실패 key=%s",
                      article_key, exc_info=True)
            form_path = None
    try:
        fields, skeleton = await asyncio.to_thread(
            intake, title, form_text, form_path=form_path,
            source_note=f"출처: {cite.get('publisher') or '법제처'} · "
                        f"`{article_key}`")
    finally:
        if tmpdir:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)

    # 보고서 레코드로 저장 — 조회·다운로드·기입 라우트가 전부 report_id 기준이다.
    from src.persistence import get_report_runs_repo
    from src.persistence.reports_repo import ReportMeta

    report_id = f"doc_{uuid.uuid4().hex[:16]}"
    blob_uri = await asyncio.to_thread(
        get_blob_store().put, f"{report_id}.md", skeleton)
    await asyncio.to_thread(get_reports_repo().create, ReportMeta(
        # kind="doc" — 보고서 목록·카드·메일과 분리(책임 분리 2026-08-27).
        id=report_id, thread_id=thread_id, mode="deep", kind="doc",
        status="done", blob_uri=blob_uri, title=title,
        summary=f"{title} 기입 문서",
        citations_json=json.dumps([cite], ensure_ascii=False),
        completed_at=None, filled_values="{}",
    ))
    # `latest_draft_report_for_thread` 가 이 문서를 최신 초안으로 집게 한다 —
    # 채팅 턴 대조 기입(doc_fill)의 게이트가 report_runs 를 보기 때문.
    runs = get_report_runs_repo()
    idem = f"rpt_form_{report_id}"
    await asyncio.to_thread(
        lambda: runs.acquire(idempotency_key=idem, thread_id=thread_id,
                             user_id=str(getattr(request.state, "user_id",
                                                 "") or ""),
                             prompt=f"[서식] {title}",
                             purpose="document_draft"))
    await asyncio.to_thread(
        lambda: runs.finish(idem, status="completed", report_id=report_id))
    _log.info("from-form: 문서 생성 %s (%s, 항목 %d개)",
              report_id, title[:30], len(fields))
    return {"report_id": report_id, "title": title, "fields": fields,
            "filled": {}, "remaining": fields}


@router.get("/documents/{report_id}/original-form")
async def download_original_form(report_id: str, request: Request,
                                 authorization: Optional[str] = Header(None)):
    """관보 원본 서식(.hwpx) 기입 다운로드 (2026-08-25).

    서류 초안(document_draft)의 근거 인용에서 별표·서식 원본(law.go.kr HWP)을
    받아 kordoc 으로 `filled_values` 를 기입, **원형 유지** .hwpx 로 반환.
    - 404 no_form: 인용에 관보 서식 원본이 없음(기관 서식 등) — FE 안내용.
    - 503: kordoc 미가용(KORDOC_CLI 미설정 배포).
    """
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)

    from src.form_fill import build_filled_form, kordoc_cmd
    from src.tools.citations import pick_form_citation

    if not kordoc_cmd():
        raise HTTPException(status_code=503, detail="form fill unavailable")
    try:
        citations = json.loads(meta.citations_json or "[]")
    except ValueError:
        citations = []
    try:
        filled = json.loads(meta.filled_values or "{}")
    except ValueError:
        filled = {}

    # 어떤 인용이 서식 원본인지는 인용 스키마 소유자가 판단하고, 기입 엔진에는
    # URL 만 넘긴다(분리 경계 — form_fill 은 인용을 모른다).
    cite = pick_form_citation(citations)
    if not cite:
        raise HTTPException(
            status_code=404,
            detail="이 서류의 근거에서 관보 서식 원본을 찾지 못했습니다")
    try:
        data, summary = await build_filled_form(
            cite["download_url"], filled, form_title=cite.get("title"))
    except Exception as e:  # noqa: BLE001 — 원인은 서버 로그로(외부 내부정보 차단)
        logging.getLogger(__name__).exception(
            "original-form 실패 report=%s: %s", report_id, e)
        raise HTTPException(status_code=502, detail="서식 원본 처리 실패")

    try:
        get_events_repo().emit(Event(
            id="", ts="", event_type="report_download",
            user_id=getattr(request.state, "user_id", None),
            thread_id=meta.thread_id,
            payload_json=json.dumps({
                "report_id": report_id, "kind": meta.kind,
                "format": "original_form", **summary,
            }, ensure_ascii=False)))
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("form download event 실패: %s", e)

    # 확장자는 원본을 따른다(2026-08-27 patch 전환) — .hwp 원본이면 .hwp 그대로.
    _ext = str(summary.get("ext") or "hwp")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition":
                f'attachment; filename="form_{report_id[:8]}.{_ext}"',
            # FE 파일명용 — Content-Disposition 파싱보다 단순.
            "X-File-Ext": _ext,
            "Access-Control-Expose-Headers": "X-File-Ext",
        },
    )


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, request: Request,
                    format: str = "md", fill: int = 1,
                    authorization: Optional[str] = Header(None)):
    """보고서 다운로드. `?format=md|docx` (기본 md). docx 는 pandoc 으로 변환.

    `fill=1`(기본): 서류 초안이면 기입값(`filled_values`)으로 `[확인 필요:]`
    마커를 치환해 내보낸다(미기입 마커는 유지 — 검토자 식별용).
    `fill=0`: 원본 그대로 — FE 문서 패널이 칩 렌더용으로 사용.
    """
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)
    if not meta.blob_uri:
        raise HTTPException(status_code=409, detail="report has no blob (status={!r})".format(meta.status))
    try:
        body = get_blob_store().get(meta.blob_uri)
    except Exception as e:
        # 예외 문자열엔 blob 경로·스토리지 내부가 실린다 — 클라이언트엔 일반
        # 메시지만, 상세는 서버 로그로(내부정보 유출 차단).
        logging.getLogger(__name__).exception(
            "report blob fetch failed id=%s: %s", report_id, e)
        raise HTTPException(status_code=500, detail="report body unavailable")

    # 다운로드 event emit (사용 패턴 분석용)
    try:
        get_events_repo().emit(Event(
            id="", ts="",
            event_type="report_download",
            user_id=getattr(request.state, "user_id", None),
            thread_id=meta.thread_id,
            payload_json=json.dumps({
                "report_id": report_id,
                "kind": meta.kind,
                "title": meta.title,
            }, ensure_ascii=False),
        ))
    except Exception as e:
        logging.getLogger(__name__).warning("download event emit failed: %s", e)

    # 포맷 변환 — .md 가 원본, docx 는 요청 시 변환. 변환 불가 시 .md 로 폴백.
    from src.reports_convert import ConversionUnavailable, convert

    md_text = body.decode("utf-8") if isinstance(body, bytes) else body
    if fill and meta.filled_values:
        from src.doc_fill import apply_filled_values
        try:
            md_text = apply_filled_values(md_text, json.loads(meta.filled_values))
        except ValueError:
            pass  # 손상된 filled_values — 원본 그대로
    try:
        data, mime, ext = convert(md_text, format)
    except ConversionUnavailable as e:
        logging.getLogger(__name__).warning("포맷 변환 폴백(.md): %s", e)
        data, mime, ext = md_text.encode("utf-8"), "text/markdown", "md"

    filename = f"{meta.kind or 'report'}_{report_id[:8]}.{ext}"
    charset = "; charset=utf-8" if ext == "md" else ""
    return Response(
        content=data,
        media_type=f"{mime}{charset}",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── 서면·의견서 초안 (2026-10-01) ────────────────────────────────────────────
#
# 서식(`/documents/from-form`)과 저장·패널·다운로드를 공유하고, **문단 단위 수정**만
# 다르다. 자세한 설계 근거는 `src/brief.py` 머리말.

@router.get("/documents/{report_id}/paragraphs")
def list_document_paragraphs(report_id: str, request: Request):
    """현재 본문의 문단 목록 — FE 와 서버가 **같은 쪼개기**를 쓰게 한다.

    FE 가 자체적으로 나누면 두 쪽 인덱스가 어긋나 엉뚱한 문단을 고치게 된다.
    """
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)

    from src.brief import allowed_citations, split_paragraphs
    from src.persistence import get_blob_store as _bs

    try:
        body = _bs().get(meta.blob_uri) if meta.blob_uri else ""
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="document body unavailable")
    return {
        "report_id": report_id,
        "title": meta.title,
        "paragraphs": split_paragraphs(body),
        "citation_numbers": sorted(allowed_citations(body)),
    }


@router.post("/documents/{report_id}/revise")
async def revise_document_paragraph(report_id: str, request: Request,
                                    authorization: Optional[str] = Header(None)):
    """문단 하나를 지시대로 고쳐 쓴다.

    body: {"index": int, "original_text": str, "instruction": str,
           "replacement": str(선택 — 있으면 LLM 없이 그대로 교체)}
    반환: {"ok", "index", "before", "after", "dropped_citations", "paragraphs"}

    `original_text` 가 그 자리의 현재 내용과 다르면 **409** — 조용히 다른 문단을
    고치느니 거부하고 다시 읽게 한다(낙관적 동시성).
    """
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)

    payload = await request.json()
    try:
        index = int(payload.get("index"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="index 가 필요합니다")
    original_text = str(payload.get("original_text") or "")
    instruction = str(payload.get("instruction") or "").strip()
    manual = payload.get("replacement")
    if not original_text:
        raise HTTPException(status_code=422, detail="original_text 가 필요합니다")
    if manual is None and not instruction:
        raise HTTPException(status_code=422,
                            detail="instruction 또는 replacement 가 필요합니다")

    from src.brief import (ReviseConflict, generate_revision, revise_paragraph,
                           split_paragraphs)
    from src.persistence import get_blob_store as _bs

    try:
        body = _bs().get(meta.blob_uri) if meta.blob_uri else ""
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="document body unavailable")

    if manual is not None:
        replacement = str(manual)
    else:
        # 서면에는 사건 사실관계가 들어간다 — 서식 기입과 같은 레인을 쓴다.
        from src.doc_fill import onprem_configured, onprem_fill

        if not onprem_fill():
            raise HTTPException(
                status_code=503,
                detail=("원내 작성 모델에 연결할 수 없습니다. 문단을 직접 수정해 주세요."
                        if onprem_configured() else
                        "원내 작성 모델이 설정되어 있지 않습니다. 문단을 직접 수정해 주세요."),
            )
        replacement = await generate_revision(
            document=body, paragraph=original_text, instruction=instruction)
        if not replacement:
            raise HTTPException(status_code=422,
                                detail="이 지시로는 문단을 고치지 못했습니다.")

    try:
        new_body, dropped = revise_paragraph(
            body, index=index, original_text=original_text,
            replacement=replacement)
    except ReviseConflict as e:
        raise HTTPException(status_code=409, detail={
            "message": str(e), "current": e.current})

    await asyncio.to_thread(_bs().put, f"{report_id}.md", new_body)
    _log.info("brief revise: %s 문단 %d (인용 제거 %d건)",
              report_id, index, len(dropped))
    return {
        "ok": True,
        "index": index,
        "before": original_text,
        "after": replacement,
        "dropped_citations": dropped,
        "paragraphs": split_paragraphs(new_body),
    }


@router.post("/documents/from-brief")
async def create_document_from_brief(request: Request,
                                     authorization: Optional[str] = Header(None)):
    """채팅 대화에서 **서면·의견서 초안**을 만든다 (2026-10-01).

    body: {"thread_id": str, "title": str(선택)}
    반환: {"report_id", "title", "paragraphs", "citation_numbers"}

    서식(`/documents/from-form`)과 달리 **조문 본문을 받아 오지 않는다** — 근거는
    이미 대화의 인용에 있다. 그래서 openlaw PG·`/articles/bodies` 가 없어도 동작한다.

    초안 본문은 골격 + 대화에서 모은 인용 목록까지만 만든다. 섹션 내용은 사용자가
    문단 수정(`/documents/{id}/revise`)으로 채운다 — 처음부터 LLM 에 통째로
    쓰게 하면 근거 없는 사실관계를 지어내고, 변호사는 그걸 지우는 데 더 오래 걸린다.
    """
    _check_auth(authorization)
    payload = await request.json()
    thread_id = str(payload.get("thread_id") or "").strip()
    if not thread_id:
        raise HTTPException(status_code=422, detail="thread_id 가 필요합니다")

    from src.brief import (allowed_citations, compose_from_thread,
                           skeleton, split_paragraphs)
    from src.persistence import get_report_runs_repo
    from src.persistence.reports_repo import ReportMeta
    from src.persistence.threads_repo import get_threads_repo

    meta_t = await asyncio.to_thread(get_threads_repo().get_meta, thread_id)
    if not meta_t:
        raise HTTPException(status_code=404, detail="thread not found")
    owner = str(meta_t.get("user_id") or "")
    me = str(getattr(request.state, "user_id", "") or "")
    # 거부 기본값(2026-10-03): owner 나 me 가 없으면 **거부**. 종전 AND 조건은
    # 셋 중 하나만 비어도 통과였다.
    if not owner or not me or owner != me:
        raise HTTPException(status_code=403, detail="forbidden")

    title = (str(payload.get("title") or "").strip()
             or f"{meta_t.get('title') or '상담'} 의견서")

    # 대화가 모은 인용 — 번호를 그대로 이어 써야 본문의 [n] 과 맞는다.
    state = await asyncio.to_thread(get_threads_repo().get_state, thread_id)
    cites: list[dict] = []
    seen_no: set[int] = set()
    for st in (state.steps or []):
        for c in (st.get("citations") or []):
            n = c.get("number")
            if not isinstance(n, int) or n in seen_no:
                continue
            seen_no.add(n)
            cites.append(c)
    cites.sort(key=lambda c: c.get("number") or 0)

    # 대화와 인용으로 **채워진** 초안을 만든다(2026-10-02). 종전엔 골격만 줬는데
    # "그냥 서식만 나온다"는 지적을 받았다 — 맞다. 재료는 이미 이 스레드에 있다.
    if state.messages:
        body = compose_from_thread(state.messages, cites, title=title)
    else:
        body = skeleton(title)
    # 면책 결정적 부착(2026-10-03) — 가장 민감한 산출물(의견서)만 면책 없이 Word 로
    # 나가고 있었다. 심층 보고서는 `report_pipeline` 이 처음부터 붙였다.
    from src.legal import append_report_disclaimer

    body = append_report_disclaimer(body)

    report_id = f"doc_{uuid.uuid4().hex[:16]}"
    blob_uri = await asyncio.to_thread(
        get_blob_store().put, f"{report_id}.md", body)
    await asyncio.to_thread(get_reports_repo().create, ReportMeta(
        id=report_id, thread_id=thread_id, mode="deep", kind="doc",
        status="done", blob_uri=blob_uri, title=title,
        summary="서면·의견서 초안",
        citations_json=json.dumps(cites, ensure_ascii=False),
        completed_at=None, filled_values="{}",
    ))
    runs = get_report_runs_repo()
    idem = f"rpt_brief_{report_id}"
    await asyncio.to_thread(
        lambda: runs.acquire(idempotency_key=idem, thread_id=thread_id,
                             user_id=me, prompt=f"[서면] {title}",
                             purpose="document_draft"))
    await asyncio.to_thread(
        lambda: runs.finish(idem, status="completed", report_id=report_id))
    _log.info("from-brief: 초안 생성 %s (%s, 인용 %d건)",
              report_id, title[:30], len(cites))
    return {
        "report_id": report_id,
        "title": title,
        "paragraphs": split_paragraphs(body),
        "citation_numbers": sorted(allowed_citations(body)),
    }


@router.post("/documents/{report_id}/polish")
async def polish_document(report_id: str, request: Request,
                          authorization: Optional[str] = Header(None)):
    """초안을 **보고서체로 다듬는다** (2026-10-02).

    body: {"sections": ["사실관계", ...]}(선택 — 미지정이면 전 절)
    반환: {"ok", "polished": [절 이름], "skipped": [...], "dropped_citations": [n],
           "paragraphs": [...]}

    다듬기는 **쓰기가 아니다** — 주어진 절의 내용을 논리 순서로 재배열하고
    격식체로 고칠 뿐이다. 새 인용 번호는 기계적으로 제거하고 알린다.
    실패한 절은 원문을 그대로 둔다(부분 성공을 허용) — 전부 아니면 전무로 하면
    긴 문서에서 한 절만 실패해도 아무것도 못 얻는다.
    """
    _check_auth(authorization)
    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    assert_report_access(meta, request)

    from src.brief import (allowed_citations, join_sections, polish_section,
                           split_paragraphs, split_sections)
    from src.doc_fill import onprem_configured, onprem_fill
    from src.persistence import get_blob_store as _bs

    payload = await request.json() if await request.body() else {}
    want = {str(x) for x in (payload.get("sections") or [])}

    try:
        body = _bs().get(meta.blob_uri) if meta.blob_uri else ""
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="document body unavailable")
    if not body.strip():
        raise HTTPException(status_code=422, detail="본문이 비어 있습니다")

    # 서면에는 사건 사실관계가 들어간다 — 서식 기입과 같은 레인을 쓴다.
    if not onprem_fill():
        raise HTTPException(
            status_code=503,
            detail=("원내 작성 모델에 연결할 수 없습니다. 문단을 직접 수정해 주세요."
                    if onprem_configured() else
                    "원내 작성 모델이 설정되어 있지 않습니다. 문단을 직접 수정해 주세요."),
        )

    allowed = allowed_citations(body)
    sections = split_sections(body)
    out: list[tuple[str, str]] = []
    polished: list[str] = []
    skipped: list[str] = []
    dropped_all: list[int] = []

    for title, content in sections:
        if not title or (want and title not in want):
            out.append((title, content))
            continue
        res = await polish_section(title, content, allowed=allowed)
        if res is None:
            skipped.append(title)
            out.append((title, content))
            continue
        text, dropped = res
        polished.append(title)
        dropped_all.extend(n for n in dropped if n not in dropped_all)
        out.append((title, text))

    if not polished:
        raise HTTPException(status_code=422,
                            detail="다듬을 수 있는 절이 없었습니다.")

    new_body = join_sections(out)
    await asyncio.to_thread(_bs().put, f"{report_id}.md", new_body)
    _log.info("brief polish: %s %d개 절 (스킵 %d, 인용 제거 %d)",
              report_id, len(polished), len(skipped), len(dropped_all))
    return {
        "ok": True,
        "polished": polished,
        "skipped": skipped,
        "dropped_citations": dropped_all,
        "paragraphs": split_paragraphs(new_body),
    }
