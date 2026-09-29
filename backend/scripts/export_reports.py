"""thread의 산출물 파일을 디스크에 .md로 export.

`state.files` 의 FileEntry(`02_INTERFACE §2.3`) 에서 본문 추출 → 평문 .md 저장.

usage:
    python scripts/export_reports.py <thread_id> [--out OUT_DIR] [--url URL]

예시:
    python scripts/export_reports.py 437fe749-8d5a-... --out reports/
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

import httpx


def get_file_text(entry: dict) -> str:
    """FileEntry → 평문 markdown."""
    content = entry.get("content", [])
    if isinstance(content, list):
        return "\n".join(content)
    return str(content)


def export(thread_id: str, *, base_url: str, api_key: str | None,
           out_dir: pathlib.Path) -> list[pathlib.Path]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    r = httpx.get(f"{base_url}/threads/{thread_id}/state",
                  headers=headers, timeout=10.0)
    r.raise_for_status()
    state = r.json()
    files = state.get("values", {}).get("files", {}) or {}

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[pathlib.Path] = []
    for path, entry in sorted(files.items()):
        text = get_file_text(entry)
        rel = path.lstrip("/")
        out = out_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        written.append(out)
        print(f"[{path}]  {len(text):>6} bytes  →  {out}")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("thread_id")
    ap.add_argument("--out", default="reports", type=pathlib.Path,
                    help="출력 디렉터리 (default: ./reports)")
    ap.add_argument("--url", default=os.getenv("BASE_URL", "http://127.0.0.1:2024"),
                    help="LangGraph 배포 URL")
    ap.add_argument("--api-key", default=os.getenv("LANGSMITH_API_KEY"))
    args = ap.parse_args()

    files = export(
        args.thread_id,
        base_url=args.url.rstrip("/"),
        api_key=args.api_key,
        out_dir=args.out,
    )
    if not files:
        print(f"[!] thread {args.thread_id}에 파일 없음.", file=sys.stderr)
        return 1
    print(f"\n→ {len(files)}개 파일 export → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
