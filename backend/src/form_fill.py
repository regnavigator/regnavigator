"""원본 서식 기입 — 원본 파일(HWP/HWPX)에 셀 텍스트만 patch (2026-08-27).

"docx 변환본이 아니라 원래 파일형식으로" 요구 대응. 경로:
  서식 원본 URL → 다운로드 → kordoc(fill, 원본 스타일 보존)으로 라벨-값
  기입 → 미매칭 라벨은 HWPX XML 라벨 런 뒤 덧붙이기 폴백 → .hwpx 반환.

**경계(2026-08-25 분리)**: 본 모듈은 medi-back 의 인용·보고서 스키마를
모른다 — 입력은 `서식 URL + {항목: 값}`, 출력은 `(bytes, 요약)` 뿐이다.
"어떤 인용이 서식 원본인가"(article_key·doc_category 해석)는 인용 스키마
소유자인 `src.tools.citations.pick_form_citation` 이 판단한다. 덕분에 이
모듈은 그대로 별도 서비스로 떼어낼 수 있다(kordoc 은 이미 subprocess 경계).

kordoc: 자매 06_parser 의 npm 패키지(HWP/HWPX 파싱·양식 채우기).
- 실행: `KORDOC_CLI`(cli.js 경로) 지정 시 `node <cli>`, 미지정 시 PATH 의
  `kordoc`. 없으면 503 — 기능 자체가 조용히 잘못되는 것보다 명시 실패.
- 알려진 엣지(실측 2026-08-25): 전폭 병합 셀 라벨('명칭(상호)'·'소재지')은
  kordoc 매칭 실패 → XML 폴백이 커버.

filled_values 키(writer 의 [확인 필요:] 항목명)와 서식 라벨은 표기가 다르다
— 휴리스틱(정규화 동등·포함) 우선, 잔여는 LLM 1콜(명시 대응만)로 매핑.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from typing import Any, Optional

_log = logging.getLogger(__name__)

_FORM_FETCH_MAX_BYTES = 10 * 1024 * 1024
_FORM_FETCH_TIMEOUT_S = 30
_KORDOC_TIMEOUT_S = 120

_MAP_PROMPT = """서식의 라벨 목록과 사용자가 작성한 {{항목: 값}} 데이터를 대응시켜라.

규칙(엄수):
- 의미가 명확히 같은 항목만 대응한다(예: "업체명" ↔ "명칭(상호)"). 추측 금지.
- 값은 **한 글자도 바꾸지 말고 그대로** 복사한다.
- 대응이 없으면 그 라벨은 생략한다. 없는 라벨·없는 값 창작 금지.
- **JSON 객체만** 출력: {{"서식 라벨": "값"}}.

서식 라벨 목록: {labels}
작성 데이터: {values}"""


# ── 서식 원본 다운로드 ──────────────────────────────────────────────

def fetch_form_bytes(url: str) -> bytes:
    """law.go.kr 서식 HWP 다운로드 — 크기 상한·타임아웃."""
    req = urllib.request.Request(url, headers={"User-Agent": "medireg/1.0"})
    with urllib.request.urlopen(req, timeout=_FORM_FETCH_TIMEOUT_S) as r:
        data = r.read(_FORM_FETCH_MAX_BYTES + 1)
    if len(data) > _FORM_FETCH_MAX_BYTES:
        raise ValueError("form file too large")
    if len(data) < 256:
        raise ValueError("form file too small — 링크가 파일이 아님")
    return data


# ── kordoc 실행 ──────────────────────────────────────────────────────

def kordoc_cmd() -> Optional[list[str]]:
    """kordoc CLI 호출 커맨드 — 미가용이면 None."""
    cli = (os.getenv("KORDOC_CLI") or "").strip()
    if cli:
        return ["node", cli] if cli.endswith(".js") else [cli]
    path = shutil.which("kordoc")
    return [path] if path else None


def _run_kordoc(args: list[str]) -> subprocess.CompletedProcess:
    cmd = kordoc_cmd()
    if not cmd:
        raise RuntimeError("kordoc unavailable")
    return subprocess.run(
        cmd + args, capture_output=True, timeout=_KORDOC_TIMEOUT_S,
        encoding="utf-8", errors="replace")


def kordoc_extract_labels(form_path: str) -> list[str]:
    """서식 필드 라벨 목록 — `kordoc fill --dry-run` JSON."""
    p = _run_kordoc(["fill", form_path, "--dry-run", "--silent"])
    m = re.search(r"\{.*\}", p.stdout or "", re.S)
    if not m:
        raise RuntimeError(f"kordoc dry-run 실패: {(p.stderr or p.stdout)[:200]}")
    fields = json.loads(m.group(0)).get("fields") or []
    out: list[str] = []
    seen: set[str] = set()
    for f in fields:
        lb = str(f.get("label") or "").strip()
        if lb and lb not in seen:
            seen.add(lb)
            out.append(lb)
    return out


def kordoc_fill(form_path: str, values: dict, out_path: str) -> list[str]:
    """kordoc fill 실행 — 반환: 매칭 실패(미기입) 라벨 목록."""
    with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False)
        vpath = f.name
    try:
        p = _run_kordoc(["fill", form_path, "-j", vpath, "-o", out_path])
    finally:
        try:
            os.unlink(vpath)
        except OSError:
            pass
    if not os.path.exists(out_path):
        raise RuntimeError(f"kordoc fill 실패: {(p.stderr or p.stdout)[:300]}")
    m = re.search(r"매칭 실패:\s*(.+)", (p.stdout or "") + (p.stderr or ""))
    if not m:
        return []
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


def kordoc_parse_md(form_path: str, md_path: str) -> str:
    """서식 → 구조 보존 마크다운(HTML 표) — patch 의 입력."""
    p = _run_kordoc([form_path, "-o", md_path])
    if not os.path.exists(md_path):
        raise RuntimeError(f"kordoc parse 실패: {(p.stderr or p.stdout)[:300]}")
    with open(md_path, encoding="utf-8") as f:
        return f.read()


def kordoc_patch(form_path: str, md_path: str, out_path: str) -> str:
    """서식 보존 라운드트립 패치 — **원본 바이너리에 셀 텍스트만 교체**.

    fill(파싱→재조립. 산출물이 "임의로 만든 표"로 보임 — 2026-08-27 실사용
    지적)과 달리, patch 는 원본을 1바이트 단위로 보존하고 바뀐 셀만 건드린다.
    .hwp 입력이면 .hwp 그대로 나온다(실측: 제1호서식 44,032B → 44,032B).
    """
    p = _run_kordoc(["patch", form_path, md_path, "-o", out_path])
    if not os.path.exists(out_path):
        raise RuntimeError(f"kordoc patch 실패: {(p.stderr or p.stdout)[:300]}")
    return (p.stdout or "") + (p.stderr or "")


_TD_RE = re.compile(r"<td([^>]*)>((?:(?!</td>|<table).)*?)</td>", re.S)


def _cell_text(inner: str) -> str:
    """셀 내부 HTML → 비교용 텍스트(태그 제거)."""
    return re.sub(r"<[^>]+>", " ", inner)


def apply_values_to_md(md: str, values: dict) -> tuple[str, list[str], list[str]]:
    """구조 보존 md 의 표 셀에 값 기입 — (수정 md, 적용 라벨, 미적용 라벨).

    관보 서식의 두 가지 기입 위치를 다룬다:
      ① 라벨 셀 바로 **옆 빈 셀** → 그 셀에 값 (예: 담당자 전화번호 | ___ )
      ② 라벨만 있는 셀(옆이 빈 셀이 아님) → 같은 셀에 `<br>값` 병기
        (관보 서식은 라벨 아래 여백에 쓰는 구조 — 실측 POC 로 확인)
    매칭은 정규화 동등만 — 비슷한 라벨에 슬쩍 넣지 않는다(오기입이 미기입보다
    나쁘다). 중첩 표가 든 셀은 건드리지 않는다(_TD_RE 가 배제).
    """
    applied: list[str] = []
    unmatched: list[str] = []
    for label, val in (values or {}).items():
        val = str(val).strip()
        if not val:
            continue
        target_norm = _norm(label)
        done = False
        for m in _TD_RE.finditer(md):
            if _norm(_cell_text(m.group(2))) != target_norm:
                continue
            # ① 같은 행의 바로 다음 셀이 빈 셀이면 거기에.
            after = md[m.end():]
            nxt = re.match(r"\s*<td([^>]*)>\s*</td>", after)
            if nxt:
                start = m.end() + nxt.start()
                md = (md[:start]
                      + f"<td{nxt.group(1)}>{val}</td>"
                      + md[m.end() + nxt.end():])
            else:
                # ② 라벨 셀에 병기 — patch 가 줄바꿈 병합으로 넣는다.
                md = (md[:m.start()]
                      + f"<td{m.group(1)}>{m.group(2)}<br>{val}</td>"
                      + md[m.end():])
            applied.append(label)
            done = True
            break
        if not done:
            unmatched.append(label)
    return md, applied, unmatched


# ── 라벨 매핑 (filled_values 키 → 서식 라벨) ─────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[\s()\[\]·:：/-]+", "", str(s or ""))


def heuristic_map(labels: list[str], filled: dict) -> dict:
    """정규화 동등 → 포함 관계 순 휴리스틱. 라벨당 1값."""
    out: dict = {}
    used: set[str] = set()
    norm_labels = {lb: _norm(lb) for lb in labels}
    for key, val in filled.items():
        nk = _norm(key)
        if not nk or not str(val).strip():
            continue
        best = None
        for lb, nl in norm_labels.items():
            if lb in out:
                continue
            if nl == nk:
                best = lb
                break
            if best is None and len(nk) >= 3 and (nk in nl or nl in nk):
                best = lb
        if best and key not in used:
            out[best] = str(val)
            used.add(key)
    return out


async def map_values_to_labels(labels: list[str], filled: dict,
                               *, model: Any | None = None) -> dict:
    """휴리스틱 + 잔여분 LLM 매핑. LLM 실패 시 휴리스틱만."""
    mapping = heuristic_map(labels, filled)
    rest_labels = [lb for lb in labels if lb not in mapping]
    rest_values = {k: v for k, v in filled.items()
                   if str(v) not in set(mapping.values())}
    if not rest_labels or not rest_values:
        return mapping
    # 독립 레인 정책(2026-08-27): 매핑 프롬프트에는 **기입값(개인정보)** 이
    # 실린다 — 온프레미스가 아니면 LLM 보강을 생략하고 휴리스틱 결과만 쓴다
    # (명시 model 주입은 테스트·전용 모델 경로이므로 통과).
    from src.doc_fill import onprem_fill
    if model is None and not onprem_fill():
        _log.info("form label mapping: 온프레미스 미설정 — LLM 보강 생략")
        return mapping
    try:
        from src.doc_fill import _fill_model, _parse_json_object
        llm = model or _fill_model()
        res = await llm.ainvoke(_MAP_PROMPT.format(
            labels=json.dumps(rest_labels, ensure_ascii=False),
            values=json.dumps(rest_values, ensure_ascii=False)))
        extra = _parse_json_object(getattr(res, "content", ""))
        allowed_vals = {str(v) for v in rest_values.values()}
        for lb, v in extra.items():
            # 라벨·값 둘 다 실존해야 — 모델 창작 차단.
            if lb in rest_labels and str(v) in allowed_vals and lb not in mapping:
                mapping[lb] = str(v)
    except Exception:  # noqa: BLE001 — 매핑 보강 실패는 휴리스틱 결과로 진행
        _log.debug("form label LLM mapping failed", exc_info=True)
    return mapping


# ── XML 폴백 (kordoc 미매칭 라벨) ────────────────────────────────────

def xml_append_fallback(hwpx_path: str, values: dict) -> int:
    """라벨 텍스트 런 뒤에 값 덧붙이기 — 전폭 병합 셀 라벨용 최소침습 폴백.

    `<hp:t>라벨</hp:t>` 정확 매칭 1회 치환. 적용 건수 반환.
    (실측 POC 2026-08-25: '명칭(상호)'·'소재지' 계열 커버.)
    """
    if not values:
        return 0
    src = zipfile.ZipFile(hwpx_path)
    sections = {n: src.read(n).decode("utf-8")
                for n in src.namelist() if re.match(r"Contents/section\d+\.xml", n)}
    applied = 0
    done: set[str] = set()
    for name, xml in sections.items():
        for label, val in values.items():
            if label in done:
                continue
            needle = f"<hp:t>{label}</hp:t>"
            if needle in xml:
                xml = xml.replace(
                    needle, f"<hp:t>{label}      {val}</hp:t>", 1)
                applied += 1
                done.add(label)
        sections[name] = xml
    if not applied:
        src.close()
        return 0
    tmp = hwpx_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename in sections:
                data = sections[item.filename].encode("utf-8")
            out.writestr(item, data)
    src.close()
    os.replace(tmp, hwpx_path)
    return applied


# ── 오케스트레이터 ───────────────────────────────────────────────────

async def build_filled_form(
    form_url: str,
    filled: dict,
    *,
    form_title: Optional[str] = None,
    model: Any | None = None,
) -> tuple[bytes, dict]:
    """서식 다운로드→라벨 매핑→**원본 보존 patch** 기입. 반환 (bytes, 요약).

    산출물은 원본과 같은 형식(.hwp 는 .hwp) — 재조립본이 아니다(2026-08-27
    전환, "원본 파일에 내용을 채운 게 아니라 임의로 표로 만들어졌다" 지적).
    인용·보고서 스키마를 모른다 — 서식 URL 과 {항목: 값} 만 받는다(분리 경계).
    `model` 은 라벨 매핑용 LLM 주입구. 실패는 예외로 — 라우트가 번역한다.
    요약 `ext` 로 산출 확장자를 알린다(다운로드 파일명용).
    """
    url = form_url
    raw = await asyncio.to_thread(fetch_form_bytes, url)
    with tempfile.TemporaryDirectory() as td:
        ext = "hwpx" if url.endswith(".hwpx") else "hwp"
        form_path = os.path.join(td, f"form.{ext}")
        md_path = os.path.join(td, "form.md")
        edit_path = os.path.join(td, "edit.md")
        out_path = os.path.join(td, f"filled.{ext}")
        with open(form_path, "wb") as f:
            f.write(raw)
        # 라벨 목록은 구조 md 의 셀 텍스트가 진실원 — 값 키를 셀 라벨로 번역.
        md = await asyncio.to_thread(kordoc_parse_md, form_path, md_path)
        labels = []
        seen: set[str] = set()
        for m in _TD_RE.finditer(md):
            t = re.sub(r"\s+", " ", _cell_text(m.group(2))).strip()
            if 1 < len(t) <= 40 and t not in seen:
                seen.add(t)
                labels.append(t)
        mapping = await map_values_to_labels(labels, filled or {}, model=model)
        edited, applied, unmatched = apply_values_to_md(md, mapping)
        if not applied:
            # 한 칸도 못 채우면 patch 를 돌릴 이유가 없다 — 원본을 그대로 준다
            # (조용한 빈손 산출물 방지: 요약이 사실을 말한다).
            data = raw
        else:
            with open(edit_path, "w", encoding="utf-8") as f:
                f.write(edited)
            await asyncio.to_thread(kordoc_patch, form_path, edit_path, out_path)
            with open(out_path, "rb") as f:
                data = f.read()
    summary = {
        "form_title": form_title,
        "ext": ext,
        "labels": len(labels),
        "mapped": len(mapping),
        "patched": len(applied),
        "unfilled_labels": unmatched,
    }
    return data, summary
