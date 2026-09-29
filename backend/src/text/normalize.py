"""법령 본문 → frontend-ready markdown 정규화.

기존엔 frontend `preprocessLawText`에서 regex로 후처리 했지만, backend가 한 번에
깔끔한 markdown으로 보내면 그 단계 전체를 폐기 가능. 본 모듈은 동일 변환을
backend 단일 출처에서 수행 — citation snippet, /article.full_text, /annex.markdown
어디든 동일 결과.

frontend 명세 (P6.3.* + frontend 핸드오프 문서):
  1. CRLF → LF, BOM 제거
  2. paragraph 간 \n\n, paragraph 내부 한 줄
  3. ① ② ... ⑳ ㉑ ... ㉟ 항 / "1. 2. ..." 호 시작 시 줄바꿈 + 빈 줄
  4. <개정 ...> <신설 ...> <삭제 ...> <이동 ...> <폐지 ...> <폐기 ...> 인라인 OK,
     다음 항 시작 시 빈 줄
  5. ──── 가로 구분선 앞뒤 빈 줄
  6. ASCII 박스 표(┌┬┐│└┴┘├┤─┼) → markdown 표
  7. 한 줄에 묶인 markdown 표(| a | b | | --- | --- | | x | y |) → 행별 분리
  8. 0-padded 조항 번호(제0001조, 제0012항) → 제1조, 제12항
  9. 본문 시작부 헤더 라인 중복 제거 (law_title / article_num / article_title 단독)
 10. <심사주체> 같은 한글 태그 라인 → 앞뒤 빈 줄
"""

from __future__ import annotations

import re
from typing import Optional

__all__ = ["normalize_law_text"]


# ─── 정규식 모음 ───────────────────────────────────────────────────────────

# 항 번호 (① ~ ⑳ + ㉑ ~ ㉟). 인라인일 때 줄바꿈.
_HANG_RE = re.compile(r"([^\n])\s*([①-⑳㉑-㉟])")

# 호 번호 ("1. ", "2. " 등)가 *문장 도중* 인라인일 때 줄바꿈. 줄 시작은 그대로.
# 단순 숫자+점은 본문 일반 패턴과 겹치니 보수적으로 "}" "다" "." 뒤에만.
# 마침표 앞이 숫자면 날짜(2011. 4. 14.)이므로 제외 — 판례 본문 오분할 방지.
_HO_RE = re.compile(r"((?<!\d)\.|[다}])\s+(\d{1,2}\.\s)")

# 개정 이력 태그. 줄 끝에 인라인 OK, 다음 항 전 빈 줄 보장.
_REV_RE = re.compile(r"(<(?:신설|개정|삭제|이동|폐지|폐기)[^>]*>)\s*(?=[①-⑳㉑-㉟]|\Z|$)")

# 가로 구분선 — ─ U+2500 3개 이상.
_HR_RE = re.compile(r"^[\s─]*[─]{3,}[\s─]*$", re.MULTILINE)

# 0-padded 조항 번호: 제0001조 → 제1조. 항/호도 같은 패턴 적용.
_ZEROPAD_RE = re.compile(r"제0+(\d+)(조|항|호|목|관|장|절|편|편|편)")

# ASCII 박스 표 — 한 라인이 ┌─┐│└┴┘├┤┼ 만으로 구성된 boundary 줄 감지.
_BOX_CHARS = "┌┬┐│└┴┘├┤┼─━┃┏┓┗┛┣┫┻┳"
_BOX_BOUNDARY_RE = re.compile(r"^[\s" + re.escape(_BOX_CHARS) + r"]+$")
# 한국어 텍스트가 들어간 박스 행 — │로 시작/끝
_BOX_DATA_RE = re.compile(r"^\s*[│┃](.+)[│┃]\s*$")

# 표가 한 줄에 묶인 경우: `| a | b | | --- | --- | | x | y |`
# row 경계는 `| | --- |` 패턴 또는 `| ... | | ... |` 같은 `| |` 직접 연속.
_INLINE_TABLE_PIPE_RE = re.compile(r"\|\s+\|(?=\s*[-:\s]|\s*[^|])")

# 한글 태그 라인 (<심사주체>, <심사방법> 등). 줄에 그것만 단독으로 있을 때.
_KO_TAG_LINE_RE = re.compile(r"^\s*<[가-힣][^<>\s]*>\s*$")


# ─── 헬퍼 ─────────────────────────────────────────────────────────────────


def _split_inline_tables(text: str) -> str:
    """한 줄에 묶인 markdown table을 행별로 풀어 분리.

    `| a | b | | --- | --- | | x | y |` →
    `| a | b |\n| --- | --- |\n| x | y |`
    """
    # `| |` 직접 인접한 곳을 `|\n|` 으로 분리.
    # 단, 이미 줄바꿈이 있으면 건드리지 X — 정상 markdown 표는 패스.
    if "|" not in text:
        return text
    return _INLINE_TABLE_PIPE_RE.sub("|\n|", text)


def _convert_ascii_box_table(text: str) -> str:
    """ASCII 박스 표(┌┐└┘│─) → markdown 표.

    PDF/HWP에서 추출된 표가 ASCII 박스로 들어오면, boundary 라인 제거 +
    데이터 라인의 │ → | 치환 + header/separator 삽입.

    표 못 알아본 케이스는 원본 그대로 둠 (안전 fallback).
    """
    if not any(c in text for c in "┌└├┃│"):
        return text

    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        is_boundary = bool(_BOX_BOUNDARY_RE.match(line)) and any(
            c in line for c in _BOX_CHARS
        )
        is_data = bool(_BOX_DATA_RE.match(line))
        if not (is_boundary or is_data):
            out.append(line)
            i += 1
            continue

        # 표 블록 수집
        block: list[str] = []
        while i < len(lines):
            cur = lines[i]
            b = bool(_BOX_BOUNDARY_RE.match(cur)) and any(c in cur for c in _BOX_CHARS)
            d = bool(_BOX_DATA_RE.match(cur))
            if not (b or d):
                break
            block.append(cur)
            i += 1

        # 블록 → markdown 표
        rows: list[list[str]] = []
        for bl in block:
            if not _BOX_DATA_RE.match(bl):
                continue  # boundary 라인은 skip
            # │ ↔ | 치환, 양끝 │ 제거
            inner = bl.strip().strip("│┃").strip()
            cells = [c.strip() for c in re.split(r"[│┃]", inner)]
            rows.append(cells)
        if rows:
            ncols = max(len(r) for r in rows)
            # 행 컬럼 수 맞추기
            for r in rows:
                while len(r) < ncols:
                    r.append("")
            # header / separator / body
            out.append("")  # 표 앞 빈 줄
            out.append("| " + " | ".join(rows[0]) + " |")
            out.append("| " + " | ".join(["---"] * ncols) + " |")
            for r in rows[1:]:
                out.append("| " + " | ".join(r) + " |")
            out.append("")  # 표 뒤 빈 줄
        # i는 이미 다음 비-표 라인 가리킴
    return "\n".join(out)


_ARTICLE_HEADER_RE = re.compile(
    r"^\s*제\s*\d+조(?:의\s*\d+)?\s*\(.+\)\s*$"  # 예: "제4조 (제조허가...)" — 길이 무관
)
# 별표·서식 제목 라인 — "별표 N (제목)" / "별표 시설과 ..." / "별지 제N호서식" 등
_ATTACHMENT_HEADER_RE = re.compile(
    r"^\s*(?:별표|별지|서식)\s.*$"
)
# 법령명 단독 라인 — "의료기기법" / "의료기기법 시행규칙" / "...에 관한 법률" 등.
# 본문 시작부에만 적용 (헤더 dedup 컨텍스트), 본문 중간엔 영향 X.
_LAW_NAME_LINE_RE = re.compile(
    r"^\s*[가-힣\sㆍ·\(\)0-9]+(?:법|법률|규칙|령|례|조약|규정|규약|훈령|예규|고시)\s*$"
)


def _strip_leading_header_dups(
    text: str,
    *,
    law_title: Optional[str],
    article_num: Optional[str],
    article_title: Optional[str],
) -> str:
    """본문 시작부의 헤더성 라인(law_title / article_num / article_title 단독) 제거.

    Mongo 추출 결과가 카테고리마다 일관되지 않아 본문 첫 부분에 의미 없는 중복
    헤더가 들어옴. /article 헤더 prepend 전에 호출.

    헤더 판정:
      1) 빈 줄
      2) law_title / article_num / article_title 단독 (길이 +20 이내)
      3) "제N조 (제목)" 패턴 (길이 무관) — 본문 항(① ② ...)이 아니므로 안전
    """
    if not text:
        return text
    prefixes = [p for p in [article_title, article_num, law_title] if p]
    lines = text.split("\n")
    cleaned: list[str] = []
    skipping = True
    for ln in lines:
        s = ln.strip()
        if skipping:
            if not s:
                continue
            if _ARTICLE_HEADER_RE.match(s):
                continue
            if _ATTACHMENT_HEADER_RE.match(s) and len(s) < 80:
                continue
            if _LAW_NAME_LINE_RE.match(s) and len(s) < 40:
                continue
            if prefixes and any(
                s.startswith(p) and len(s) <= len(p) + 20 for p in prefixes
            ):
                continue
            # title prefix가 본문에 길게 박힌 경우 — 시작부 + 길이 < 100자면 dedup
            if prefixes and any(p in s and len(s) < 100 for p in prefixes):
                continue
        skipping = False
        cleaned.append(ln)
    return "\n".join(cleaned)


def _ensure_hr_blanks(text: str) -> str:
    """가로 구분선 앞뒤 빈 줄 보장."""
    def _sub(m: re.Match) -> str:
        return "\n\n" + m.group(0).strip() + "\n\n"

    out = _HR_RE.sub(_sub, text)
    return re.sub(r"\n{3,}", "\n\n", out)


def _ensure_ko_tag_blanks(text: str) -> str:
    """한글 태그 라인(<심사주체> 등) 앞뒤 빈 줄 보장."""
    lines = text.split("\n")
    out: list[str] = []
    for i, ln in enumerate(lines):
        if _KO_TAG_LINE_RE.match(ln):
            if out and out[-1].strip():
                out.append("")
            out.append(ln.strip())
            # 다음 라인이 비어있지 않으면 빈 줄 삽입 (다음 iter에서 처리)
            if i + 1 < len(lines) and lines[i + 1].strip():
                out.append("")
            continue
        out.append(ln)
    return "\n".join(out)


# ─── 메인 진입점 ──────────────────────────────────────────────────────────


def normalize_law_text(
    text: str,
    *,
    law_title: Optional[str] = None,
    article_num: Optional[str] = None,
    article_title: Optional[str] = None,
    strip_leading_header: bool = True,
) -> str:
    """법령 본문을 frontend가 그대로 react-markdown에 넣을 수 있는 형태로 정규화.

    Args:
        text: raw 본문 (Mongo/PG/Neo4j에서 fetch한 그대로).
        law_title / article_num / article_title:
            본문 시작부 헤더 중복 제거에 사용. 미지정이면 dedup skip.
        strip_leading_header: True면 헤더 dedup. /annex처럼 본문 자체가 별표
            제목으로 시작해도 OK인 경우 False.

    Returns:
        정규화된 markdown 문자열. None 입력은 빈 문자열.
    """
    if not text:
        return ""

    # 1. 인코딩 정리 — CRLF → LF, BOM 제거.
    s = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")

    # 1.1. HTML <br> → 줄바꿈. 판례(prec) 등 openlaw 원문이 [판시사항]…<br/>
    #      [참조조문]…<br/> 처럼 섹션을 <br/>로 나눔. react-markdown 은 raw HTML 을
    #      안 그려 그대로 노출되므로 여기서 문단 줄바꿈으로 변환(단일 출처).
    s = re.sub(r"<br\s*/?>", "\n\n", s, flags=re.IGNORECASE)

    # 1.5. 항 번호(①②③) 인라인 → 줄바꿈을 헤더 제거보다 *먼저* 수행.
    #   admrul 등은 본문이 "제N조(제목) ① …②…)"처럼 한 줄에 통째로 들어오는데,
    #   먼저 줄바꿈하지 않으면 다음 단계 헤더 제거의 _ARTICLE_HEADER_RE(greedy
    #   \(.+\)$)가 그 긴 본문 줄 전체를 헤더로 오인해 본문을 통째 삭제함.
    s = _HANG_RE.sub(r"\1\n\n\2", s)

    # 2. 헤더 중복 제거 (caller가 prepend 별도 헤더 생성 예정인 경우 도움).
    if strip_leading_header:
        s = _strip_leading_header_dups(
            s,
            law_title=law_title,
            article_num=article_num,
            article_title=article_title,
        )

    # 3. 한 줄에 묶인 markdown 표 분리.
    s = _split_inline_tables(s)

    # 4. ASCII 박스 표 → markdown 표.
    s = _convert_ascii_box_table(s)

    # 5. 0-padded 조항 번호 정리.
    s = _ZEROPAD_RE.sub(r"제\1\2", s)

    # 6. (항 번호 줄바꿈은 헤더 제거 전에 1.5 단계에서 이미 수행 — idempotent라
    #     중간 단계가 새 인라인 항을 만들지 않는 한 재실행 불필요.)

    # 7. 호 번호 인라인 → 줄바꿈 ("...다. 1. " → "...다.\n1. ").
    s = _HO_RE.sub(r"\1\n\2", s)

    # 8. 개정 이력 태그 — 다음 항 직전이면 빈 줄 보장.
    s = _REV_RE.sub(r"\1\n\n", s)

    # 9. 가로 구분선 앞뒤 빈 줄.
    s = _ensure_hr_blanks(s)

    # 10. 한글 태그 라인 격리.
    s = _ensure_ko_tag_blanks(s)

    # 11. 연속 빈 줄 3+ → 2.
    s = re.sub(r"\n{3,}", "\n\n", s)

    return s.strip()
