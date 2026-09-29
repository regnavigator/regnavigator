# -*- coding: utf-8 -*-
"""중복 서류(kind='doc') 정리 — [이 서식으로 작성] 연타 가드 이전 생성분.

같은 (thread_id, title) 그룹에서 **최신 1건만 남기고** 삭제한다.
`latest_draft_report_for_thread` 가 최신 run 의 report_id 를 집으므로,
최신만 남기면 채팅 기입·문서 패널 게이트는 그대로 정상이다.
run 이력(report_runs)은 정책대로 보존한다.

사용:
    python scripts/cleanup_duplicate_docs.py            # 드라이런(목록만)
    python scripts/cleanup_duplicate_docs.py --apply    # 실제 삭제
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    apply = "--apply" in sys.argv
    dsn = (os.getenv("REPORTS_PG_DSN") or "").strip()
    if not dsn:
        print("REPORTS_PG_DSN 미설정 — 운영 PG 대상 스크립트입니다.")
        sys.exit(1)
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, thread_id, title, created_at,
                      COALESCE(filled_values,'{}') AS fv  -- enc1: 암호문일 수 있음(field_crypto.decrypt_text)
                 FROM reports WHERE kind='doc' ORDER BY created_at"""
        )
        rows = cur.fetchall()
        groups: dict = defaultdict(list)
        for r in rows:
            groups[(r["thread_id"], r["title"])].append(r)
        victims: list[str] = []
        for (tid, title), g in groups.items():
            if len(g) <= 1:
                continue
            print(f"-- {tid} | {title} | {len(g)}건 (최신 유지: {g[-1]['id']})")
            for r in g[:-1]:
                print(f"   삭제 대상: {r['id']} {r['created_at']} "
                      f"filled={r['fv'][:50]}")
                victims.append(r["id"])
        print(f"\n삭제 대상 합계: {len(victims)}건 / 전체 doc {len(rows)}건")
        if not victims:
            return
        if not apply:
            print("드라이런 — 실제 삭제는 --apply")
            return
        cur.execute("DELETE FROM reports WHERE id = ANY(%s)", (victims,))
        conn.commit()
        print(f"삭제 완료: {cur.rowcount}행")
        cur.execute(
            """SELECT thread_id, title, count(*) c FROM reports
                WHERE kind='doc' GROUP BY 1,2 HAVING count(*) > 1"""
        )
        left = cur.fetchall()
        print("잔여 중복 그룹:", left or "없음")


if __name__ == "__main__":
    main()
