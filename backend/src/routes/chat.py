"""POST /chat — 자체 SSE 채팅 엔드포인트 (ADR-0001 Phase 1 PoC).

langgraph native `/threads/{tid}/runs/stream` 을 대체하는 병행 경로. 기존
langgraph 경로는 무접촉 — 검증(bench 동등성) 후 Phase 4 에서 프런트가 이쪽으로
전환한다.

요청 (JSON):
    {
      "message": "질문 텍스트",                    # 필수
      "thread_id": "уuid",                          # 선택 — 없으면 새 thread 생성
      "selected_law_keys": ["009514_0006001", ...], # 선택 — null=미변경, []=해제
      "model": "anthropic:claude-sonnet-4-6"        # 선택 — dev/벤치용 오버라이드
    }

응답: `text/event-stream`. 각 이벤트는 `event: <type>` + `data: <json>`.
    meta / token / tool_progress / step_lifecycle / steps / clarify / error / done
페이로드 스키마는 langgraph custom 채널(tool_progress·step_lifecycle)·Step dict
와 동일 — FE 파서 재사용 (ADR-0001-migration-plan §2 "자체 프로토콜, 페이로드
무변경").

인증·쿼터·rate limit 은 app 레벨 HTTP 미들웨어가 처리 (QuotaMiddleware 검사
경로에 /chat 포함).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.guardrail.gate import PiiScanIncomplete

_log = logging.getLogger(__name__)

router = APIRouter()

_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 자동 제목 프롬프트 — 구 routes/auto_title.py(loopback 방식, Phase 5 삭제)에서 이관.
_TITLE_PROMPT = (
    "다음 사용자 질의를 5~15자 한국어로 요약해 thread 제목을 만들어주세요. "
    "응답은 제목만, 따옴표·마침표·이모지 없이.\n\n"
    "예시:\n"
    "- 의료기기 광고 사전심의 → 광고 사전심의\n"
    "- 의료기기법 제25조 인용해줘 → 제25조 광고심의\n"
    "- 식약처 GMP 절차가 어떻게 바뀌었나요? → GMP 절차 변경\n\n"
    "질의: {query}\n\n"
    "제목:"
)


def _max_input_chars() -> int:
    """채팅 1턴 입력 상한(문자). 사용자가 문서를 붙여넣는 사용을 전제로 잡는다.

    모델 한계와는 무관하다 — 채팅 모델 컨텍스트는 1M 이고 대화 압축 트리거도
    24,000토큰(≈72,000자)이다. 예전 8,000자는 그 여력에 비해 지나치게 작아
    문서를 붙여넣으면 422 로 튕겼다(2026-08-04 사용자 리포트).

    상한을 정하는 것은 **PII 게이트 처리량**이지 모델이 아니다. 한때 12,000자까지
    낮춰 잡았는데, 그건 NER 이 왕복 N회 구조라 긴 입력에서 마스킹이 무너졌기
    때문이다. 서버측 윈도잉+GPU 배치 배포(2026-08-04)로 해소돼 상향했다.

    배포 후 실측(실사용형 문서, 이름 3개 심음): 5,474자 1.0s · 18,354자 3.2s ·
    36,754자 7.0s — **전 구간 이름 3/3 마스킹**. 32,000자는 그 안쪽이다.
    더 올릴 수는 있으나 토큰 쿼터·이후 턴 컨텍스트 비용도 함께 커진다.
    """
    try:
        return max(1000, int((os.getenv("CHAT_MAX_INPUT_CHARS") or "").strip() or "32000"))
    except ValueError:
        return 32000


class ChatAttachment(BaseModel):
    """첨부 문서 — /files/extract 가 돌려준 추출 텍스트를 프런트가 되보낸다.

    서버가 업로드~전송 사이 상태를 들지 않기 위한 설계(files.py 참조).
    텍스트는 본문과 합성돼 기존 PII 게이트·압축·검색 강제를 그대로 통과한다.
    """
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = None
    selected_law_keys: list[str] | None = None
    model: str | None = None
    # 답변 설명 수준 — "expert"(RA/QA, 조문 중심) | "simple"(비전문가, 쉬운 설명)
    style: str | None = None
    confidential: bool = False
    # 첨부 문서(파일 업로드 v1, 2026-08-05) — 계약: docs/contracts/frontend_chat_v2.md
    attachments: list[ChatAttachment] | None = None
    # 스킬 명시 진입(2026-08-21) — "irb_drb": IRB/DRB 버튼. 키워드 프리게이트가
    # 놓쳐도 기관 지침 스킬을 부착·강제한다(이중 접근). 미지원 값은 무시.
    skill_hint: str | None = None


def _max_attachments() -> int:
    try:
        return max(1, int((os.getenv("CHAT_MAX_ATTACHMENTS") or "").strip() or "3"))
    except ValueError:
        return 3


def _max_total_input_chars() -> int:
    """본문+첨부 합산 상한(문자).

    60,000→150,000(2026-09-14): 계획서 50쪽(≈10만 자)+보완 공문을 한 턴에.
    종전 근거였던 PII 게이트 처리량(36,754자 7.0s, 2026-08-04)은 NER 교체 후
    실측 150,000자 1.8s·300,000자 3.2s 로 병목이 아니다. 남은 제약은 모델
    컨텍스트와 턴당 토큰 비용 — 150,000자 ≈ 5~8만 토큰.
    """
    try:
        return max(1000, int((os.getenv("CHAT_MAX_TOTAL_INPUT_CHARS") or "").strip() or "150000"))
    except ValueError:
        return 150000


def _compose_message(message: str, attachments: list[ChatAttachment] | None) -> str:
    """본문 + 첨부 블록 합성. <attachment> 태그는 프런트 접기 렌더와
    모델 구분(첨부 vs 질문) 양쪽에 쓰인다 — 형식 변경 시 FE 파서와 동기."""
    if not attachments:
        return message
    # 인젝션 보강(2026-09-15): 파일명은 속성값으로 안전하게, 본문 안의 첨부 태그는
    # 전각으로 바꿔 프레임 탈출을 막는다. 모델에는 "첨부는 자료" 규칙(supervisor)이 붙는다.
    from src.text.messages import neutralize_attachment_tags, sanitize_attachment_name

    blocks = [
        f'\n\n<attachment name="{sanitize_attachment_name(a.name)}">\n'
        f'{neutralize_attachment_tags(a.text.strip())}\n</attachment>'
        for a in attachments
    ]
    return message + "".join(blocks)


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    if (os.getenv("CHAT_LOOP_DISABLE") or "").strip() == "1":
        raise HTTPException(status_code=404, detail="chat loop disabled")

    # 동의 없는 이용 차단(2026-09-23) — 프런트 게이트만으론 조회 실패 시 통과했다.
    from src.routes.privacy import require_consent
    await asyncio.to_thread(require_consent, request)

    # 길이 초과는 **한국어로** 알린다 — Pydantic max_length 로 두면 FE 에 영문
    # 검증 오류("String should have at most N characters")가 그대로 노출된다.
    limit = _max_input_chars()
    if len(req.message) > limit:
        raise HTTPException(
            status_code=422,
            detail=(f"입력이 너무 깁니다({len(req.message):,}자). 한 번에 "
                    f"{limit:,}자까지 보낼 수 있습니다. 문서는 핵심 부분만 "
                    f"나눠서 올리거나 파일로 첨부해 주세요."),
        )

    # 첨부 검증 — 개수·본문+첨부 합산 문자 상한(초과 시 한국어 422).
    if req.attachments:
        if len(req.attachments) > _max_attachments():
            raise HTTPException(
                status_code=422,
                detail=f"첨부는 한 번에 {_max_attachments()}개까지 가능합니다.",
            )
        # 파일당 방어 상한 — /files/extract cap 우회 대비. 추출 상한을 그대로 따른다
        # (종전 `_max_input_chars()*2`=64,000 은 상한 상향 후 정상 첨부를 거절했다).
        from src.file_extract import max_extract_chars
        per_cap = max(max_extract_chars(), _max_input_chars())
        for a in req.attachments:
            if len(a.text) > per_cap:
                raise HTTPException(
                    status_code=422,
                    detail=f"첨부 '{a.name}' 이(가) 너무 큽니다.",
                )
        total = len(req.message) + sum(len(a.text) for a in req.attachments)
        total_limit = _max_total_input_chars()
        if total > total_limit:
            raise HTTPException(
                status_code=422,
                detail=(f"본문과 첨부를 합친 길이가 너무 깁니다({total:,}자, "
                        f"상한 {total_limit:,}자). 첨부 수를 줄이거나 문서의 "
                        f"핵심 부분만 올려주세요."),
            )

    thread_id = req.thread_id or f"t_{uuid4().hex}"
    if not _THREAD_ID_RE.match(thread_id):
        raise HTTPException(status_code=422, detail="invalid thread_id")

    # AuthMiddleware 가 박은 서버 신뢰 신원 (dev bypass 시 None).
    user_id = getattr(request.state, "user_id", None)

    # 소유권 — 남의 thread 에 이어쓰기(=맥락 열람) 차단. 신규 thread 는 통과.
    _owned_meta_or_404(thread_id, request, allow_missing=True)

    # 모델 오버라이드는 dev/벤치 전용 — 운영에선 무시(비용·품질 통제).
    model_name = req.model if (os.getenv("CHAT_MODEL_OVERRIDE_ALLOW") or "").strip() == "1" else None

    from src.chat_loop import run_chat_turn

    # SSE 하트비트 — 무이벤트 구간(느린 검색 HTTP 1콜·LLM 첫 토큰 대기·DGX 혼잡)
    # 이 프론트 무수신 임계(60s)를 넘으면 StreamInactivityTimeoutError 로 끊긴다
    # (실측 2026-07-24: "streamchunk timeout 계속 뜸"). 15s 마다 ping 이벤트를
    # 흘려 연결 생존을 알림 — FE 파서는 모든 data 프레임에서 타이머를 리셋하고
    # unknown 타입(ping)은 렌더 없이 무시한다.
    _HEARTBEAT_S = float((os.getenv("CHAT_SSE_HEARTBEAT_S") or "").strip() or "15")

    async def _gen():
        try:
            style = req.style if req.style in ("expert", "simple") else None
            confidential = bool(req.confidential)
            agen = run_chat_turn(
                thread_id,
                _compose_message(req.message, req.attachments),
                user_id=user_id,
                selected_law_keys=req.selected_law_keys,
                model_name=model_name,
                style=style,
                confidential=confidential,
                skill_hint=req.skill_hint if req.skill_hint == "irb_drb" else None,
            ).__aiter__()
            while True:
                nxt = asyncio.ensure_future(agen.__anext__())
                # 다음 이벤트가 나올 때까지 — 침묵이 길어지면 ping 으로 채움.
                while True:
                    done, _pending = await asyncio.wait({nxt}, timeout=_HEARTBEAT_S)
                    if done:
                        break
                    yield _sse("ping", {"type": "ping"})
                try:
                    ev = nxt.result()
                except StopAsyncIteration:
                    break
                yield _sse(str(ev.get("type") or "message"), ev)
        except PiiScanIncomplete as e:
            # 개인정보 검사가 전 구간을 못 덮었다 — 답변을 만들지 않고 중단한다.
            # 일반 오류 메시지로 뭉개면 사용자가 "왜 실패했는지"를 알 수 없고,
            # 재시도·분할 같은 해결 행동을 못 한다.
            _log.error("/chat 차단 — PII 검사 불완전: %s", e)
            yield _sse("error", {"type": "error", "message": str(e)})
        except Exception as e:  # noqa: BLE001 — 스트림 중 에러는 이벤트로만
            _log.exception("/chat stream failed: %s", e)
            yield _sse("error", {
                "type": "error",
                "message": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            })

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 버퍼링 방지 (deployment_docker nginx)
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# FE 조회 — 사이드바 목록 · 대화 리로드 · 제목 (langgraph /threads/* 대체)
# ---------------------------------------------------------------------------
def _owned_meta_or_404(
    thread_id: str, request: Request, *, allow_missing: bool = False
) -> dict | None:
    """thread 메타 + 소유자 검사 — 구경로 `@auth.on.threads` 스코프 대체.

    소유자 불일치는 404(존재 비노출). dev 무인증(user_id=None)·소유자 미기록
    (owner=None, dev 생성분)은 통과. `allow_missing=True` 면 미존재 thread 를
    None 으로 반환(POST /chat 의 신규 thread 생성 경로).
    """
    from src.persistence.threads_repo import get_threads_repo

    meta = get_threads_repo().get_meta(thread_id)
    if not meta:
        if allow_missing:
            return None
        raise HTTPException(status_code=404, detail="thread not found")
    user_id = getattr(request.state, "user_id", None)
    owner = meta.get("user_id")
    if user_id is not None and owner is not None and str(owner) != str(user_id):
        raise HTTPException(status_code=404, detail="thread not found")  # 비노출
    return meta


def _message_view(m) -> dict:
    """FE 렌더용 메시지 축약 — 구경로 values.messages 와 같은 판단 재료 제공."""
    from src.text.messages import content_text as _msg_text

    out = {
        "id": getattr(m, "id", None),
        "type": getattr(m, "type", None),          # human | ai | tool
        "content": _msg_text(getattr(m, "content", None)),
    }
    tool_calls = getattr(m, "tool_calls", None) or []
    if tool_calls:
        out["tool_calls"] = [tc.get("name") for tc in tool_calls]
    # kind 태그(report_overview 등) — FE 가 일반 답변과 다른 카드로 렌더.
    ak = getattr(m, "additional_kwargs", None) or {}
    if ak.get("kind"):
        out["kind"] = ak["kind"]
        if ak.get("report_id"):
            out["report_id"] = ak["report_id"]
    # 길이 상한 잘림 — 새로고침·재진입 후에도 [이어서 작성] 버튼이 뜨게 영속 메타에서
    # 복원(종전엔 SSE done 에만 실려 라이브 세션 전용, 2026-09-15). 자동 이어쓰기
    # 이전에 저장된 메시지는 truncated 키가 없어 stop_reason 으로 판정.
    rm = getattr(m, "response_metadata", None) or {}
    if out["type"] == "ai" and not tool_calls and (
            rm.get("truncated") or rm.get("stop_reason") == "max_tokens"):
        out["truncated"] = True
    return out


@router.get("/chat/threads")
def list_chat_threads(request: Request, limit: int = 50):
    """사이드바 thread 목록 — 본인 것만, 최근 갱신순."""
    from src.persistence.threads_repo import get_threads_repo

    user_id = getattr(request.state, "user_id", None)
    rows = get_threads_repo().list_for_user(user_id, limit=min(max(1, limit), 200))
    return {"threads": [
        {"thread_id": r["id"], "title": r.get("title"),
         "created_at": r.get("created_at"), "updated_at": r.get("updated_at"),
         "pinned": bool(r.get("pinned"))}
        for r in rows
    ]}


@router.get("/chat/search")
def search_chat_threads(request: Request, q: str = "", limit: int = 30):
    """대화 *본문* 검색 — 제목만이던 사이드바 검색을 메시지 내용까지 확장.
    본인 대화 중 q 를 포함하는 thread 목록(최근순). q 2자 미만이면 빈 결과."""
    from src.persistence.threads_repo import get_threads_repo

    query = (q or "").strip()
    if len(query) < 2:
        return {"threads": []}
    user_id = getattr(request.state, "user_id", None)
    rows = get_threads_repo().search_messages(
        user_id, query, limit=min(max(1, limit), 100),
    )
    return {"threads": [
        {"thread_id": r["id"], "title": r.get("title"),
         "created_at": r.get("created_at"), "updated_at": r.get("updated_at"),
         "pinned": bool(r.get("pinned")),
         # 매칭 발췌 — 비슷한 제목이 여러 개일 때 어느 대화인지 고르는 근거.
         "match_snippet": r.get("match_snippet") or ""}
        for r in rows
    ]}


def _answer_markdown(content: str, citations: list) -> str:
    """답변 본문 + 참고자료(인용) 섹션 조립 — 내보내기용."""
    md = content
    lines = []
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        bits = " · ".join(
            str(x).strip() for x in (c.get("title"), c.get("publisher"), c.get("article")) if x
        )
        link = str(c.get("url") or c.get("download_url") or "").strip()
        entry = f"[{c.get('number')}] {bits}"
        # 링크는 명시적 markdown 링크로 — pandoc→docx 에서 클릭 가능 하이퍼링크로 변환.
        # (bare URL 을 텍스트에 섞으면 한 줄에 엉켜 링크 파싱이 깨졌음.)
        if link:
            entry += f" — [{link}]({link})"
        lines.append(entry)
    if lines:
        # 항목 사이 **빈 줄**(문단 분리) — 단일 \n 은 markdown soft break 라 pandoc 이
        # 전부 한 문단으로 뭉쳐 줄바꿈이 사라졌음(사용자 보고 2026-07-21).
        md = content + "\n\n## 참고 자료\n\n" + "\n\n".join(lines)
    return md


@router.post("/answers/export")
async def export_answer(request: Request):
    """답변을 Word(docx) 또는 md 로 내보내기. body: { content, citations?, format? }.

    docx 는 보고서와 동일한 pandoc 변환 재활용. pandoc 미설치/실패 시 md 폴백.
    (PDF 는 별도 PDF 엔진 필요라 미포함 — docx/md 만.)
    """
    body = await request.json()
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="content 필요")
    fmt = str(body.get("format") or "docx").lower()
    citations = body.get("citations") if isinstance(body.get("citations"), list) else []
    md = _answer_markdown(content, citations)

    if fmt == "docx":
        from src import reports_convert
        if reports_convert.is_available():
            try:
                data = reports_convert.md_to_docx(md)
                return Response(
                    content=data,
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": 'attachment; filename="medi-answer.docx"'},
                )
            except Exception as e:  # noqa: BLE001 — 변환 실패 시 md 폴백
                _log.warning("answer docx 변환 실패 — md 폴백: %s", e)
    # md 폴백/요청
    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="medi-answer.md"'},
    )


@router.get("/chat/{thread_id}/state")
def get_chat_state(thread_id: str, request: Request):
    """대화 리로드 — 구경로 `GET /threads/{tid}/state` 대체.

    반환 shape 은 FE derive 로직이 쓰던 재료와 동등: messages(전체 — human/ai
    필터는 FE 몫, 기존과 동일) + steps(citations 포함) + selected_law_keys.
    """
    meta = _owned_meta_or_404(thread_id, request)
    from src.persistence.threads_repo import get_threads_repo

    state = get_threads_repo().get_state(thread_id)
    from src.report_runner import is_report_running

    return {
        "thread_id": thread_id,
        "title": meta.get("title"),
        "messages": [_message_view(m) for m in state.messages],
        "steps": state.steps,
        "selected_law_keys": state.selected_law_keys,
        # 진행 배지 — 폴링 중 FE 가 "보고서 작성 중" 유지(비차단 설계 유지).
        "report_running": is_report_running(thread_id),
    }


@router.delete("/chat/{thread_id}")
def delete_chat_thread(thread_id: str, request: Request):
    """thread 삭제(메시지·steps 포함) — 구경로 `DELETE /threads/{tid}` 대체."""
    _owned_meta_or_404(thread_id, request)
    from src.form_docs import delete_thread_documents
    from src.persistence.threads_repo import get_threads_repo

    # 이 대화에서 만든 서식도 함께 지운다 — 보관(kept)한 것만 남는다(2026-09-18).
    docs = delete_thread_documents(thread_id)
    get_threads_repo().delete_thread(thread_id)
    return {"ok": True, "thread_id": thread_id,
            "documents_deleted": docs["deleted"], "documents_kept": docs["kept"]}


class ThreadPatch(BaseModel):
    title: str = Field(min_length=1, max_length=60)


@router.patch("/chat/{thread_id}")
def patch_chat_thread(thread_id: str, body: ThreadPatch, request: Request):
    """thread 이름 변경 — 구경로 `threads.update(metadata.title)` 대체."""
    _owned_meta_or_404(thread_id, request)
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().set_title(thread_id, body.title.strip())
    return {"ok": True, "thread_id": thread_id, "title": body.title.strip()[:60]}


class ThreadPin(BaseModel):
    pinned: bool


@router.post("/chat/{thread_id}/pin")
def pin_chat_thread(thread_id: str, body: ThreadPin, request: Request):
    """thread 고정/해제 — 사이드바 상단 고정(진행 중 프로젝트 대화 유지)."""
    _owned_meta_or_404(thread_id, request)
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().set_pinned(thread_id, body.pinned)
    return {"ok": True, "thread_id": thread_id, "pinned": body.pinned}


@router.post("/chat/{thread_id}/auto-title")
async def chat_auto_title(thread_id: str, request: Request):
    """첫 human 메시지 → 5~15자 제목 → chat_threads.title (idempotent).

    구경로 `POST /threads/{tid}/auto-title`(langgraph metadata + loopback) 대체 —
    threads_repo 직접이라 loopback 불요. 응답 shape `{thread_id, title}` 동일.
    """
    meta = _owned_meta_or_404(thread_id, request)
    if meta.get("title"):
        return {"thread_id": thread_id, "title": meta["title"]}

    from src.persistence.threads_repo import get_threads_repo

    repo = get_threads_repo()
    state = repo.get_state(thread_id)
    first_human = next(
        (m for m in state.messages if getattr(m, "type", None) == "human"), None)
    if first_human is None:
        raise HTTPException(status_code=409, detail="thread has no user message")

    from src.text.messages import content_text as _msg_text

    query = _msg_text(getattr(first_human, "content", None))[:500]
    title = ""
    try:
        from src.chat_loop import _base_model

        spec = (os.getenv("TITLE_MODEL") or os.getenv("SUBAGENT_MODEL")
                or "anthropic:claude-haiku-4-5-20251001")
        llm = _base_model(spec)
        resp = await llm.ainvoke(_TITLE_PROMPT.format(query=query))
        title = _msg_text(getattr(resp, "content", None)).strip().strip('"')[:30]
    except Exception as e:  # noqa: BLE001 — LLM 실패 시 질문 앞부분 폴백
        _log.info("chat auto-title LLM 실패 — 폴백: %s", e)
    if not title:
        title = query[:20] or "새 대화"
    repo.set_title(thread_id, title)
    return {"thread_id": thread_id, "title": title}
