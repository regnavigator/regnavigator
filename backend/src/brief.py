"""서면·의견서 초안 — 문단 단위 수정 (2026-10-01).

변호사 업무지원 4/4. 조사에서 확인된 병목 중 "서면 초안 작성"을 겨냥한다.

**서식과 무엇이 다른가.** 서식은 빈 칸을 채우는 일이라 `[확인 필요: 항목]` 마커를
찾아 값을 꽂으면 끝난다(`doc_fill`). 서면은 산문이라 채울 칸이 없다 — 대신
"이 문단만 다시 써 달라"가 된다. 패널(좌 문서 / 우 도우미)·저장·다운로드·
온프레미스 레인은 서식 쪽을 그대로 쓰고, **주소 지정 방식만** 다르다.

설계
- **문단 주소는 인덱스 + 원문 대조**다. 인덱스만 쓰면 문단이 추가·삭제될 때 번호가
  밀려 엉뚱한 곳을 고친다. 본문에 앵커 주석을 심으면 견고하지만 마크다운이
  더러워지고 내보내기에 샌다. 그래서 FE 가 `{index, original_text}` 를 같이 보내고,
  서버가 그 자리 텍스트가 **아직 같은지** 확인한 뒤에만 교체한다. 어긋나면 거부한다
  (낙관적 동시성 — Edit 도구와 같은 규율).
- **인용 번호는 새로 못 만든다.** 수정된 문단이 `[7]` 을 지어내면 서면 전체가
  오염된다. 문서가 이미 가진 번호 집합 밖의 `[n]` 은 떼어내고 호출자에게 알린다.
  환각 방지 3중 장치와 같은 원칙 — 모델의 선의에 기대지 않는다.
- 제목(`#`·`##`)은 문단으로 세지 않는다. 섹션 제목을 "문단 3" 으로 고치라고 하면
  구조가 깨진다.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: 서면 골격 — 의견서의 관용 구성. 섹션 제목은 사용자가 고칠 수 있다.
BRIEF_SECTIONS: list[dict] = [
    {"key": "facts", "title": "사실관계",
     "focus": "다툼 없는 사실과 다투는 사실을 구분해 시간순으로"},
    {"key": "issues", "title": "쟁점",
     "focus": "법적 쟁점을 번호로 분리 — 사실 다툼과 법리 다툼을 섞지 않는다"},
    {"key": "law", "title": "관련 법령·조문",
     "focus": "적용 조문과 그 요건. 각 조문에 인용 번호를 단다"},
    {"key": "analysis", "title": "검토",
     "focus": "쟁점별로 요건 충족 여부. 반대 견해가 가능하면 함께 적는다"},
    {"key": "conclusion", "title": "결론",
     "focus": "단정하지 않는다 — 확인이 필요한 사항을 남긴다"},
]

#: 한 서면이 가질 수 있는 최대 문단 — 넘으면 수정 UI 가 의미를 잃는다.
MAX_PARAGRAPHS = 400

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_CITE = re.compile(r"\[(\d{1,3})\]")


class ReviseConflict(Exception):
    """지정한 자리의 원문이 바뀌어 있어 교체를 거부했다."""

    def __init__(self, message: str, *, current: Optional[str] = None):
        super().__init__(message)
        self.current = current


def split_paragraphs(body: str) -> list[dict]:
    """본문을 문단으로 쪼갠다 — `{index, text, kind}`.

    빈 줄 기준으로 나누고, 제목 블록은 `kind="heading"` 으로 표시해 수정 대상에서
    뺄 수 있게 한다(인덱스는 그대로 부여 — FE 가 같은 번호로 가리킨다).
    """
    out: list[dict] = []
    for i, raw in enumerate(re.split(r"\n\s*\n", body or "")):
        text = raw.strip()
        if not text:
            continue
        out.append({
            "index": len(out),
            "text": text,
            "kind": "heading" if _HEADING.match(text) else "paragraph",
        })
        if len(out) >= MAX_PARAGRAPHS:
            break
    return out


def allowed_citations(body: str) -> set[int]:
    """문서 전체가 이미 쓰고 있는 인용 번호."""
    return {int(m) for m in _CITE.findall(body or "")}


def sanitize_citations(text: str, allowed: set[int]) -> tuple[str, list[int]]:
    """허용 집합 밖의 `[n]` 을 떼어낸다. (정리된 텍스트, 떼어낸 번호들)

    모델이 근거를 지어내는 가장 흔한 형태가 **없는 인용 번호 붙이기**다. 본문에
    남겨 두면 읽는 사람은 그 번호에 해당하는 근거가 있다고 믿는다.
    """
    dropped: list[int] = []

    def _sub(m: re.Match) -> str:
        n = int(m.group(1))
        if n in allowed:
            return m.group(0)
        if n not in dropped:
            dropped.append(n)
        return ""

    cleaned = _CITE.sub(_sub, text or "")
    # 인용을 뗀 자리에 생긴 군더더기 공백 정리 — " ." / "  " 같은 꼴.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.·」』\)])", r"\1", cleaned)
    return cleaned.strip(), dropped


def revise_paragraph(
    body: str,
    *,
    index: int,
    original_text: str,
    replacement: str,
) -> tuple[str, list[int]]:
    """`index` 문단을 `replacement` 로 바꾼 새 본문. (본문, 제거된 인용번호)

    `original_text` 가 그 자리의 현재 텍스트와 다르면 `ReviseConflict`.
    조용히 다른 문단을 고치느니 거부하고 다시 읽게 하는 편이 낫다.
    """
    paras = split_paragraphs(body)
    if index < 0 or index >= len(paras):
        raise ReviseConflict(f"문단 {index} 이 없습니다(현재 {len(paras)}개).")

    current = paras[index]["text"]
    if current.strip() != (original_text or "").strip():
        raise ReviseConflict(
            "그 사이 문단이 바뀌었습니다. 문서를 다시 읽고 수정해 주세요.",
            current=current,
        )

    new_text, dropped = sanitize_citations(replacement, allowed_citations(body))
    if not new_text:
        raise ReviseConflict("수정 결과가 비어 있습니다.")

    paras[index]["text"] = new_text
    return "\n\n".join(p["text"] for p in paras), dropped


def skeleton(title: str, *, sections: Optional[list[dict]] = None) -> str:
    """빈 서면 골격 — 각 섹션은 `pending` 안내 한 줄로 시작한다."""
    parts = [f"# {title.strip() or '의견서'}", ""]
    for sec in (sections or BRIEF_SECTIONS):
        # 제목과 안내문 사이에 빈 줄을 **반드시** 둔다 — 붙여 두면 한 덩어리가 돼
        # 전체가 heading 으로 분류되고, 수정할 수 있는 문단이 하나도 없어진다.
        parts.append(f"## {sec['title']}")
        parts.append("")
        parts.append(f"_{sec['focus']}_")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


# ── 모델 호출 (2026-10-01) ───────────────────────────────────────────────────
#
# `doc_fill` 의 온프레미스 레인을 그대로 쓴다 — 서면에는 사건 사실관계가 들어가므로
# 서식 기입과 같은 취급이어야 한다. 모델 선택·서킷브레이커·슬롯 제한 전부 재사용.

_REVISE_PROMPT = """당신은 법률 서면을 다듬는 조수다. 아래 **문단 하나만** 고쳐 쓴다.

규칙:
- 고친 문단 **본문만** 출력한다. 머리말·설명·따옴표·코드펜스를 붙이지 않는다.
- `[1]` 같은 인용 번호는 **문서에 이미 있는 것만** 쓴다. 새 번호를 만들지 않는다.
- 근거 없는 단정을 보태지 않는다. 지시가 근거를 요구하면 문서 안에서만 찾는다.
- 지시를 수행할 수 없으면 `CANNOT` 한 단어만 출력한다.

[문서 전체 — 맥락 파악용. 이 부분을 고치는 게 아니다]
{document}

[고칠 문단]
{paragraph}

[지시]
{instruction}
"""


async def generate_revision(
    *,
    document: str,
    paragraph: str,
    instruction: str,
    model=None,
) -> Optional[str]:
    """문단 수정안을 받아 온다. 모델이 거부하거나 호출이 실패하면 None.

    인용 번호 검증은 호출자(`revise_paragraph`)가 한다 — 프롬프트로 부탁하는 것과
    기계적으로 막는 것은 다르다.
    """
    from src.doc_fill import (_commercial_model, _fill_model, assist_slot,
                              mark_onprem_failure, mark_onprem_ok, onprem_fill)

    use_onprem = onprem_fill()
    llm = model or (_fill_model() if use_onprem else _commercial_model())
    prompt = _REVISE_PROMPT.format(
        document=(document or "")[:12000],
        paragraph=(paragraph or "")[:4000],
        instruction=(instruction or "")[:800],
    )
    try:
        with assist_slot():
            res = await llm.ainvoke(prompt)
        if model is None and use_onprem:
            mark_onprem_ok()
    except Exception:  # noqa: BLE001 — 실패는 '수정 없음'으로 떨어뜨린다
        if model is None and use_onprem:
            mark_onprem_failure("brief_revise")
        return None

    raw = getattr(res, "content", "")
    if isinstance(raw, list):
        raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
    text = str(raw or "").strip()
    # 코드펜스로 감싸 오는 모델이 있다 — 벗긴다.
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    if not text or text.upper().startswith("CANNOT"):
        return None
    return text[:4000]


# ── 초안 조립 (2026-10-02) ───────────────────────────────────────────────────
#
# 처음엔 골격만 만들었다. "지어내지 않는다"를 지키려던 건데, 실사용 반응은
# "그냥 서식만 나온다"였다 — 맞는 지적이다. 빈 칸만 주는 건 도구가 아니다.
#
# 해법은 "모델에게 쓰게 한다"가 아니라 **이미 가진 재료로 조립한다**이다.
# 이 스레드에는 사용자가 직접 쓴 사실관계(질문)와 근거를 갖춘 답변, 그리고 인용
# 목록이 있다. 그걸 섹션에 배치하면 **아무것도 지어내지 않고** 초안이 찬다.
# LLM 은 그 뒤에 '다듬기'로만 들어간다 — 없는 사실을 만드는 자리가 아니다.

_MAX_FACT_CHARS = 1500
_MAX_SECTION_CHARS = 2500


def _msg_text(m: Any) -> str:
    c = getattr(m, "content", m if isinstance(m, str) else "")
    if isinstance(c, list):
        c = "".join(b.get("text", "") for b in c if isinstance(b, dict))
    return str(c or "").strip()


def _strip_markers(text: str) -> str:
    """`<next_steps>`·`<pathway>` 등 마커를 걷어낸다 — 서면에 들어갈 글이 아니다."""
    return re.sub(r"<(next_steps|pathway|verdict)>.*?</\1>", "", text or "",
                  flags=re.S | re.I).strip()


#: 채팅 서두 — v32 에서 금지했지만 **그 전에 쌓인 답변**에는 남아 있다.
#: 서면에 "지금까지 확보한 근거를 바탕으로 정리합니다" 가 들어가면 그대로 우스워진다.
_PREAMBLE_RE = re.compile(
    r"^\s*(지금까지\s*확보한\s*근거[^\n.]*[.。]?"
    r"|검색\s*결과를\s*종합[^\n.]*[.。]?"
    r"|관련\s*법령을\s*찾아[^\n.]*[.。]?"
    r"|질문(해\s*주신|하신)[^\n.]*답변[^\n.]*[.。]?"
    r"|아래와\s*같이\s*안내[^\n.]*[.。]?)\s*",
    re.M)


def _strip_preamble(text: str) -> str:
    return _PREAMBLE_RE.sub("", text or "", count=1).lstrip("-— \n")


#: AI 에게 시킨 **지시문** — 사실관계가 아니다. "…정리해줘", "…알려주세요".
_INSTRUCTION_RE = re.compile(
    r"[^.。!?\n]*?(?:해\s*줘|해줘|알려\s*줘|알려주세요|정리해|작성해\s*줘|"
    r"분해해\s*줘|찾아\s*줘|해\s*주세요|바랍니다)\s*[.。!?]?\s*$")


def _facts_only(text: str) -> str:
    """사용자 입력에서 **AI 에게 시킨 부분**을 떼어낸다.

    기능 카드 템플릿은 "…와 관련해 밟아야 하는 의무를 단계별로 분해해줘. 각
    단계마다 어디에 접수하는지…" 처럼 지시문이 길다. 그대로 사실관계에 넣으면
    의견서에 "분해해줘"가 적힌다. 지시 문장을 떼고 남는 것이 사실이다.
    """
    kept = []
    for sent in re.split(r"(?<=[.。!?])\s+", (text or "").strip()):
        if not sent.strip():
            continue
        if _INSTRUCTION_RE.fullmatch(sent.strip()):
            continue
        kept.append(sent.strip())
    return " ".join(kept).strip()


def compose_from_thread(
    messages: list,
    citations: list[dict],
    *,
    title: str,
) -> str:
    """대화와 인용으로 **채워진** 초안을 조립한다. LLM 을 쓰지 않는다.

    - 사실관계 : 사용자가 **직접 쓴** 질문 — 지어낼 여지가 없다
    - 쟁점     : 질문을 번호로 분리
    - 관련 법령 : 수집된 인용 목록(번호 그대로)
    - 검토/결론 : 이미 근거 검증을 거친 답변 본문
    각 섹션에 재료가 없으면 비워 두지 않고 **"대화에서 확인되지 않음"** 으로
    표시한다 — 빈 칸은 빠뜨린 것인지 없는 것인지 구분이 안 된다(원칙 5와 같다).
    """
    humans = [_msg_text(m) for m in messages
              if getattr(m, "type", "") == "human"]
    ais = [_strip_preamble(_strip_markers(_msg_text(m))) for m in messages
           if getattr(m, "type", "") == "ai"]
    humans = [h for h in humans if h]
    ais = [a for a in ais if len(a) > 80]

    def _missing(what: str) -> str:
        return f"_（{what} — 대화에서 확인되지 않았습니다. 직접 작성하세요.）_"

    out: list[str] = [f"# {title.strip() or '의견서'}", ""]

    # 1) 사실관계 — 사용자가 쓴 그대로. 요약하면 그 순간부터 해석이 섞인다.
    out += ["## 사실관계", ""]
    facts = [f for f in (_facts_only(h) for h in humans) if f]
    if facts:
        out += ["\n\n".join(facts)[:_MAX_FACT_CHARS], "",
                "_위 내용은 상담 과정에서 입력된 내용입니다. 사건 기록과 대조해 "
                "보완하십시오._", ""]
    elif humans:
        # 사실 진술 없이 질의만 오간 대화다(기능 카드 템플릿이 흔히 그렇다).
        # 질의문을 사실관계인 척 올리면 의견서에 "분해해줘"가 적힌다. 그 상태를
        # 그대로 드러내고, 입력된 질의는 인용으로 남겨 참고하게 한다.
        out += ["_（이 상담에는 사건의 사실관계가 입력되지 않았습니다. "
                "의뢰인 사실관계를 여기에 적으십시오.）_", ""]
        for h in humans[:3]:
            out += ["> " + " ".join(h.split())[:200], ""]
    else:
        out += [_missing("사실관계"), ""]

    # 2) 쟁점 — 물어본 것이 곧 쟁점이다.
    out += ["## 쟁점", ""]
    if humans:
        for i, h in enumerate(humans, start=1):
            one = " ".join(h.split())[:160]
            out.append(f"{i}. {one}")
        out.append("")
    else:
        out += [_missing("쟁점"), ""]

    # 3) 관련 법령·조문 — 인용 번호를 그대로 쓴다(본문 [n] 과 맞물린다).
    out += ["## 관련 법령·조문", ""]
    laws = [c for c in citations if c.get("source_kind") != "web"]
    if laws:
        for c in laws[:40]:
            t = str(c.get("title") or "").strip() or "(제목 없음)"
            pub = str(c.get("publisher") or "").strip()
            out.append(f"- `[{c.get('number')}]` {t}" + (f" — {pub}" if pub else ""))
        out.append("")
    else:
        out += [_missing("관련 법령"), ""]

    # 4) 검토 — 이미 근거 검증(grounding)을 거친 답변이 재료다.
    out += ["## 검토", ""]
    if ais:
        out += [ais[-1][:_MAX_SECTION_CHARS], ""]
        if len(ais) > 1:
            out += ["### 앞선 검토", ""]
            for a in ais[:-1]:
                out += [" ".join(a.split())[:400], ""]
    else:
        out += [_missing("검토"), ""]

    # 5) 결론 — 단정하지 않는다. 확인이 필요한 것을 남기는 자리다.
    out += ["## 결론", "",
            "_（위 검토를 토대로 결론을 작성하십시오. 확인이 필요한 사항은 "
            "그대로 남겨 두는 편이 낫습니다.）_", ""]

    if any(c.get("source_kind") == "web" for c in citations):
        out += ["## 참고(웹 자료)", ""]
        for c in [c for c in citations if c.get("source_kind") == "web"][:15]:
            u = str(c.get("url") or "").strip()
            out.append(f"- `[{c.get('number')}]` {c.get('title')}"
                       + (f" — {u}" if u else ""))
        out.append("")

    return "\n".join(out).rstrip() + "\n"


# ── 자동 다듬기 (2026-10-02) ────────────────────────────────────────────────
#
# 조립 결과는 재료 그대로라 문체가 섞인다 — 사용자가 쓴 구어, 채팅 답변의
# 설명체, 인용 목록이 한 문서에 있다. 의견서로 내려면 보고서체로 통일해야 한다.
#
# **다듬기는 쓰기가 아니다.** 모델에게 주는 것은 그 섹션의 내용뿐이고, 할 일은
# "주어진 내용을 논리적 순서로 재배열하고 격식체로 고쳐 쓰기"다. 새 사실·새 인용
# 번호는 금지하고, 인용 번호는 호출자가 기계적으로 검증한다(`sanitize_citations`).

_POLISH_PROMPT = """다음은 법률 의견서의 「{section}」 절 초안이다. 이를 **보고서체**로 고쳐 써라.

지켜야 할 것:
- **주어진 내용만** 쓴다. 새로운 사실·법령·수치·날짜를 보태지 않는다.
- `[1]` 같은 인용 번호는 **원문에 있는 것만** 그대로 둔다. 새로 만들지 않는다.
- 격식체(`-다`체)로 통일한다. "~해요", "~합니다" 같은 구어·설명체를 쓰지 않는다.
- 논리 순서로 재배열한다: 전제 → 근거 → 결과. 중복은 합치고 군더더기는 뺀다.
- 목록이 적절한 내용은 목록으로, 서술이 적절한 내용은 문단으로 쓴다.
- 제목(`##`)은 건드리지 않는다. 본문만 돌려준다.
- 원문이 비어 있거나 안내문(`_（…）_`)뿐이면 **그대로** 돌려준다.

고쳐 쓴 본문만 출력한다. 설명·머리말을 붙이지 않는다.

[「{section}」 절 원문]
{content}
"""


async def polish_section(
    section: str,
    content: str,
    *,
    allowed: set[int],
    model=None,
) -> Optional[tuple[str, list[int]]]:
    """한 절을 보고서체로 다듬는다. (다듬은 본문, 제거된 인용번호) 또는 None.

    실패하면 None — 호출자는 원문을 그대로 둔다. 다듬기가 안 되는 것보다
    없는 사실이 들어가는 게 나쁘다.
    """
    body = (content or "").strip()
    if len(body) < 40:
        return None               # 안내문뿐인 절은 다듬을 것이 없다

    from src.doc_fill import (_commercial_model, _fill_model, assist_slot,
                              mark_onprem_failure, mark_onprem_ok, onprem_fill)

    use_onprem = onprem_fill()
    llm = model or (_fill_model() if use_onprem else _commercial_model())
    prompt = _POLISH_PROMPT.format(section=section, content=body[:6000])
    try:
        with assist_slot():
            res = await llm.ainvoke(prompt)
        if model is None and use_onprem:
            mark_onprem_ok()
    except Exception:  # noqa: BLE001
        if model is None and use_onprem:
            mark_onprem_failure("brief_polish")
        return None

    raw = getattr(res, "content", "")
    if isinstance(raw, list):
        raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", str(raw or "").strip()).strip()
    if not text:
        return None

    cleaned, dropped = sanitize_citations(text, allowed)
    if not cleaned:
        return None
    # 길이가 1/4 밑으로 줄면 다듬기가 아니라 요약이다 — 내용이 날아간다.
    if len(cleaned) < len(body) * 0.25:
        _log.info("다듬기 결과가 과도하게 짧다(%d→%d) — 원문 유지",
                  len(body), len(cleaned))
        return None
    return cleaned, dropped


def split_sections(body: str) -> list[tuple[str, str]]:
    """`## 제목` 기준으로 (제목, 본문) 으로 가른다. 머리말은 제목 `""`."""
    out: list[tuple[str, str]] = []
    cur_title, buf = "", []
    for line in (body or "").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            out.append((cur_title, "\n".join(buf).strip()))
            cur_title, buf = m.group(1), []
        else:
            buf.append(line)
    out.append((cur_title, "\n".join(buf).strip()))
    return out


def join_sections(sections: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for title, body in sections:
        if title:
            parts.append(f"## {title}")
            parts.append("")
        if body:
            parts.append(body)
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"
