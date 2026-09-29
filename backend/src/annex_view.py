"""별표·서식 HWP → 문서 뷰어 HTML (2026-09-08).

운영자 요청 "법령정보센터처럼 뷰어 형식으로 볼 수 없냐". 텍스트 변환본(markdown)은 표
구조가 무너져 미리보기가 전부 깨졌다. 법령정보센터 뷰어는 HWP 를 서버에서 렌더한 것이고,
같은 방식으로 원본 HWP 를 pyhwp(`hwp5html`)로 HTML+CSS 로 변환하면 표·칸·제목이 문서
그대로 나온다(실측: 의료기기 제조(수입) 허가신청서 — 표 2개, 페이지 폭 210mm 레이아웃).

흐름: attachment_key → 다운로드 링크(`pinned_form_asset`/Neo4j) → HWP 바이트(크기 상한)
→ 임시 디렉터리에서 `hwp5html` 서브프로세스 → index.xhtml + styles.css → CSS 인라인·
XML 프롤로그 제거·script/iframe 제거 → 디스크 캐시(`ANNEX_VIEW_CACHE_DIR`, 기본 임시 폴더).

- 프런트는 인증된 fetch 로 HTML 문자열을 받아 **sandbox iframe 의 srcdoc** 에 넣는다 —
  공개 라우트가 필요 없고, 스크립트가 섞여도 실행되지 않는다.
- HWPX(zip)·HWPML 은 pyhwp 가 못 읽는다 → 503 + 원본 링크 안내. 현재 법령정보센터 서식은
  HWP 5(OLE) 가 대부분이다(실측 Content-Type application/hwp, 시그니처 D0CF11E0).
- 변환은 CPU 작업(수백 ms~수 초). 라우트는 `def`(스레드풀), 동시 변환은 세마포어로 2개.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Optional

_log = logging.getLogger(__name__)

_SEM = threading.BoundedSemaphore(2)
_TIMEOUT_S = 60
_MAX_HTML = 3_000_000  # 3MB — 그림 많은 서식도 이 아래


class AnnexViewError(Exception):
    """변환 불가(형식 미지원·도구 없음·다운로드 실패) — 503 으로 매핑."""


def _cache_dir() -> str:
    d = (os.getenv("ANNEX_VIEW_CACHE_DIR") or "").strip() or os.path.join(
        tempfile.gettempdir(), "medi_annex_view")
    os.makedirs(d, exist_ok=True)
    return d


def _cache_path(key: str) -> str:
    return os.path.join(_cache_dir(), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".html")


def is_hwp5(data: bytes) -> bool:
    return data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _sanitize(html: str) -> str:
    """스크립트·외부 로드 제거. srcdoc+sandbox 가 1차 방어지만 저장본도 깨끗하게."""
    html = re.sub(r"(?is)<script.*?</script>", "", html)
    html = re.sub(r"(?is)<(iframe|object|embed|link)[^>]*>(.*?</\1>)?", "", html)
    html = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html)
    return html


def _inline_css(index_html: str, css: str) -> str:
    """styles.css 를 <style> 로 박고 XML 프롤로그·DOCTYPE 을 뗀다(srcdoc 용)."""
    html = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", index_html)
    html = re.sub(r"(?is)^\s*<!DOCTYPE[^>]*>\s*", "", html)
    html = re.sub(r"(?is)<link[^>]*styles\.css[^>]*/?>", "", html)
    viewer_css = (
        "html,body{margin:0;background:#f3f4f6}"
        ".Section-0,.Section-1,.Section-2{background:#fff;margin:16px auto;"
        "box-shadow:0 1px 6px rgba(0,0,0,.12)}"
        "table{border-collapse:collapse}"
    )
    style = f"<style>{css}\n{viewer_css}</style>"
    if re.search(r"(?i)</head>", html):
        return re.sub(r"(?i)</head>", style + "</head>", html, count=1)
    return style + html


def convert_hwp_bytes(data: bytes) -> str:
    """HWP 5 바이트 → 자기완결 HTML 문자열. 미지원 형식은 AnnexViewError."""
    if not is_hwp5(data):
        raise AnnexViewError("HWP 5(OLE) 형식이 아님 — HWPX/HWPML 은 뷰어 미지원")
    tmp = tempfile.mkdtemp(prefix="annex_view_")
    try:
        src = os.path.join(tmp, "form.hwp")
        out = os.path.join(tmp, "html")
        with open(src, "wb") as fh:
            fh.write(data)
        cmd = [sys.executable, "-c",
               "import sys; from hwp5.hwp5html import main; "
               f"sys.argv=['hwp5html', {src!r}, '--output', {out!r}]; main()"]
        with _SEM:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S)
        index = os.path.join(out, "index.xhtml")
        if p.returncode != 0 or not os.path.exists(index):
            # 마지막 줄이 원인(ImportError 등) — 앞 200자만 남기면 Traceback 머리만 보인다
            # (운영 2026-09-09: `from .cli import init_logger` 에서 잘려 원인 불명).
            err = (p.stderr or p.stdout or "").strip()
            tail = err[-600:]
            _log.warning("annex_view: hwp5html 실패 rc=%s\n%s", p.returncode, err[-3000:])
            raise AnnexViewError(f"hwp5html 실패: {tail}")
        with open(index, encoding="utf-8") as fh:
            html = fh.read()
        css = ""
        css_path = os.path.join(out, "styles.css")
        if os.path.exists(css_path):
            with open(css_path, encoding="utf-8") as fh:
                css = fh.read()
        html = _sanitize(_inline_css(html, css))
        if len(html) > _MAX_HTML:
            raise AnnexViewError("변환 결과가 너무 큼")
        return html
    except subprocess.TimeoutExpired as e:
        raise AnnexViewError("변환 시간 초과") from e
    except ModuleNotFoundError as e:  # pragma: no cover — 배포 의존성 누락
        _log.warning("annex_view: pyhwp 미설치", exc_info=True)
        raise AnnexViewError("pyhwp 미설치") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def resolve_download_url(attachment_key: str) -> Optional[str]:
    """attachment_key → law.go.kr 다운로드 URL. 인용 조립 경로 재사용(중복 구현 금지)."""
    try:
        from src.report_pipeline import pinned_form_asset
        cites = pinned_form_asset(attachment_key) or []
        url = (cites[0] if cites else {}).get("download_url")
        if url:
            return str(url)
    except Exception:  # noqa: BLE001
        _log.info("annex_view: pinned_form_asset 실패 key=%s", attachment_key, exc_info=True)
    try:
        from src.retrieval.neo4j_client import fetch_attachment_by_key
        link = (fetch_attachment_by_key(attachment_key) or {}).get("link")
        if link:
            return link if str(link).startswith("http") else f"https://www.law.go.kr{link}"
    except Exception:  # noqa: BLE001
        pass
    return None


def view_html(attachment_key: str) -> str:
    """캐시 → 없으면 다운로드·변환·저장. 실패는 AnnexViewError."""
    key = (attachment_key or "").strip()
    if not key:
        raise AnnexViewError("key 필요")
    path = _cache_path(key)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    url = resolve_download_url(key)
    if not url:
        raise AnnexViewError("원본 다운로드 링크 없음")
    from src.form_fill import fetch_form_bytes
    try:
        data = fetch_form_bytes(url)
    except Exception as e:  # noqa: BLE001
        raise AnnexViewError(f"원본 다운로드 실패: {type(e).__name__}") from e
    html = convert_hwp_bytes(data)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    os.replace(tmp_path, path)
    return html
