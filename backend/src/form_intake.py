"""서식 → 즉시 기입 가능한 문서 (2026-08-27).

**왜 있나.** [이 서식으로 작성]을 누르면 심층 보고서 파이프라인(분해→수집→
vLLM writer, 5~40분)이 돌고, 그게 끝나야 항목이 화면에 떴다. 사용자가 기대한
동작은 "서식이 뜨고 그걸 채우게 안내"인데 실사용에서 "왜 심층보고서 생성으로
가냐"는 지적을 받았다. **항목 목록은 서식 자체에 이미 있다** — LLM이 초안을 다
써야 알 수 있는 게 아니다. 그래서 서식 본문/파일에서 항목을 바로 뽑아 몇 초 만에
기입 화면을 띄우는 경로를 분리했다.

**분리 원칙.** 이 모듈은 repo·라우트·SSE 를 모르고, 문자열/바이트만 다룬다.
입력은 (서식 제목, 서식 본문 텍스트, 선택적 HWPX 경로), 출력은 (항목 목록,
`[확인 필요: X]` 마커가 박힌 skeleton 본문). 하위 경로(`doc_fill.run_turn_fill`,
`/documents/{id}/fill`, `form_fill.build_filled_form`)는 이 마커 계약만 보므로
그대로 재사용된다.
"""

from __future__ import annotations

import logging
import re

_log = logging.getLogger(__name__)

# 관보 서식 본문은 표가 박스문자로 평탄화돼 온다 — 라벨은 셀 안에 들어 있다.
#   `| 신청인 | │성명(한글) | │(한자) |`
# 그래서 줄 단위 정규식이 아니라 **셀 단위**로 쪼갠 뒤 걸러낸다.
_CELL_SPLIT_RE = re.compile(r"[│|┃]")
_BOX_ONLY_RE = re.compile(r"^[\s─━┈┄┬┴┼├┤┌┐└┘═╞╡╪\-]+$")

# 여기부터는 기입란이 아니다 — 첨부서류 목록·수수료표·처리절차 흐름도·유의사항.
# ※ `처리기간`·`접수번호` 는 관청 기입란이라 **멈춤이 아니라 잡음**이다(같은
#    줄에 실제 기입란이 없으므로 건너뛰기만 하면 된다). 여기서 멈추면 서식
#    본문 첫 표에서 파싱이 끝나 버린다.
_STOP_RE = re.compile(r"^(첨부서류|구비서류|수수료|처리\s*절차|유의사항|작성방법)")

# 셀이지만 라벨이 아닌 것 — 안내문·근거조문·관청 기입란(접수번호·발급일 등은
# 민원인이 채우는 칸이 아니다)·용지 규격.
_NOISE_RE = re.compile(
    r"(붙임|첨부|유의사항|작성방법|처리절차|구비서류|수수료|210mm|297mm|"
    r"백상지|일반용지|제\s*\d+\s*조|「|」|다음과 같이|위와 같이|"
    r"접수번호|접수일|발급일|처리기간|참조|해당|표시|신청할 수 있습니다|원$|"
    # 서명란·수신처·서식 자신의 이름(법령명·서식명)은 기입란이 아니다.
    r"귀하|서명\s*또는\s*인|^년\s*월\s*일$|시행규칙|시행령|앞쪽|뒤쪽|"
    r"(신청서|신고서|보고서|허가증|증명서)$|"
    # 체크박스 보기(`[ ]동의함`)·줄바꿈으로 잘린 안내 문장 조각. 라벨이 아니라
    # 선택지·설명이라 칩으로 띄우면 채울 수 없는 칸이 늘어난다.
    r"\[\s*\]|되거나|하지 않음|경우\)?$|"
    # 번호 매긴 안내문(`2. 기술문서 심사 대상: 65일`).
    r"^\d+\s*[.)]\s)"
)

# 조사가 붙은 문장 조각은 라벨이 아니다 — 체크박스 보기 문구가 셀에 통째로
# 들어오면 `의약품과 의료기기가 조합` 같은 게 기입 칸으로 뜬다.
_SENTENCE_RE = re.compile(r"[가-힣](?:이|가|을|를|은|는|와|과|에|로)\s")

# 짧고 뒤에 하위 셀을 거느리는 첫 셀은 구획 머리말이다(신청인·품질책임자).
# 같은 `성명`이 두 구획에 나오므로, 중복될 때 이 머리말로 한정해야 사용자가
# 어느 칸을 채우는지 알 수 있다.
_SECTION_MAX = 10

# 관보 서식에 거의 항상 있고 사용자가 반드시 채워야 하는 항목. 본문 파싱이
# 부실해도 최소한 이만큼은 기입 화면에 뜨게 하는 바닥값.
_BASELINE_FIELDS = ["성명(법인명)", "주소", "연락처"]

MAX_FIELDS = 25


def _clean(label: str) -> str:
    """라벨 정규화 — 꼬리 기호·공백 정리. 빈 문자열이면 버린다."""
    s = re.sub(r"\s+", " ", str(label or "")).strip(" \t·.,[]{}〔〕")
    # 표 셀 경계에서 잘려 짝이 안 맞는 괄호를 복원한다 — `성명(한글` 이 그대로
    # 칩에 뜨면 사용자가 서식과 대조하기 어렵다.
    if s.count("(") == s.count(")") + 1:
        s += ")"
    elif s.count(")") == s.count("(") + 1:
        s = "(" + s
    return s.strip(" ()") if set(s) <= {"(", ")", " "} else s


def _looks_like_field(label: str) -> bool:
    if not (2 <= len(label) <= 20):
        return False
    # "또는"의 "는"이 조사로 오인되면 `법인등록번호 또는 주민등록번호` 같은
    # 진짜 항목이 탈락한다 — 접속사는 조사 판정에서 빼고 본다.
    if _NOISE_RE.search(label) or _SENTENCE_RE.search(
            label.replace('또는', '및').replace('그리고', '및')):
        return False
    # 숫자·기호만 있는 조각은 라벨이 아니다.
    return bool(re.search(r"[가-힣A-Za-z]", label))


def fields_from_text(full_text: str, *, limit: int = MAX_FIELDS) -> list[str]:
    """서식 본문 텍스트에서 기입 항목 라벨을 뽑는다(등장 순서, dedupe).

    표 셀로 쪼갠 뒤 첨부서류·수수료표 앞에서 멈춘다 — 그 뒤는 제출 안내지
    기입란이 아니다.
    """
    out: list[str] = []
    seen: set[str] = set()
    section = ""
    for line in str(full_text or "").splitlines():
        if _BOX_ONLY_RE.match(line):
            continue
        cells = [_clean(c) for c in _CELL_SPLIT_RE.split(line)]
        cells = [c for c in cells if c]
        if not cells:
            continue
        if any(_STOP_RE.match(c) for c in cells):
            break
        head, rest = cells[0], cells[1:]
        if rest and len(head) <= _SECTION_MAX and _looks_like_field(head):
            # 구획 머리말 — 자신은 기입란이 아니고, 뒤 셀들의 소속을 정한다.
            section = head
            candidates = rest
        else:
            candidates = cells
        for cell in candidates:
            if not _looks_like_field(cell):
                continue
            label = cell
            if label in seen and section and section != label:
                label = f"{section} {cell}"
            if label in seen:
                continue
            seen.add(label)
            out.append(label)
            if len(out) >= limit:
                return out
    return out


def fields_from_form_file(form_path: str, *, limit: int = MAX_FIELDS) -> list[str]:
    """HWPX 실파일에서 라벨 추출(kordoc). 미가용·실패는 빈 목록 — 호출자가
    본문 파싱으로 폴백한다."""
    try:
        from src.form_fill import kordoc_extract_labels

        labels = kordoc_extract_labels(form_path) or []
    except Exception:  # noqa: BLE001 — kordoc 미설치·서식 파손 모두 폴백 대상
        _log.debug("form_intake: kordoc 라벨 추출 실패 path=%s",
                   form_path, exc_info=True)
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in labels:
        label = _clean(raw)
        if _looks_like_field(label) and label not in seen:
            seen.add(label)
            out.append(label)
        if len(out) >= limit:
            break
    return out


def build_skeleton(title: str, fields: list[str], *,
                   source_note: str = "") -> str:
    """기입 화면이 곧바로 읽는 skeleton 본문.

    `[확인 필요: X]` 마커 계약은 기존 초안 본문과 동일하므로, 채팅 기입·항목별
    AI 작성·원본 서식 다운로드가 코드 변경 없이 그대로 붙는다.
    """
    head = str(title or "서식").strip() or "서식"
    lines = [f"# {head}", ""]
    if source_note:
        lines += [source_note, ""]
    lines += ["## 기입 항목", ""]
    for f in fields:
        lines.append(f"- **{f}**: [확인 필요: {f}]")
    lines += [
        "",
        "## 안내",
        "",
        "- 위 항목은 선택하신 서식에서 뽑은 것입니다. 대화로 값을 말씀하시면 "
        "해당 항목이 자동으로 채워집니다.",
        "- 항목별 ✨ 버튼을 누르면 대화 맥락을 근거로 초안을 제안합니다. "
        "근거가 없으면 지어내지 않고 비워 둡니다.",
        "- 모두 채운 뒤 원본 서식(.hwpx)으로 내려받아 제출본으로 쓰십시오.",
    ]
    return "\n".join(lines)


def intake(title: str, full_text: str, *, form_path: str | None = None,
           source_note: str = "") -> tuple[list[str], str]:
    """서식 한 건 → (항목 목록, skeleton 본문).

    우선순위: 실파일 라벨(kordoc) > 본문 텍스트 파싱 > 바닥값. 셋 다 합쳐서
    보강하지 않는 이유 — 라벨이 섞이면 같은 항목이 표기만 달리해 중복으로
    뜬다(사용자에겐 채워야 할 칸이 늘어난 것처럼 보인다).
    """
    fields: list[str] = []
    if form_path:
        fields = fields_from_form_file(form_path)
    if not fields:
        fields = fields_from_text(full_text)
    if not fields:
        _log.info("form_intake: 라벨 추출 실패 — 바닥값 사용 title=%s",
                  str(title)[:40])
        fields = list(_BASELINE_FIELDS)
    return fields, build_skeleton(title, fields, source_note=source_note)
