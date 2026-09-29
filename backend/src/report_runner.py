"""자체 보고서 잡러너 — ADR-0001 Phase 3 (`agent_report` StateGraph 대체 PoC).

langgraph `build_report_graph`(entry_check→decompose→gather→synthesize 3노드)를
평범한 async 함수 체인으로 이식. 진입은 `POST /reports`(routes/reports.py) —
멱등락(`report_runs_repo.acquire`)을 라우트에서 잡고, 본 러너를 asyncio task 로
백그라운드 실행한다.

parent 맥락 상속: langgraph 경로의 loopback HTTP(`/threads/{id}/state`) 대신
**threads_repo 직조회** — 자체 /chat 루프로 쌓인 대화·steps·selected_law_keys 를
그대로 쓴다(같은 thread_id). langgraph 경로로만 대화한 thread 는 비어 있음 —
새 경로는 chat·report 쌍으로 함께 전환(Phase 4)한다는 전제.

재사용(프레임워크 무관 코어): decompose_queries · gather_for_report ·
synthesize_and_persist(writer 27B + 동시성 세마포어 + grounding + persist) ·
report_runs_repo 멱등락 · notify_report_ready.

진행 노출: steps 를 threads_repo 에 merge — FE 는 thread 상태/보고서 목록
폴링으로 확인(라이브 SSE 구독은 Phase 4 FE 계약에서 결정). 완료 시 '## 개요'
를 AIMessage 로 thread 에 append(채팅 답변 계약 유지) + 이메일 첨부 발송.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional
from uuid import uuid4

from langchain_core.messages import AIMessage

from src.observability import usage_context
from src.persistence import get_report_runs_repo
from src.persistence.threads_repo import get_threads_repo
from src.steps import step_done, step_error, step_start
from src.tools.reports import ReportPersistError

_log = logging.getLogger(__name__)

# 프로세스 내 실행 중 잡 추적 — 종료 대기·중복 spawn 방지(멱등락과 별개 belt).
_active_jobs: dict[str, asyncio.Task] = {}
# 시작 순서(monotonic) — FE 큐 위치 안내("앞에 N건") 용. 프로세스 로컬로 충분
# (멀티 워커 금지 불변식).
_job_started_at: dict[str, float] = {}
# thread_id → 실행 중 잡 수. 채팅 경로가 "이 thread 에 보고서 작성 중?"을 O(1)
# 로 조회(진행 배지·컨텍스트 주입). 단일 워커 불변식이라 프로세스 로컬로 충분.
_active_by_thread: dict[str, int] = {}
# 사용자 [중단] 버튼으로 cancel 한 키 — CancelledError 핸들러가 "사용자 중단"과
# "프로세스 종료(배포·재시작)"를 구분하는 유일한 근거. 종료로 인한 취소를
# cancelled 로 마감하면 orphan 재기동 대상에서 빠져 보고서가 조용히 증발한다
# (실측 2026-09-15: 23분 진행 보고서가 배포 재시작과 겹쳐 유실).
_user_cancelled: set[str] = set()


def is_report_running(thread_id: str) -> bool:
    """이 thread 에 실행 중 보고서 잡이 있는가 — 채팅 진행 배지/컨텍스트용."""
    return _active_by_thread.get(thread_id, 0) > 0


def _upstream_maintenance() -> bool:
    """새벽 갱신 등 정비 구간인가 — 보고서를 죽이지 않고 *대기*시키기 위한 판정.

    셋 중 하나면 True(전부 best-effort, 판정 실패는 False):
    1) medi-back 점검 모드(수동/일일 스케줄) 활성
    2) DGX 갱신 신호 — /monitor/status 의 chat_vllm.maintenance (BM25 재빌드로
       27B 를 내리는 구간에만 true, openlaw-etl chat_maintenance.json)
    3) writer(27B vLLM) 자체 미도달 — 신호가 없어도 실제로 내려가 있으면 대기
    """
    try:
        from src.maintenance import is_active
        if is_active():
            return True
    except Exception:  # noqa: BLE001
        pass
    import os as _os, json as _json, urllib.request as _rq
    base = (_os.getenv("RAG_SEARCH_API_URL") or "").rstrip("/")
    if base:
        try:
            with _rq.urlopen(f"{base}/monitor/status", timeout=3) as r:
                d = _json.load(r)
            if bool((d.get("chat_vllm") or {}).get("maintenance")):
                return True
        except Exception:  # noqa: BLE001
            pass
    wbase = (_os.getenv("REPORT_WRITER_BASE_URL") or "").rstrip("/")
    if wbase:
        try:
            _rq.urlopen(f"{wbase}/models", timeout=4).read(64)
        except Exception:  # noqa: BLE001
            return True  # writer 다운 — 정비로 간주하고 대기
    return False


async def _await_service_window(repo, thread_id: str, step_id: str | None = None) -> None:
    """정비 구간이면 끝날 때까지 대기(기본 최대 45분) — 보고서 잡 pause/resume.

    step_id 가 있으면 진행 라벨을 갱신해 사용자에게 '갱신 대기 중'을 노출
    (프런트 사이드 카드가 progress_message 를 표시).
    """
    try:
        max_wait = int((os.getenv("REPORT_MAINT_WAIT_MAX_S") or "").strip() or "2700")
    except ValueError:
        max_wait = 2700
    waited = 0
    notified = False
    # ⚠️ _upstream_maintenance 는 동기 urllib(타임아웃 3+4초) — 이벤트 루프에서
    # 직접 부르면 20초 주기마다 최대 7초씩 서버 전체가 굳는다. 정비 구간이 최대
    # 45분이라 그동안 계속 반복됐다(2026-08-04 감사 C-3).
    while await asyncio.to_thread(_upstream_maintenance) and waited < max_wait:
        if step_id and not notified:
            try:
                repo.merge_steps(thread_id, [{
                    "id": step_id,
                    "progress_message": "새벽 데이터 갱신 중 — 끝나면 자동 재개됩니다",
                }])
            except Exception:  # noqa: BLE001
                pass
            notified = True
        _log.info("report 대기 — 정비/갱신 구간 (%ds 경과)", waited)
        await asyncio.sleep(20)
        waited += 20
    if notified:
        try:
            repo.merge_steps(thread_id, [{
                "id": step_id, "progress_message": "재개됨 — 작업 계속",
            }])
        except Exception:  # noqa: BLE001
            pass


def resume_orphan_runs() -> int:
    """재시작으로 죽은 'running' run 재기동 — 배포/크래시 후 보고서 유실 방지.

    프로세스가 죽으면 asyncio 잡은 사라지고 run 은 running 으로 남는다
    (CancelledError 는 Exception 이 아니라 failed 마감도 안 됨). 기동 시 running
    잔재를 같은 멱등키로 reclaim(acquire stale_after_s=0)해 이어서 생성한다 —
    thread 상태(질문·선택법령)는 threads_repo 영속이라 재현 가능. FE 는 기존
    폴링/새로고침 복원(GET /reports/runs/active)으로 그대로 이어받는다.
    (실측 2026-07-24: 배포마다 진행 중 보고서가 조용히 증발 → "생성 실패/무소식"
    피드백의 한 축.)
    """
    runs = get_report_runs_repo()
    try:
        orphans = runs.list_running()
    except Exception as e:  # noqa: BLE001 — 재기동 실패가 부팅을 막으면 안 됨
        _log.warning("orphan report 조회 실패: %s", e)
        return 0
    n = 0
    for r in orphans:
        if r.idempotency_key in _active_jobs:
            continue  # 이 프로세스가 이미 실행 중(정상 경로)
        try:
            acquired, _existing = runs.acquire(
                idempotency_key=r.idempotency_key, thread_id=r.thread_id,
                user_id=str(r.user_id or ""), stale_after_s=0)
            if not acquired:
                continue
            uid = str(r.user_id or "")
            # user_id 는 NextAuth JWT sub(UUID)라 이메일 형태가 아니다 — 종전의
            # `uid if "@" in uid else None` 은 복원 잡에서 **항상 None** 이 되어
            # 완료 메일이 영영 안 나갔다(2026-08-11 발견, §6 이메일 사고 동계열).
            # users 테이블에서 이메일을 조회해 채운다(실패 시 미발송 유지).
            user_email = uid if "@" in uid else None
            if user_email is None and uid:
                try:
                    from src.persistence import get_users_repo
                    u = get_users_repo().get(uid)
                    user_email = getattr(u, "email", None) if u else None
                except Exception as e:  # noqa: BLE001 — 조회 실패가 복원을 막으면 안 됨
                    _log.warning("orphan report 이메일 조회 실패 uid=%s: %s", uid, e)
            spawn_report_job(
                thread_id=r.thread_id, user_id=uid,
                idempotency_key=r.idempotency_key,
                user_email=user_email,
                # run 에 저장된 주제·목적으로 정확 복원(재설계 2026-07-24).
                prompt=r.prompt, purpose=r.purpose,
            )
            n += 1
        except Exception as e:  # noqa: BLE001 — 한 건 실패가 나머지를 막으면 안 됨
            _log.warning("orphan report 재기동 실패 idem=%s: %s",
                         r.idempotency_key, e)
    if n:
        _log.info("orphan report %d건 재기동(재시작 복원)", n)
    return n


def queue_ahead(idempotency_key: str) -> int | None:
    """이 잡보다 먼저 시작해 아직 실행 중인 잡 수. 미추적(재시작 등)이면 None."""
    t = _job_started_at.get(idempotency_key)
    if t is None:
        return None
    return sum(1 for k, v in _job_started_at.items()
               if k != idempotency_key and v < t)


def cancel_run(idempotency_key: str) -> bool:
    """진행 중 run 중단(2026-09-02) — 사용자 [중단] 버튼.

    태스크가 이 프로세스에 있으면 cancel() — CancelledError 핸들러가 DB 마감
    까지 한다. 태스크가 없는데 DB 가 running 이면(재시작 직후 등) DB 만
    cancelled 로 마감해 orphan 재기동을 막는다. 반환: 중단 성립 여부.
    """
    task = _active_jobs.get(idempotency_key)
    if task is not None and not task.done():
        _user_cancelled.add(idempotency_key)
        task.cancel()
        return True
    runs = get_report_runs_repo()
    run = runs.get(idempotency_key)
    if run and run.status == "running":
        runs.finish(idempotency_key, status="cancelled", error=None)
        return True
    return False


def spawn_report_job(
    *,
    thread_id: str,
    user_id: str,
    idempotency_key: str,
    user_email: Optional[str] = None,
    prompt: Optional[str] = None,
    purpose: Optional[str] = None,
    form_article_key: Optional[str] = None,
) -> asyncio.Task:
    """백그라운드 잡 시작 — 호출자(라우트)가 이미 멱등락을 acquire 한 상태여야 함.

    `prompt`: next_steps 클릭 문구 — 있으면 human 메시지로 thread 에 append 후
    보고서 주제로 사용(구경로에서 input.messages 로 실어 보내던 계약 대응).
    """
    task = asyncio.create_task(
        _run_report_job(
            thread_id=thread_id, user_id=user_id,
            idempotency_key=idempotency_key, user_email=user_email,
            prompt=prompt,
            purpose=purpose,
            form_article_key=form_article_key,
        ),
        name=f"report_{idempotency_key}",
    )
    import time as _time

    _active_jobs[idempotency_key] = task
    _job_started_at[idempotency_key] = _time.monotonic()
    _active_by_thread[thread_id] = _active_by_thread.get(thread_id, 0) + 1

    def _cleanup(_t) -> None:
        _active_jobs.pop(idempotency_key, None)
        _job_started_at.pop(idempotency_key, None)
        _user_cancelled.discard(idempotency_key)
        n =_active_by_thread.get(thread_id, 1) - 1
        if n <= 0:
            _active_by_thread.pop(thread_id, None)
        else:
            _active_by_thread[thread_id] = n

    task.add_done_callback(_cleanup)
    return task


async def _run_report_job(
    *,
    thread_id: str,
    user_id: str,
    idempotency_key: str,
    user_email: Optional[str],
    prompt: Optional[str] = None,
    purpose: Optional[str] = None,
    form_article_key: Optional[str] = None,
) -> None:
    """decompose → gather → synthesize — build_report_graph 3노드와 동등.

    실패는 report_runs.finish(failed) 로 마감 + error step. 예외가 위로 새지
    않게 전부 여기서 흡수(백그라운드 task 의 조용한 죽음 방지 — CLAUDE.md §9).
    """
    runs = get_report_runs_repo()
    repo = get_threads_repo()
    ctx_cfg = {  # _persist_report/이메일용 명시 config (ensure_config 대체)
        "thread_id": thread_id,
        "parent_thread_id": thread_id,  # 단일 thread — chat thread 가 곧 부모
        "user_id": user_id,
        "run_id": f"job_{uuid4().hex[:12]}",
    }
    # 백그라운드 잡의 LLM 토큰 귀속(2026-08-05). 이 잡은 요청 태스크와 수명이
    # 달라 요청 컨텍스트를 믿을 수 없다 — 잡 안에서 다시 심는다.
    usage_context.bind(user_id=user_id, thread_id=thread_id,
                       run_id=ctx_cfg["run_id"])
    try:
        # 재설계(2026-07-24): 트리거 프롬프트를 **대화록에 append 하지 않는다** —
        # 채팅 supervisor 가 이를 "답해야 할 질문"으로 읽어 '버튼 안내' 재발화 등
        # 오염을 일으켰다. 주제는 run(prompt 컬럼)과 이 변수로만 전달(PII 스크럽 유지).
        report_topic: Optional[str] = None
        if prompt and prompt.strip():
            from src.guardrail.gate import scrub_input

            try:
                report_topic, _found = scrub_input(prompt.strip())
            except Exception:  # noqa: BLE001 — 게이트 오류가 보고서를 막으면 안 됨
                report_topic = prompt.strip()

        state = repo.get_state(thread_id)
        tool_state = state.as_tool_state()
        # ⚠️ 아래 report_* step 은 **채팅 턴에 바인딩하지 않는다**(`state=None`).
        # tool_state 를 넘기면 resolve_turn_context 가 *마지막 human 메시지*를
        # source_message_id 로 박아, 프런트 filterTurnSteps 가 보고서 진행 step 을
        # 그 채팅 턴의 step 목록에 끼워 넣었다(채팅↔보고서 완전 분리 요구,
        # 2026-07-25). 보고서 진행은 `/reports/runs/{key}` 폴링 + 우측 패널 담당.

        from src.report_pipeline import (
            decompose_and_classify,
            extract_report_context,
            gather_for_report,
            synthesize_and_persist,
        )

        # ── decompose (노드 2) ────────────────────────────────────
        rctx = extract_report_context(tool_state)
        if report_topic:
            # 명시 주제(트리거 프롬프트)가 대화 마지막 질문보다 우선.
            rctx["user_query"] = report_topic
        sid, start = step_start(
            "쿼리 분해 중", tool_name="report_decompose",
            input_preview=(rctx["user_query"] or "")[:80], state=None,
        )
        repo.merge_steps(thread_id, [start])
        queries, _inferred = await decompose_and_classify(
            rctx["user_query"], rctx["provisional_answer"], purpose=purpose)
        if not (purpose or "").strip() and _inferred:
            # 트리거에 목적이 없으면 서버 판정을 채택(2026-08-25) — 목적별
            # 분량·관점이 실제로 적용되려면 누군가는 정해야 한다(운영 93% 미지정).
            purpose = _inferred
            _log.info("report purpose 판정: %s (트리거 미지정)", purpose)
        repo.merge_steps(thread_id, [step_done(
            sid, output_preview=f"{len(queries)}개 쿼리 생성")])

        # ── gather (노드 3) ───────────────────────────────────────
        sid, start = step_start(
            "자료 수집 중 · 웹 + 법령", tool_name="report_gather",
            input_preview=f"{len(queries)}개 쿼리 병렬 검색", state=None,
        )
        repo.merge_steps(thread_id, [start])
        await _await_service_window(repo, thread_id, sid)  # 새벽 갱신이면 대기 후 재개
        # 채팅이 근거를 얻은 종별을 이어받는다 — 보고서가 "주어진 대화를 바탕으로"
        # 생성되려면 질의어뿐 아니라 **근거 코퍼스**도 계승해야 한다(2026-08-25).
        _inherited = rctx.get("inherited_kinds") or []
        if _inherited:
            _log.info("report: 채팅 근거 코퍼스 계승 %s", _inherited)
        gathered = await gather_for_report(
            queries, event_ctx={"thread_id": thread_id, "user_id": user_id},
            inherited_kinds=_inherited)
        if not (gathered["web_ok"] or gathered["rag_ok"]):
            repo.merge_steps(thread_id, [step_error(
                sid, message="관련 자료를 찾지 못했습니다. 질문을 더 "
                             "구체화해 다시 시도해주세요.")])
            runs.finish(idempotency_key, run_id=ctx_cfg["run_id"], status="failed",
                        error="수집 실패: web/rag 결과 없음")
            return
        # ── 근거 충분성 게이트(2026-07-25) ────────────────────────
        # 종전 가드는 "1건이라도 있으면 통과" 였다. 실측 사고: 검색 API 간헐
        # 실패 + 웹 쿼터 사망이 겹친 턴에서 **근거 2건**으로 통과해 3.9k자
        # 보고서가 '완료'로 배달됐다(같은 주제 채팅 누적 답변은 19k자 —
        # 사용자가 "왜 보고서가 더 짧냐"고 지적). 근거가 이만큼 얇으면
        # rp 프롬프트의 "정확성 > 충실함" 원칙상 writer 는 분량을 채우지 않는
        # 게 맞고(날조 금지), 따라서 **얇은 보고서를 완성품으로 내보내지 않는
        # 것**이 옳다. 원인이 대개 일시적이므로 1회 재수집 후 판정.
        _min_cites = max(1, int((os.getenv("REPORT_MIN_CITATIONS") or "").strip() or "6"))
        _n = len(gathered["web"]) + len(gathered["rag"])
        if _n < _min_cites:
            _log.warning(
                "report gather 근거 부족(%d < %d) — 1회 재수집", _n, _min_cites)
            repo.merge_steps(thread_id, [step_start(
                f"근거 부족({_n}건) — 재수집 중", tool_name="report_gather",
                input_preview="충분성 게이트 재시도", state=None)[1]])
            retry = await gather_for_report(
                queries, event_ctx={"thread_id": thread_id, "user_id": user_id},
                inherited_kinds=_inherited)
            if (len(retry["web"]) + len(retry["rag"])) > _n:
                gathered = retry
                _n = len(gathered["web"]) + len(gathered["rag"])
        if _n < _min_cites:
            # 여기서 멈추는 게 얇은 완성품보다 낫다 — 사용자는 수 분을 기다린
            # 뒤 '심층 보고서'라는 이름의 빈약한 문서를 받게 되고, 그 얇음이
            # 근거 부재 때문임을 알 수 없다. 실패로 명시하고 사유를 알린다.
            msg = (f"확보된 근거가 {_n}건뿐이어서 심층 보고서를 작성하지 "
                   "않았습니다. 검색이 일시 불안정했을 수 있으니 잠시 후 "
                   "다시 시도하거나, 주제를 좁혀 요청해주세요.")
            repo.merge_steps(thread_id, [step_error(sid, message=msg)])
            runs.finish(idempotency_key, run_id=ctx_cfg["run_id"], status="failed",
                        error=f"수집 근거 부족: {_n}건 < {_min_cites}건")
            return
        repo.merge_steps(thread_id, [step_done(
            sid, output_preview=(
                f"web {len(gathered['web'])}건 · 법령 {len(gathered['rag'])}건"
            ))])

        # ── synthesize (노드 4) ───────────────────────────────────
        sid, start = step_start(
            "보고서 작성 중", tool_name="report_writer",
            input_preview=f"{len(gathered['web']) + len(gathered['rag'])}건 자료 통합",
            state=None,
        )
        repo.merge_steps(thread_id, [start])
        # 서류 초안 모드 — 기관 서식 구조 자산(스킬)을 rag 맨 앞에 주입(2026-08-24).
        # 낮은 번호([1][2])를 받아 writer 예산에서 절대 잘리지 않게 한다.
        rag_results = gathered["rag"]
        if (purpose or "").strip() == "document_draft":
            from src.report_pipeline import draft_form_assets, pinned_form_asset
            assets = draft_form_assets(
                rctx.get("user_query") or "", rctx.get("provisional_answer") or "")
            if assets:
                _log.info("document_draft: 기관 서식 자산 %d건 주입", len(assets))
                rag_results = assets + rag_results
            # 사용자가 고른 서식은 **가장 앞**(= 근거 [1]) — writer 가 그 구조를
            # 근거로 쓰고, 다운로드 시 pick_form_citation 도 같은 것을 고른다.
            pinned = await asyncio.to_thread(pinned_form_asset,
                                             form_article_key or "")
            if pinned:
                rag_results = pinned + rag_results
        payload = {
            "purpose": purpose,
            "web_results": gathered["web"],
            "rag_results": rag_results,
            "conversation_context": rctx,
            "queries": queries,
        }
        await _await_service_window(repo, thread_id, sid)  # writer(27B) 다운 구간이면 대기
        try:
            try:
                report_id, overview, used_cites = await synthesize_and_persist(
                    payload, tool_state, {"configurable": ctx_cfg})
            except Exception as first_err:  # noqa: BLE001 — 정비로 죽었으면 대기 후 1회 재시도
                if not await asyncio.to_thread(_upstream_maintenance):
                    raise
                _log.warning("writer 실패가 정비 구간과 겹침 — 재개 대기 후 재시도: %s", first_err)
                await _await_service_window(repo, thread_id, sid)
                report_id, overview, used_cites = await synthesize_and_persist(
                    payload, tool_state, {"configurable": ctx_cfg})
        except ReportPersistError as e:
            # 합성은 성공했는데 **저장만** 실패 — writer 오류와 구분해야 운영이
            # 모델 서버가 아니라 GCS/PG 를 본다(2026-08-04 감사 H-11).
            _log.exception("report 영속 실패 idem=%s: %s", idempotency_key, e)
            runs.finish(idempotency_key, run_id=ctx_cfg["run_id"], status="failed",
                        error=f"보고서 저장 실패({e})")
            repo.merge_steps(thread_id, [step_error(
                sid, message="보고서 저장에 실패했습니다. 잠시 후 다시 시도해주세요.")])
            return
        except Exception as e:  # noqa: BLE001
            # error 는 /reports/runs 폴링으로 프런트에 그대로 노출 — 예외 문자열
            # (URL·모델명·스택)은 로그로만, 저장은 유형명까지만.
            _log.exception("report writer 실패 idem=%s: %s", idempotency_key, e)
            runs.finish(idempotency_key, run_id=ctx_cfg["run_id"], status="failed",
                        error=f"writer 오류({type(e).__name__})")
            repo.merge_steps(thread_id, [step_error(
                sid, message="보고서 작성 중 오류가 발생했습니다. "
                             "잠시 후 다시 시도해주세요.")])
            return
        if not report_id:
            runs.finish(idempotency_key, run_id=ctx_cfg["run_id"], status="failed", error="보고서 영속 실패")
            repo.merge_steps(thread_id, [step_error(
                sid, message="보고서 저장에 실패했습니다. 잠시 후 다시 시도해주세요.")])
            return

        runs.finish(idempotency_key, run_id=ctx_cfg["run_id"], status="completed", report_id=report_id)
        repo.merge_steps(thread_id, [step_done(
            sid, output_preview="보고서 작성 완료", citations=used_cites or None)])

        # 채팅↔보고서 완전 분리(2026-07-25 사용자 요구): 완료 개요를 **채팅
        # 메시지로 append 하지 않는다**. 개요는 reports 레코드의 `summary` 로
        # 남고(사이드바 목록·우측 패널·미리보기·이메일이 소비), 채팅 대화록에는
        # 보고서 흔적이 남지 않는다.
        #   · 부수 효과(의도됨): 구 구현은 append 순서 보존을 위해
        #     `hold_turn_lock(thread_id)` 을 잡아 **보고서 잡이 채팅 턴을 기다렸다**.
        #     이제 그 결합이 없어 진짜 병렬이다.
        #   · FE 는 기존 `kind:"report_overview"` 턴 렌더를 과거 메시지 호환용으로
        #     유지하고, 완료 신호는 폴링(`/reports/runs/{key}`) → 토스트·브라우저
        #     알림·사이드바 갱신으로 받는다.
        #   · 계약: docs/contracts/frontend_chat_v2.md §4.

        # 완료 이메일(.md 첨부) — best-effort. SMTP 미설정(dev)=stub.
        # 발송 결과는 events(report_email) 로 영속화(2026-08-21) — 컨테이너
        # stdout 에 앱 로그가 안 흘러 발송 여부를 사후 확인할 수단이 없었다.
        # /admin/reports 목록이 이 이벤트를 조인해 발송 상태를 보여준다.
        if user_email:
            try:
                await asyncio.to_thread(
                    _send_report_email, user_email, thread_id, report_id)
                _emit_report_email_event(
                    user_id=user_id, thread_id=thread_id,
                    report_id=report_id, ok=True)
            except Exception as e:  # noqa: BLE001
                # WARNING + ops 알림 — INFO 한 줄로 소멸해 발송 실패가 관측
                # 불가였다(2026-08-11 발견). 5~40분 잡의 완료 통보 실패는 사고다.
                _log.warning("보고서 완료 이메일 발송 실패 report=%s to=%s: %s",
                             report_id, user_email, e)
                _emit_report_email_event(
                    user_id=user_id, thread_id=thread_id,
                    report_id=report_id, ok=False, error=type(e).__name__)
                try:
                    from src.observability.alerts import send_ops_alert
                    await asyncio.to_thread(
                        send_ops_alert,
                        "보고서 완료 메일 발송 실패",
                        f"report={report_id} to={user_email}: {e}",
                        dedup_key="report_email_fail")
                except Exception:  # noqa: BLE001 — 알림 실패는 무해
                    _log.debug("send_ops_alert failed", exc_info=True)
        _log.info("report job done idem=%s report=%s", idempotency_key, report_id)
    except asyncio.CancelledError:
        if idempotency_key not in _user_cancelled:
            # 프로세스 종료(배포·재시작)로 인한 취소 — run 을 running 으로 남겨
            # 다음 부팅의 resume_orphan_runs 가 같은 키로 재기동하게 한다.
            _log.warning("report 잡 종료 중단 idem=%s — 재기동 대상으로 유지",
                         idempotency_key)
            raise
        _user_cancelled.discard(idempotency_key)
        # 사용자 중단(cancel_run) — 실패가 아니다. 부분 산출물은 저장하지 않고
        # (synthesize 완료 전이므로 report_id 없음), run 만 cancelled 마감.
        # 진행 중이던 writer 스트림은 태스크 취소로 함께 닫혀 GPU 가 풀린다.
        _log.info("report 중단됨 idem=%s (사용자 요청)", idempotency_key)
        try:
            runs.finish(idempotency_key, run_id=ctx_cfg["run_id"],
                        status="cancelled", error=None)
        except Exception:  # noqa: BLE001 — 마감 실패해도 취소는 취소
            _log.warning("cancelled 마감 실패 idem=%s", idempotency_key,
                         exc_info=True)
        return  # 흡수 — task 는 정상 종료(정리는 done_callback 수행)
    except Exception as e:  # noqa: BLE001 — 마지막 안전망: 락을 failed 로 마감
        _log.exception("report job crashed idem=%s: %s", idempotency_key, e)
        try:
            # 폴링 노출 필드 — 예외 문자열 대신 유형명만(상세는 위 exception 로그).
            runs.finish(idempotency_key, run_id=ctx_cfg["run_id"], status="failed",
                        error=f"runner 오류({type(e).__name__})")
        except Exception:  # noqa: BLE001
            _log.warning("report job finish(failed) 마감도 실패 idem=%s", idempotency_key)


def _emit_report_email_event(*, user_id: str, thread_id: str, report_id: str,
                             ok: bool, error: str | None = None) -> None:
    """발송 시도 결과를 events(report_email) 로 기록 — best-effort(실패 무해).

    run_id 컬럼에 report_id 를 실어 /admin/reports 가 조인한다. error 는
    예외 유형명만(수신 주소·SMTP 상세는 로그 몫 — 이벤트에 PII 비적재).
    """
    try:
        import json as _json

        from src.persistence import get_events_repo
        from src.persistence.events_repo import Event as _Ev
        payload = {"ok": ok}
        if error:
            payload["error"] = error
        get_events_repo().emit(_Ev(
            id="", ts="", event_type="report_email",
            user_id=user_id, thread_id=thread_id, run_id=report_id,
            payload_json=_json.dumps(payload, ensure_ascii=False)))
    except Exception:  # noqa: BLE001 — 기록 실패가 발송 흐름을 막으면 안 됨
        _log.debug("report_email event emit failed", exc_info=True)


def _send_report_email(email: str, thread_id: str, report_id: str) -> None:
    """`src/app.py:_send_report_email` 와 동등 — app import(=그래프 빌드) 회피용 사본.

    Phase 5 컷오버 때 app.py 쪽을 지우고 이쪽만 남긴다.
    """
    from src.observability.notifications import notify_report_ready
    # 사용자 수신 설정(기본 ON) — opt-out 이면 발송 생략. (이 함수 스코프엔
    # email 만 있으므로 email 로 조회.)
    try:
        from src.persistence import get_users_repo
        u = get_users_repo().get_by_email(email) if email else None
        if u is not None and not getattr(u, "report_email_opt_in", True):
            _log.info("report email opt-out — 발송 생략 (email=%s)", email)
            return
    except Exception:  # noqa: BLE001 — 설정 조회 실패 시 기존 동작(발송)
        pass
    from src.persistence import get_blob_store, get_reports_repo

    meta = get_reports_repo().get(report_id)
    body = None
    if meta and meta.blob_uri:
        try:
            body = get_blob_store().get(meta.blob_uri)
        except Exception:  # noqa: BLE001 — 본문 없이도 알림은 보냄
            body = None
    notify_report_ready(email=email, thread_id=str(thread_id or ""),
                        report_id=report_id, report_md=body,
                        title=(meta.title if meta else None),
                        # kind="doc" = 서류 초안 — 메일 문구도 분리(2026-08-27).
                        is_document=(getattr(meta, "kind", "") == "doc"))


def has_capacity() -> bool:
    """동시 잡 상한(REPORT_MAX_CONCURRENCY 는 writer 세마포어가 지키므로,
    여기선 큐 폭주만 방지하는 프로세스 내 상한)."""
    try:
        cap = int((os.getenv("REPORT_JOB_MAX_PENDING") or "").strip() or "4")
    except ValueError:
        cap = 4
    return len(_active_jobs) < cap
