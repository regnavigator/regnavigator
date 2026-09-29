"""보고서 본문 작성 엔진 — 섹션 분할 / 단발 (2026-08-25 분리).

**경계**: 이 모듈은 medi-back 의 보고서 파이프라인·저장소·인용 스키마를
모른다. 입력은 `llm`(주입) + 작성 규율 문자열 + writer 입력 dict 뿐이고,
출력은 **본문 마크다운 문자열**이다. DB·repo·FastAPI 의존 0 — 그대로 떼어
다른 파이프라인에 붙일 수 있다(경계 가드: tests/test_report_sectioned.py).

왜 섹션 분할인가: 단발 writer 는 응답 하나의 자연 길이 한계(운영 실측
중앙값 5,995자)에 갇힌다. `max_tokens` 를 올려도 모델이 그만큼 길게 쓰지
않는다 — 상위 구간만 상한(8,000토큰)에 압착돼 있었을 뿐. 길이는 **호출
수**로 늘린다: 섹션마다 독립 호출 → 각자 목표치를 채우고 합이 곧 분량.
(참고 설계: Agent-Swarm-4-Research-Report-Generator 의 section-writer —
 같은 레포의 *단발* 경로도 목표가 4,000~5,000자로 우리와 같은 벽이었다.)
"""
from __future__ import annotations

import json
import logging
import os

_log = logging.getLogger(__name__)

def sectioned_enabled() -> bool:
    return (os.getenv("REPORT_SECTIONED") or "").strip() != "0"


def section_target() -> int:
    """섹션 1개 기본 목표 글자수 — 총 분량은 배분 배수의 합(아래 _SECTION_PLAN)."""
    try:
        return max(800, int((os.getenv("REPORT_SECTION_TARGET_CHARS")
                             or "").strip() or "4000"))
    except ValueError:
        return 4000


# (섹션명, 목표 배수, 초점) — 기존 5섹션 계약 유지(FE·overview 추출이 의존).
# 배수는 **실측 달성률**에 맞춰 배분한다(2026-08-25 첫 섹션 분할 보고서):
# 실무 액션 122%·근거 86% 는 소재가 풍부해 넘치고, 리스크/후속 40%·핵심 결론
# 55% 는 소재 자체가 적어 확장 재호출로도 못 채웠다. 못 채울 목표를 걸면
# 헛된 재호출만 늘고 억지 서술 압박이 된다 — 총합(4.75)은 유지한 채 재배분.
_SECTION_PLAN: tuple[tuple[str, float, str], ...] = (
    ("개요", 0.15,
     "결론·핵심 근거·다음 행동을 3~5문장으로. 채팅 응답으로 그대로 발췌되므로 "
     "이것만 읽고도 이해되게 쓴다. 여기서는 길게 쓰지 않는다."),
    ("핵심 결론", 0.8,
     "결론마다 근거 조항과 실무 함의를 함께 단다. 질문에 대한 답을 단정적으로 "
     "제시하되 근거가 해석을 경유하면 그 사실을 밝힌다."),
    ("근거", 1.9,
     "관련 조문(조·항·호)의 요건·정의·적용범위·예외를 소단락으로 나눠 상술하고 "
     "조문 간 관계(위임·준용·연계)를 설명한다. 분야·층위가 갈리면 공통 원칙 "
     "소단락 + 분야별 차이 소단락으로 나누고 비교표를 둔다. 가장 두꺼운 섹션이다."),
    ("실무 액션", 1.3,
     "단계별 절차·필요 서류·기한·주체를 표로 정리하고, 표 앞뒤에 결론 문장과 "
     "예외·주의 해설 문단을 둔다."),
    ("리스크/후속", 0.6,
     "위반 시 제재를 구체 수치(징역·벌금액·처분 기간)로, 예외·가중·판례·최신 "
     "동향까지. 제재 유형별로 분리 서술한다."),
)


# ── 동적 본론 목차 (2026-08-28) ─────────────────────────────────────────
# 서론(개요)·결론은 고정, 본론은 주제에 맞게 설계된 플랜(외부에서 LLM 이
# 생성)을 받는다. 플랜이 없거나 깨지면 기존 5섹션(_SECTION_PLAN)으로 폴백
# — 목차 설계 실패가 보고서를 망치면 안 된다(개악 없음 원칙).
_HEAD_SPEC = _SECTION_PLAN[0]  # ("개요", 0.15, …) — 채팅 발췌 계약이라 불변
_TAIL_MULT = 0.75
_TAIL_SPEC = ("결론 및 권고", _TAIL_MULT,
              "질문에 대한 종합 결론을 명시적으로 재진술하고, 남은 리스크"
              "(위반 시 제재는 징역·벌금액 등 구체 수치로)·판단의 전제와 "
              "한계·후속 확인 경로(소관 부처·절차·기한)를 정리한다. 본론을 "
              "요약 반복하지 말고 판단과 권고로 마무리한다.")
_BODY_MULT_TOTAL = 4.75 - _HEAD_SPEC[1] - _TAIL_MULT  # 총 분량 경제 유지


def build_dynamic_specs(purpose: str | None, evidence_count: int | None,
                        body_plan: list[dict]) -> list[dict]:
    """서론·결론 고정 + 본론 플랜([{name,focus,share}] 2~5개) → 섹션 스펙.

    share 는 상대 가중치 — 합으로 정규화해 본론 총 배수(4.75-머리-꼬리)를
    배분한다. 목표 분량 경제(목적·근거량 배수)는 고정 플랜과 동일.
    """
    factor = (_PURPOSE_LENGTH.get((purpose or "").strip(), 1.0)
              * _evidence_factor(evidence_count))
    base = section_target() * factor
    shares = [max(0.05, float(b.get("share") or 1.0)) for b in body_plan]
    ssum = sum(shares) or 1.0
    plan = [_HEAD_SPEC] + [
        (str(b["name"]).strip(), _BODY_MULT_TOTAL * sh / ssum,
         str(b.get("focus") or "").strip())
        for b, sh in zip(body_plan, shares)
    ] + [_TAIL_SPEC]
    return [{"name": n, "target": max(400, int(base * m)), "focus": f}
            for n, m, f in plan]


def insert_toc(body: str) -> str:
    """H1 아래에 `## ` 헤더들로 목차 삽입 — 조립 마지막에 호출(순수)."""
    import re as _re

    heads = _re.findall(r"(?m)^## (.+?)\s*$", body)
    heads = [h for h in heads if h.strip() != "목차"]
    if len(heads) < 2:
        return body
    toc = "\n".join(f"{i}. {h}" for i, h in enumerate(heads, 1))
    m = _re.search(r"(?m)^# .+?\n", body)
    if not m:
        return f"## 목차\n\n{toc}\n\n{body}"
    at = m.end()
    return body[:at] + f"\n## 목차\n\n{toc}\n" + body[at:]


# 목적별 분량 배수 (2026-08-25) — 같은 5섹션이라도 쓰임새가 다르다.
# 적용 규제 '요약'에 2만 자를 요구하면 채우기용 서술이 나온다(정확성 우선 위배).
_PURPOSE_LENGTH: dict[str, float] = {
    # 인허가 전략: 경로·등급·선택지·리스크·실행순서까지 — 최대 깊이.
    "license_strategy": 1.0,
    # 규제 변화 대응: 개정 사항·영향·시점별 조치 중심 — 중간.
    "change_response": 0.8,
    # 적용 규제 요약: 요건을 체계적으로 정리하는 게 목적 — 간결하게.
    "reg_summary": 0.55,
}


def _evidence_factor(n: int | None) -> float:
    """근거량 연동 — 근거가 얇은데 분량 목표만 높으면 '채우기 위한 서술'이 된다.

    분량은 목표지 의무가 아니다(규율: 정확성 > 충실함 > 형식). 확보된 인용
    건수에 맞춰 목표 자체를 낮춰, 미달 확장 재호출이 헛돌지 않게 한다.
    """
    if n is None:
        return 1.0
    if n < 8:
        return 0.55
    if n < 15:
        return 0.8
    return 1.0


def section_specs(purpose: str | None = None,
                  evidence_count: int | None = None) -> list[dict]:
    """섹션별 목표 — 기본 배수 × 목적 배수 × 근거량 배수."""
    factor = (_PURPOSE_LENGTH.get((purpose or "").strip(), 1.0)
              * _evidence_factor(evidence_count))
    base = section_target() * factor
    return [{"name": name, "target": max(400, int(base * mult)), "focus": focus}
            for name, mult, focus in _SECTION_PLAN]


_SECTION_MODE_HEADER = (
    "\n\n[섹션 분할 작성 모드 — 이번 호출 규정이 위 형식 규칙보다 **우선**]\n"
    "이번 호출에서는 지정된 **한 섹션만** 작성합니다. 다른 섹션은 쓰지 않습니다.\n"
    "- 위 규율의 '첫 줄 H1 제목'·'본문 전체 8,000자' 규칙은 이번 호출에 "
    "적용하지 않습니다(제목과 총 분량은 시스템이 조립합니다).\n"
    "- 출력은 `## {섹션명}` 헤더 한 줄로 시작해 그 섹션 본문만 이어 씁니다. "
    "다른 `## ` 헤더를 만들지 않습니다(섹션 내부 구분은 `### ` 소제목 사용).\n"
    "- **목표 분량은 확정 요구사항입니다** — 미달하면 실패로 처리됩니다. 다만 "
    "분량을 채우려고 근거 없는 서술을 만들지 않습니다(정확성이 우선). 근거가 "
    "모자라면 제공된 citation 을 더 폭넓게 활용해 요건·예외·실무 함의를 "
    "상술하는 방식으로 채웁니다.\n"
    "- **수치가 든 문장은 예외 없이 `[N]` 인용을 답니다 — 표 셀 안도 "
    "동일합니다**(금액·비율·기한·형량·본인부담률 등). 표는 서술보다 인용이 "
    "빠지기 쉬우니 셀마다 근거를 확인하십시오.\n"
    "- 배정된 범위 밖 주제는 쓰지 않습니다. 앞뒤 섹션이 다룰 내용을 미리 "
    "요약하거나 반복하지 않습니다.\n"
    "- 첫 문장은 보고서 전체 흐름과 연결되게, 마지막 문장은 다음 섹션으로 "
    "이어지게 씁니다(개요·마지막 섹션 제외).\n"
)

_TITLE_PROMPT = (
    "다음 보고서 본문을 대표하는 한국어 제목 한 줄만 출력하라.\n"
    "- 40자 이내 명사구, 마크다운·따옴표·설명 없이 제목 텍스트만.\n"
    "- 사용자 사이드바에 그대로 노출된다. placeholder 금지.\n\n"
    "[본문 앞부분]\n{head}"
)


async def _stream_text(llm, prompt: str, cfg: dict, emit, label: str) -> str:
    """writer 스트림 1회 — 진행 라벨만 흘리고 본문은 서버에서만 누적."""
    chunks: list[str] = []
    if emit:
        emit("report_writer", "writing", label)
    async for c in llm.astream(prompt, cfg):
        delta = getattr(c, "content", "") or ""
        if isinstance(delta, list):
            delta = "".join(p.get("text", "") for p in delta
                            if isinstance(p, dict))
        delta = str(delta)
        if delta:
            chunks.append(delta)
    return "".join(chunks).strip()


def strip_stray_headers(text: str, name: str) -> str:
    """섹션 응답 정리 — 지정 섹션 외의 `## ` 헤더는 `### ` 로 강등.

    모델이 다음 섹션까지 앞서 쓰면 조립 시 중복 헤더가 된다(계약 위반).
    """
    out: list[str] = []
    seen_own = False
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("## ") and not s.startswith("### "):
            title = s[3:].strip()
            if not seen_own and title.startswith(name[:4]):
                seen_own = True
                out.append(f"## {name}")
                continue
            out.append("### " + title)  # 남의 섹션 → 소제목으로 강등
            continue
        if s.startswith("# ") and not s.startswith("## "):
            continue  # H1 은 시스템이 붙인다
        out.append(line)
    body = "\n".join(out).strip()
    if not body.startswith("## "):
        body = f"## {name}\n\n{body}"
    return body


async def write_sections(
    llm, *, base_rules: str, purpose_note: str | None,
    writer_input: dict, cfg: dict, emit, sem, load,
    purpose: str | None = None, evidence_count: int | None = None,
    yield_gate=None,
    specs: list[dict] | None = None,
) -> str:
    """섹션별 독립 호출로 본문 작성 → 조립 (2026-08-25).

    각 호출에 전체 섹션 개요 + 자기 섹션 스펙 + **직전 섹션 꼬리**를 넣어
    응집성을 유지한다(병렬 fan-out 설계는 이걸 못 한다 — 순차의 이점).
    목표 미달(<80%) 섹션은 1회 확장 재호출.
    """
    if specs is None:
        specs = section_specs(purpose, evidence_count)
    _log.info("report sections: purpose=%s cites=%s 목표합=%d자 (%s)",
              purpose or '-', evidence_count,
              sum(x['target'] for x in specs),
              ', '.join(f"{x['name']} {x['target']}" for x in specs))
    outline = "\n".join(
        f"{i+1}. {s['name']} (목표 {s['target']:,}자) — {s['focus']}"
        for i, s in enumerate(specs))
    cites_json = json.dumps(writer_input, ensure_ascii=False)
    parts: list[str] = []
    prev_tail = ""
    for i, spec in enumerate(specs):
        name, target = spec["name"], spec["target"]
        prompt = (
            base_rules
            + (f"\n\n[보고서 목적] {purpose_note}" if purpose_note else "")
            + _SECTION_MODE_HEADER
            + f"\n[보고서 전체 구성]\n{outline}\n"
            + f"\n[이번 섹션] {i+1}. {name}\n"
            + f"- 초점: {spec['focus']}\n"
            + f"- **목표 분량: {target:,}자 이상** (확정 요구사항)\n"
            + (f"\n[직전 섹션 마지막 부분 — 이어지게 쓸 것]\n{prev_tail}\n"
               if prev_tail else "")
            + "\n[입력 JSON]\n" + cites_json
        )
        if yield_gate is not None:
            # 대화형(스킬 로컬) 우선 — 다음 섹션만 미룸. 훅 주입(순수 엔진 계약:
            # 이 모듈은 src.* 를 import 하지 않는다 — 결합 테스트가 강제).
            await yield_gate(emit)
        async with sem:
            load.report_active(1)
            try:
                text = await _stream_text(
                    llm, prompt, cfg, emit,
                    f"작성 중 · {name} ({i+1}/{len(specs)})")
                # 미달 확장 1회 — 레포 설계에 없던 구멍(길이 검증 부재) 보완.
                if text and len(text) < int(target * 0.8):
                    _log.info("report section '%s' %d자 < 목표 %d자 — 확장 재호출",
                              name, len(text), target)
                    ext = await _stream_text(
                        llm,
                        prompt
                        + "\n\n[확장 지시] 아래 초안은 목표 분량에 미달합니다. "
                          "**같은 섹션을 처음부터 다시**, 더 깊고 구체적으로 "
                          "작성하십시오(요건→예외→제재·연결→실무 함의 순으로 "
                          "소단락을 늘리고, 제공된 citation 을 더 폭넓게 인용). "
                          "새 사실을 지어내지 말고 기존 근거를 상술하십시오.\n"
                          f"[초안 {len(text)}자]\n{text[:3000]}",
                        cfg, emit, f"보강 중 · {name}")
                    if len(ext) > len(text):
                        text = ext
            finally:
                load.report_active(-1)
        if not text:
            _log.warning("report section '%s' 빈 응답 — 건너뜀", name)
            continue
        cleaned = strip_stray_headers(text, name)
        parts.append(cleaned)
        prev_tail = cleaned[-600:]
    return "\n\n".join(parts).strip()


async def write_single(llm, prompt: str, cfg: dict, emit) -> str:
    """단발 writer 스트림(구 경로) — 서식 초안 모드·섹션 모드 실패 시 폴백.

    본문은 서버에서만 누적하고, 마크다운 헤더가 나올 때만 진행 라벨을 흘린다
    (회귀 방지: 작성 중 본문이 통째로 채팅에 스트리밍된 사고).
    """
    chunks: list[str] = []
    buffer = ""
    async for c in llm.astream(prompt, cfg):
        delta = getattr(c, "content", "") or ""
        if isinstance(delta, list):
            delta = "".join(p.get("text", "") for p in delta
                            if isinstance(p, dict))
        delta = str(delta)
        if not delta:
            continue
        chunks.append(delta)
        buffer += delta
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                if title:
                    emit("report_writer", "writing", f"작성 중 · {title}")
    return "".join(chunks).strip()


async def make_title(llm, body: str, cfg: dict) -> str:
    """H1 제목 — 섹션 모드는 본문에 H1 이 없으므로 별도 1콜(짧음)."""
    try:
        raw = await llm.ainvoke(_TITLE_PROMPT.format(head=body[:1500]), cfg)
        t = getattr(raw, "content", "") or ""
        if isinstance(t, list):
            t = "".join(p.get("text", "") for p in t if isinstance(p, dict))
        t = str(t).strip().splitlines()[0].strip().lstrip("#").strip()
        t = t.strip('"“”\'')
        if t and len(t) <= 60:
            return t
    except Exception:  # noqa: BLE001 — 제목 실패가 보고서를 막으면 안 됨
        _log.debug("report title 생성 실패", exc_info=True)
    return "심층 보고서"
