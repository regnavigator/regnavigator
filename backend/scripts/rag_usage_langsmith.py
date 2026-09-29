"""실서비스 RAG(qdrant_search) 검색결과 통계 — LangSmith 트레이스 기반.

채팅(fast, graph=agent)·보고서(deep, graph=agent_deep) 양쪽의 qdrant_search 호출이
LangSmith 에 이미 트레이싱되어 있다. 이 스크립트는 그 run 들을 읽어
- 호출 수 / 고유 질의 수 / 고유 thread 수
- 출처 종류(doc/web) · 검증 여부 · 기관(publisher) · 문서 카테고리(doc_category)
- 검색당 매칭 수 분포
를 집계한다. 백엔드 hot path 에 아무것도 쓰지 않으므로 **응답 성능 영향 0**.

추출 로직은 `scripts/_langsmith_citations.py` 공유 코어. env(.env 자동 로드):
LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGSMITH_ENDPOINT.

usage:
    python scripts/rag_usage_langsmith.py                      # 최근 30일 채팅+보고서
    python scripts/rag_usage_langsmith.py --graph agent        # 채팅만
    python scripts/rag_usage_langsmith.py --graph agent_deep   # 보고서만
    python scripts/rag_usage_langsmith.py --tool tavily_search # 웹 출처
    python scripts/rag_usage_langsmith.py --since 2026-05-01 --json
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

import _langsmith_citations as lc


def aggregate(runs, *, graph_filter: str) -> dict:
    kind = collections.Counter()
    verified = collections.Counter()
    publisher = collections.Counter()
    category = collections.Counter()
    by_graph = collections.Counter()
    per_search: list[int] = []
    queries: set[str] = set()
    threads: set[str] = set()
    n_searches = 0

    for run in runs:
        if graph_filter != "all" and run["graph_id"] != graph_filter:
            continue
        n_searches += 1
        by_graph[run["mode"]] += 1
        if run["query"]:
            queries.add(run["query"])
        if run["thread_id"]:
            threads.add(run["thread_id"])
        cits = run["citations"]
        per_search.append(len(cits))
        for ci in cits:
            kind[ci.get("source_kind") or "(unknown)"] += 1
            verified["검증됨" if ci.get("verified") else "미검증"] += 1
            publisher[lc.publisher_name(ci)] += 1
            category[ci.get("doc_category") or "(미분류)"] += 1

    total = sum(kind.values())
    per_search.sort()
    return {
        "searches": n_searches,
        "by_graph": dict(by_graph.most_common()),
        "unique_queries": len(queries),
        "unique_threads": len(threads),
        "total_citations": total,
        "source_kind": dict(kind.most_common()),
        "verified": dict(verified.most_common()),
        "publisher": dict(publisher.most_common()),
        "doc_category": dict(category.most_common()),
        "per_search": {
            "min": per_search[0] if per_search else 0,
            "median": per_search[len(per_search) // 2] if per_search else 0,
            "max": per_search[-1] if per_search else 0,
            "avg": round(total / n_searches, 1) if n_searches else 0,
        },
    }


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "—"


def print_human(s: dict, *, top: int) -> None:
    total = s["total_citations"]
    print("=== RAG 검색결과 통계 (LangSmith) ===")
    print(f"검색 호출: {s['searches']}회  {s['by_graph']}")
    print(f"고유 질의: {s['unique_queries']}개 · 고유 thread: {s['unique_threads']}개")
    print(f"총 매칭 citation: {total}개  "
          f"(검색당 min {s['per_search']['min']} / median {s['per_search']['median']} / "
          f"avg {s['per_search']['avg']} / max {s['per_search']['max']})")
    for label, key in (("출처 종류", "source_kind"), ("검증 여부", "verified")):
        print(f"\n[{label}]")
        for k, v in s[key].items():
            print(f"  {v:>6}  {_pct(v, total):>6}  {k}")
    for label, key in (("기관 publisher", "publisher"), ("문서 카테고리", "doc_category")):
        print(f"\n[{label} — top {top}]")
        for k, v in list(s[key].items())[:top]:
            print(f"  {v:>6}  {_pct(v, total):>6}  {k}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    lc.load_env()

    ap = argparse.ArgumentParser(description="LangSmith 기반 RAG 검색결과 통계")
    ap.add_argument("--graph", default="all", choices=["all", "agent", "agent_deep"],
                    help="agent=채팅 / agent_deep=보고서 (기본 all)")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (기본: 30일 전)")
    ap.add_argument("--tool", default="qdrant_search", help="툴 run 이름 (기본 qdrant_search)")
    ap.add_argument("--limit", type=int, default=5000, help="run 상한")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        client, proj = lc.get_client_and_project()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    since = lc.parse_since(args.since)
    print(f"# project: {proj}  tool={args.tool}  graph={args.graph}  "
          f"since={since.date()}  limit={args.limit}\n", file=sys.stderr)

    runs = lc.iter_runs(client, proj, tool=args.tool, since=since, limit=args.limit)
    stats = aggregate(runs, graph_filter=args.graph)

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print_human(stats, top=args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
