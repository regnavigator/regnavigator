"""실서비스 reports.citations_json 레퍼런스(출처) 통계 집계.

운영 Postgres(REPORTS_PG_DSN)의 `reports` 테이블에 저장된 citation을 읽어
- 출처 종류(doc/web)
- 검증 여부(verified — 정부·공공기관 화이트리스트)
- 기관(publisher)
- 문서 카테고리(doc_category)
- 보고서당 인용 수 분포
를 집계한다. 답변에 실제 붙은 출처의 분포를 보기 위한 운영 관측 도구.

usage:
    # 운영 PG (env REPORTS_PG_DSN 자동):
    python scripts/citation_stats.py

    # DSN 직접 지정:
    python scripts/citation_stats.py --pg-dsn "postgresql://medi:pass@host:6001/medi"

    # 로컬 dev SQLite 로 스크립트 검증:
    python scripts/citation_stats.py --sqlite ./medi_reports.db

옵션:
    --kind final         최종 보고서만 (기본). web/rag 는 sub-agent 중간 산출물 →
                         all 로 켜면 출처가 2~3중 카운트되니 주의.
    --kind all           모든 보고서.
    --since 2026-05-01   created_at 하한 (ISO, UTC).
    --until 2026-05-23   created_at 상한 (exclusive).
    --top 15             publisher/category 상위 N (기본 15).
    --json               집계 결과를 JSON 으로 출력 (대시보드/파이프 용).

주의:
- 운영은 PG, dev 는 SQLite. --sqlite 와 --pg-dsn 둘 다 없으면 REPORTS_PG_DSN 사용.
- citations_json: PG 는 JSONB(파싱됨 dict/list), SQLite 는 TEXT(문자열) → 둘 다 처리.
- publisher 가 raw dict({'content': ...}) 로 들어간 정규화 버그 케이스를 flatten.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys


# ---------------------------------------------------------------------------
# citations_json 정규화
# ---------------------------------------------------------------------------
def _coerce_citations(raw) -> list[dict]:
    """PG(JSONB→list/dict) / SQLite(TEXT) 양쪽의 citations_json → list[dict]."""
    if raw is None:
        return []
    if isinstance(raw, (list, dict)):
        val = raw
    else:
        try:
            val = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if isinstance(val, dict):
        val = [val]
    return [c for c in val if isinstance(c, dict)]


def _publisher_name(ci: dict) -> str:
    """publisher → 문자열. publisher 가 dict 또는 dict 의 repr 문자열로 들어간
    정규화 버그 케이스를 모두 flatten (예: {'content': '식약처', ...} → '식약처')."""
    p = ci.get("publisher")
    if isinstance(p, str) and p.startswith("{") and "content" in p:
        # str(dict) 로 저장된 케이스 — JSON 아닌 Python repr 일 수 있음
        import ast
        try:
            p = ast.literal_eval(p)
        except (ValueError, SyntaxError):
            pass
    if isinstance(p, dict):
        p = p.get("content") or json.dumps(p, ensure_ascii=False)
    return p if p else "(미상/미검증 웹)"


# ---------------------------------------------------------------------------
# row fetch — PG / SQLite
# ---------------------------------------------------------------------------
def _fetch_rows(*, sqlite_path, pg_dsn, kind, since, until):
    """reports 에서 (created_at, kind, citations_json) 행 yield. 백엔드 무관."""
    where = ["citations_json IS NOT NULL"]
    params: list = []

    if sqlite_path:
        ph = "?"
    else:
        ph = "%s"

    if kind != "all":
        where.append(f"kind = {ph}")
        params.append(kind)
    if since:
        where.append(f"created_at >= {ph}")
        params.append(_norm_ts(since, pg=bool(pg_dsn)))
    if until:
        where.append(f"created_at < {ph}")
        params.append(_norm_ts(until, pg=bool(pg_dsn)))

    sql = (
        "SELECT created_at, kind, citations_json FROM reports WHERE "
        + " AND ".join(where)
    )

    if sqlite_path:
        import sqlite3
        c = sqlite3.connect(sqlite_path)
        c.row_factory = sqlite3.Row
        try:
            for r in c.execute(sql, params):
                yield r["created_at"], r["kind"], r["citations_json"]
        finally:
            c.close()
    else:
        from src.persistence import _pg
        with _pg.pg_cursor(pg_dsn) as cur:
            cur.execute(sql, params)
            for r in cur.fetchall():
                yield r["created_at"], r["kind"], r["citations_json"]


def _norm_ts(s: str, *, pg: bool):
    """--since/--until 값 정규화. PG 는 datetime, SQLite 는 ISO 문자열 비교."""
    if not pg:
        return s  # SQLite created_at 은 ISO 문자열 → 사전식 비교 OK
    from src.persistence import _pg
    # 'YYYY-MM-DD' 만 와도 fromisoformat 통과
    return _pg._iso_to_dt(s if "T" in s else s + "T00:00:00Z")


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------
def aggregate(rows) -> dict:
    kind = collections.Counter()
    verified = collections.Counter()
    publisher = collections.Counter()
    category = collections.Counter()
    per_report: list[int] = []
    report_kind = collections.Counter()
    n_reports = 0

    for _created_at, rkind, raw in rows:
        cits = _coerce_citations(raw)
        if not cits:
            continue
        n_reports += 1
        report_kind[rkind] += 1
        per_report.append(len(cits))
        for ci in cits:
            kind[ci.get("source_kind") or "(unknown)"] += 1
            verified["검증됨" if ci.get("verified") else "미검증"] += 1
            publisher[_publisher_name(ci)] += 1
            category[ci.get("doc_category") or "(미분류)"] += 1

    total = sum(kind.values())
    per_report.sort()
    return {
        "reports_with_citations": n_reports,
        "reports_by_kind": dict(report_kind),
        "total_citations": total,
        "source_kind": dict(kind.most_common()),
        "verified": dict(verified.most_common()),
        "publisher": dict(publisher.most_common()),
        "doc_category": dict(category.most_common()),
        "per_report": {
            "min": per_report[0] if per_report else 0,
            "median": per_report[len(per_report) // 2] if per_report else 0,
            "max": per_report[-1] if per_report else 0,
            "avg": round(total / n_reports, 1) if n_reports else 0,
        },
    }


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "—"


def print_human(stats: dict, *, top: int) -> None:
    total = stats["total_citations"]
    print(f"=== 레퍼런스 통계 ===")
    print(f"citation 있는 보고서: {stats['reports_with_citations']}건  "
          f"{stats['reports_by_kind']}")
    print(f"총 citation: {total}개  "
          f"(보고서당 min {stats['per_report']['min']} / "
          f"median {stats['per_report']['median']} / "
          f"avg {stats['per_report']['avg']} / "
          f"max {stats['per_report']['max']})")

    print("\n[출처 종류]")
    for k, v in stats["source_kind"].items():
        print(f"  {v:>6}  {_pct(v, total):>6}  {k}")

    print("\n[검증 여부]")
    for k, v in stats["verified"].items():
        print(f"  {v:>6}  {_pct(v, total):>6}  {k}")

    print(f"\n[기관 publisher — top {top}]")
    for k, v in list(stats["publisher"].items())[:top]:
        print(f"  {v:>6}  {_pct(v, total):>6}  {k}")

    print(f"\n[문서 카테고리 — top {top}]")
    for k, v in list(stats["doc_category"].items())[:top]:
        print(f"  {v:>6}  {_pct(v, total):>6}  {k}")


def main() -> int:
    # Windows 콘솔 UTF-8 (한글 출처명 깨짐 방지)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="reports.citations_json 출처 통계")
    ap.add_argument("--pg-dsn", default=None, help="Postgres DSN (없으면 REPORTS_PG_DSN)")
    ap.add_argument("--sqlite", default=None, help="로컬 SQLite 경로 (검증용)")
    ap.add_argument("--kind", default="final", choices=["final", "web", "rag", "all"],
                    help="보고서 kind 필터 (기본 final — 답변에 실제 붙은 출처)")
    ap.add_argument("--since", default=None, help="created_at 하한 (ISO/날짜, UTC)")
    ap.add_argument("--until", default=None, help="created_at 상한 (exclusive)")
    ap.add_argument("--top", type=int, default=15, help="publisher/category 상위 N")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args()

    sqlite_path = args.sqlite
    pg_dsn = None if sqlite_path else (args.pg_dsn or os.environ.get("REPORTS_PG_DSN"))

    if not sqlite_path and not pg_dsn:
        print(
            "운영 DSN 이 없습니다. REPORTS_PG_DSN 을 설정하거나 --pg-dsn / --sqlite 지정.",
            file=sys.stderr,
        )
        return 2

    src = sqlite_path or f"PG {pg_dsn.split('@')[-1]}"
    print(f"# source: {src}  kind={args.kind}"
          f"{f'  since={args.since}' if args.since else ''}"
          f"{f'  until={args.until}' if args.until else ''}\n", file=sys.stderr)

    rows = _fetch_rows(
        sqlite_path=sqlite_path, pg_dsn=pg_dsn,
        kind=args.kind, since=args.since, until=args.until,
    )
    stats = aggregate(rows)

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print_human(stats, top=args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
