"""인용된 출처 추출 파이프라인 — 새 DB 시드용 manifest 생성.

LangSmith 트레이스에서 채팅·보고서가 **실제로 인용한** 출처를 모아
중복 제거(dedup)하고 인용 빈도순으로 정렬해 JSONL 로 내보낸다. 나중에 인용 기반
DB / Qdrant 컬렉션을 구성할 때 "어떤 문서를 시드할지" 한방에 결정하는 입력이 된다.

채팅 런타임과 무관한 **오프라인 배치** — hot path 영향 0. 추출 로직은
`scripts/_langsmith_citations.py` 공유 코어와 동일(통계 스크립트와 한 소스).

usage:
    # citation(조문 단위) dedup, 최근 30일, 인용 빈도순 JSONL
    python scripts/cited_docs_export.py --out cited_citations.jsonl

    # 문서(doc_id) 단위로 묶기 — DB 시드는 보통 이쪽
    python scripts/cited_docs_export.py --by doc --out cited_docs.jsonl

    # 2회 이상 인용된 것만 / 보고서 인용만 / 웹 출처
    python scripts/cited_docs_export.py --by doc --min-cites 2
    python scripts/cited_docs_export.py --graph agent_deep
    python scripts/cited_docs_export.py --tool tavily_search --by doc

옵션:
    --by {citation,doc}   citation=조문 단위(citation id) / doc=문서 단위(doc_id). 기본 citation.
    --graph {all,agent,agent_deep}
    --since YYYY-MM-DD    기본 30일 전.
    --tool NAME           기본 qdrant_search.
    --limit N             run 상한 (기본 5000).
    --min-cites N         인용 빈도 N 미만 제외 (기본 1).
    --out PATH            JSONL 출력 파일 (없으면 stdout).
    --summary            manifest 대신 요약만 출력.

출력 레코드 (--by citation):
    {"id","doc_id","source_kind","title","article","doc_category","publisher",
     "verified","date","cite_count","query_count","graphs","sample_queries",
     "first_seen","last_seen"}
--by doc 는 doc_id 로 묶고 articles[] 에 인용된 조문 목록을 담는다.
"""
from __future__ import annotations

import argparse
import json
import sys

import _langsmith_citations as lc


def _key(ci: dict, by: str) -> str | None:
    if by == "doc":
        return ci.get("doc_id") or ci.get("id")
    return ci.get("id")


def collect(runs, *, by: str, graph_filter: str) -> dict[str, dict]:
    """dedup 키 → 집계 레코드."""
    acc: dict[str, dict] = {}
    for run in runs:
        if graph_filter != "all" and run["graph_id"] != graph_filter:
            continue
        q, mode, ts = run["query"], run["mode"], run["ts"]
        for ci in run["citations"]:
            k = _key(ci, by)
            if not k:
                continue
            rec = acc.get(k)
            if rec is None:
                rec = acc[k] = {
                    "id": ci.get("id"),
                    "doc_id": ci.get("doc_id"),
                    "source_kind": ci.get("source_kind"),
                    "title": ci.get("title"),
                    "doc_category": ci.get("doc_category"),
                    "publisher": lc.publisher_name(ci),
                    "verified": bool(ci.get("verified")),
                    "date": ci.get("date"),
                    "url": ci.get("url"),
                    "cite_count": 0,
                    "_queries": set(),
                    "_graphs": set(),
                    "_articles": set(),
                    "first_seen": ts,
                    "last_seen": ts,
                }
            rec["cite_count"] += 1
            if q:
                rec["_queries"].add(q)
            rec["_graphs"].add(mode)
            if ci.get("article"):
                rec["_articles"].add(ci["article"])
            if ts:
                rec["first_seen"] = min(rec["first_seen"] or ts, ts)
                rec["last_seen"] = max(rec["last_seen"] or ts, ts)
    return acc


def finalize(acc: dict, *, by: str, min_cites: int) -> list[dict]:
    out = []
    for rec in acc.values():
        if rec["cite_count"] < min_cites:
            continue
        r = {k: v for k, v in rec.items() if not k.startswith("_")}
        r["query_count"] = len(rec["_queries"])
        r["graphs"] = sorted(rec["_graphs"])
        r["sample_queries"] = sorted(rec["_queries"])[:3]
        if by == "doc":
            r["articles"] = sorted(rec["_articles"])
            r.pop("id", None)  # doc 단위에선 대표 id 무의미
        out.append(r)
    out.sort(key=lambda x: x["cite_count"], reverse=True)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    lc.load_env()

    ap = argparse.ArgumentParser(description="인용 출처 추출 → DB 시드 manifest")
    ap.add_argument("--by", default="citation", choices=["citation", "doc"])
    ap.add_argument("--graph", default="all", choices=["all", "agent", "agent_deep"])
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (기본 30일 전)")
    ap.add_argument("--tool", default="qdrant_search")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--min-cites", type=int, default=1)
    ap.add_argument("--out", default=None, help="JSONL 출력 파일 (없으면 stdout)")
    ap.add_argument("--summary", action="store_true", help="manifest 대신 요약만")
    args = ap.parse_args()

    try:
        client, proj = lc.get_client_and_project()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    since = lc.parse_since(args.since)
    print(f"# project: {proj}  tool={args.tool}  by={args.by}  graph={args.graph}  "
          f"since={since.date()}  min_cites={args.min_cites}\n", file=sys.stderr)

    runs = lc.iter_runs(client, proj, tool=args.tool, since=since, limit=args.limit)
    acc = collect(runs, by=args.by, graph_filter=args.graph)
    records = finalize(acc, by=args.by, min_cites=args.min_cites)

    total_cites = sum(r["cite_count"] for r in records)
    print(f"# unique {args.by}: {len(records)}  ·  총 인용 {total_cites}회", file=sys.stderr)

    if args.summary:
        for r in records[:30]:
            label = r.get("title") or r.get("doc_id") or r.get("id")
            print(f"  {r['cite_count']:>4}x  [{r.get('doc_category')}]  {label}")
        return 0

    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        print(f"# wrote {len(lines)} records → {args.out}", file=sys.stderr)
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
