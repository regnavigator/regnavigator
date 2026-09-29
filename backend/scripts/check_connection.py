"""프런트 연결 사전 점검 - 단일 endpoint(2024)에 모든 라우트가 응답하는지·CORS·Qdrant.

usage:
    python scripts/check_connection.py
    python scripts/check_connection.py --origin http://localhost:5173
    python scripts/check_connection.py --base http://medi.example.com  # production

출력은 "[ok]" / "[!]" 마커. 종료코드 0 = 통과.
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx


def _line(label: str, ok: bool, detail: str = "") -> bool:
    mark = "[ok]" if ok else "[!]"
    print(f"  {mark} {label}" + (f"  - {detail}" if detail else ""))
    return ok


def check_langgraph_routes(base: str) -> bool:
    print(f"\n[1] LangGraph 기본 라우트 - {base}")
    try:
        r = httpx.get(f"{base}/info", timeout=3.0)
    except Exception as e:
        return _line("info 응답", False, repr(e))
    if r.status_code != 200:
        return _line("info 응답", False, f"HTTP {r.status_code}")
    _line("version", True, r.json().get("version", "?"))

    try:
        r2 = httpx.post(f"{base}/assistants/search", json={"limit": 50}, timeout=3.0)
        graph_ids = {a.get("graph_id") for a in r2.json()} if r2.status_code == 200 else set()
    except Exception:
        graph_ids = set()
    ok_fast = "agent" in graph_ids
    ok_deep = "agent_deep" in graph_ids
    _line("graph 'agent' (fast)", ok_fast)
    _line("graph 'agent_deep' (deep)", ok_deep)
    return r.status_code == 200 and ok_fast and ok_deep


def check_custom_routes(base: str, origin: str) -> bool:
    print(f"\n[2] 커스텀 라우트 (Reports/Suggestions) - {base}")
    # 같은 origin에서 langgraph dev가 마운트
    try:
        r = httpx.get(f"{base}/healthz", timeout=3.0)
    except Exception as e:
        return _line("healthz", False, repr(e))
    _line("healthz", r.status_code == 200,
          str(r.json()) if r.status_code == 200 else f"HTTP {r.status_code}")

    # /suggestions
    try:
        s = httpx.get(f"{base}/suggestions", timeout=3.0)
        ok_sug = s.status_code == 200 and "categories" in s.json()
        n_cats = len(s.json().get("categories", [])) if ok_sug else 0
    except Exception as e:
        ok_sug, n_cats = False, 0
    _line("/suggestions", ok_sug, f"{n_cats} categories")

    # /threads/{tid}/reports — 빈 thread도 200 + count 0
    try:
        rp = httpx.get(f"{base}/threads/_probe/reports", timeout=3.0)
        ok_reports = rp.status_code in (200, 401)
    except Exception as e:
        ok_reports = False
    _line("/threads/{tid}/reports", ok_reports,
          f"HTTP {rp.status_code}" if ok_reports else "no response")

    # CORS preflight
    try:
        pre = httpx.options(
            f"{base}/threads/_probe/reports",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
            timeout=3.0,
        )
        allow_origin = pre.headers.get("access-control-allow-origin", "")
        ok_cors = pre.status_code in (200, 204) and (allow_origin == origin or allow_origin == "*")
    except Exception as e:
        ok_cors, allow_origin = False, repr(e)
    _line(f"CORS preflight from {origin}", ok_cors, f"allow-origin={allow_origin!r}")

    # 인증 모드
    expected_token = os.getenv("API_TOKEN")
    if expected_token:
        no_tok = httpx.get(f"{base}/threads/_probe/reports", timeout=3.0)
        _line("API_TOKEN 설정 - 무인증 시 401", no_tok.status_code == 401)
        with_tok = httpx.get(
            f"{base}/threads/_probe/reports",
            headers={"Authorization": f"Bearer {expected_token}"},
            timeout=3.0,
        )
        _line("올바른 token - 200", with_tok.status_code == 200)
    else:
        _line("API_TOKEN 미설정 (dev 모드)", True, "production은 API_TOKEN 반드시 설정")

    return ok_sug and ok_reports and ok_cors


def check_qdrant() -> bool:
    print("\n[3] 검색 API 연결 (openlaw-etl /search)")
    try:
        from src.retrieval.search_api_client import is_available, ping
        if not is_available():
            return _line("config", False, "RAG_SEARCH_API_URL/KEY 미설정")
        ok, detail = ping()
        return _line("connect", ok, detail)
    except Exception as e:
        return _line("connect", False, repr(e))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://127.0.0.1:2024",
                   help="medi-back endpoint (langgraph dev = 모든 라우트 호스팅)")
    p.add_argument("--origin", default="http://localhost:3000",
                   help="프런트 origin (CORS 검사에 사용)")
    args = p.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    print("== medi-back 프런트 연결 사전 점검 ==")
    ok = True
    ok &= check_langgraph_routes(args.base)
    ok &= check_custom_routes(args.base, args.origin)
    ok &= check_qdrant()

    print()
    if ok:
        print(f"→ 모든 검사 통과. 프런트가 {args.origin}에서 {args.base} 단일 origin으로 호출 가능.")
        return 0
    print("→ 일부 검사 실패. 위 [!] 항목 해결 후 재실행.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
