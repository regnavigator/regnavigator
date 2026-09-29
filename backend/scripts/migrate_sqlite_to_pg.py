"""SQLite dev DB → Postgres 이관 스크립트.

dev 환경에서 쌓인 데이터(events·feedback·users·reports)를 production Postgres로
한 번만 옮길 때 사용. 재실행은 `--mode=upsert`로 멱등 처리 가능.

usage:
    # 기본: dry-run (행 수만 출력)
    python scripts/migrate_sqlite_to_pg.py \\
        --sqlite ./medi_reports.db \\
        --pg-dsn "postgresql://medi:pass@host:6001/medi"

    # 실 이관:
    python scripts/migrate_sqlite_to_pg.py \\
        --sqlite ./medi_reports.db \\
        --pg-dsn "postgresql://medi:pass@host:6001/medi" \\
        --apply

    # 멱등 모드 (이미 있는 행은 skip):
    python scripts/migrate_sqlite_to_pg.py --apply --mode=upsert ...

주의:
- LangGraph 체크포인터(thread state)는 옮기지 않음 — 별도 PostgresSaver 사용.
- prod에 데이터 있으면 충돌 가능 — 먼저 백업 권장.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Optional


def _open_pg(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as e:
        print("psycopg not installed. `pip install medi-back[prod]`", file=sys.stderr)
        sys.exit(2)
    return psycopg.connect(dsn, autocommit=True), dict_row


def _ensure_pg_schema(dsn: str):
    """PG 스키마 보장 — 첫 import 시 자동 init."""
    from src.persistence import _pg as pg_helpers
    pg_helpers.init_schema(dsn)


def _iso_to_pg(s: Optional[str]):
    """ISO 8601 string → datetime (PG TIMESTAMPTZ 호환)."""
    if s is None:
        return None
    from datetime import datetime
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    *,
    table: str,
    pg_columns: list[str],
    sqlite_columns: list[str],
    on_conflict: str,
    transform_row=None,
    apply: bool,
) -> int:
    """한 테이블 이관 — sqlite → pg.

    pg_columns / sqlite_columns: 같은 길이·동순서. 보통 같지만 타입 변환 필요 시 transform.
    on_conflict: PG ON CONFLICT 절 (e.g., "(id) DO NOTHING").
    """
    sqlite_conn.row_factory = sqlite3.Row
    cur = sqlite_conn.execute(f"SELECT {', '.join(sqlite_columns)} FROM {table}")
    rows = list(cur.fetchall())
    print(f"  [{table}] sqlite rows: {len(rows)}")

    if not apply:
        return len(rows)

    if not rows:
        return 0

    cols = ", ".join(pg_columns)
    placeholders = ", ".join(["%s"] * len(pg_columns))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT {on_conflict}"

    inserted = 0
    with pg_conn.cursor() as pcur:
        for r in rows:
            values = transform_row(r) if transform_row else tuple(r)
            pcur.execute(sql, values)
            inserted += pcur.rowcount
    print(f"  [{table}] applied: {inserted}")
    return inserted


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sqlite", required=True, help="SQLite DB 경로")
    p.add_argument("--pg-dsn", required=True, help="Postgres DSN")
    p.add_argument("--apply", action="store_true",
                   help="실제 INSERT (미지정 시 dry-run)")
    p.add_argument("--mode", choices=["upsert", "skip"], default="skip",
                   help="upsert=ON CONFLICT UPDATE / skip=DO NOTHING (default)")
    args = p.parse_args()

    print(f"=== SQLite → Postgres 이관 (apply={args.apply}, mode={args.mode}) ===")
    print(f"  src: {args.sqlite}")
    print(f"  dst: {args.pg_dsn.split('@')[-1] if '@' in args.pg_dsn else args.pg_dsn}")

    if args.apply:
        _ensure_pg_schema(args.pg_dsn)

    src = sqlite3.connect(args.sqlite)

    if args.apply:
        pg_conn, _ = _open_pg(args.pg_dsn)
    else:
        pg_conn = None

    try:
        on_conflict = "(id) DO NOTHING" if args.mode == "skip" else "(id) DO UPDATE SET updated_at = EXCLUDED.updated_at"

        # users
        migrate_table(
            src, pg_conn, apply=args.apply, table="users",
            sqlite_columns=[
                "id", "email", "email_verified_at", "is_admin",
                "daily_token_limit_override", "monthly_token_limit_override",
                "created_at", "updated_at",
            ],
            pg_columns=[
                "id", "email", "email_verified_at", "is_admin",
                "daily_token_limit_override", "monthly_token_limit_override",
                "created_at", "updated_at",
            ],
            on_conflict=on_conflict,
            transform_row=lambda r: (
                r["id"], r["email"], _iso_to_pg(r["email_verified_at"]),
                bool(r["is_admin"]),
                r["daily_token_limit_override"],
                r["monthly_token_limit_override"],
                _iso_to_pg(r["created_at"]), _iso_to_pg(r["updated_at"]),
            ),
        )

        # reports
        migrate_table(
            src, pg_conn, apply=args.apply, table="reports",
            sqlite_columns=[
                "id", "thread_id", "run_id", "mode", "kind", "status",
                "blob_uri", "title", "citations_json",
                "created_at", "completed_at", "error_message",
            ],
            pg_columns=[
                "id", "thread_id", "run_id", "mode", "kind", "status",
                "blob_uri", "title", "citations_json",
                "created_at", "completed_at", "error_message",
            ],
            on_conflict="(id) DO NOTHING",
            transform_row=lambda r: (
                r["id"], r["thread_id"], r["run_id"], r["mode"], r["kind"], r["status"],
                r["blob_uri"], r["title"],
                json.dumps(json.loads(r["citations_json"])) if r["citations_json"] else None,
                _iso_to_pg(r["created_at"]), _iso_to_pg(r["completed_at"]),
                r["error_message"],
            ),
        )

        # events
        migrate_table(
            src, pg_conn, apply=args.apply, table="events",
            sqlite_columns=[
                "id", "ts", "event_type", "user_id", "thread_id", "run_id",
                "message_id", "payload_json", "cost_usd",
                "input_tokens", "output_tokens",
            ],
            pg_columns=[
                "id", "ts", "event_type", "user_id", "thread_id", "run_id",
                "message_id", "payload_json", "cost_usd",
                "input_tokens", "output_tokens",
            ],
            on_conflict="(id) DO NOTHING",
            transform_row=lambda r: (
                r["id"], _iso_to_pg(r["ts"]), r["event_type"],
                r["user_id"], r["thread_id"], r["run_id"], r["message_id"],
                json.dumps(json.loads(r["payload_json"])) if r["payload_json"] else None,
                r["cost_usd"], r["input_tokens"], r["output_tokens"],
            ),
        )

        # feedback
        migrate_table(
            src, pg_conn, apply=args.apply, table="feedback",
            sqlite_columns=[
                "id", "rating", "user_id", "thread_id", "message_id",
                "report_id", "comment", "created_at",
            ],
            pg_columns=[
                "id", "rating", "user_id", "thread_id", "message_id",
                "report_id", "comment", "created_at",
            ],
            on_conflict="(id) DO NOTHING",
            transform_row=lambda r: (
                r["id"], r["rating"], r["user_id"], r["thread_id"],
                r["message_id"], r["report_id"], r["comment"],
                _iso_to_pg(r["created_at"]),
            ),
        )
    finally:
        src.close()
        if pg_conn:
            pg_conn.close()

    if not args.apply:
        print("\n→ DRY-RUN (apply=False). 실 이관은 --apply 추가.")
    else:
        print("\n→ DONE. PG에 데이터 적재 완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
