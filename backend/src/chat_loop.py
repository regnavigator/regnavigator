"""자체 chat 에이전트 루프 — ADR-0001 Phase 1 (`langgraph`/`deepagents` 무의존 PoC).

`create_deep_agent`(deepagents) + langgraph 런타임을 대체하는 수동 tool-loop:
    while: 모델 스트리밍 → tool_calls 실행 → ToolMessage append → 반복 → 최종 답변.

**의존 목표 증명**: 이 모듈(및 신규 경로)은 `langchain_core` + `langchain_anthropic`
만 직접 import 한다. 기존 미들웨어 모듈에서 가져오는 헬퍼(전이적으로 langchain
메타를 import)는 Phase 5 에서 이 파일/전용 모듈로 이관 — `# transitional` 표시.

미들웨어 → 훅 이식 맵 (동작 동등이 목표 — bench_run 비교로 검증):
| 기존 (langgraph AgentMiddleware)   | 여기                                    |
|------------------------------------|-----------------------------------------|
| PiiGateMiddleware (at-rest/egress) | `_scrub_user_text` / `_egress_scrub`    |
| IntentSearchMiddleware             | `_should_force_search` → forced 바인딩  |
| StepsMiddleware (reducer)          | ThreadsRepo.merge_steps + turn 누적     |
| ReportContextMiddleware            | **폐지**(2026-07-25 채팅↔보고서 분리)   |
| GroundingGateMiddleware            | `_apply_grounding` (답변 후)            |
| TokenLoggerMiddleware              | TokenUsageLogger 콜백 (그대로 재사용)   |
| LLMRateLimitMiddleware             | 모델 `rate_limiter=` (전역 limiter 공유)|
| ModelCallLimit/Fallback/Retry      | 루프 상한 / `with_fallbacks` / `max_retries` |

HITL: `ask_clarify` 는 interrupt 가 아니라 **턴 종료** — `clarify` 이벤트 발행 후
턴을 끝내고, 사용자 답변은 다음 `/chat` 요청의 human 메시지로 들어온다
(ADR-0001-migration-plan §2).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import replace
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.guardrail.gate import (
    PiiScanIncomplete,
    scrub_content as _scrub_content,
    scrub_input,
)
from src.models import (
    build_chat_model,
    provider_credential_ok,
    split_model_spec,
)
from src.text.messages import content_text as _msg_text
from src.observability.search_progress import (
    _emit_progress,
    _emit_result,
    _emit_step_lifecycle,
    reset_progress_sink,
    set_progress_sink,
)
from src.observability import usage_context
from src.persistence.threads_repo import ThreadState, get_threads_repo
from src.official_sources import (
    registry_haystack,
    render_reference_block,
    sanitize_body_urls,
)
from src.prompts.supervisor import (
    PROMPT_VERSION as _SUPERVISOR_PROMPT_VERSION,
    SUPERVISOR_PROMPT,
)
from src.steps import merge_steps_by_id, new_step_id, now_ms, resolve_turn_context
from src.steps import step_done, step_error, step_start
from src.tools.citations import _publisher_from_url
from src.tools.search import (
    DOC_KIND_LABELS,
    SearchConfigError,
    SearchError,
    _assign_turn_citation_numbers,
    _count_tool_calls,
    _format_rag_hits,
    _format_web_results,
    run_qdrant,
    run_qdrant_pinned,
    run_tavily,
    sanitize_doc_kinds,
)

_log = logging.getLogger(__name__)

_FORCE_TOOL = "qdrant_search"


_WEB_TOOL = "tavily_search"


def _tool_called_this_turn(messages: list, tool_name: str) -> bool:
    """마지막 human 이후 지정 도구호출이 있었나 (강제 루프 방지 공통 헬퍼)."""
    last_human = -1
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", None) == "human":
            last_human = i
            break
    if last_human < 0:
        return False
    for m in messages[last_human + 1:]:
        if getattr(m, "type", None) != "ai":
            continue
        for tc in (getattr(m, "tool_calls", None) or []):
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            if name == tool_name:
                return True
    return False


def _already_searched_this_turn(messages: list) -> bool:
    """마지막 human 이후 qdrant_search 도구호출이 있었나 (intent 강제 루프 방지).

    구 `middleware/intent_search` 이관(ADR-0001 Phase 5).
    """
    return _tool_called_this_turn(messages, _FORCE_TOOL)


def _turn_citation_count(turn_steps: list[dict]) -> int:
    """이번 턴 수집된 서로 다른 근거(citation) 수 — 충분성 게이트용."""
    ids: set = set()
    for st in turn_steps or []:
        for c in (st.get("citations") or []):
            cid = c.get("id") if isinstance(c, dict) else None
            if cid:
                ids.add(cid)
    return len(ids)

_DONE = object()  # 내부 큐 종료 센티널

# per-thread 턴 직렬화 — langgraph-api 가 해주던 "같은 thread 의 run 직렬화" 대체.
# 같은 thread 동시 요청(더블클릭·중복 탭)이 메시지 히스토리를 interleave 시키는
# 것을 방지. 프로세스 로컬(멀티 워커 금지 불변식과 정합 — CLAUDE.md §10).
_turn_locks: dict[str, asyncio.Lock] = {}
_turn_lock_refs: dict[str, int] = {}


def _acquire_turn_lock(thread_id: str) -> asyncio.Lock:
    _turn_lock_refs[thread_id] = _turn_lock_refs.get(thread_id, 0) + 1
    return _turn_locks.setdefault(thread_id, asyncio.Lock())


def _release_turn_lock(thread_id: str) -> None:
    n = _turn_lock_refs.get(thread_id, 1) - 1
    if n <= 0:  # 마지막 사용자 — dict 누적 방지
        _turn_lock_refs.pop(thread_id, None)
        _turn_locks.pop(thread_id, None)
    else:
        _turn_lock_refs[thread_id] = n


@asynccontextmanager
async def hold_turn_lock(thread_id: str):
    """외부(보고서 러너)가 thread 메시지 append 를 채팅 턴과 직렬화하는 진입점.

    보고서 잡은 채팅과 별개 태스크라 턴 락을 우회해 thread 에 직접 쓴다 —
    개요 append 가 진행 중 채팅 턴과 interleave 되면 대화 순서가 튄다. 완료
    개요 append 만 이 락으로 감싸 원자적으로 직렬화한다(전체 잡을 감싸면 5~12분
    간 채팅이 막히므로 append 구간만).
    """
    lock = _acquire_turn_lock(thread_id)
    try:
        async with lock:
            yield
    finally:
        _release_turn_lock(thread_id)


# ---------------------------------------------------------------------------
# 도구 스키마 — bind_tools 용 (실행은 아래 _exec_tool 이 수동으로)
# ---------------------------------------------------------------------------
TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "qdrant_search",
            "description": (
                "내부 자료(법령·시행령·고시·판례 등)를 검색한다. 의료 규제 질문의 "
                "근거 확보에 사용. query 는 맥락을 반영한 한국어 검색어. "
                "기본 검색은 법령 조문이 상위를 차지한다 — 논점에 판례·해석례·"
                "행정규칙·조례·가이드라인이 유용해 보이면 doc_kinds 로 그 종별만 "
                "추가 검색하라 (예: 처벌·분쟁·위반 사례 → prec, 법령 해석 다툼 → "
                "expc, 세부 기준·고시 → admrul, 지자체 지원·규제 → ordin, "
                "실무 절차·심사기준·제출자료 안내 → guide, 급여기준·심사지침·"
                "수가 등 고시 첨부의 세부 기준 → admrul_attach)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 질의"},
                    "top_k": {"type": "integer", "description": "결과 수(기본 8)"},
                    "doc_kinds": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            # 단일 진실원(tools.search.DOC_KIND_LABELS) — 여기에
                            # 직접 나열하면 검증 화이트리스트와 어긋난다(8/24 사고).
                            "enum": list(DOC_KIND_LABELS),
                        },
                        "description": (
                            "검색할 문서 종별 제한 — law=법령, admrul=행정규칙(고시·"
                            "훈령), ordin=자치법규(조례), prec=판례, expc=법령해석례, "
                            "guide=식약처 가이드라인, admrul_attach=행정규칙 첨부 본문"
                            "(급여기준·심사지침 등 별표/첨부에만 있는 세부 기준). "
                            "미지정 시 전 종별."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tavily_search",
            "description": (
                "웹에서 의료 규제·가이드라인·최신 동향을 검색한다. 법령 DB 에 없는 "
                "해외 규제·뉴스·기관 발표에 사용."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 질의"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarify",
            "description": (
                "질문이 매우 모호할 때만 사용자에게 명확화를 요청한다. 정상적인 "
                "의료 규제 질문에는 호출하지 않는다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "사용자 향 한국어 질문 한 줄"},
                    "options": {
                        "type": "array", "items": {"type": "string"},
                        "description": "라디오 선택지 라벨(선택)",
                    },
                    "allow_free_text": {"type": "boolean", "description": "자유 텍스트 허용(기본 true)"},
                },
                "required": ["question"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# 모델 빌드 — src.models.build_chat_model (provider 직접 생성) 사용
# ---------------------------------------------------------------------------
# ── 보조 LLM 호출의 기밀 정책 (2026-10-03) ──────────────────────────────────
#
# 감사 결과: 기밀 모드는 답변 모델 1개와 웹 도구에만 걸려 있었고, 같은 턴의 보조
# LLM 호출(압축 요약·커버리지 심판·적용가능성·grounding·무인용 감사·서류 기입)은
# 전부 상용 Haiku 로 나갔다. "기밀" 이라는 약속이 거짓이었다.
#
# 보조 호출은 전부 모듈 전역 함수라 `confidential` 을 인자로 꿰기 어렵다. 그래서
# **턴 단위 contextvar** 하나를 두고, 보조 호출이 모델을 만들 때 이걸 본다:
#   - 기밀 턴 + 원내 모델 있음 → 원내 모델로 (`aux_model()`)
#   - 기밀 턴 + 원내 모델 없음 → **건너뛴다** (`aux_model()` 이 None)
#   - 비기밀 턴 → 상용 그대로
# 보조 품질이 조금 떨어지더라도 사건 내용이 밖으로 나가는 것보다 낫다.

import contextvars as _cv

_AUX_POLICY: _cv.ContextVar[Optional[dict]] = _cv.ContextVar("aux_policy", default=None)


def set_aux_policy(*, confidential: bool, local_model: Optional[str]) -> None:
    """턴 시작 시 호출 — 이 턴의 보조 호출이 따를 정책."""
    _AUX_POLICY.set({"confidential": bool(confidential), "local_model": local_model})


def aux_model(spec: str, *, max_tokens: int):
    """보조 호출용 모델. 기밀 턴에 원내 모델이 없으면 **None** — 호출자는 건너뛴다.

    `build_chat_model(spec)` 을 직접 부르는 보조 경로는 이걸로 바꿔야 한다.
    """
    pol = _AUX_POLICY.get()
    if not pol or not pol["confidential"]:
        return build_chat_model(spec, max_tokens=max_tokens)
    if pol["local_model"]:
        from src import skill_local as _skill_local

        return _skill_local.build_model(pol["local_model"], max_tokens=max_tokens)
    _log.info("보조 LLM 호출 건너뜀 — 기밀 턴인데 원내 모델이 없다(spec=%s)", spec)
    return None


def is_confidential_turn() -> bool:
    pol = _AUX_POLICY.get()
    return bool(pol and pol["confidential"])


def _base_model(spec: str):
    """대화용 모델 — CHAT_MAX_TOKENS 반영. (요약·제목 등 저비용 콜도 재사용.)"""
    try:
        max_tokens = int((os.getenv("CHAT_MAX_TOKENS") or "").strip() or "4096")
    except ValueError:
        max_tokens = 4096
    return build_chat_model(spec, max_tokens=max_tokens)


def _ab_model(user_id: Optional[str], override: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """LLM A/B 배정. `CHAT_MODEL_AB="specA|specB"` 설정 시 user_id 해시로 변형 선택.

    반환 (model_spec, variant_label). 명시 오버라이드(dev)나 미설정 시 (None, None).
    같은 user 는 항상 같은 변형(안정) — 변형별 피드백/지연/비용 비교용.
    """
    if override:
        return None, None
    raw = (os.getenv("CHAT_MODEL_AB") or "").strip()
    specs = [s.strip() for s in raw.split("|") if s.strip()]
    if len(specs) < 2:
        return None, None
    key = (user_id or "anon").encode("utf-8")
    idx = int(hashlib.sha1(key).hexdigest(), 16) % len(specs)
    return specs[idx], chr(ord("A") + idx)


# 보고서 중단 발화 감지 — 고정밀 우선(오탐=안내 한 줄, 미탐=모델 일반 답변).
_CANCEL_INTENT_RE = re.compile(
    r"(보고서|리포트)[^\n]{0,12}(중단|취소|멈춰|멈추|그만|정지|스톱|stop)"
    r"|(중단|취소|멈춰|정지)[^\n]{0,8}(보고서|리포트)",
    re.IGNORECASE)


def build_models(
    model_name: Optional[str] = None, *, skill_tools: Optional[list[dict]] = None,
    local_skill_model: Optional[str] = None,
) -> tuple[Any, Any, Any, Any]:
    """(normal, forced_qdrant, forced_web, forced_skill) — tool 바인딩 4종.

    forced_qdrant 는 qdrant_search, forced_web 는 tavily_search 강제(웹 게이트).
    forced_skill 은 `skill_tools`(스킬 턴에만 전달) 가 있을 때만 생성 — load_skill
    강제(지침 우선 계약). 없으면 None (스킬 미부착 턴은 기존 3종과 동일).
    폴백: `LLM_FALLBACK` env(자격증명 있을 때만) — 구 `ModelFallbackMiddleware` 대응.
    """
    spec = model_name or os.environ.get("LLM_MODEL") or "anthropic:claude-sonnet-4-6"
    # 스킬 턴 로컬 라우팅(skill_local) — 이 턴의 모델을 온프레미스 vLLM 으로 교체.
    # ⚠️ LLM_FALLBACK 미부착: 로컬 실패가 상용으로 새면 개인정보 정책이 뚫린다.
    if local_skill_model:
        from src import skill_local as _sl

        # 판정 답변은 길다(경로표·IRB+DRB·말미 <verdict>). 4096 에서 잘리면
        # verdict 블록이 사라져 판정 로그·가드가 무력화된다(2026-09-15 e2e 실측:
        # 4,071자에서 절단, skill_verdict 미발행). 스킬 턴 전용 상한을 둔다.
        try:
            _mt = int((os.getenv("SKILL_LOCAL_MAX_TOKENS") or "").strip() or "8192")
        except ValueError:
            _mt = 8192
        primary = _sl.build_model(local_skill_model, max_tokens=_mt)
        # ⚠️ 온프레미스 턴에는 **웹 검색 도구를 주지 않는다**(2026-09-10).
        # 이 턴을 로컬 모델로 돌리는 이유는 연구계획·환자군 서술을 외부로 안 내보
        # 내려는 것인데, tavily 는 검색어를 Tavily(미국)로 보낸다 — 모델만 원내로
        # 옮기고 도구를 열어두면 정책이 반만 서는 셈이다. 법령 근거는 qdrant
        # (DGX 내부 검색 API)로 확보되므로 실손실은 "지침 밖 최신 웹 보강"뿐이고,
        # 스킬 지침 자체가 웹을 보조로만 쓰라고 규정한다.
        tools = [t for t in TOOL_SPECS
                 if t.get("function", {}).get("name") != _WEB_TOOL]
        tools += (skill_tools or [])

        def _bind_local(**kw):
            return primary.bind_tools(tools, **kw)

        # forced_web = None — 호출부의 웹 게이트가 `forced_web is not None` 을
        # 검사하므로 이것만으로 강제 경로도 함께 닫힌다.
        return (_bind_local(), _bind_local(tool_choice="qdrant_search"),
                None,
                _bind_local(tool_choice="load_skill") if skill_tools else None)
    primary = _base_model(spec)

    fb_model = None
    fb = (os.getenv("LLM_FALLBACK") or "").strip()
    if fb and provider_credential_ok(split_model_spec(fb)[0]):
        try:
            fb_model = _base_model(fb)
        except Exception as e:  # noqa: BLE001 — 폴백 구성 실패가 채팅을 막으면 안 됨
            _log.warning("chat_loop 폴백(%s) 구성 실패 — 폴백 비활성: %s", fb, e)

    tools = TOOL_SPECS + (skill_tools or [])

    def _bind(**kw):
        m = primary.bind_tools(tools, **kw)
        if fb_model is not None:
            m = m.with_fallbacks([fb_model.bind_tools(tools, **kw)])
        return m

    return (_bind(), _bind(tool_choice="qdrant_search"),
            _bind(tool_choice="tavily_search"),
            _bind(tool_choice="load_skill") if skill_tools else None)


# ---------------------------------------------------------------------------
# 대화 압축 — deepagents 내장 SummarizationMiddleware 대체 (Phase 2)
# ---------------------------------------------------------------------------
_SUMMARY_PROMPT = """다음은 의료 규제 상담 대화의 오래된 앞부분이다{prev_note}. 후속 턴 답변에 필요한 것만 남기고 압축하라:
- 사용자의 제품/상황/제약 조건
- 이미 안내한 결론과 근거 법령(법령명·조문 번호 유지)
- 미해결 질문·사용자가 명확화한 내용
800자 이내 한국어 서술. 서두·메타 설명 없이 요약 본문만.

{prev_block}=== 대화 ===
{block}"""


def _estimate_tokens(messages: list[BaseMessage]) -> int:
    """보수적 추정 — 한국어 ~3자/토큰. 정밀할 필요 없음(트리거 용도)."""
    total = 0
    for m in messages:
        c = getattr(m, "content", "")
        total += len(c) if isinstance(c, str) else len(str(c))
    return total // 3


async def _summarize_text(block: str, prev_summary: Optional[str]) -> str:
    """오래된 턴 블록(+기존 요약)을 저비용 모델로 재요약."""
    spec = (
        os.getenv("CHAT_SUMMARY_MODEL")
        or os.getenv("SUBAGENT_MODEL")
        or "anthropic:claude-haiku-4-5-20251001"
    )
    try:
        max_tokens = int((os.getenv("CHAT_MAX_TOKENS") or "").strip() or "4096")
    except ValueError:
        max_tokens = 4096
    model = aux_model(spec, max_tokens=max_tokens)
    if model is None:
        return ""  # 기밀 턴 + 원내 없음 → 요약 생략(무압축 진행 — 호출자가 처리)
    prompt = _SUMMARY_PROMPT.format(
        prev_note=" (기존 요약이 있으면 병합)" if prev_summary else "",
        prev_block=f"=== 기존 요약 ===\n{prev_summary}\n\n" if prev_summary else "",
        block=block,
    )
    resp = await model.ainvoke(prompt)
    return _msg_text(getattr(resp, "content", None)).strip()


async def _maybe_compact(repo, state: ThreadState) -> tuple[list[BaseMessage], Optional[str]]:
    """토큰 임계 초과 시 오래된 턴을 요약으로 대체. 반환 (프롬프트용 tail, 요약).

    - 컷은 **human 메시지 경계** — tool_use/tool_result 짝이 갈라지지 않고,
      tail 이 human 으로 시작해 Anthropic 히스토리 규칙에 안전.
    - 최근 `CHAT_SUMMARY_KEEP_TURNS`(기본 2) 턴은 원문 유지.
    - 요약·컷 지점은 thread 에 영속(다음 턴 재사용) — DB 원본 메시지는 보존.
    - 요약 실패 시 무압축 진행(다음 턴 재시도) — 압축이 대화를 막으면 안 됨.
    """
    msgs = state.messages
    seqs = state.seqs or list(range(len(msgs)))
    summary = state.summary_text
    upto = state.summary_upto_seq
    pairs = [(m, s) for m, s in zip(msgs, seqs) if upto is None or s > upto]
    tail_msgs = [m for m, _ in pairs]

    # 60,000(2026-09-14, 종전 24,000): 첨부 상한을 120,000자로 올리면서 함께 상향.
    # 24,000이면 50쪽 계획서(≈10만 자 ≈ 3.3만 토큰 추정)가 **바로 다음 턴에서
    # 요약으로 대체**돼 "그럼 선정기준은?" 같은 후속 질문이 문서를 잃는다.
    try:
        trigger = int((os.getenv("CHAT_SUMMARY_TRIGGER_TOKENS") or "").strip() or "60000")
    except ValueError:
        trigger = 60000
    if trigger <= 0 or _estimate_tokens(tail_msgs) <= trigger:
        return tail_msgs, summary

    try:
        keep = max(1, int((os.getenv("CHAT_SUMMARY_KEEP_TURNS") or "").strip() or "2"))
    except ValueError:
        keep = 2
    human_idx = [i for i, (m, _) in enumerate(pairs)
                 if getattr(m, "type", None) == "human"]
    if len(human_idx) <= 1:
        # 턴이 하나뿐 — 그게 **지금 답해야 할 턴**이라 원문을 유지한다.
        # 문서를 붙여넣은/첨부한 첫 턴이 여기 해당(본문+첨부 상한 150,000자 ≈
        # 5만 토큰 추정 — 컨텍스트에 충분히 들어간다). 요약하면 답변 근거가 사라진다.
        return tail_msgs, summary
    if len(human_idx) <= keep:
        # 유지 턴수(keep)만큼도 안 되지만 임계는 넘은 상태 — 예전엔 여기서
        # 포기해 **붙여넣은 문서가 이후 모든 턴 컨텍스트에 영구히 실렸다**
        # (2026-08-04). keep 을 무시하고 마지막 턴만 남긴다: 지난 턴의 문서는
        # 요약으로 대체되고, 현재 턴은 그대로 남아 답변 품질에 영향이 없다.
        cut = human_idx[-1]
        _log.info("chat_loop compact: 거대 턴 — keep=%d 무시하고 마지막 턴만 유지", keep)
    else:
        cut = human_idx[-keep]
    head, tail = pairs[:cut], pairs[cut:]
    block = "\n".join(
        f"[{getattr(m, 'type', '?')}] {_msg_text(getattr(m, 'content', None))[:2000]}"
        for m, _ in head
    )
    try:
        new_summary = await _summarize_text(block, summary)
    except Exception as e:  # noqa: BLE001 — 요약 실패가 대화를 막으면 안 됨
        _log.warning("chat_loop compact skipped: %s", e)
        return tail_msgs, summary
    if not new_summary:
        return tail_msgs, summary

    upto_new = head[-1][1]
    await asyncio.to_thread(repo.set_summary, state.thread_id, new_summary, upto_new)
    state.summary_text, state.summary_upto_seq = new_summary, upto_new
    _log.info(
        "chat_loop compact: %d msgs → 요약(≤%d seq), tail %d msgs",
        len(head), upto_new, len(tail),
    )
    return [m for m, _ in tail], new_summary


# ---------------------------------------------------------------------------
# 훅 — 기존 미들웨어 로직 이식
# ---------------------------------------------------------------------------
def _pii_enabled() -> bool:
    return (os.getenv("PII_GATE_DISABLE") or "").strip() != "1"


def _scrub_user_text(text: str) -> tuple[str, list[str], list[dict]]:
    """at-rest — 저장 전 스크럽(체크포인트/DB 원문에서 PII 제거).

    (마스킹된 텍스트, 카테고리 리스트, NER 마스킹 단어 리스트) 반환. 카테고리는
    프론트 알림 + 답변 지침에, 단어 리스트는 오탐 개선리스트 전수 수집
    (`pii_terms.observe_many`)에 쓴다. 수집은 **이 경로에서만** — egress
    재스크럽에서 하면 같은 턴이 중복 집계된다.
    """
    if not _pii_enabled():
        return text, [], []
    spans: list[dict] = []
    try:
        scrubbed, found = scrub_input(text, collect=spans)
        if found:
            _log.info("chat_loop pii at-rest: 저장 스크럽 %d건", len(found))
        return scrubbed, found, spans
    except PiiScanIncomplete:
        # ⚠️ 삼키면 안 된다 — 여기서 원문을 반환하면 마스킹되지 않은 이름·주소가
        # 그대로 DB 에 저장되고 LLM 으로 나간다(fail-open). 이 예외만은 올린다.
        raise
    except Exception as e:  # noqa: BLE001 — 그 외 게이트 오류가 대화를 막으면 안 됨
        _log.warning("chat_loop pii at-rest skipped: %s", e)
        return text, [], []


#: 기밀 메시지가 빠진 자리에 남기는 표식. 내용은 주지 않되 "앞에 뭔가 있었다"는
#: 사실은 알려야 모델이 맥락 단절을 날조로 메우지 않는다.
SENSITIVE_PLACEHOLDER = "(기밀 단계에서 처리된 내용 — 이 대화에는 포함되지 않습니다)"


def _drop_sensitive(state: ThreadState) -> ThreadState:
    """기밀 턴에서 나온 메시지를 이력에서 제거한다(비기밀 턴용).

    제거한 자리에 human 플레이스홀더 하나를 남긴다 — 연속된 기밀 구간은 하나로
    합친다. tool 메시지를 짝 없이 남기면 Anthropic 히스토리 규칙에 걸리므로
    **구간 통째로** 뺀다.

    `seqs` 를 `messages` 와 평행하게 유지해야 한다 — 대화 압축이 둘을 zip 한다.
    """
    flags = state.sensitive or []
    if not any(flags):
        return state

    msgs = state.messages
    seqs = state.seqs or list(range(len(msgs)))
    out_m: list[BaseMessage] = []
    out_s: list[int] = []
    prev_dropped = False
    for i, m in enumerate(msgs):
        if i < len(flags) and flags[i]:
            if not prev_dropped:
                out_m.append(HumanMessage(content=SENSITIVE_PLACEHOLDER))
                out_s.append(seqs[i] if i < len(seqs) else i)
                prev_dropped = True
            continue
        prev_dropped = False
        out_m.append(m)
        out_s.append(seqs[i] if i < len(seqs) else i)

    return replace(state, messages=out_m, seqs=out_s,
                   sensitive=[False] * len(out_m))


def _egress_scrub(messages: list[BaseMessage]) -> list[BaseMessage]:
    """egress backstop — 이번 LLM 호출 사본의 human 메시지 스크럽(멱등)."""
    if not _pii_enabled():
        return messages
    try:
        out: list[BaseMessage] = []
        for m in messages:
            if getattr(m, "type", None) != "human":
                out.append(m)
                continue
            new_content, found = _scrub_content(getattr(m, "content", None))
            out.append(m.model_copy(update={"content": new_content}) if found else m)
        return out
    except PiiScanIncomplete:
        # at-rest 와 같은 이유 — 원문을 그대로 LLM 에 보내면 안 된다.
        raise
    except Exception as e:  # noqa: BLE001
        _log.warning("chat_loop pii egress skipped: %s", e)
        return messages


def _intent_force_search(user_text: str, context: Optional[str]) -> bool:
    """규제 의도면 검색을 강제해야 하나 (의도 DGX 1콜, IntentSearchMiddleware 이식).

    턴당 한 번만 판정하며, PII 스크럽과 **병렬** 실행돼 임계 경로 왕복을 겹친다
    (순차 대비 TTFT↓). 이번-턴 미검색 여부는 호출자(루프)가 `_already_searched_this_turn`
    으로 별도 확인. 비활성·예외 시 False(안전 — 검색 안 함).
    """
    if (os.getenv("INTENT_SEARCH_DISABLE") or "").strip() == "1":
        return False
    try:
        from src.guardrail.intent import should_search

        if should_search(user_text, context):
            _log.info("chat_loop intent: qdrant_search 강제")
            return True
    except Exception as e:  # noqa: BLE001 — 강제 실패가 대화를 막으면 안 됨
        _log.warning("chat_loop intent skipped: %s", e)
    return False


def build_stable_system(extra_mid: Optional[str] = None) -> str:
    """캐시되는 stable system 프롬프트 — 실 턴과 캐시 웜퍼가 **같은 함수**를 쓴다.

    프롬프트 캐시는 바이트 단위 프리픽스 매치라, 웜퍼가 여기와 한 글자라도 다르게
    조립하면 웜핑이 무효가 된다. 날짜는 KST 일 단위(자정에 프리픽스가 바뀌고
    웜퍼가 자연히 새 프리픽스를 데운다). extra_mid = 스킬 카탈로그(스킬 턴만).
    """
    now_kst = datetime.now(timezone(timedelta(hours=9)))
    # 요일은 %a(로케일 의존 — 서버 로케일에 따라 'Fri'/cp949 깨짐) 대신 고정 매핑.
    weekday_ko = "월화수목금토일"[now_kst.weekday()]
    mid = render_reference_block()
    if extra_mid:
        mid = f"{mid}\n\n{extra_mid}"
    return SUPERVISOR_PROMPT.replace(
        "{date}", f"{now_kst.strftime('%Y-%m-%d')} ({weekday_ko})"
    ).replace("{official_sources}", mid)


def _system_blocks(stable: str, variable: Optional[str]):
    """system 프롬프트를 Anthropic 프롬프트 캐시 breakpoint 가 있는 블록 리스트로.

    안정 부분(supervisor 프롬프트 + 도구 스키마 프리픽스)에 `cache_control` 을 달아
    캐시에 태운다 → 후속 턴 TTFT↓ + 입력 토큰 비용 ~90%↓(캐시 히트 시). 가변 부분
    (보고서 컨텍스트·대화 요약)은 매 턴 달라지므로 별도 비캐시 블록. `CHAT_PROMPT_CACHE_DISABLE=1`
    이면 평문 문자열로 폴백(캐시 미사용).

    TTL 기본 1h(2026-08-14) — 베타 트래픽이 성겨 5분 캐시는 거의 항상 식어 있었고,
    1차 LLM 콜이 2만 토큰 콜드 처리로 6~7s 였다(운영 실측). 1h 쓰기는 2×(5m 는
    1.25×)지만 웜퍼(api.py)와 함께 상시 히트(0.1×)가 돼 총비용·지연 모두 준다.
    `CHAT_PROMPT_CACHE_TTL=5m` 으로 종전 동작 복귀 가능.
    """
    if (os.getenv("CHAT_PROMPT_CACHE_DISABLE") or "").strip() == "1":
        return stable + (f"\n\n{variable}" if variable else "")
    ttl = (os.getenv("CHAT_PROMPT_CACHE_TTL") or "1h").strip()
    cache_control: dict = {"type": "ephemeral"}
    if ttl and ttl != "5m":  # 5m = API 기본값이라 명시 불요
        cache_control["ttl"] = ttl
    blocks: list[dict] = [
        {"type": "text", "text": stable, "cache_control": cache_control}
    ]
    if variable:
        blocks.append({"type": "text", "text": variable})
    return blocks


def warm_prompt_cache() -> bool:
    """프롬프트 캐시 웜핑 — stable 프리픽스(tools+supervisor)를 캐시에 상주시킨다.

    리랭커 keepalive 와 같은 발상: 트래픽이 성긴 시간대에도 첫 사용자가 콜드
    프리픽스 처리(6~7s)를 맞지 않게 주기적으로 데운다. 히트 시 입력 0.1× 비용
    (2만 토큰 ≈ $0.002/회). max_tokens 를 4로 캡해 출력 비용은 무시 수준.
    스킬 변형 프리픽스는 웜핑하지 않는다(운영자 한정 노출이라 트래픽 미미).
    실패는 False — 호출부(api.py 루프)가 로그만 남기고 다음 주기 재시도.
    """
    # 자격증명 없으면(로컬 dev·테스트) 시도 자체를 안 한다 — 네트워크 재시도로
    # 테스트가 느려지는 것 방지.
    spec = os.environ.get("LLM_MODEL") or "anthropic:claude-sonnet-4-6"
    if not provider_credential_ok(split_model_spec(spec)[0]):
        return False
    try:
        primary = _base_model(spec)
        bound = primary.bind_tools(TOOL_SPECS).bind(max_tokens=4)
        system_content = _system_blocks(build_stable_system(), None)
        bound.invoke([SystemMessage(content=system_content),
                      HumanMessage(content="캐시 웜업 핑입니다. ok 라고만 답하세요.")])
        return True
    except Exception as e:  # noqa: BLE001 — 웜핑 실패가 서비스에 영향 주면 안 됨
        _log.info("prompt cache warm 실패(다음 주기 재시도): %s", e)
        return False


_CARRYOVER_CITE_RE = re.compile(r"(?<!\\)\[(\d+)\]")


def _carryover_citation_step(state, turn_steps: list[dict], body: str) -> Optional[dict]:
    """이전 턴 근거를 [n] 로 재인용한 답변에, 그 citation(스레드-안정 번호 그대로)을
    이번 턴 step 으로 이어붙인다.

    무검색·부분검색 턴에서 인용이 turn_steps 에만 매여 있어, 재사용 근거가 현재
    답변 각주로 안 뜨고 grounding 도 못 받던 갭을 메운다(번호는 이미 스레드-안정 —
    `_assign_turn_citation_numbers` 가 state.steps 를 이어 매김).

    원칙(무결·정확·정합):
    - state.steps 의 *기존* citation 만 대상 — 새 출처를 만들지 않는다(날조 0).
    - body 에 실제 등장하는 [n] 중 pool 에 존재하는 번호만. 없는 [n] 은 무시.
    - 이번 턴이 이미 커버한 번호는 제외(중복 방지).
    - 번호 재배정 없음.
    - 검증은 이후 `_apply_grounding` 이 *현재* claim 기준으로 재수행 → 못 뒷받침하면
      verified=False 로 표시(오귀속 차단).
    """
    if not body or "[" not in body:
        return None
    referenced = {int(m) for m in _CARRYOVER_CITE_RE.findall(body)}
    if not referenced:
        return None
    turn_nums = {
        c.get("number")
        for st in turn_steps
        for c in (st.get("citations") or [])
        if isinstance(c.get("number"), int)
    }
    pool: dict[int, dict] = {}
    for st in (getattr(state, "steps", None) or []):
        for c in (st.get("citations") or []):
            n = c.get("number")
            if isinstance(n, int) and n not in pool:
                pool[n] = c  # 최초(가장 이른) 등장 유지 — 원출처 id 안정
    carried = [
        dict(pool[n]) for n in sorted(referenced)
        if n in pool and n not in turn_nums
    ]
    if not carried:
        return None
    src_id, turn_idx = resolve_turn_context({"messages": getattr(state, "messages", [])})
    ts = now_ms()
    step: dict = {
        "id": new_step_id(),
        "ts": ts,
        "ended_at": ts,
        "status": "done",
        "label": "이전 근거 재인용",
        "output_preview": f"{len(carried)}건 재인용",
        "citations": carried,
    }
    if src_id is not None:
        step["source_message_id"] = src_id
    if turn_idx is not None:
        step["turn_idx"] = turn_idx
    return step


# ── 검증 불가 링크·연락처 backstop (B안) ──────────────────────────────────
# 프롬프트 가드(A)가 새도 코드가 잡는다. 파괴적 스트립이 아니라 *경고 step* 만 —
# false positive 로 정상 링크를 지우지 않기 위함(무결). URL/전화가 검색 source 에
# 실제로 등장하면 검증됨으로 통과.
_URL_RE = re.compile(
    r"https?://[^\s)\]}>,]+"
    r"|(?<![\w.@/])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
    r"(?:go\.kr|or\.kr|co\.kr|ne\.kr|com|net|org|kr)\b(?:/[^\s)\]}>,]*)?",
    re.I,
)
# 국내 전화/팩스: 0 으로 시작하는 국번 형식만(날짜 2026-07-22·조번호와 구분).
_PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}-\d{3,4}-\d{4}(?!\d)")


def _norm_for_match(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).lower()


def _unverified_contacts(body: str, haystack: str) -> list[str]:
    """답변 body 의 URL·전화번호 중 검색 source(haystack)에 없는(=검증 불가) 것.

    대소문자·공백 무시 substring — source 에 실제로 있으면 통과. 없으면 지어낸
    것으로 보고 목록에 담는다(경고용, 삭제 아님).
    """
    if not body:
        return []
    hay = _norm_for_match(haystack)
    out: list[str] = []
    seen: set[str] = set()
    for rx in (_URL_RE, _PHONE_RE):
        for m in rx.finditer(body):
            raw = m.group(0).rstrip(").,]}")
            key = _norm_for_match(raw)
            if not key or key in seen:
                continue
            # 평문 http:// 는 source 에 있더라도 신호로 잡는다(2026-08-19).
            # 실측: 답변이 `http://adv.kmdia.or.kr/ADV` 를 제시했는데 ① 스킴이
            # http ② 그 경로는 403(진입점은 루트) 였다. 공공기관 사이트는
            # 사실상 전부 https 라, http 는 출처가 낡았거나 모델이 지어낸 신호다.
            if raw.lower().startswith("http://"):
                seen.add(key)
                out.append(raw)
                continue
            if key not in hay:
                seen.add(key)
                out.append(raw)
    return out


def _turn_source_haystack(state, turn_steps: list[dict]) -> str:
    """이번 턴 검색 근거 텍스트 총합 — citation 필드 + 이번 턴 tool 메시지 원문.

    ⚠️ 공식 창구 레지스트리는 **맨 앞에** 둔다. 소비자(`audit_uncited_claims`)가
    haystack 앞부분만 잘라 쓰는데(_AUDIT_SRC_CAP), 종전엔 레지스트리가 맨 뒤라
    검색 원문에 밀려 거의 항상 잘려나갔다 — 시스템이 직접 주입한 emedi 주소·
    콜센터 번호까지 unverified 로 판정되던 원인(2026-08-13 운영 샘플 실측).
    """
    parts: list[str] = [registry_haystack()]
    for st in turn_steps:
        for c in (st.get("citations") or []):
            for k in ("url", "download_url", "title", "snippet", "text"):
                v = c.get(k)
                if v:
                    parts.append(str(v))
    for m in reversed(getattr(state, "messages", []) or []):
        t = getattr(m, "type", None)
        if t == "human":
            break  # 이번 턴 경계
        if t == "tool":
            parts.append(_msg_text(getattr(m, "content", "")))
    return "\n".join(parts)


def _detect_unverified_contacts(state, turn_steps: list[dict], body: str) -> list[str]:
    """검증 불가 URL·전화 목록 반환 — *운영자 신호 전용, 사용자 비노출*.

    이전엔 경고 step 으로 사용자에게 보였으나 "지가 답하고 지가 경고" 자기모순이라
    내부 신호로 강등(2026-07-22). 호출부가 log + events(`unverified_contact`)에 기록해
    어드민이 발생률만 관측한다. `CHAT_CONTACT_GUARD_DISABLE=1` 로 끔.
    """
    if (os.getenv("CHAT_CONTACT_GUARD_DISABLE") or "").strip() == "1":
        return []
    return _unverified_contacts(body, _turn_source_haystack(state, turn_steps))


async def _apply_grounding(turn_steps: list[dict], body: str) -> list[dict]:
    """GroundingGateMiddleware 이식 — 답변 후 [n] 인용 검증 → citations merge dict."""
    if (os.getenv("CHAT_GROUNDING_GATE_DISABLE") or "").strip() == "1":
        return []
    try:
        if not body or "[" not in body:
            return []
        affected: list[tuple[str, list[dict]]] = []
        cited: list[dict] = []
        for st in turn_steps:
            sid = st.get("id")
            cites = st.get("citations") or []
            hits = [c for c in cites
                    if isinstance(c.get("number"), int) and f"[{c['number']}]" in body]
            if sid and hits:
                affected.append((sid, cites))
                cited.extend(hits)
        if not cited:
            return []

        from src.grounding import ground_answer

        grounded = await ground_answer(body, cited)
        by_id = {c.get("id"): c for c in grounded}
        out_steps = []
        for sid, cites in affected:
            new_cites = [by_id.get(c.get("id"), c) for c in cites]
            out_steps.append({"id": sid, "citations": new_cites})
        return out_steps
    except Exception as e:  # noqa: BLE001 — 검증 실패가 답변을 막으면 안 됨
        _log.info("chat_loop grounding skipped: %s", e)
        return []


# ---------------------------------------------------------------------------
# 도구 실행 — 기존 @tool 래퍼의 Command 버전을 (ToolMessage, steps, clarify) 로
# ---------------------------------------------------------------------------
class ToolExec:
    """도구 실행 산물 — 루프가 state/repo/이벤트에 반영."""

    __slots__ = ("tool_message", "steps", "clarify")

    def __init__(self, tool_message: ToolMessage, steps: list[dict],
                 clarify: Optional[dict] = None):
        self.tool_message = tool_message
        self.steps = steps
        self.clarify = clarify


def _quota_exec(sid: str, start: dict, tcid: str, *, tool_name: str, limit: int) -> ToolExec:
    llm_msg = (
        f"[system] 이번 질문에서 {tool_name} 를 {limit}회 호출했습니다. 추가 검색 없이 "
        f"지금까지의 결과만으로 답변/보고서를 작성하세요."
    )
    user_msg = "검색을 충분히 수행해 결과 정리 단계로 넘어갑니다."
    return ToolExec(
        ToolMessage(content=llm_msg, tool_call_id=tcid),
        # 정상 전환 안내 — step_error 로 발행하면 FE 가 "오류"로 렌더한다
        # (실측: 검색 상한 도달 시 화면에 오류 표시). done + preview 로.
        [start, step_done(sid, output_preview=user_msg)],
    )


def _hit_score(h) -> float | None:
    """검색 hit 의 랭킹 점수 — API hit 은 dict, pinned 는 `_PgPoint`(점수 없음)."""
    raw = h.get("score") if isinstance(h, dict) else None
    try:
        return round(float(raw), 4) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _abort_exec(sid: str, start: dict, tcid: str, message: str) -> ToolExec:
    return ToolExec(
        ToolMessage(content=message, tool_call_id=tcid),
        [start, step_error(sid, message=message)],
    )


def _tool_tavily(args: dict, state: dict, tcid: str,
                 prefetched: Optional[list] = None) -> ToolExec:
    query = str(args.get("query") or "")
    sid, start = step_start(
        f"웹·외부 자료 검색: {query[:50]}",
        tool_name="tavily_search", input_preview=query, state=state,
    )
    _emit_step_lifecycle("start", start)
    _emit_progress("tavily_search", "started", f"웹 검색 시작: {query[:40]}")

    limit = int((os.getenv("MAX_TAVILY_CALLS_PER_RUN") or "").strip() or "3")
    if _count_tool_calls(state, "tavily_search") >= limit:
        return _quota_exec(sid, start, tcid, tool_name="tavily_search", limit=limit)
    if prefetched is not None:
        # 웹 프리페치 주입 경로 — fetch(run_tavily)는 턴 시작 시 병렬로 이미 완료
        # (순수 HTTP, 상태 무접촉 → 경합 없음). 여기선 번호매김·step 발행만 직렬.
        built = prefetched
    else:
        if not os.getenv("TAVILY_API_KEY"):
            return _abort_exec(sid, start, tcid,
                               "웹 검색 설정 누락 (TAVILY_API_KEY). 관리자에게 문의해주세요.")
        _emit_progress("tavily_search", "searching", "웹 자료 수집 중...")
        try:
            built = run_tavily(query)
        except (SearchConfigError, SearchError) as e:
            return _abort_exec(sid, start, tcid, e.user_message)

    results = [r for r, _ in built]
    for i, r in enumerate(results, start=1):
        title = r.get("title") or r.get("url", "")
        url = r.get("url", "")
        _emit_result("tavily_search", index=i, title=title[:80],
                     subtitle=_publisher_from_url(url) or "", url=url)
    _emit_progress("tavily_search", "complete", f"{len(results)}건 발견")

    citations = _assign_turn_citation_numbers(state, [c for _, c in built])
    num_by_id = {c["id"]: c["number"] for c in citations}
    text = _format_web_results(
        [(num_by_id[c["id"]], r) for r, c in built if c["id"] in num_by_id]
    )
    return ToolExec(
        ToolMessage(content=text, tool_call_id=tcid),
        [start, step_done(sid, output_preview=f"결과 {len(results)}건", citations=citations)],
    )


def _tool_qdrant(args: dict, state: dict, tcid: str) -> ToolExec:
    query = str(args.get("query") or "")
    top_k = args.get("top_k")
    if top_k is None:
        top_k = int((os.getenv("QDRANT_TOP_K") or "").strip() or "8")
    # LLM 이 종별을 지목한 검색 (판례·해석례 등 보충) — 검증 후 전달.
    doc_kinds = sanitize_doc_kinds(args.get("doc_kinds"))

    selected = [k for k in (state.get("selected_law_keys") or []) if k]
    pinned = bool(selected)
    kinds_label = ("·".join(DOC_KIND_LABELS.get(k, k) for k in doc_kinds)
                   if doc_kinds else "법령")
    label = (f"선택 법령 grounding: {len(selected)}건" if pinned
             else f"{kinds_label} 벡터 검색: {query[:50]}")
    sid, start = step_start(
        label, tool_name="qdrant_search",
        input_preview=(", ".join(selected) if pinned else query), state=state,
    )
    _emit_step_lifecycle("start", start)
    _emit_progress(
        "qdrant_search", "started",
        (f"선택 법령 {len(selected)}건 근거 구성..." if pinned
         else f"법령 벡터 검색 시작: {query[:40]}"),
    )

    limit = int((os.getenv("MAX_QDRANT_CALLS_PER_RUN") or "").strip() or "4")
    if _count_tool_calls(state, "qdrant_search") >= limit:
        return _quota_exec(sid, start, tcid, tool_name="qdrant_search", limit=limit)

    from src.observability.load import is_congested
    if not pinned and is_congested():
        _emit_progress("qdrant_search", "busy",
                       "서버 혼잡 · 응답이 평소보다 느릴 수 있어요")

    try:
        core = (run_qdrant_pinned(selected, top_k=top_k) if pinned
                else run_qdrant(query, top_k=top_k, target_types=doc_kinds))
    except SearchError as e:
        return _abort_exec(sid, start, tcid, e.user_message)

    pg_meta_by_key = core.pg_meta_by_key
    qdrant_by_key = core.qdrant_by_key
    for i, ak in enumerate(core.final_keys, start=1):
        meta = pg_meta_by_key.get(ak) or {}
        h = qdrant_by_key.get(ak)
        hp = (h.payload if hasattr(h, "payload") else h) or {}
        title = meta.get("law_title") or hp.get("law_title") or hp.get("title") or ak
        article_num = meta.get("article_num") or hp.get("article_num") or ""
        _emit_result("qdrant_search", index=i, title=str(title)[:80],
                     subtitle=str(article_num)[:40])

    # ── 검색 수집 데이터 적재(best-effort) — "이용자 질의별 어떤 법령이 수집됐나".
    # events.rag_search 1행/검색: 질의 + 히트 조문 메타. 집계는 /admin/stats/search-laws.
    try:
        from src.persistence import get_events_repo
        from src.persistence.events_repo import Event as _Ev
        import json as _json
        _hits = []
        for ak in core.final_keys[:20]:
            h = qdrant_by_key.get(ak)
            hp = (h.payload if hasattr(h, "payload") else h) or {}
            _hits.append({
                "article_key": ak,
                "law_id": hp.get("law_id") or ak.split("_")[0],
                "law_title": str(hp.get("law_title") or hp.get("title") or hp.get("article_title") or "")[:80],
                "article_num": str(hp.get("article_num") or "")[:20],
                "target_type": hp.get("target_type") or "law",
                # 리랭커 점수(2026-09-17) — 답변 검수에서 "검색은 됐는데 안 쓴 것"과
                # "검색 자체가 빗나간 것"을 사후 구분. pinned 는 검색이 없어 None.
                "score": _hit_score(h),
            })
        get_events_repo().emit(_Ev(
            id="", ts="", event_type="rag_search",
            user_id=state.get("user_id"), thread_id=state.get("thread_id"),
            payload_json=_json.dumps({
                "query": ("(pinned)" if pinned else query[:300]),
                "pinned": pinned,
                "doc_kinds": doc_kinds,
                "hit_count": len(core.final_keys),
                "hits": _hits,
            }, ensure_ascii=False),
        ))
    except Exception:
        _log.debug("rag_search event emit failed", exc_info=True)

    citations = _assign_turn_citation_numbers(state, [c for _, _, c in core.built])

    # 적용가능성 판정(2026-10-02) — 규칙(`source_filter`)이 법령명만 보고 놓친
    # 것을 받는다. 제목·발췌만 보내는 하이쿠 1콜이고, 실패하면 아무것도 거르지
    # 않는다(검증 계층이 답변을 막으면 안 된다는 이 저장소 규율).
    _unfit: dict[int, str] = {}
    try:
        from src import applicability

        _unfit = applicability.judge_sync(query, citations)
    except Exception:  # noqa: BLE001
        _log.debug("applicability judge failed", exc_info=True)
    if _unfit:
        _log.info("applicability: %d건 제외 %s", len(_unfit), sorted(_unfit))
        citations = [c for c in citations if c.get("number") not in _unfit]

    num_by_id = {c["id"]: c["number"] for c in citations}
    msg = (f"{len(citations)}건 (선택 법령 grounding)" if pinned
           else f"{len(citations)}건 매칭")
    _emit_progress("qdrant_search", "complete", msg)

    numbered_hits = [
        (num_by_id[c["id"]], h, pg_meta_by_key.get(ak))
        for ak, h, c in core.built
        if h is not None and c["id"] in num_by_id
    ]
    text = _format_rag_hits(numbered_hits)

    # 관할 되묻기(2026-10-02) — 자치법규를 다수 걸렀으면 모델에게 **지역을 묻게**
    # 한다. 버리고 입을 닫으면 "지자체마다 다르다"는 사실까지 사라지고, 추측해서
    # 특정 지자체 조례를 인용하면 그게 더 나쁜 오안내다(사용자 결정).
    _dropped = list(getattr(core, "filtered_out", None) or [])
    if _dropped:
        from src import source_filter as _sf

        _hint = _sf.region_hint(_dropped)
        if _hint:
            text = f"{text}\n\n{_hint}"
        try:
            from src.persistence import get_events_repo as _ger
            from src.persistence.events_repo import Event as _Ev2

            _ger().emit(_Ev2(
                id="", ts="", event_type="source_filter",
                user_id=state.get("user_id"), thread_id=state.get("thread_id"),
                payload_json=_json.dumps({
                    "query": query[:200],
                    "dropped": len(_dropped),
                    "kept": len(citations),
                    # 사유별 건수만 — 제목은 길고, 집계가 목적이다.
                    "reasons": {r: sum(1 for d in _dropped
                                       if d["reason"].split("(")[0] == r)
                                for r in {d["reason"].split("(")[0]
                                          for d in _dropped}},
                    "samples": [d["title"][:60] for d in _dropped[:5]],
                }, ensure_ascii=False),
            ))
        except Exception:
            _log.debug("source_filter event emit failed", exc_info=True)

    return ToolExec(
        ToolMessage(content=text, tool_call_id=tcid),
        [start, step_done(sid, output_preview=f"{len(citations)}건 매칭",
                          citations=citations, doc_kinds=doc_kinds)],
    )


def _tool_clarify(args: dict, state: dict, tcid: str) -> ToolExec:
    """interrupt 대체 — clarify 페이로드를 반환하고 루프가 **턴을 종료**한다.

    메시지 히스토리 유효성(tool_use ↔ tool_result 짝)을 위해 ToolMessage 를
    남긴다 — 다음 턴의 human 메시지가 실제 답변.
    """
    question = str(args.get("question") or "")
    options = args.get("options")
    allow_free_text = bool(args.get("allow_free_text", True))

    sid, start = step_start(
        f"추가 정보 요청: {question[:40]}",
        tool_name="ask_clarify", input_preview=question, state=state,
    )
    payload: dict = {
        "type": "clarify",
        "step_id": sid,
        "question": question,
        "allow_free_text": allow_free_text,
    }
    if options:
        payload["options"] = [str(o) for o in options]

    return ToolExec(
        ToolMessage(
            content=("[system] 사용자에게 명확화 질문을 전달했습니다. "
                     "다음 사용자 메시지가 그 답변입니다."),
            tool_call_id=tcid,
        ),
        [start, step_done(sid, output_preview="사용자 응답 대기")],
        clarify=payload,
    )


async def _inject_searches(
    searches: list[dict],
    state,
    repo,
    thread_id: str,
    user_id: Optional[str],
    emit,
    turn_steps: list[dict],
    sensitive: bool = False,
    hidden: bool = False,
) -> list[dict]:
    """커버리지 게이트(2·3층)가 지시한 겨냥 검색을 직접 실행해 히스토리에 주입.

    `sensitive`/`hidden` 은 저장 플래그(기밀 턴·조합 중간 단계) — 호출부가 턴 값을
    넘긴다. ⚠️ 2026-10-03: 본문은 이 인자를 쓰는데 시그니처에 빠져 있었다(ruff F821).
    커버리지 LLM 경로를 테스트가 스텁해 실제로 돌면 TypeError 가 나는 상태였다.

    모델에게 "다시 검색해"라고 맡기면 같은 질의를 반복할 수 있어, 심판이 지정한
    query+doc_kinds 를 그대로 tool_use/tool_result 쌍으로 실행·주입한다. 다음
    회차에 모델이 이 근거까지 보고 답변한다.
    """
    tool_calls = [
        {
            "name": "tavily_search" if s.get("lane") == "web" else "qdrant_search",
            "args": (
                {"query": s.get("query") or ""}
                | ({"doc_kinds": s["doc_kinds"]}
                   if s.get("lane") != "web" and s.get("doc_kinds") else {})
            ),
            "id": f"tc_{uuid4().hex[:10]}",
            "type": "tool_call",
        }
        for s in searches
    ]
    ai = AIMessage(content="", tool_calls=tool_calls, id=f"msg_{uuid4().hex[:12]}")
    state.messages.append(ai)
    await asyncio.to_thread(repo.append_messages, thread_id, [ai],
                            sensitive=sensitive, hidden=hidden)

    # 겨냥 검색은 **서로 독립**이라 병렬 실행한다(2026-08-19). 종전 순차 루프는
    # 검색 1건당 ~1s 를 그대로 더했다(실측: 2건 주입 시 +2.0s). 결과는 tool_calls
    # 순서대로 히스토리에 넣어야 tool_use↔tool_result 짝과 인용 번호가 안정적이다
    # — 그래서 gather 로 모아 **원래 순서대로** 반영한다.
    async def _run(tc: dict):
        tool_state = state.as_tool_state()
        tool_state["thread_id"] = thread_id
        tool_state["user_id"] = user_id
        return await _exec_tool(tc, tool_state, tc["id"])

    results = await asyncio.gather(*(_run(tc) for tc in tool_calls),
                                   return_exceptions=True)
    for tc, result in zip(tool_calls, results):
        if isinstance(result, BaseException):
            # 개별 검색 실패는 그 건만 스킵 — 단, tool_use 에는 반드시 tool_result
            # 가 짝으로 있어야 다음 회차 메시지가 유효하다(Anthropic 계약).
            _log.warning("주입 검색 실패(%s): %s", tc.get("name"), result)
            fallback = ToolMessage(
                content="검색을 완료하지 못했습니다.", tool_call_id=tc["id"])
            state.messages.append(fallback)
            await asyncio.to_thread(repo.append_messages, thread_id, [fallback],
                                    sensitive=sensitive, hidden=hidden)
            continue
        state.messages.append(result.tool_message)
        await asyncio.to_thread(repo.append_messages, thread_id,
                                [result.tool_message],
                                sensitive=sensitive, hidden=hidden)
        if result.steps:
            state.steps = merge_steps_by_id(state.steps, result.steps)
            await asyncio.to_thread(repo.merge_steps, thread_id, result.steps)
            turn_steps = merge_steps_by_id(turn_steps, result.steps)
            emit({"type": "steps", "steps": turn_steps})
    return turn_steps


async def _exec_tool(tc: dict, state: dict, tcid: str) -> ToolExec:
    name = tc.get("name")
    args = tc.get("args") or {}
    if name == "qdrant_search":
        return await asyncio.to_thread(_tool_qdrant, args, state, tcid)
    if name == "tavily_search":
        return await asyncio.to_thread(_tool_tavily, args, state, tcid)
    if name == "ask_clarify":
        return _tool_clarify(args, state, tcid)
    # 스킬 도구(load_skill/read_skill_reference) — 스킬 부착 턴에만 바인딩되므로
    # 평상시엔 진입 불가. 로직은 src/skills/chat_integration 에 격리(분리 계약).
    from src.skills import chat_integration as _skills

    if _skills.is_skill_tool(name):
        return await asyncio.to_thread(
            _skills.exec_tool, state.get("skill_session"), name, args, state, tcid)
    return ToolExec(
        ToolMessage(content=f"[system] 알 수 없는 도구: {name}", tool_call_id=tcid),
        [],
    )


# ---------------------------------------------------------------------------
# 스트리밍 헬퍼
# ---------------------------------------------------------------------------
def _chunk_text(chunk: Any) -> str:
    c = getattr(chunk, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(
            b.get("text", "") for b in c
            if isinstance(b, dict) and b.get("type", "text") == "text"
        )
    return ""


def _web_query_text(user_text: str) -> str:
    """외부(Tavily)로 나가는 검색어 — 첨부 블록 제외. 질문이 비면 첨부 파일명."""
    from src.text.messages import attachment_names, strip_attachments

    q = strip_attachments(user_text)
    if q:
        return q
    names = attachment_names(user_text)
    return " ".join(names)[:300] if names else (user_text or "")[:300]


def _with_guard_note(ai: BaseMessage, note: str) -> BaseMessage:
    """AI 메시지 사본에 가드 문구를 덧붙인다(str 은 <next_steps> 앞, 블록 리스트는 말미)."""
    from src.skills import chat_integration as _skills

    content = getattr(ai, "content", None)
    if isinstance(content, str):
        new_content = _skills.insert_guard_note(content, note)
    elif isinstance(content, list):
        new_content = list(content) + [{"type": "text", "text": note}]
    else:
        new_content = _skills.insert_guard_note(_msg_text(content), note)
    return ai.model_copy(update={"content": new_content})


def _msg_body_text(m: Optional[BaseMessage]) -> str:
    if m is None:
        return ""
    return _msg_text(getattr(m, "content", None))


async def _stream_one(model, messages, config, emit, *, message_id=None):
    """단일 스트림 — 누적 chunk 반환. message_id 지정 시 그 id 로 토큰 emit
    (자동 이어쓰기 연장분이 FE 누적을 리셋하지 않게 — applyMessageChunk 의
    isNewMessage 가 message_id 경계로 동작한다)."""
    full = None
    async for chunk in model.astream(messages, config=config):
        full = chunk if full is None else full + chunk
        t = _chunk_text(chunk)
        if t:
            emit({"type": "token", "text": t,
                  "message_id": message_id or getattr(full, "id", None)})
    if full is None:
        raise RuntimeError("모델 응답 없음(빈 스트림)")
    return full


def _auto_continue_max() -> int:
    try:
        return int((os.getenv("CHAT_AUTO_CONTINUE_MAX") or "").strip() or "2")
    except ValueError:
        return 2


async def _stream_model(model, messages, config, emit) -> AIMessage:
    full = await _stream_one(model, messages, config, emit)
    # 연장분 토큰은 첫 스트림이 쓴 것과 **같은 값**으로 emit (None 포함) —
    # message_id 가 바뀌면 FE 가 누적을 리셋한다(applyMessageChunk).
    stream_mid = getattr(full, "id", None)
    mid = stream_mid or f"msg_{uuid4().hex[:12]}"
    text = _chunk_text(full)
    meta = dict(getattr(full, "response_metadata", None) or {})
    usage = getattr(full, "usage_metadata", None)

    # 자동 이어쓰기(2026-08-24, 베타 피드백 "서류 작성이 몇 번에 끊김"):
    # CHAT_MAX_TOKENS(4096) 에서 잘리면(stop_reason=max_tokens) assistant
    # prefill 로 같은 지점부터 이어서 생성 — 사용자에겐 하나의 답변으로 보인다.
    # 상한(CHAT_AUTO_CONTINUE_MAX, 기본 2회)까지 자동, 그래도 잘리면 done 에
    # truncated 플래그를 실어 FE 가 [이어서 작성] 버튼을 띄운다.
    # tool_calls 가 있는 스트림은 제외 — 답변 본문 생성만 대상.
    n = 0
    while (meta.get("stop_reason") == "max_tokens"
           and not (getattr(full, "tool_calls", None) or [])
           and n < _auto_continue_max()):
        n += 1
        _log.info("auto-continue %d/%d (stop_reason=max_tokens, %d자)",
                  n, _auto_continue_max(), len(text))
        # ⚠️ Anthropic prefill 규약: 마지막 assistant 내용이 공백으로 끝나면 400.
        prefill = AIMessage(content=text.rstrip())
        cont = await _stream_one(
            model, list(messages) + [prefill], config, emit,
            message_id=stream_mid)
        cont_text = _chunk_text(cont)
        if not cont_text:
            break
        text = text + cont_text
        meta = dict(getattr(cont, "response_metadata", None) or {})
        cu = getattr(cont, "usage_metadata", None)
        if usage and cu:  # 토큰 회계 합산(llm_call 이벤트 정확성)
            usage = {
                "input_tokens": (usage.get("input_tokens") or 0) + (cu.get("input_tokens") or 0),
                "output_tokens": (usage.get("output_tokens") or 0) + (cu.get("output_tokens") or 0),
                "total_tokens": (usage.get("total_tokens") or 0) + (cu.get("total_tokens") or 0),
            }
        full = cont  # tool_calls 판정은 마지막 스트림 기준
    if meta.get("stop_reason") == "max_tokens" and not (getattr(full, "tool_calls", None) or []):
        meta["truncated"] = True

    # AIMessageChunk → 순수 AIMessage (직렬화·히스토리 안정)
    if n == 0:
        content = full.content
    else:
        content = text  # 연장 병합본(텍스트 전용)
    return AIMessage(
        content=content,
        tool_calls=list(getattr(full, "tool_calls", None) or []),
        id=mid,
        response_metadata=meta,
        usage_metadata=usage,
    )


# ---------------------------------------------------------------------------
# 턴 실행 — 이벤트 async generator (route 가 SSE 로 중계)
# ---------------------------------------------------------------------------
async def run_chat_turn(
    thread_id: str,
    user_text: str,
    *,
    user_id: Optional[str] = None,
    selected_law_keys: Optional[list[str]] = None,
    model_name: Optional[str] = None,
    models: Optional[tuple[Any, Any]] = None,  # 테스트 주입용 (normal, forced)
    style: Optional[str] = None,  # "expert" | "simple" — 답변 설명 수준
    confidential: bool = False,  # 기밀 모드 — 온프레미스 전용 처리
    hidden: bool = False,  # 조합 중간 단계 — 채팅에 렌더하지 않는다
    skill_hint: Optional[str] = None,  # "irb_drb" — 프런트 버튼 명시 진입
) -> AsyncIterator[dict]:
    """한 턴 실행 — 이벤트 dict 스트림.

    이벤트: meta / token / tool_progress / step_lifecycle / steps / clarify /
            error / done. 도구 코어의 emit(워커 스레드)은 progress sink 로 합류.
    """
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _sink(payload: dict) -> None:  # 워커 스레드에서 호출됨 — thread-safe 전달
        loop.call_soon_threadsafe(queue.put_nowait, dict(payload))

    def _emit(ev: dict) -> None:
        queue.put_nowait(ev)

    async def _worker() -> None:
        token = set_progress_sink(_sink)
        lock = _acquire_turn_lock(thread_id)
        try:
            async with lock:  # 같은 thread 턴 직렬화(interleave 방지)
                await _run_turn(
                    thread_id, user_text, user_id=user_id,
                    selected_law_keys=selected_law_keys,
                    model_name=model_name, models=models, emit=_emit,
                    style=style, confidential=confidential, hidden=hidden,
                    skill_hint=skill_hint,
                )
        except Exception as e:  # noqa: BLE001 — 스트림에 사용자향 에러 후 종료
            _log.exception("chat_loop turn failed: %s", e)
            _emit({
                "type": "error",
                "message": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            })
        finally:
            _release_turn_lock(thread_id)
            reset_progress_sink(token)
            # 보조 호출 정책도 턴과 함께 끝난다 — 안 지우면 다음 턴(같은 태스크·
            # 테스트)이 앞 턴의 기밀 정책을 물려받는다(2026-10-03 실측: 전체
            # 테스트 순서에서만 applicability 가 "원내 없음→생략" 을 상속해 실패).
            _AUX_POLICY.set(None)
            queue.put_nowait(_DONE)

    task = asyncio.create_task(_worker())
    try:
        while True:
            ev = await queue.get()
            if ev is _DONE:
                break
            yield ev
    finally:
        if not task.done():
            # 클라이언트 중단(탭 닫힘·이탈) — 종전엔 여기서 task.cancel() 로
            # 워커를 죽였다. 그런데 답변 영속(ai append)은 스트림 **완료 후**라,
            # 취소하면 그때까지 생성된 답변이 통째로 유실되고 로그도 없었다
            # (2026-08-11 발견 — thread 에 질문만 남는 상태). 취소 대신 **분리**:
            # 워커가 끝까지 돌아 답변·steps 를 영속하고 턴 락도 정상 해제한다.
            # 큐는 소비자 없이 커지지만 턴 1개 분량이고 태스크 종료와 함께 GC.
            # 같은 스레드 재질문은 턴 락이 직렬화하므로 안전(완주까지 대기).
            _log.warning(
                "chat_loop: 클라이언트 스트림 중단 — 턴 백그라운드 완주 (thread=%s)",
                thread_id)
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None)
        else:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


async def _run_turn(
    thread_id: str,
    user_text: str,
    *,
    user_id: Optional[str],
    selected_law_keys: Optional[list[str]],
    model_name: Optional[str],
    models: Optional[tuple[Any, Any]],
    emit,
    style: Optional[str] = None,
    confidential: bool = False,  # 기밀 모드 — 온프레미스 전용 처리
    hidden: bool = False,  # 조합 중간 단계 — 채팅에 렌더하지 않는다
    skill_hint: Optional[str] = None,
) -> None:
    # 동기 I/O(SQLite·PII NER HTTP)는 전부 to_thread — 이벤트 루프 점유 방지.
    # (20인 동시 부하 실측에서 /healthz 지연 ~7s 스파이크의 원인이었음.)
    repo = get_threads_repo()
    await asyncio.to_thread(repo.ensure_thread, thread_id, user_id=user_id)
    await asyncio.to_thread(repo.set_selected_law_keys, thread_id, selected_law_keys)
    state: ThreadState = await asyncio.to_thread(repo.get_state, thread_id)

    # 기밀 단계 격리(2026-10-02) — **비기밀 턴은 기밀 메시지를 보지 못한다.**
    #
    # 이게 단계별 기밀의 전부다. 요청 컨텍스트는 스레드 전체 이력이라, 이 필터가
    # 없으면 앞 기밀 단계 내용이 다음 비기밀 단계에서 통째로 상용 모델로 나간다.
    # UI 토글만 두는 것은 보호가 아니라 보호하는 척이다.
    #
    # 압축보다 **먼저** 건다 — 이후 경로(요약·의도판정·도구 카운트·egress)가 전부
    # 걸러진 이력만 보도록. 기밀 턴은 원내 모델이므로 전체를 본다.
    if not confidential:
        state = _drop_sensitive(state)

    # 대화 압축 — 임계 초과 시 오래된 턴을 요약으로 대체(working set 만, DB 보존).
    working, summary = await _maybe_compact(repo, state)
    state.messages = working  # 이후 turn 컨텍스트·도구 카운트도 압축본 기준

    # PII 스크럽(at-rest)과 의도판정(검색 강제)은 서로 독립한 DGX 호출 —
    # 병렬 실행해 임계 경로에서 왕복 하나를 겹친다(순차 대비 TTFT↓). 의도는
    # 원문 기준(스크럽은 규제 의도 신호를 안 바꿈), 이번 턴 1회만 판정.
    prev_humans = [m for m in state.messages if getattr(m, "type", None) == "human"]
    intent_ctx = (
        _msg_text(getattr(prev_humans[-1], "content", None))[:60]
        if prev_humans else None
    )
    # 기밀 턴은 의도 분류 서비스에 원문을 보내지 않는다(2026-10-03) — 원내 DGX 가
    # 전제지만 코드에 강제가 없었다. 기밀이면 규제 질의로 보고 검색을 강제한다
    # (휴리스틱 폴백도 거치지 않는다 — 어차피 기밀 질의는 거의 전부 규제 질의다).
    if confidential:
        _scrub_result = await asyncio.to_thread(_scrub_user_text, user_text)
        turn_force_search = True
    else:
        _scrub_result, turn_force_search = await asyncio.gather(
            asyncio.to_thread(_scrub_user_text, user_text),
            asyncio.to_thread(_intent_force_search, user_text, intent_ctx),
        )
    scrubbed, pii_found, pii_spans = _scrub_result

    # 기관 내부 지침 스킬(IRB/DRB) — 3단 스위치(env·화이트리스트·프리게이트/스티키).
    # 전부 off 면 이 턴은 기존 흐름과 완전 동일(도구·카탈로그·강제 미부착).
    # 로직은 src/skills/chat_integration 에 격리 — 순수 함수·LLM 무호출.
    from src.skills import chat_integration as _skills

    turn_skill, turn_skill_force = _skills.resolve_turn_skill(
        user_id, state.messages, state.summary_text, user_text,
        hint=(skill_hint == "irb_drb"))
    if turn_skill:
        _log.info("chat_loop skills: 부착 (force=%s)", turn_skill_force)

    # at-rest PII 스크럽 후 저장 (PiiGate before_agent 대응)
    human = HumanMessage(content=scrubbed, id=f"msg_{uuid4().hex[:12]}")
    state.messages.append(human)
    await asyncio.to_thread(repo.append_messages, thread_id, [human],
                            sensitive=confidential, hidden=hidden)
    # `hidden` 은 스트리밍 중에도 필요하다 — 안 주면 조합 단계가 화면에 쏟아졌다가
    # 새로고침 후에야 사라진다.
    emit({"type": "meta", "thread_id": thread_id, "human_message_id": human.id,
          **({"hidden": True} if hidden else {})})

    # 입력이 PII 필터링된 경우 프론트에 알림(배지/토스트). 카테고리는 중복 제거.
    # 프론트: 이 메시지에 "개인정보(이름·주소 등)가 자동 제거되었습니다" 가벼운 표시.
    # masked_text(2026-08-13) = 저장·표시되는 마스킹본 그대로 — 프런트가 원문(클라
    # 메모리)과 대조해 **어떤 단어**가 치환됐는지 짚어 토스트에 보여주고, 오탐이면
    # 그 단어로 신고(POST /feedback/pii)하게 한다. 서버는 원문을 모른 채로 유지.
    pii_categories = sorted(set(pii_found))
    if pii_categories:
        emit({"type": "pii_notice", "thread_id": thread_id,
              "human_message_id": human.id, "categories": pii_categories,
              "masked_text": scrubbed})
    # NER 마스킹 단어 전수 수집(2026-08-13) — 신고 여부와 무관하게 개선리스트에
    # 쌓아 관리자가 correct/wrong 라벨링. 실패해도 대화는 계속(경고 로그로 관측).
    if pii_spans:
        try:
            from src.guardrail import pii_terms as _pii_terms

            # 원문(user_text)은 여기서만 쓰고 저장하지 않는다 — 가린 글 기준 자리 문맥만 남긴다.
            await asyncio.to_thread(
                _pii_terms.observe_many, pii_spans, thread_id=thread_id,
                message_id=human.id, original=user_text, masked=scrubbed)
        except Exception:  # noqa: BLE001
            _log.warning("pii_terms observe_many failed", exc_info=True)

    # 이용자 질문 수집(best-effort) — 질문 유형 분석·기능 개선용(운영자 요청
    # 2026-07-21). 마스킹본(scrubbed)만 적재. 조회: GET /admin/questions.
    try:
        import json as _json

        from src.persistence import get_events_repo
        from src.persistence.events_repo import Event as _Ev

        await asyncio.to_thread(get_events_repo().emit, _Ev(
            id="", ts="", event_type="user_question",
            user_id=user_id, thread_id=thread_id,
            payload_json=_json.dumps(
                {"question": scrubbed[:300],
                 "forced_search": bool(turn_force_search),
                 # 스킬 부착 턴 표시 — 검수 큐가 인용 축을 적용하지 않게(2026-09-17).
                 **({"skill": True} if turn_skill else {}),
                 # 마스킹 발생 턴 표시 — admin 오탐 점검(개선리스트)에서 필터용.
                 **({"pii": pii_categories} if pii_categories else {}),
                 # 프롬프트 변경 전후 품질 비교용(supervisor 버전 라벨).
                 "prompt_version": _SUPERVISOR_PROMPT_VERSION},
                ensure_ascii=False),
        ))
    except Exception:
        _log.debug("user_question emit failed", exc_info=True)

    # 보고서 중단 발화(2026-09-02) — "보고서 중단해줘" 류. 자유 텍스트로
    # 파괴적 행동을 실행하지 않는다(트리거가 버튼-멱등인 것과 대칭). 진행
    # 중 run 이 실제로 있을 때만 LLM 없이 [중단] 버튼 안내로 턴을 마친다.
    # 대화 모델은 설계상 보고서 진행을 모르므로(분리 계약) 모델에 맡기면
    # "중단했다"고 지어낼 위험이 있다.
    if _CANCEL_INTENT_RE.search(user_text or ""):
        from src.persistence import get_report_runs_repo

        _active_run = await asyncio.to_thread(
            get_report_runs_repo().latest_running_for_thread, thread_id)
        if _active_run is not None:
            notice = (
                "진행 중인 심층 보고서가 있어요. 실수 방지를 위해 대화로는 "
                "중단하지 않습니다 — 화면 우측 **진행 카드의 [중단] 버튼**을 "
                "눌러 확인 후 중단할 수 있어요. 버튼을 누르기 전까지 작성은 "
                "계속 진행됩니다."
            )
            ai_notice = AIMessage(content=notice, id=f"msg_{uuid4().hex[:12]}")
            state.messages.append(ai_notice)
            await asyncio.to_thread(repo.append_messages, thread_id, [ai_notice],
                                    sensitive=confidential, hidden=hidden)
            emit({"type": "token", "text": notice, "message_id": ai_notice.id})
            emit({"type": "done", "thread_id": thread_id,
                  "message_id": ai_notice.id, "text": notice, "steps": []})
            return

    # 스킬 턴 로컬 라우팅(2026-08-28) — 심의 질의는 민감 정보가 실리기 쉬워
    # 상용 노출 자체를 없앤다(SKILL_LOCAL_MODEL=1). 로컬 다운이면 상용 폴백
    # 없이 안내 후 종료(유출 정책이 시간대에 따라 구멍 나지 않게 — 새벽 4시
    # vLLM 재구동 포함). 테스트 모델 주입(models=) 경로는 종전과 동일.
    # 기밀 모드(2026-10-01) — 변호사가 사건 파일·의뢰인 사실관계를 다룰 때 켠다.
    # 스킬 턴과 **같은 경로**로 처리한다: 온프레미스 모델 + 웹 도구 제거 + 상용
    # 폴백 없음. 둘 중 하나라도 켜지면 로컬로 보낸다.
    local_skill_model: Optional[str] = None
    if (turn_skill or confidential) and models is None:
        from src import skill_local as _skill_local

        # ⚠️ fail-closed — 기밀 모드를 켰는데 온프레미스 라우팅이 **설정되어 있지
        # 않으면** 상용 모델로 조용히 넘어가서는 안 된다. 사용자는 보호받는다고
        # 믿고 사건 파일을 넣는다. 설정이 없으면 답하지 않고 알린다(2026-10-01).
        if confidential and not _skill_local.enabled():
            notice = _skill_local.CONFIDENTIAL_NOT_CONFIGURED_NOTICE
            ai_notice = AIMessage(content=notice, id=f"msg_{uuid4().hex[:12]}")
            state.messages.append(ai_notice)
            await asyncio.to_thread(repo.append_messages, thread_id, [ai_notice],
                                    sensitive=confidential, hidden=hidden)
            emit({"type": "token", "text": notice, "message_id": ai_notice.id})
            emit({"type": "done", "thread_id": thread_id,
                  "message_id": ai_notice.id, "text": notice, "steps": []})
            _log.warning("기밀 모드 요청됐으나 온프레미스 라우팅 미설정 — "
                         "상용 폴백 금지, 안내 후 종료")
            return

        if _skill_local.enabled():
            local_skill_model = await asyncio.to_thread(_skill_local.probe)
            if not local_skill_model:
                notice = (_skill_local.CONFIDENTIAL_UNAVAILABLE_NOTICE
                          if confidential and not turn_skill
                          else _skill_local.UNAVAILABLE_NOTICE)
                ai_notice = AIMessage(content=notice,
                                      id=f"msg_{uuid4().hex[:12]}")
                state.messages.append(ai_notice)
                await asyncio.to_thread(
                    repo.append_messages, thread_id, [ai_notice],
                    sensitive=confidential, hidden=hidden)
                emit({"type": "token", "text": notice,
                      "message_id": ai_notice.id})
                emit({"type": "done", "thread_id": thread_id,
                      "message_id": ai_notice.id, "text": notice, "steps": []})
                _log.warning("skill_local: 로컬 모델 사용 불가 — 안내 후 종료 "
                             "(상용 폴백 금지)")
                return
            _log.info("skill_local: 로컬 라우팅 — model=%s confidential=%s",
                      local_skill_model, confidential)
            # 어떤 경로로 처리되는지 사용자에게 알린다(2026-10-01 요구) — 조용히
            # 원내 모델로 돌면 사용자는 보호되는지 알 수 없고, 반대로 보호된다고
            # 착각할 수도 있다. 실제 라우팅이 확정된 **이 지점**에서만 보낸다.
            emit({
                "type": "processing_mode",
                "thread_id": thread_id,
                "local": True,
                "confidential": bool(confidential),
                "web_search": False,   # 로컬 라우팅 턴은 웹 도구를 받지 않는다
            })
            if confidential:
                # 이 스레드에 기밀 내용이 들어왔음을 영속한다. 이후 기밀을 끄면
                # 저장된 이 대화가 통째로 상용 모델로 가므로 FE 가 경고해야 한다.
                # ⚠️ 삼키지 않는다(2026-10-03). 종전엔 WARNING 한 줄이었다 — 기록이
                # 안 되면 FE 가 "기밀 끄면 이 대화가…" 경고를 못 띄우고, 사용자는
                # 모른 채 끈다. 보호 기록 실패는 답변 실패와 같은 무게다.
                try:
                    await asyncio.to_thread(repo.mark_confidential, thread_id)
                except Exception as e:  # noqa: BLE001
                    _log.error("confidential_seen 기록 실패 thread=%s", thread_id,
                               exc_info=True)
                    notice = ("기밀 보호 기록을 저장하지 못해 이 요청을 처리하지 "
                              "않았습니다. 잠시 후 다시 시도해 주세요.")
                    emit({"type": "error", "message": notice})
                    raise RuntimeError("confidential_seen 기록 실패") from e

    # 이 턴의 보조 호출 정책 — 여기서부터 압축·심판·grounding·감사·기입이 전부 본다.
    set_aux_policy(confidential=bool(confidential), local_model=local_skill_model)

    # system prompt — supervisor(안정, 캐시) + 가변(보고서 컨텍스트·요약, 비캐시).
    # 안정 부분에 캐시 breakpoint → tools+supervisor 프리픽스를 프롬프트 캐시에 태운다.
    # SUPERVISOR + 검증된 공식 창구 참고(레지스트리, {official_sources} placeholder).
    # ⚠️ 레지스트리는 프롬프트 *중간*(검색도구 뒤)에 주입 — 끝에 append 하면 출력
    # 계약(<next_steps> 마커·면책)이 프롬프트 끝에서 밀려 recency 약화 → next_steps
    # 누락(2026-07-23 버그). 계약은 프롬프트 끝에 유지.
    # 날짜는 **KST 고정** — 컨테이너 TZ(docker-compose 는 Asia/Seoul 이지만 dev·
    # CI 는 UTC)에 따라 서버 로컬 날짜가 하루 어긋나던 문제. KST 는 DST 없어 +9 고정.
    _now_kst = datetime.now(timezone(timedelta(hours=9)))
    # 스킬 부착 턴 — 턴마다 로더 세션 새로 생성(README 계약: 인스턴스 재사용 금지).
    # 히스토리에 이미 실린 지침은 seed 로 중복 억제(압축으로 접힌 건 재로드 허용).
    skill_session = _skills.new_session(state.messages) if turn_skill else None
    # 카탈로그는 프롬프트 *중간*(공식 창구 레지스트리 자리)에 주입 — 끝에 붙이면
    # <next_steps> 계약이 밀려 누락된다(2026-07-23 버그와 동일 원리). 스킬 유/무로
    # stable 프리픽스는 2종 — 스티키(스레드 단위 고정) 덕에 캐시가 번갈아 깨지지 않음.
    stable_system = build_stable_system(
        _skills.catalog_block(skill_session) if skill_session is not None else None)
    _variable_parts: list[str] = []
    # 현재 시각 — **가변부(비캐시)에만** 넣는다. stable_system 에 분 단위 값을
    # 박으면 매 턴 프리픽스가 바뀌어 프롬프트 캐시가 전부 깨진다(비용·지연).
    # supervisor v14 E 분기("지금 몇 시야")가 이 라인을 참조 — 라인명 변경 시 짝 수정.
    _variable_parts.append(
        f"[현재 시각] {_now_kst.strftime('%Y-%m-%d %H:%M')} (KST, 한국 표준시)"
    )
    # 답변 설명 수준(사용자 선택) — 시스템 프롬프트 가변부(비캐시)에 부착.
    if style == "expert":
        _variable_parts.append(
            "답변 스타일: 전문가(RA/QA) 대상 — 조문 번호·원문 표현 중심으로 간결하게. "
            "기초 개념 설명은 생략한다.")
    elif style == "simple":
        # 한 문장짜리 지침은 긴 시스템 프롬프트(조문 중심 답변)에 밀려 거의
        # 반영되지 않았다 — 같은 질문에 expert/simple 답변이 사실상 동일했다
        # (2026-10-01 측정). 규칙을 구체화해 실제로 어투가 갈리게 한다.
        _variable_parts.append(
            "답변 스타일: 일반인 대상.\n"
            "- 첫 문단은 결론을 한두 문장으로. 조문 인용으로 시작하지 않는다.\n"
            "- 법률 용어는 일상어로 먼저 설명하고 조문은 괄호로 뒤에 붙인다. "
            "예: \"식약처 승인을 받아야 합니다(의료기기법 제10조)\"\n"
            "- \"무엇을 → 어디에 → 어떤 서류로\" 순서의 절차 안내를 우선한다.\n"
            "- 약어(IND·GCP·RA/QA 등)는 풀어 쓰거나 쓰지 않는다.\n"
            "- 표·중첩 목록보다 짧은 문단과 번호 목록을 쓴다.\n"
            "- [n] 인용 표기는 그대로 유지한다.")
    # 입력에 개인정보가 있어 [이름]/[주소] 등으로 치환된 턴 — 모델이 자리표시자를
    # 실제 값으로 오해하지 않도록 지침. 2분기: (a) 자리표시자를 빼도 일반 규제 질문이
    # 남으면 그걸 답하고, (b) 질문이 오직 특정 개인·주소 조회뿐이라 답할 내용이 없으면
    # (예: "[이름] 알려줘", "[주소] 판례") 억지로 답하지 말고 안내한다.
    # (사용자 결정: 알림 + 일반질문이면 일반답변)
    if pii_categories:
        _variable_parts.append(
            "이번 질문에는 개인정보가 포함되어 자리표시자([이름]·[주소] 등)로 자동 치환되었다. "
            "자리표시자를 실제 값으로 추측하거나 특정 개인·주소를 조회하려 하지 마라. "
            "다음 둘 중 하나로 처리하라: "
            "(a) 자리표시자를 걷어내도 일반적인 규제·법령 질문이 남으면, 답변 서두에 '입력에 포함된 "
            "개인정보는 제외하고 일반적인 관점에서 답변드린다'고 이유를 한 문장으로 먼저 밝힌 뒤, "
            "특정 개인과 무관한 그 일반 질문에 답한다. 이때도 URL·전화번호는 검증원이 있는 것(검색 "
            "결과 또는 시스템이 제공한 '공식 창구 참고')만 정확히 제공하고, 어디에도 없으면 지어내지 "
            "말고 '식약처 공식 채널에서 확인'으로 대신한다(추측한 링크·번호를 표에 채우지 말 것). "
            "(b) 질문이 오직 특정 개인·주소를 조회·특정하는 것뿐이라 자리표시자를 빼면 답할 실질이 "
            "없으면(예: '[이름] 알려줘', '[주소] 판례 알려줘'), 지어내지 말고 짧게 안내한다 — "
            "'입력에 개인정보가 포함되어 자동으로 필터(제거)되었고 특정 개인·주소는 조회해 드릴 수 "
            "없으니, 개인정보를 빼고 일반적인 규제·법령 질문으로 다시 물어봐 달라'는 취지. "
            "필터되는 정보 종류를 일일이 나열하지는 마라.")
    # 채팅↔보고서 완전 분리(2026-07-25 사용자 요구) — 보고서 컨텍스트를 채팅
    # 시스템 프롬프트에 **주입하지 않는다**. 구 `_report_context_block` 은
    # ⓐ "[진행 상황] 보고서 작성 중" 지시 ⓑ 과거 보고서 목록 + `read_report`
    # 호출 지시를 넣었는데, ⓑ 는 **존재하지 않는 도구**였다(도구는 qdrant·
    # tavily·ask_clarify 3개) — 모델이 부를 수 없는 것을 부르라는 죽은 지시.
    # 진행/완료는 프런트가 `/reports/runs/{key}` 폴링으로 알므로 대화 모델이
    # 보고서를 알 필요가 없다. (제거된 함수: _report_context_block)
    # 작성 중인 서식은 **예외적으로** 대화 모델에게 알린다(2026-08-27). 보고서와
    # 달리 서류는 사용자가 *이 대화로* 채우는 대상이라, 모델이 그 존재를 모르면
    # 남은 칸을 물어봐 주지도, 이미 채운 걸 안 묻지도 못한다(두 입력 경로가
    # 한 화면에 있는데 서로를 모르는 상태). 항목명·진행률만 — **값은 넣지
    # 않는다**(개인정보는 온프레미스 기입 모델만 본다).
    try:
        from src.doc_fill import draft_context_note

        _doc_note = await asyncio.to_thread(draft_context_note, thread_id)
        if _doc_note:
            _variable_parts.append(_doc_note)
    except Exception:  # noqa: BLE001
        # 조용히 넘기면 "왜 서식을 모르지"가 원인 불명이 된다 — 배선 오류를
        # 은폐하지 않도록 warning(CLAUDE.md §6).
        _log.warning("서식 진행 주입 실패 — 대화가 서류를 모른 채 진행",
                     exc_info=True)
    # 광의 게이트(2026-09-10) — 스킬은 안 붙이고 **심의 가능성 고지만** 유도.
    # 스킬이 붙은 턴(turn_skill)은 이미 판정을 하므로 중복 고지하지 않는다.
    if not turn_skill and _skills.skills_configured():
        try:
            if _skills.is_review_adjacent(user_text):
                _variable_parts.append(_skills.REVIEW_NUDGE)
                _log.info("chat_loop skills: 광의 게이트 적중 — 심의 가능성 고지")
        except Exception:  # noqa: BLE001 — 고지 실패가 답변을 막으면 안 된다
            _log.warning("심의 가능성 고지 주입 실패", exc_info=True)
    if summary:
        _variable_parts.append(
            f"[이전 대화 요약 — 오래된 턴은 아래 요약으로 압축됨]\n{summary}"
        )
    system_content = _system_blocks(stable_system, "\n\n".join(_variable_parts) or None)

    if models is not None:
        # 테스트 주입: (normal, forced[, forced_web[, forced_skill]]).
        # 2튜플이면 웹게이트 비활성, 4번째 없으면 스킬 강제 비활성.
        normal, forced, *_rest = models
        forced_web = _rest[0] if _rest else None
        forced_skill = _rest[1] if len(_rest) > 1 else None
    else:
        # A/B 배정(CHAT_MODEL_AB) — user 해시로 변형 선택. 명시 오버라이드 없을 때만.
        ab_spec, ab_variant = _ab_model(user_id, model_name)
        if ab_variant:
            _log.info("chat_loop A/B: variant=%s spec=%s user=%s",
                      ab_variant, ab_spec, (user_id or "anon"))
            try:  # 변형을 events 에 태깅 — 피드백/지연/비용 비교용(비차단)
                from src.persistence import Event, get_events_repo
                get_events_repo().emit(Event(
                    id="", ts="", event_type="model_ab",
                    user_id=user_id, thread_id=thread_id,
                    payload_json=json.dumps(
                        {"variant": ab_variant, "spec": ab_spec},
                        ensure_ascii=False),
                ))
            except Exception:  # noqa: BLE001 — 태깅 실패가 채팅을 막으면 안 됨
                pass
        normal, forced, forced_web, forced_skill = build_models(
            ab_spec or model_name,
            skill_tools=(skill_session.tool_defs() if skill_session else None),
            local_skill_model=local_skill_model)
    # 귀속을 이 턴 전체(하위 태스크·to_thread 포함)에 심는다. 로거는
    # build_chat_model 이 모델마다 붙이므로 config 로는 안 넘긴다(2026-08-05).
    usage_context.bind(thread_id=thread_id, user_id=user_id)
    config = {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
    }

    turn_steps: list[dict] = []  # 이번 턴 발행 steps (grounding·done 이벤트용)
    try:
        call_limit = int((os.getenv("MAX_MODEL_CALLS_PER_RUN") or "").strip() or "250")
    except ValueError:
        call_limit = 250

    ai: Optional[AIMessage] = None
    calls = 0
    sufficiency_retried = False  # #6 1층: 근거 0건 시 재검색 1회만(무한 방지)
    coverage_checked = False     # #6 2·3층: 턴당 1사이클만
    # 웹 프리페치(지연 개선 2026-07-25) — 규제 턴이면 tavily fetch 를 턴 시작과
    # 동시에 병렬로 띄운다. 구 forced_web 바인딩은 "웹 쿼리 한 줄 만들려는 LLM
    # 왕복"(대형 컨텍스트 ~4-8s) + 웹 검색이 qdrant 뒤 직렬이었다(실측 TTFT
    # 54~60s의 주범 중 하나). run_tavily 는 순수 HTTP(상태 무접촉)라 경합 없음 —
    # 번호매김·step 발행은 주입 시점(직렬)에. 실패 시 기존 forced_web 바인딩 폴백.
    web_prefetch: Optional[asyncio.Task] = None
    web_skip = False  # 프리페치 실패 시 이번 턴 웹 강제 억제(아래 주입 블록에서 set)
    if (
        turn_force_search
        # 스킬 턴 — 병원 SOP 논점이라 웹 레인이 무의미하고, 무엇보다 검색어가
        # 외부로 나간다. 종전엔 `turn_skill_force`(이번 턴 질의가 IRB/DRB)만
        # 봐서, **스티키 후속 턴**(attach=True·force=False, 예: "그럼 서류는?")이
        # 온프레미스 모델로 돌면서도 웹 프리페치는 열려 있었다 — 2026-09-10 발견.
        # 부착 기준(turn_skill)으로 바꿔 그 구멍을 닫는다.
        and not turn_skill
        and forced_web is not None
        and os.getenv("CHAT_FORCE_WEB", "1") == "1"
        and os.getenv("TAVILY_API_KEY")
    ):
        # 인젝션·유출 보강(2026-09-15): 첨부 전문을 검색어로 보내지 않는다 — 질문
        # 텍스트만, 질문이 비면 첨부 파일명으로 검색한다.
        web_prefetch = asyncio.create_task(
            asyncio.to_thread(run_tavily, _web_query_text(scrubbed)))
        # 미소비 종료(clarify 등) 대비 — 예외 미회수 경고 억제.
        web_prefetch.add_done_callback(
            lambda t: t.exception() if not t.cancelled() else None)
    while True:
        calls += 1
        if calls > call_limit:
            # ModelCallLimitMiddleware(exit_behavior="end") 대응 — graceful 종료.
            _log.warning("chat_loop: 모델 호출 상한(%d) 도달 — 턴 종료", call_limit)
            break

        # 스킬 사슬 맨 앞 — 이번 턴 질의가 IRB/DRB(프리게이트 발화)면 load_skill 을
        # 1회차 강제(지침 우선 계약 — 검색·답변보다 먼저). 로드 후엔 해제(기존
        # 사슬이 이어받아 qdrant 검색까지 수행). 스티키만으로는 강제하지 않는다
        # (문진 후속 답변엔 히스토리의 지침이 이미 있다 — 부착 ≠ 강제).
        force_skill = (
            turn_skill_force
            and forced_skill is not None
            and not _tool_called_this_turn(state.messages, "load_skill")
        )
        # 이번 턴 규제 의도(사전 병렬 판정) + 아직 미검색이면 qdrant 강제 바인딩.
        # 검색 후엔 _already_searched_this_turn=True 라 강제 해제(무한 강제 방지).
        force_qdrant = (
            not force_skill
            # 스킬 판정 턴(프리게이트 발화)은 강제 제외 — 병원 SOP 논점이라
            # 법령 검색 강제는 무관 조문 노이즈만 넣는다(2026-09-02 실측:
            # "IRB 소요기간" 질의에 대통령직인수법이 상위). 모델 재량 검색은
            # 여전히 가능(법령 근거가 필요한 심의 질의 대비). 웹 레인 제외
            # (turn_skill_force 조건)와 같은 근거.
            and not turn_skill_force
            and turn_force_search
            and not _already_searched_this_turn(state.messages)
        )
        # #6 충분성 게이트(규칙 기반) — 검색은 했는데 확보 근거가 0건(빈손)이면,
        # 모델이 근거 없는 답을 스트리밍하기 *전에* qdrant 재검색을 1회 강제한다.
        # forced 회차엔 답변 텍스트가 안 나오므로 이중 답변 없음. 1회만(무한 방지).
        if (
            not force_skill
            and not force_qdrant
            and turn_force_search
            # 스킬 지침을 로드한 턴은 면제 — SOP 기반 답변은 [n] 인용 0건이
            # 정상이라, 이 게이트가 불필요한 재검색 회차를 끼운다.
            and not _tool_called_this_turn(state.messages, "load_skill")
            and _already_searched_this_turn(state.messages)
            and not sufficiency_retried
            and _turn_citation_count(turn_steps) == 0
            # ⚠️ dict 뷰 필수 — ThreadState 객체를 그대로 넘기면 .get 크래시.
            # 검색 실패 시에만 타는 분기라 잠복했었다(실측 2026-07-24: ETL 재배포
            # 순간 검색 오류 → 이 분기 진입 → 턴 전체가 일반 오류로 사망).
            and _count_tool_calls(state.as_tool_state(), "qdrant_search")
            < int((os.getenv("MAX_QDRANT_CALLS_PER_RUN") or "").strip() or "4")
        ):
            force_qdrant = True
            sufficiency_retried = True
            _log.info("chat_loop: 근거 0건 — 충분성 게이트 재검색 강제")
        # 웹 프리페치 주입 — qdrant 라운드가 끝났으면, 턴 시작 시 띄워둔 tavily
        # 결과를 LLM 왕복 없이 tool_use/tool_result 쌍으로 주입하고 다음 회차로.
        # (모델이 웹 쿼리를 다듬는 이점 < LLM 왕복 제거 + 검색 겹침의 지연 이득.)
        if (
            web_prefetch is not None
            and turn_force_search
            and not force_qdrant
            and _already_searched_this_turn(state.messages)
            and not _tool_called_this_turn(state.messages, _WEB_TOOL)
        ):
            built = None
            try:
                built = await web_prefetch
            except Exception as e:  # noqa: BLE001
                # 프리페치 실패(쿼터 초과·네트워크) → 이번 턴 웹 스킵. forced_web
                # 바인딩 폴백은 두지 않는다 — 방금 실패한 웹 검색을 LLM 왕복(쿼리
                # 생성)까지 태워 재시도해봐야 또 실패한다(실측 2026-07-25: Tavily
                # 쿼터 초과 시 폴백 회차가 LLM 1회 + abort 만 낭비). 웹은 보충
                # 레인 — qdrant 근거만으로 답변 진행. web_skip 으로 force_web 억제.
                _log.info("chat_loop web prefetch 실패 → 이번 턴 웹 스킵: %s", e)
                web_skip = True
            web_prefetch = None  # 1회용
            if built:
                inj_tcid = f"tc_{uuid4().hex[:10]}"
                ai_inj = AIMessage(
                    content="",
                    tool_calls=[{"name": "tavily_search",
                                 "args": {"query": _web_query_text(scrubbed)},
                                 "id": inj_tcid, "type": "tool_call"}],
                    id=f"msg_{uuid4().hex[:12]}")
                state.messages.append(ai_inj)
                await asyncio.to_thread(repo.append_messages, thread_id, [ai_inj],
                                        sensitive=confidential, hidden=hidden)
                tool_state = state.as_tool_state()
                tool_state["thread_id"] = thread_id
                tool_state["user_id"] = user_id
                result = await asyncio.to_thread(
                    _tool_tavily, {"query": _web_query_text(scrubbed)}, tool_state,
                    inj_tcid, built)
                state.messages.append(result.tool_message)
                await asyncio.to_thread(
                    repo.append_messages, thread_id, [result.tool_message],
                    sensitive=confidential, hidden=hidden)
                if result.steps:
                    state.steps = merge_steps_by_id(state.steps, result.steps)
                    await asyncio.to_thread(repo.merge_steps, thread_id, result.steps)
                    turn_steps = merge_steps_by_id(turn_steps, result.steps)
                    emit({"type": "steps", "steps": turn_steps})
                continue
        # 웹 게이트(구 방식): qdrant 로 법령 근거를 확보한 *다음* 회차에 tavily 를
        # 1회 강제. (Anthropic tool_choice 는 도구 1개만 지목 가능 → 회차 분리.)
        # 평상시엔 위 프리페치 주입이 담당 — 이 경로는 프리페치를 만들지 못한
        # 구성(TAVILY 키 없음 등 — 그 경우 바인딩 회차도 abort 라 사실상 발화 안 함)
        # 에만 남는다. 프리페치 *실패*(web_skip)면 이번 턴 웹 자체를 접는다.
        force_web = (
            forced_web is not None
            and turn_force_search
            # 스킬 턴 — 프리페치 스킵과 짝(둘 다 막아야 함: 프리페치가 없으면
            # 이 구방식 바인딩이 대신 발화한다 — 2026-08-10 실측).
            # 기준을 force→attach 로(2026-09-10, 스티키 턴 유출 차단).
            and not turn_skill
            and not web_skip
            and not force_skill
            and not force_qdrant
            and _already_searched_this_turn(state.messages)
            and not _tool_called_this_turn(state.messages, _WEB_TOOL)
            and os.getenv("CHAT_FORCE_WEB", "1") == "1"
        )
        # #6 커버리지 게이트(2·3층) — 강제 검색 라운드가 다 끝나고 모델이 답변할
        # 차례(둘 다 False)에 1회만. 2층: 명시 종별 규칙(무료) → 3층: LLM 판정.
        # gap 있으면 겨냥 검색을 주입하고 continue — 다음 회차에 근거까지 보고 답변.
        if (
            not force_skill
            and not force_qdrant
            and not force_web
            and turn_force_search
            and _already_searched_this_turn(state.messages)
            and not coverage_checked
        ):
            coverage_checked = True
            try:
                from src.coverage import (
                    collect_turn_citations,
                    covered_kinds,
                    explicit_gap_searches,
                    judge_coverage,
                )

                _covered = covered_kinds(turn_steps)
                searches = explicit_gap_searches(scrubbed, _covered)
                _log.info(
                    "coverage gate: covered=%s explicit_gaps=%d cites=%d q=%r",
                    sorted(_covered), len(searches),
                    _turn_citation_count(turn_steps), scrubbed[:60])
                # 3층 LLM 판정은 **근거가 얇을 때만**(2026-08-19). 판정 1콜(~2.7s)
                # + 추가 검색 라운드(~3s)로 턴당 ~6s 가 붙는데, 이미 근거가 충분한
                # 턴에서도 "더 찾자"가 나와 지연만 늘었다(실측: 26건 확보 상태에서
                # 재검색 → 인용 61건, +6s). 명시 종별 갭(2층, 무료)은 그대로 본다.
                _cites = _turn_citation_count(turn_steps)
                _judge_cap = int(
                    (os.getenv("COVERAGE_JUDGE_MAX_CITES") or "").strip() or "35")
                if not searches and 1 <= _cites < _judge_cap:
                    verdict = await judge_coverage(
                        scrubbed, collect_turn_citations(turn_steps))
                    if verdict and not verdict.get("sufficient", True):
                        searches = verdict.get("searches") or []
                elif not searches and _cites >= _judge_cap:
                    _log.info("coverage judge 스킵 — 근거 %d건(>=%d)", _cites, _judge_cap)
                if searches:
                    _log.info(
                        "chat_loop: 커버리지 게이트 — 겨냥 검색 %d건 주입", len(searches))
                    turn_steps = await _inject_searches(
                        searches[:2], state, repo, thread_id, user_id, emit,
                        turn_steps, sensitive=confidential, hidden=hidden)
                    continue
            except Exception as e:  # noqa: BLE001 — 게이트 실패가 답변을 막으면 안 됨
                _log.info("coverage gate skipped: %s", e)

        model = (forced_skill if force_skill
                 else forced if force_qdrant
                 else forced_web if force_web
                 else normal)
        request_messages = [
            SystemMessage(content=system_content),
            *await asyncio.to_thread(_egress_scrub, state.messages),
        ]
        if local_skill_model:
            from src import llm_priority as _prio

            _prio.touch()  # 보고서 양보 신호(직전) — 직후에도 갱신
        ai = await _stream_model(model, request_messages, config, emit)
        if local_skill_model:
            _prio.touch()
        state.messages.append(ai)
        await asyncio.to_thread(repo.append_messages, thread_id, [ai],
                                sensitive=confidential, hidden=hidden)

        tool_calls = list(getattr(ai, "tool_calls", None) or [])
        if not tool_calls:
            break

        clarify_payload = None
        for tc in tool_calls:
            tcid = tc.get("id") or f"tc_{uuid4().hex[:10]}"
            tool_state = state.as_tool_state()
            # 검색 수집 이벤트(rag_search)에 사용자·스레드 컨텍스트 부착용
            tool_state["thread_id"] = thread_id
            tool_state["user_id"] = user_id
            # 스킬 세션(턴 로컬) — _exec_tool 의 load_skill 분기가 사용
            tool_state["skill_session"] = skill_session
            # 참조 자동 로드 매칭용 질문(마스킹본) — chat_integration._match_auto_refs
            tool_state["skill_user_text"] = scrubbed
            result = await _exec_tool(tc, tool_state, tcid)
            state.messages.append(result.tool_message)
            await asyncio.to_thread(
                repo.append_messages, thread_id, [result.tool_message],
                sensitive=confidential, hidden=hidden)
            if result.steps:
                state.steps = merge_steps_by_id(state.steps, result.steps)
                await asyncio.to_thread(repo.merge_steps, thread_id, result.steps)
                turn_steps = merge_steps_by_id(turn_steps, result.steps)
                emit({"type": "steps", "steps": turn_steps})
            if result.clarify is not None:
                clarify_payload = result.clarify

        if clarify_payload is not None:
            # HITL 턴 종료 재해석 — 다음 human 메시지가 답변 (interrupt 아님).
            emit(clarify_payload)
            emit({
                "type": "done", "thread_id": thread_id,
                "message_id": ai.id, "text": "", "steps": turn_steps,
                "clarify_pending": True,
            })
            return

    body = _msg_body_text(ai)

    # 스킬 판정 로그 — <verdict> 마커(폴백: 말미 json 블록)에서 구조화 판정 추출.
    # events(skill_verdict) 적재 = 골든셋 축적 경로(사무국 실제 결정과 대조용).
    # done 텍스트에선 마커를 걷어 사용자 노출을 줄인다(스트리밍 원문은 FE 가
    # <next_steps> 와 같은 방식으로 숨긴다 — frontend_chat_v2 계약 추가분).
    if skill_session is not None and body:
        try:
            _verdict = _skills.find_verdict(body)
            if _verdict:
                # 면제 오판 가드(2026-09-15) — 식별정보 모순이면 HOLD 로 강등하고
                # 확인 문구를 본문에 덧붙인다(done.text 가 최종본으로 교체 렌더).
                _verdict, _guard_note = _skills.guard_verdict(_verdict)
                if _guard_note:
                    _log.warning("skill_verdict guard: EXEMPT→HOLD (%s) thread=%s",
                                 (_verdict.get("guard") or {}).get("rule"), thread_id)
                emit({"type": "skill_verdict", "thread_id": thread_id,
                      "message_id": getattr(ai, "id", None), "verdict": _verdict,
                      "rulepack_version": skill_session.version})
                import json as _json

                from src.persistence import get_events_repo
                from src.persistence.events_repo import Event as _Ev
                await asyncio.to_thread(get_events_repo().emit, _Ev(
                    id="", ts="", event_type="skill_verdict",
                    user_id=user_id, thread_id=thread_id,
                    payload_json=_json.dumps({
                        "verdict": _verdict,
                        "rulepack_version": skill_session.version,
                        "loaded": skill_session.sent_keys(),
                        "input": scrubbed[:300],
                    }, ensure_ascii=False)))
                body = _skills.strip_verdict_marker(body)
                if _guard_note:
                    body = _skills.insert_guard_note(body, _guard_note)
                    # 저장본·다음 턴 컨텍스트에도 반영 — AI 메시지는 스트림 직후
                    # 이미 저장됐다(위 append_messages). 원문(마커 포함)에 문구만
                    # 덧붙여 교체한다; 마커는 FE 가 종전처럼 숨긴다.
                    ai = _with_guard_note(ai, _guard_note)
                    if state.messages and getattr(state.messages[-1], "id", None) == ai.id:
                        state.messages[-1] = ai
                    await asyncio.to_thread(repo.replace_message, thread_id, ai)
        except Exception:
            _log.debug("skill_verdict emit failed", exc_info=True)

    # ── 규제 경로 분해(2026-10-01) — <pathway> 마커 → 전용 채널 ────────────
    # 단계 체크리스트를 본문 산문에 묻으면 추적이 안 된다(<next_steps> 와 같은
    # 이유). 마커를 걷어내고 SSE `pathway` 로 보낸다. 파싱 실패는 조용히 버린다.
    _pathway: Optional[list[dict]] = None
    if body:
        try:
            from src import pathway as _pw

            _pathway = _pw.parse(body)
            if _pathway is not None:
                # 마커는 **본문에 남긴다** — <next_steps> 와 같은 계약이다.
                # 전용 SSE 이벤트로만 보내면 새로고침·스레드 재방문 때 경로가
                # 사라진다(메시지는 영속되지만 이벤트는 휘발). FE 가 파싱해 카드로
                # 렌더하고 본문에서는 가린다.
                _log.info("pathway: %d단계 추출 thread=%s", len(_pathway), thread_id)
                try:
                    import json as _json

                    from src.persistence import get_events_repo
                    from src.persistence.events_repo import Event as _Ev
                    await asyncio.to_thread(get_events_repo().emit, _Ev(
                        id="", ts="", event_type="pathway",
                        user_id=user_id, thread_id=thread_id,
                        payload_json=_json.dumps(_pw.summary(_pathway),
                                                 ensure_ascii=False)))
                except Exception:  # noqa: BLE001 — 적재 실패가 답변을 막지 않는다
                    _log.warning("pathway 이벤트 적재 실패", exc_info=True)
        except Exception:  # noqa: BLE001 — 경로 추출 실패로 답변을 잃지 않는다
            _log.warning("pathway 처리 실패 — 무시", exc_info=True)

    # ── 본문 URL 강제(2026-08-19) — 링크 소유권을 모델에서 코드로 ──────────
    # 종전 backstop 은 "출처에 문자열이 있으면 통과"라 실제 오류(경로 403·http
    # 스킴)를 놓치고 정상(백틱 붙은 emedi)은 오탐했다. 이제 레지스트리 값만
    # 남기고 나머지는 제거한다 — 틀린 링크가 **구조적으로 나갈 수 없다**.
    # 출처 링크는 우측 패널 citation 이 정본으로 렌더하므로 손실이 아니다.
    if (os.getenv("CHAT_URL_ENFORCE_DISABLE") or "").strip() != "1":
        body, _url_changes = sanitize_body_urls(body)
        if _url_changes:
            _log.info("본문 URL 강제: %d건 교정·제거 — %s",
                      len(_url_changes), _url_changes[:5])
            try:
                import json as _json

                from src.persistence import get_events_repo
                from src.persistence.events_repo import Event as _Ev
                await asyncio.to_thread(get_events_repo().emit, _Ev(
                    id="", ts="", event_type="url_enforced",
                    user_id=user_id, thread_id=thread_id,
                    payload_json=_json.dumps(
                        {"items": _url_changes[:10]}, ensure_ascii=False)))
            except Exception:
                _log.debug("url_enforced emit failed", exc_info=True)

    # 이전 턴 근거 재인용 carry-over — 무검색 턴에서도 재사용 근거([n])가 이번 답변
    # 각주로 뜨고 grounding 을 받게 한다(기존 citation 만 이어붙임 — 날조 X). done 이
    # 이 step 을 실어야 FE 가 즉시 각주를 렌더하므로 emit 앞에서 수행.
    carry_step = _carryover_citation_step(state, turn_steps, body)
    if carry_step:
        turn_steps = merge_steps_by_id(turn_steps, [carry_step])
        state.steps = merge_steps_by_id(state.steps, [carry_step])
        await asyncio.to_thread(repo.merge_steps, thread_id, [carry_step])

    # 검증 불가 링크·연락처 backstop(B) — 프롬프트 가드(A)를 뚫은 지어낸 URL/전화
    # 감지 시 *내부 신호만*(log + events). 사용자엔 경고 안 함(자기모순 회피) — 삭제도
    # 안 함(오탐 위험). 어드민이 발생률을 관측해 가드/레지스트리 튜닝 근거로 쓴다.
    # 면책 — **시스템이 결정적으로 부착**한다(2026-10-03). `legal.py` 가 처음부터
    # 그 원칙을 선언했는데("LLM 이 매번 작성하면 표현이 흔들리고 누락될 수 있다"),
    # 실제로는 supervisor 프롬프트가 LLM 에게 "세션 최초 1회 덧붙여라"고 지시할
    # 뿐 부착 코드가 없었다 — 2턴째부터, 복사본에는, 면책이 없었다. 법령 근거로
    # 답한 턴(인용 ≥1)마다 붙인다. 프롬프트 지시는 삭제했다(이중 부착 방지).
    if body and _turn_citation_count(turn_steps) > 0:
        from src.legal import append_chat_disclaimer

        body = append_chat_disclaimer(body)
        emit({"type": "token", "text": "", "message_id": getattr(ai, "id", None)})

    _unverified = _detect_unverified_contacts(state, turn_steps, body)
    if _unverified:
        _log.warning(
            "chat_loop: 미검증 링크/연락처 %d건 — %s",
            len(_unverified), _unverified[:5])
        try:
            import json as _json

            from src.persistence import get_events_repo
            from src.persistence.events_repo import Event as _Ev
            await asyncio.to_thread(get_events_repo().emit, _Ev(
                id="", ts="", event_type="unverified_contact",
                user_id=user_id, thread_id=thread_id,
                payload_json=_json.dumps(
                    {"items": _unverified[:10]}, ensure_ascii=False),
            ))
        except Exception:
            _log.debug("unverified_contact emit failed", exc_info=True)

    # 텍스트 완료 즉시 done — 답변/인용 렌더를 grounding 이 막지 않게 한다(사용자
    # 리포트 2026-07-15: 텍스트 끝난 뒤 랙·인용 태그 지연). front 는 이 done 에서
    # 턴을 확정(인용/태그 즉시 노출).
    emit({
        "type": "done", "thread_id": thread_id,
        "message_id": getattr(ai, "id", None), "text": body, "steps": turn_steps,
        # 자동 이어쓰기 상한까지 갔는데도 잘림 — FE 가 [이어서 작성] 버튼 표시.
        "truncated": bool(
            (getattr(ai, "response_metadata", None) or {}).get("truncated")),
    })

    # grounding 검증은 done *뒤에* — verified 만 trailing steps 로 뒤따라 갱신(스트림은
    # 아직 열려 있어 전달됨). 비차단: 답변/인용은 이미 확정, 검증 배지만 곧 붙는다.
    grounded_updates = await _apply_grounding(turn_steps, body)
    if grounded_updates:
        state.steps = merge_steps_by_id(state.steps, grounded_updates)
        await asyncio.to_thread(repo.merge_steps, thread_id, grounded_updates)
        turn_steps = merge_steps_by_id(turn_steps, grounded_updates)
        emit({"type": "steps", "steps": turn_steps})

    # 무인용 사실 audit(factual-verification-design Phase 1 — 측정). check-worthy
    # 정량·특정 사실이 source 에 지지되나 판정 → events(claim_audit)로만 기록.
    # 사용자 비노출(자기모순 회피), done 뒤 비차단. CLAIM_AUDIT_DISABLE=1 로 끔.
    if (os.getenv("CLAIM_AUDIT_DISABLE") or "").strip() != "1" and len(body.strip()) >= 40:
        try:
            from collections import Counter

            from src.grounding import audit_uncited_claims

            audited = await audit_uncited_claims(
                body, _turn_source_haystack(state, turn_steps))
            if audited:
                cnt = Counter(a["verdict"] for a in audited)
                flagged = cnt.get("contradicted", 0) + cnt.get("unverified", 0)
                if flagged:
                    _log.info(
                        "claim audit: total=%d supported=%d contradicted=%d unverified=%d",
                        len(audited), cnt.get("supported", 0),
                        cnt.get("contradicted", 0), cnt.get("unverified", 0))
                # ⚠️ 깨끗한 턴(전부 supported)도 emit 한다(2026-08-14) — 종전엔
                # flagged 턴만 기록해 **분모에서 깨끗한 턴이 빠졌고**, admin
                # claim-audit 의 unsupported_rate 가 구조적으로 과대평가됐다.
                # 비율 지표는 전수 기록이 전제다(samples 는 문제 건만 유지).
                import json as _json

                from src.persistence import get_events_repo
                from src.persistence.events_repo import Event as _Ev
                await asyncio.to_thread(get_events_repo().emit, _Ev(
                    id="", ts="", event_type="claim_audit",
                    user_id=user_id, thread_id=thread_id,
                    # 검수 큐가 턴에 정확히 붙이도록(시각 창 추정 대신, 2026-09-17).
                    message_id=getattr(ai, "id", None),
                    payload_json=_json.dumps({
                        "total": len(audited),
                        "supported": cnt.get("supported", 0),
                        "contradicted": cnt.get("contradicted", 0),
                        "unverified": cnt.get("unverified", 0),
                        "samples": [a for a in audited
                                    if a["verdict"] != "supported"][:8],
                    }, ensure_ascii=False)))
        except Exception:
            _log.debug("claim audit emit failed", exc_info=True)

    # 식별자 대조 감사(2026-09-17) — 답변의 서식·별표 번호가 이번 턴 근거에 실재하나.
    # grounding 은 "인용한 문장"을 보므로 출처 옆에 새로 쓴 틀린 번호를 못 잡는다.
    # 결정적(LLM 무호출)·관측 전용 — 검수 큐 신호. IDENT_AUDIT_DISABLE=1 로 끔.
    if (os.getenv("IDENT_AUDIT_DISABLE") or "").strip() != "1":
        try:
            from src.identifier_audit import audit_identifiers

            ident_res = audit_identifiers(body, _turn_source_haystack(state, turn_steps))
            if ident_res:
                if ident_res["unsupported"] or ident_res["placeholders"]:
                    _log.info("identifier audit: unsupported=%s placeholders=%s",
                              ident_res["unsupported"], ident_res["placeholders"])
                import json as _json

                from src.persistence import get_events_repo
                from src.persistence.events_repo import Event as _Ev
                await asyncio.to_thread(get_events_repo().emit, _Ev(
                    id="", ts="", event_type="identifier_audit",
                    user_id=user_id, thread_id=thread_id,
                    message_id=getattr(ai, "id", None),
                    payload_json=_json.dumps(ident_res, ensure_ascii=False)))
        except Exception:
            _log.debug("identifier audit emit failed", exc_info=True)

    # 열거 커버리지 감사(2026-08-21, t_1398cb 침묵 누락) — 입력에 열거된 항목을
    # 답변이 다 다뤘는지 결정적 대조. claim audit 가 "쓴 문장"을 재면 이건
    # "안 쓴 항목"을 잰다. 관측 전용(events) — 빈도를 본 뒤 개입(보완 검색)을
    # 결정한다. ENUM_AUDIT_DISABLE=1 로 끔.
    if (os.getenv("ENUM_AUDIT_DISABLE") or "").strip() != "1":
        try:
            from src.enumeration_audit import audit_enumeration

            enum_res = audit_enumeration(scrubbed, body)
            if enum_res:
                if enum_res["missing"]:
                    _log.info(
                        "enum audit: items=%d covered=%d missing=%s",
                        enum_res["items"], enum_res["covered"],
                        enum_res["missing"])
                import json as _json

                from src.persistence import get_events_repo
                from src.persistence.events_repo import Event as _Ev
                await asyncio.to_thread(get_events_repo().emit, _Ev(
                    id="", ts="", event_type="enum_coverage",
                    user_id=user_id, thread_id=thread_id,
                    payload_json=_json.dumps(enum_res, ensure_ascii=False)))
        except Exception:
            _log.debug("enum audit emit failed", exc_info=True)

    # 서류 초안 기입 대조(Phase ②, 2026-08-24) — 이 스레드에 미기입 서류
    # 초안(document_draft)이 있으면 이번 발화에서 값을 추출해 채우고 SSE
    # `document_update` 로 FE 문서 패널을 갱신한다("채팅만으로 채우기").
    # 초안이 없으면 repo 조회 1번으로 끝(LLM 콜 없음 — 평상시 비용 0).
    if (os.getenv("DOC_FILL_DISABLE") or "").strip() != "1":
        try:
            from src.doc_fill import run_turn_fill

            # 원문은 온프레미스 모델일 때만 쓰인다(doc_fill.onprem_fill).
            # 서류의 성명·연락처 칸은 마스킹본으로 채울 수 없기 때문.
            if is_confidential_turn() and not local_skill_model:
                _log.info("doc fill 건너뜀 — 기밀 턴인데 원내 모델이 없다")
            else:
                await run_turn_fill(thread_id, scrubbed, emit, raw_text=user_text)
        except Exception:
            # ⚠️ 여기서 삼키면 기입이 통째로 죽어도 조용하다(실측 2026-08-26:
            # 변수명 오타 하나로 전 사용자 서류 기입이 멈춰 있었다). 원인 추적이
            # 가능하도록 warning 으로 남긴다 — 답변 자체는 계속 진행.
            _log.warning("doc fill pass failed", exc_info=True)
