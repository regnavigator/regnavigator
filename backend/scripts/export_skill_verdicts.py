"""skill_verdict 골든셋 export — events 를 jsonl 로 덤프.

IRB/DRB 스킬 판정 로그(rulepack_version·trace·loaded 포함)는 CONTENT 분류라
90일 후 삭제된다(EVENT_CONTENT_RETENTION_DAYS). 골든셋으로 쓰려면 보존기간 내
주기 export 가 필요 — 이 스크립트가 그 경로다(2026-08-11, 미비 발견 건).

    PYTHONUTF8=1 python scripts/export_skill_verdicts.py             # 전체
    PYTHONUTF8=1 python scripts/export_skill_verdicts.py --days 30   # 최근 30일
    → local/skill_verdicts_YYYYMMDD.jsonl (append-safe: 실행마다 새 파일)

각 줄: {ts, user_id, thread_id, verdict, rulepack_version, loaded, input,
        office_decision: null}  ← office_decision 은 사무국 실제 결과 대조 시 수기.
운영 export 는 컨테이너 안에서: docker compose exec medi-back python scripts/…
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="최근 N일만(0=전체)")
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    from src.persistence import get_events_repo

    since = None
    if args.days > 0:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    events = get_events_repo().list_by_type(
        "skill_verdict", since=since, limit=100_000)

    out = args.out or (
        Path(__file__).resolve().parents[1] / "local"
        / f"skill_verdicts_{datetime.now(timezone.utc):%Y%m%d}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    n = 0
    with out.open("w", encoding="utf-8") as f:
        for ev in events:
            try:
                payload = json.loads(ev.payload_json or "{}")
            except json.JSONDecodeError:
                continue
            f.write(json.dumps({
                "ts": ev.ts,
                "user_id": ev.user_id,
                "thread_id": ev.thread_id,
                **payload,                 # verdict·rulepack_version·loaded·input
                "office_decision": payload.get("office_decision"),
            }, ensure_ascii=False) + "\n")
            n += 1
    print(f"[export-skill-verdicts] {n}건 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
