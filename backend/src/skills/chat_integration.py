"""chat_loop ↔ 스킬 번들 접점 — 스킬 관련 로직을 전부 이 모듈에 격리.

chat_loop 에는 `turn_skill` 가드 뒤의 훅 몇 줄만 남긴다. 이 모듈을 지우고
chat_loop 의 가드 분기를 걷어내면 기능이 흔적 없이 제거된다(분리 계약).

3단 스위치:
  1) 서비스 — `SKILL_BUNDLE_DIR` 미설정이면 기능 자체가 없음
  2) 대상   — `SKILL_WHITELIST_EMAILS` (미설정=전면 허용, BETA_WHITELIST 관례)
  3) 스레드 — 이번 턴 질의가 IRB/DRB 이거나(프리게이트), 스레드 히스토리에
     load_skill 흔적이 있으면(스티키) on. 스티키는 별도 컬럼 없이 히스토리에서
     유도한다 — 스키마 무변경, 압축으로 흔적이 접히면 요약 키워드로 보강.

강제(force)와 부착(attach)은 분리: 스티키 스레드라도 이번 턴 질의가 IRB/DRB
일 때만 load_skill 을 강제한다. 문진 후속 답변("네, 후향적이에요")은 강제 없이
히스토리의 지침이 이끈다.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import ToolMessage

from src.skills.loader import (
    SKILL_TOOL_NAMES,
    SkillLoader,
    extract_verdict,  # noqa: F401 — chat_loop 이 이 모듈 경유로 사용
)
from src.steps import step_done, step_error, step_start

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 스위치 1·2 — 서비스·대상
# ---------------------------------------------------------------------------

def skills_configured() -> bool:
    """SKILL_BUNDLE_DIR 이 설정되고 manifest 가 존재해야 기능이 존재한다."""
    d = (os.getenv("SKILL_BUNDLE_DIR") or "").strip()
    return bool(d) and (Path(d) / "manifest.json").is_file()


def user_allowed(user_id: Optional[str]) -> bool:
    """SKILL_WHITELIST_EMAILS — 이메일 또는 @도메인, 콤마 구분. 미설정=전면 허용.

    단일 기관 번들이므로 운영에서는 해당 기관 도메인으로 잠그는 것을 전제한다.
    """
    raw = (os.getenv("SKILL_WHITELIST_EMAILS") or "").strip()
    if not raw:
        return True
    email = (user_id or "").strip().lower()
    if not email:
        return False
    for item in (x.strip().lower() for x in raw.split(",") if x.strip()):
        if item.startswith("@"):
            if email.endswith(item):
                return True
        elif email == item:
            return True
    return False


# ---------------------------------------------------------------------------
# 스위치 3 — 프리게이트(이번 턴) + 스티키(스레드 히스토리)
# ---------------------------------------------------------------------------
# 고정밀 우선 — 거짓 양성은 회차 1개 낭비, 거짓 음성은 기존 검색 답변(현상 유지)
# 이라 보수적으로 시작한다. 보강은 /admin/questions 실측으로.
_PREGATE = re.compile(
    r"(irb|drb"
    r"|심의\s*면제|심의면제"
    r"|기관\s*생명\s*윤리|생명윤리\s*(?:심의)?위원회|연구윤리\s*심의"
    r"|의료정보\s*데이터\s*심의|데이터\s*심의\s*위원회"
    r"|가명처리\s*계획"
    r"|인체\s*유래물|잔여\s*검체"
    r"|차트\s*리뷰|차트리뷰"
    r"|연구\s*계획서\s*심의)",
    re.IGNORECASE,
)


def is_skill_query(user_text: str) -> bool:
    """이번 턴 질의가 IRB/DRB 논점인가 — 순수 키워드 프리게이트(LLM·DGX 무호출)."""
    return bool(_PREGATE.search(user_text or ""))


# ---------------------------------------------------------------------------
# 광의(soft) 게이트 — 2026-09-10
#
# 왜 별도인가: 위 `_PREGATE` 는 **고정밀**이라 사용자가 'IRB·심의·차트리뷰' 같은
# 말을 직접 써야 걸린다. 그래서 "환자 100명 처방데이터로 연구를 기획 중인데
# 어떻게 시작하죠?" 처럼 **연구를 설계하며 무심코 던진 질문**은 안 잡힌다(실측
# 2026-09-10). 그런데 이런 질문이야말로 심의 대상 고지가 필요한 순간이다.
#
# 그렇다고 `_PREGATE` 를 넓히면 안 된다 — 부착 비용이 커졌기 때문이다. 스킬이
# 붙으면 ① 온프레미스 모델(대화 60s+, 상용 15~20s) ② 웹 검색 제외(2026-09-10)
# ③ 기관 지침 프레이밍이 강제된다. 일반 규제 질문이 오탐되면 느리고 근거도 얇다.
#
# 그래서 **부착은 하지 않고 고지만** 시킨다: 이 게이트가 걸리면 시스템 프롬프트
# 가변부에 한 줄을 넣어, 상용 모델이 답변 말미에 심의 가능성을 알리고 next_steps
# 로 실제 상담 진입을 제안하게 한다. 오탐 비용 = 안내 한 문장 + 칩 하나.
_SOFT_PREGATE = re.compile(
    # 후향적/의무기록 기반 연구
    r"(후향적|의무\s*기록|진료\s*기록|전자\s*의무\s*기록|EMR"
    # 연구 목적의 환자 데이터 이용
    r"|처방\s*데이터|환자\s*데이터|임상\s*데이터|검체|코호트"
    # 연구 설계·수행 일반
    r"|임상\s*연구|관찰\s*연구|증례\s*보고|연구\s*계획서|연구\s*대상자"
    r"|피험자|대조군|무작위\s*배정)",
    re.IGNORECASE,
)
# 연구 맥락이 함께 있어야 한다 — '진료기록 사본 발급' 같은 비연구 질의 제외.
_RESEARCH_CTX = re.compile(r"(연구|논문|학술|시험|분석|데이터\s*활용|과제)")


def is_review_adjacent(user_text: str) -> bool:
    """엄격 게이트엔 안 걸리지만 **심의 대상일 가능성**이 있는 질의인가.

    True 여도 스킬은 부착하지 않는다 — 고지 문구만 유도한다(`chat_loop`).
    """
    t = user_text or ""
    if _PREGATE.search(t):
        return False  # 엄격 게이트가 이미 처리 — 중복 고지 방지
    return bool(_SOFT_PREGATE.search(t) and _RESEARCH_CTX.search(t))


#: 광의 게이트 적중 시 시스템 프롬프트 가변부에 붙는 지시.
REVIEW_NUDGE = (
    "[심의 가능성 고지] 이번 질문은 사람 대상 연구 또는 환자 정보 이용으로 보여 "
    "기관 심의(IRB·DRB) 대상일 수 있다. 답변 본문 마지막에 **한 문장**으로 "
    "\"이 연구는 기관 IRB(및 진료정보 이용 시 DRB) 심의 대상일 수 있으니 "
    "소속 기관 사무국 확인이 필요하다\"는 취지를 덧붙여라. 단정하지 말고 "
    "가능성으로 말한다. 그리고 `<next_steps>` **첫 항목**으로 심의 대상 여부를 "
    "확인하는 제안을 넣어라(예: title \"심의 대상 확인\", prompt \"이 연구가 "
    "IRB·DRB 심의 대상인지 판정해줘\"). 이 고지 때문에 답변의 원래 주제를 "
    "바꾸지는 말 것 — 질문에 대한 답이 먼저다."
)


def _history_skill_keys(messages: list) -> set[str]:
    """히스토리(비압축 구간)에 실린 스킬 파일 키('{skill}/{path}') 수집.

    스티키 판정 + 로더 `_sent` 시드 겸용. 압축으로 접힌 본문은 여기 없으므로
    자연히 재로드가 허용된다(요약엔 지침 본문이 없기 때문).
    """
    keys: set[str] = set()
    for m in messages:
        for tc in (getattr(m, "tool_calls", None) or []):
            name = tc.get("name")
            args = tc.get("args") or {}
            if name == "load_skill" and args.get("name"):
                keys.add(f"{args['name']}/SKILL.md")
            elif name == "read_skill_reference" and args.get("skill") and args.get("path"):
                keys.add(f"{args['skill']}/{args['path']}")
    return keys


def resolve_turn_skill(
    user_id: Optional[str],
    messages: list,
    summary: Optional[str],
    user_text: str,
    *,
    hint: bool = False,
) -> tuple[bool, bool]:
    """(attach, force) — 이번 턴에 스킬을 부착할지 / load_skill 을 강제할지.

    attach: 프리게이트 발화(이번 턴) 또는 스티키(히스토리 흔적·요약 키워드).
    force:  이번 턴 질의가 IRB/DRB 일 때만 (부착 ≠ 강제).
    hint:   프런트 명시 진입(IRB/DRB 버튼, `ChatRequest.skill_hint`) — 키워드
            프리게이트가 놓쳐도 부착·강제한다(이중 접근, 2026-08-21). 화이트
            리스트·env 스위치는 그대로 적용된다(버튼이 게이트를 우회하지 않음).
    """
    if not skills_configured() or not user_allowed(user_id):
        return False, False
    query_hit = hint or is_skill_query(user_text)
    sticky = bool(_history_skill_keys(messages)) or is_skill_query(summary or "")
    return (query_hit or sticky), query_hit


# ---------------------------------------------------------------------------
# 세션 — 턴마다 로더 인스턴스 생성 (README 계약: 재사용 금지)
# ---------------------------------------------------------------------------

def new_session(messages: list) -> SkillLoader:
    d = Path((os.getenv("SKILL_BUNDLE_DIR") or "").strip())
    loader = SkillLoader(d, d / "manifest.json")
    loader.seed(_history_skill_keys(messages))
    return loader


def catalog_block(loader: SkillLoader) -> str:
    """시스템 프롬프트 주입 블록 — 카탈로그 + 계약 문장 + verdict 마커 계약.

    ⚠️ 프롬프트 *중간*(공식 창구 레지스트리 자리)에 주입 — 끝에 붙이면
    <next_steps> 계약이 밀린다(2026-07-23 버그 재발 방지, chat_loop 주석 참조).
    """
    return (
        f"{loader.catalog()}\n\n"
        "스킬 지침에 따라 심의 판정을 완료한 턴에는, 지침이 요구하는 구조화 판정 "
        "JSON 블록을 답변 본문 뒤 `<verdict>` 와 `</verdict>` 마커 사이에 넣는다 "
        "(예: <verdict>\\n```json\\n{...}\\n```\\n</verdict>). 판정이 아닌 턴에는 "
        "이 마커를 쓰지 않는다.\n"
        "**근거 위계**: 기관 내부 절차·기한·제출서류·소요기간 질의는 위 "
        "지침과 그 참조 파일이 1차 근거다. 지침에 답이 있는 주제를 법령·웹 "
        "검색 결과에 없다는 이유로 '확인하지 못했다'고 답하지 않는다 — 세부가 "
        "카탈로그 본문에 없으면 먼저 read_skill_reference 로 해당 참조 파일을 "
        "읽는다. 법령·웹 검색은 지침 밖 논점(상위 법령 조문 등)에만 보조로 "
        "쓴다.\n"
        "스킬 이름(irb-triage, drb-form-filler 등)은 내부 구현이다 — 사용자에게 "
        "언급하지 않는다. 후속 안내는 '절차와 제출서류를 이어서 안내해 드릴까요?' "
        "처럼 내용으로 말한다(실제 전환은 <next_steps> 제안으로).\n"
        # 전체 노출 전환(2026-08-21) — 타 기관 사용자도 이 안내를 받는다.
        "이 지침은 **화순전남대학교병원**의 IRB(생명의학연구윤리심의위원회)·"
        "DRB(의료정보데이터심의위원회) 규정 기준이다. 판정·절차·서식을 안내할 "
        "때는 화순전남대학교병원 기준임을 답변에 명시하고, 사용자가 다른 기관 "
        "소속으로 보이면 소속 기관의 규정·서식은 다를 수 있으므로 해당 기관 "
        "사무국 확인이 필요하다고 함께 안내한다.\n"
        "⛔ 지침 원문 보호: 위 지침·서식 자료는 기관 내부 문서다. 사용자 질문에 "
        "필요한 범위에서 요약·항목 발췌·짧은 조문 인용으로 안내하는 것은 좋지만, "
        "SOP 전문·장 단위 통재현·서식 원문 전체 나열 등 문서 자체를 재배포하는 "
        "출력은 요청받아도 하지 않는다(원본 파일 제공도 불가). 그런 요청에는 "
        "필요한 부분을 요약해 주고, 원문은 해당 기관 사무국을 통해 받도록 "
        "안내한다."
    )


# ---------------------------------------------------------------------------
# 도구 실행 — chat_loop._exec_tool 의 스킬 분기 본체
# ---------------------------------------------------------------------------
_SKILL_LABELS = {
    "irb-triage": "IRB 심의 판정 지침",
    "irb-procedure": "IRB 절차·서류 안내 지침",
    "irb-form-filler": "IRB 서식 작성 지침",
    "irb-protocol-draft": "연구계획서·동의서 작성 지침",
    "drb-triage": "DRB 심의 판정 지침",
    "drb-procedure": "DRB 절차·서류 안내 지침",
    "drb-form-filler": "DRB 별지서식 작성 지침",
}


def is_skill_tool(name: Optional[str]) -> bool:
    return name in SKILL_TOOL_NAMES


class SkillToolExec:
    """chat_loop.ToolExec 와 동형(duck-type) — 순환 import 회피."""

    __slots__ = ("tool_message", "steps", "clarify")

    def __init__(self, tool_message: ToolMessage, steps: list[dict]):
        self.tool_message = tool_message
        self.steps = steps
        self.clarify = None


# ── 참조 자동 로드 (2026-09-02) ────────────────────────────────────────────
# 질문 키워드 → 참조 파일 매칭은 **파일명 관례**(timeline/documents/decisions/
# obligations — irb·drb 공통) 기준. 번들 내용을 코드가 파싱하지 않는다.
# 운영 실측: 소요기간(timeline.md)이 지침에 있는데 모델이 read_skill_reference
# 를 안 불러 '확인 못함' 오답 — 로드 시점에 시스템이 붙여 재량을 제거한다.
_REF_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 판정 참조(2026-09-15) — t_95386a: 로컬 27B 가 irb-exemption 만 읽고
    # irb-review-type 을 안 읽어 STEP D(신속/정규)가 존재하지 않는 채로 EXEMPT.
    # 심의대상·면제·후향 단서면 두 결정트리를 함께 동봉한다(순서 = 우선순위).
    ("irb-exemption", ("면제", "후향", "의무기록", "차트", "심의 대상", "심의대상",
                       "대상인가", "받아야", "승인 가능", "판정")),
    ("irb-review-type", ("면제", "후향", "의무기록", "차트", "심의 대상", "심의대상",
                         "대상인가", "받아야", "승인 가능", "판정", "신속", "정규")),
    ("timeline", ("소요", "기간", "얼마나", "언제", "며칠", "몇 일", "몇일",
                  "걸려", "걸리", "기한", "일정", "마감")),
    ("documents", ("서류", "제출", "양식", "첨부", "구비", "준비물")),
    ("decisions", ("결정", "판정 결과", "승인", "보완", "반려", "부결",
                   "이의신청", "재심")),
    ("obligations", ("의무", "연차", "지속심사", "종료보고", "결과보고",
                     "변경보고", "이상반응")),
)
_AUTO_REF_MAX = 2           # 한 번에 동봉할 참조 상한
_AUTO_REF_CHAR_CAP = 16000  # 동봉 총량 상한(프롬프트 폭주 방지)


def _match_auto_refs(loader: SkillLoader, skill: str, question: str) -> list[str]:
    """질문과 파일명 관례가 맞는 등록 참조 경로(≤2). 순수 — LLM 무호출."""
    if not question:
        return []
    try:
        meta = next((s for s in loader.manifest["skills"]
                     if s["name"] == skill), None)
    except Exception:  # noqa: BLE001
        return []
    if not meta:
        return []
    out: list[str] = []
    for stem, cues in _REF_CUES:
        if not any(c in question for c in cues):
            continue
        for r in meta.get("references") or []:
            if stem in str(r) and r not in out:
                out.append(r)
                break
    return out[:_AUTO_REF_MAX]


def exec_tool(
    loader: Optional[SkillLoader], name: str, args: dict, state: dict, tcid: str
) -> SkillToolExec:
    """load_skill / read_skill_reference 실행 → (ToolMessage, steps).

    step 을 발행해 프런트 진행 표시("내부 지침 확인: …")에 노출한다 — 검색 step
    과 같은 SSE `steps` 채널(추가 FE 작업 불필요, tool_name 으로 구분 가능).
    """
    if name == "load_skill":
        skill = str(args.get("name") or "")
        label = f"내부 지침 확인: {_SKILL_LABELS.get(skill, skill)}"
        preview = skill
    else:
        skill = str(args.get("skill") or "")
        path = str(args.get("path") or "")
        label = f"지침 자료 확인: {Path(path).name or path}"
        preview = f"{skill}/{path}"
    sid, start = step_start(label, tool_name=name, input_preview=preview, state=state)
    # 검색 도구와 동일한 실시간 노출 — steps 병합 이벤트보다 먼저 FE 에 뜬다.
    from src.observability.search_progress import _emit_step_lifecycle

    _emit_step_lifecycle("start", start)

    if loader is None:  # 방어 — force 없이 도구만 남은 비정상 경로
        msg = "[system] 스킬 로더 미구성 — 이 도구는 사용할 수 없습니다."
        return SkillToolExec(
            ToolMessage(content=msg, tool_call_id=tcid),
            [start, step_error(sid, message="내부 지침을 불러올 수 없습니다.")],
        )

    content, is_error = loader.dispatch(name, args)
    if is_error:
        # 에러도 ToolMessage 로 — 모델이 오타를 고쳐 재시도한다(로더 계약).
        return SkillToolExec(
            ToolMessage(content=content, tool_call_id=tcid),
            [start, step_error(sid, message="지침 파일을 찾지 못했습니다.")],
        )
    steps = [start, step_done(sid, output_preview=f"{len(content):,}자 로드")]
    # 질문 키워드에 맞는 참조를 로드에 동봉 — read_skill_reference 재량 제거.
    if name == "load_skill":
        question = str(state.get("skill_user_text") or "")
        budget = _AUTO_REF_CHAR_CAP
        for ref in _match_auto_refs(loader, skill, question):
            rc, rerr = loader.dispatch(
                "read_skill_reference", {"skill": skill, "path": ref})
            if rerr or not rc or len(rc) > budget:
                continue
            budget -= len(rc)
            content += f"\n\n[자동 첨부 — 질문 관련 참조 {ref}]\n{rc}"
            rsid, rstart = step_start(
                f"지침 자료 확인: {Path(ref).name}",
                tool_name="read_skill_reference",
                input_preview=f"{skill}/{ref}", state=state)
            _emit_step_lifecycle("start", rstart)
            steps += [rstart, step_done(rsid, output_preview=f"{len(rc):,}자 로드")]
    return SkillToolExec(
        ToolMessage(content=content, tool_call_id=tcid), steps,
    )


# ---------------------------------------------------------------------------
# 판정 로그 — verdict 마커/JSON 추출 (본문은 건드리지 않음)
# ---------------------------------------------------------------------------
_VERDICT_MARKER = re.compile(r"<verdict>\s*(.*?)\s*</verdict>", re.S)


_TRAILING_JSON = re.compile(
    r"```json\s*(\{.*?\})\s*```\s*(?:<next_steps>.*?</next_steps>\s*)?$", re.S)


def find_verdict(body: str) -> Optional[dict]:
    """<verdict> 마커 우선, 없으면 **말미** ```json 블록 폴백.

    (2026-09-15 인젝션 보강) 종전엔 본문 어디든 마지막 json 블록을 받아, 첨부·검색
    자료를 인용하다 옮겨 적은 JSON 이 판정으로 적재될 수 있었다. 폴백은 답변 끝
    (next_steps 마커만 뒤따르는 경우 포함)에 있는 블록만 인정한다.
    """
    m = _VERDICT_MARKER.search(body or "")
    if m:
        v = extract_verdict(m.group(1))
        if v:
            return v
    t = _TRAILING_JSON.search(body or "")
    if not t:
        return None
    return extract_verdict("```json\n" + t.group(1) + "\n```")


def strip_verdict_marker(body: str) -> str:
    """영속 본문에서 verdict 마커 블록 제거 — FE 는 SSE `skill_verdict` 이벤트로 수신."""
    return _VERDICT_MARKER.sub("", body or "").rstrip()


# ---------------------------------------------------------------------------
# 판정 가드 — 결정트리 자기모순을 코드가 잡는다 (2026-09-15, t_95386a)
# ---------------------------------------------------------------------------
# 배경: 후향적 의무기록 연구를 EXEMPT 로 판정한 두 건(9/10 관리자 테스트, 9/15
# 전남대 사용자 — 사무국 정답은 신속심의)이 모두 같은 모순을 갖고 있었다:
#   SUBJ.2 "개인식별정보 이용" 으로 인간대상연구(=identifiable_info) 이면서
#   H3 "개인식별정보 수집·기록 안 함"(collects_identifiable_info=false).
# 의무기록번호↔연구번호 대응표(연결키)를 보유하면 간접 식별이 가능해 H3 는
# '예'다. SKILL.md 절대규칙 3("심의대상을 면제로 판정하는 오류는 절대 허용되지
# 않는다")을 모델 재량에서 코드로 옮긴다: 모순이면 HOLD 로 강등하고 확인 질문을
# 본문에 덧붙인다. 모델이 `has_linking_key=false` 를 명시(사용자 확인)한 경우만
# EXEMPT 를 통과시킨다.
_GUARD_RULE = "exempt_identifiable_contradiction"
_GUARD_NOTE = (
    "\n\n---\n**판정 보류 안내(자동 검토)**: 이 연구는 기존 의무기록 등 개인식별이 "
    "가능한 자료를 이용하는 것으로 파악되는데, 판정 경로에서는 개인식별정보를 "
    "수집·기록하지 않는 것으로 처리되었습니다. 의무기록번호와 연구번호의 대응표"
    "(연결키)를 연구진이 보관하면 간접적으로 식별 가능한 정보를 기록하는 연구에 "
    "해당해 심의면제가 아니라 **신속심의 대상**이 되는 것이 일반적입니다. "
    "대응표를 보관하는지 알려주시면 판정을 이어가겠습니다. 완전히 익명화된 자료만 "
    "이용하고 대응표를 두지 않는 경우에 한해 심의면제를 검토할 수 있습니다."
)


def _falsy(v) -> bool:
    return v is False or (isinstance(v, str) and v.strip().lower() == "false")


def _truthy(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() == "true")


def guard_verdict(verdict: Optional[dict]) -> tuple[Optional[dict], Optional[str]]:
    """EXEMPT 판정의 식별정보 모순을 HOLD 로 강등한다. (판정, 본문 추가 문구).

    순수 함수 — 입력 dict 는 수정하지 않고 사본을 돌려준다. 조건:
      irb.verdict == EXEMPT
      and collects_identifiable_info 가 false
      and (interaction_type == identifiable_info or uses_existing_records true)
      and has_linking_key 가 false 로 명시되지 않음
    """
    if not isinstance(verdict, dict):
        return verdict, None
    irb = verdict.get("irb")
    if not isinstance(irb, dict) or str(irb.get("verdict") or "").upper() != "EXEMPT":
        return verdict, None
    slots = verdict.get("used_slots") or {}
    if not isinstance(slots, dict):
        return verdict, None
    if not _falsy(slots.get("collects_identifiable_info")):
        return verdict, None
    identifiable_source = (
        str(slots.get("interaction_type") or "") == "identifiable_info"
        or _truthy(slots.get("uses_existing_records"))
    )
    if not identifiable_source or _falsy(slots.get("has_linking_key")):
        return verdict, None

    import copy

    out = copy.deepcopy(verdict)
    out["irb"]["verdict"] = "HOLD"
    unknowns = out["irb"].get("unknowns")
    if not isinstance(unknowns, list):
        unknowns = []
    unknowns.append("의무기록번호↔연구번호 대응표(연결키) 보관 여부 — 보관 시 "
                    "간접 식별 가능(H3 예) → STEP D 신속심의")
    out["irb"]["unknowns"] = unknowns
    out["guard"] = {"rule": _GUARD_RULE, "original_verdict": "EXEMPT"}
    return out, _GUARD_NOTE


def insert_guard_note(body: str, note: str) -> str:
    """가드 문구를 본문에 넣는다 — `<next_steps>` 블록이 있으면 그 앞에."""
    if not note:
        return body
    i = (body or "").find("<next_steps>")
    if i < 0:
        return (body or "").rstrip() + note + "\n"
    return body[:i].rstrip() + note + "\n\n" + body[i:]
