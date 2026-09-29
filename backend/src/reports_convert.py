"""보고서 포맷 변환 — Markdown(원본) → DOCX.

보고서 저장 원본은 `.md`(source of truth). 사용자가 요구하는 배포 포맷(DOCX)은
**요청 시 변환 + blob 캐시**한다(완료 시 전부 미리 만들면 느리고 저장소만 먹음).

엔진: pandoc(`pypandoc-binary` — pip 로 바이너리 동봉, 시스템 설치 불요).
실측: 20KB 보고서 → 18.7KB docx, 0.37s. 헤더(H1~H3)·굵게·중첩 번호목록(numPr)·
인용 마커 `[n]` 전부 보존.

pandoc 미설치 시 `ConversionUnavailable` — 호출자는 `.md` 로 폴백한다(대화·보고서
흐름을 막지 않음).
"""

from __future__ import annotations

import logging
import re

_log = logging.getLogger(__name__)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FORMATS = ("md", "docx")

# pandoc 입력 정규화용 라인 패턴들. 선행 공백 0~3칸 — 4칸 이상은 markdown 스펙상
# indented code block 이라 건드리면 안 됨.
_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
_HR_LINE_RE = re.compile(r"^ {0,3}-{3,}[ \t]*$")
_LIST_ITEM_RE = re.compile(r"^ {0,3}(?:[*+-]|\d+\.)[ \t]")
_BULLET_NEXT_RE = re.compile(r"^ {0,3}[*+-][ \t]")


def _preprocess_md(md: str) -> str:
    """pandoc 입력 정규화 — `---` 오해석·리스트 미인식 패턴 제거.

    라인 단위 + 코드펜스 추적. 정규식 일괄 치환이던 1차 구현의 실버그 3건
    (2026-07-10 리뷰) 회귀 방지:
      1. setext H2(`제목\\n---`)의 `---` 까지 `***` 로 바꿔 헤딩 파괴 + `***`
         리터럴 노출 → **앞줄이 빈 줄일 때만** hr 로 취급해 치환.
      2. 날짜 연속행("2026. 7. 1. …")을 ordered list 로 오인해 빈 줄 삽입 →
         3중 번호목록 변조 → 빈 줄 삽입은 **bullet(`*`·`-`·`+`) 리스트에만**.
      3. 코드펜스 내부 `---`·리스트 치환 오염 → 펜스 구간 통과.

    치환 자체의 목적(1차와 동일):
      - hr `---` 가 YAML metadata block / multiline·simple table 경계로 오해석돼
        본문 소실·표 뭉개짐(References 1열 표 실사고) → `***` 로.
      - 문장 직후 빈 줄 없는 bullet(writer 흔한 패턴)이 문단에 리터럴로
        이어붙음 → 빈 줄 삽입.
    """
    lines = md.split("\n")
    out: list[str] = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if _HR_LINE_RE.match(line):
            prev_blank = not out or out[-1].strip() == ""
            # 앞줄이 텍스트면 setext H2 — pandoc 이 헤딩으로 처리하도록 보존.
            out.append("***" if prev_blank else line)
            continue
        out.append(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if (
            nxt is not None
            and line.strip()
            and not _LIST_ITEM_RE.match(line)
            and _BULLET_NEXT_RE.match(nxt)
        ):
            out.append("")
    return "\n".join(out)


class ConversionUnavailable(RuntimeError):
    """pandoc 미설치/변환 실패 — 호출자가 .md 로 폴백."""


def is_available() -> bool:
    """pandoc 사용 가능 여부(미설치면 docx 요청을 .md 로 폴백)."""
    try:
        import pypandoc

        pypandoc.get_pandoc_version()
        return True
    except Exception:  # noqa: BLE001
        return False


def md_to_docx(md: str) -> bytes:
    """Markdown → DOCX 바이트. 실패 시 ConversionUnavailable."""
    if not md:
        raise ConversionUnavailable("빈 보고서 본문")
    import os
    import tempfile

    try:
        import pypandoc
    except ImportError as e:
        raise ConversionUnavailable("pypandoc 미설치") from e

    # pandoc 은 파일 출력만 지원(docx 는 바이너리) → 임시파일 경유.
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        # 확장 비활성 — `---` 가로 구분선이 (1) YAML metadata block(exitcode 64),
        # (2) multiline/simple table(References 섹션이 1열 표로 뭉개짐)로 오해석되는
        # 것을 차단. 표는 writer 가 실제로 쓰는 pipe_tables 만 유지.
        # -subscript: 한국어 범위 표기 "3~5일"류 홑물결이 아래첨자로 먹혀 물결이
        # 소실되는 것 방지(FE remark-gfm singleTilde:false 와 짝, 2026-07-23).
        # _preprocess_md 가 hr 치환·리스트 앞 빈 줄 삽입으로 한 번 더 방어.
        pypandoc.convert_text(
            _preprocess_md(md),
            "docx",
            format=("markdown-yaml_metadata_block-multiline_tables"
                    "-simple_tables-subscript"),
            outputfile=path,
        )
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        # 원인 메시지를 보존 — 타입명만 남기면 서버에서만 실패하는 케이스
        # (pandoc stderr 등)를 진단할 수 없다.
        _log.warning("pandoc docx 변환 실패 상세: %r", e)
        raise ConversionUnavailable(
            f"docx 변환 실패: {type(e).__name__}: {str(e)[:200]}"
        ) from e
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def convert(md: str, fmt: str) -> tuple[bytes, str, str]:
    """(bytes, mime, 확장자). fmt='md' 는 무변환. 그 외는 변환(실패 시 예외)."""
    f = (fmt or "md").lower()
    if f == "md":
        return md.encode("utf-8"), "text/markdown", "md"
    if f == "docx":
        return md_to_docx(md), DOCX_MIME, "docx"
    raise ConversionUnavailable(f"지원하지 않는 포맷: {fmt} (지원: {FORMATS})")
