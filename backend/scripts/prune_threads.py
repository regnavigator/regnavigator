"""대화(thread) 보존정리 — 개인정보처리방침 §3(대화 90일) 이행.

마지막 활동(chat_threads.updated_at)이 보존기간 이전인 thread 를 메시지·steps
포함 완전 삭제. 구 `prune_checkpoints.py`(langgraph 체크포인터, Phase 5 은퇴)
대체 — 이제 대화 상태는 threads_repo(운영 PG / dev SQLite)에 있다.

env:
  CHAT_RETENTION_DAYS=90     보존기간(일, 기본 90)
  PRUNE_APPLY=1              실삭제(미설정=DRY_RUN 미리보기)

사용:
  python scripts/prune_threads.py                 # 미리보기
  PRUNE_APPLY=1 python scripts/prune_threads.py   # 실삭제

medi-cron 컨테이너가 일 1회 실행(docker-compose).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    try:
        days = int(os.getenv("CHAT_RETENTION_DAYS") or "90")
    except ValueError:
        days = 90
    apply = (os.getenv("PRUNE_APPLY") or "").strip() == "1"
    cutoff = _cutoff_iso(days)

    from src.persistence.threads_repo import get_threads_repo

    repo = get_threads_repo()
    stale = repo.stale_thread_ids(cutoff_iso=cutoff)
    print(f"[prune-threads] retention={days}d cutoff={cutoff[:10]} "
          f"stale={len(stale)} apply={apply}")

    if not stale:
        print("[prune-threads] 대상 없음.")
        return
    if not apply:
        for tid in stale[:20]:
            print(f"  (dry) {tid}")
        if len(stale) > 20:
            print(f"  … 외 {len(stale) - 20}건")
        print("[prune-threads] DRY_RUN — 삭제 안 함. 실삭제: PRUNE_APPLY=1")
        return

    deleted = 0
    for tid in stale:
        try:
            # 대화에 딸린 서식(기입값=개인정보)도 함께 — 보관한 것만 남는다(2026-09-18).
            from src.form_docs import delete_thread_documents
            delete_thread_documents(tid)
            repo.delete_thread(tid)
            deleted += 1
        except Exception as e:  # noqa: BLE001 — 한 건 실패가 전체를 막지 않음
            print(f"  [warn] {tid} 삭제 실패: {e}")
    print(f"[prune-threads] 삭제 {deleted}/{len(stale)}건 완료.")


if __name__ == "__main__":
    main()
