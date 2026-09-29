"""보고서 소유권 확인 가능성 점검 — **읽기 전용**. 배포 전 게이트.

왜 필요한가: 2026-08-04 부터 `/reports/{id}`·`/download`·`/threads/{tid}/reports`
는 소유자만 통과한다(감사 C-1). 소유자는 ① 소속 thread 의 user_id, ② 없으면
report_runs 의 run 기록으로 판정하고, **둘 다 실패하면 차단**한다(fail-open 금지).

따라서 배포 전에 "둘 다로도 소유자를 못 찾는 보고서"가 운영에 얼마나 있는지
알아야 한다. 그 보고서들은 배포 즉시 **정당한 소유자에게도 404** 가 된다.

usage:
    python scripts/check_report_ownership.py          # .env 의 백엔드 자동 판별
    REPORTS_BACKEND=postgres python scripts/check_report_ownership.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


_SQL_SQLITE = """
SELECT
  (SELECT COUNT(*) FROM reports) AS total,
  (SELECT COUNT(*) FROM reports r
     WHERE EXISTS (SELECT 1 FROM chat_threads t
                    WHERE t.id = r.thread_id AND t.user_id IS NOT NULL)) AS by_thread,
  (SELECT COUNT(*) FROM reports r
     WHERE NOT EXISTS (SELECT 1 FROM chat_threads t
                        WHERE t.id = r.thread_id AND t.user_id IS NOT NULL)
       AND EXISTS (SELECT 1 FROM report_runs u
                    WHERE u.report_id = r.id AND u.user_id IS NOT NULL)) AS by_run
"""

_SQL_PG = _SQL_SQLITE  # 표준 SQL — 방언 차이 없음


def main() -> int:
    backend = (os.getenv("REPORTS_BACKEND") or "sqlite").lower()

    if backend == "postgres":
        from src.persistence import _pg
        dsn = os.environ["REPORTS_PG_DSN"]
        with _pg.pg_cursor(dsn) as cur:
            cur.execute(_SQL_PG)
            row = dict(cur.fetchone())
    else:
        import sqlite3
        path = os.getenv("REPORTS_SQLITE_PATH") or "./medi_reports.db"
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute(_SQL_SQLITE).fetchone())
        conn.close()

    total = row["total"] or 0
    resolvable = (row["by_thread"] or 0) + (row["by_run"] or 0)
    orphan = total - resolvable

    print(f"backend        : {backend}")
    print(f"보고서 전체    : {total}")
    print(f"  thread 로 확인: {row['by_thread']}")
    print(f"  run 으로 확인 : {row['by_run']}")
    print(f"소유자 확인 불가: {orphan}"
          + (f"  ({orphan / total * 100:.1f}%)" if total else ""))

    if orphan:
        print()
        print("⚠️  이 보고서들은 배포 후 소유자에게도 404 가 된다.")
        print("    벤치·테스트 산출물이면 무시, 실사용자 것이면 reports 에 user_id 를")
        print("    백필한 뒤 배포할 것.")
        return 1
    print("\n✅ 전부 소유자 확인 가능 — 배포해도 정상 사용자가 잠기지 않는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
