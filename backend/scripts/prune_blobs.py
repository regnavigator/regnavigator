"""보고서 보존정책 정리 — 만료 보고서 완전 삭제 + orphan blob 삭제.

두 부류를 지운다:

1. **만료(expired)** — `reports.created_at` 이 보존기간(`BLOB_RETENTION_DAYS`) 이전인 보고서.
   blob(전문)과 **메타 행(목록·제목·요약·인용)을 함께 삭제**한다(2026-09-23 운영자 결정:
   "따로 저장한 게 아니면 삭제되는 게 맞다"). 종전엔 blob 만 지우고 행을 남겨, 사이드바에
   열리지 않는 보고서가 계속 떴다. 사용자가 계속 쓸 보고서는 완료 메일의 Word 첨부로 보관한다.
   `report_runs` 이력은 사용자 삭제(`DELETE /reports/{id}`)와 같이 남긴다(사용량·관측 근거).
2. **orphan** — 스토어엔 있는데 `reports` 행이 없는 blob(중단된 실행·수동 삭제 잔재).

**작성한 서식(`kind="doc"`)은 만료 대상이 아니다**(2026-09-23). 서식 blob 은 기입의
원본 골격이라 지우면 서식이 깨진다. 서식 수명은 대화 cascade(`src/form_docs.py`)가
정한다 — 대화와 함께 지워지거나, 보관(`kept`)하면 남는다.

안전장치: 기본 **DRY_RUN**(미리보기). 실제 삭제는 `PRUNE_APPLY=1`.

env:
  BLOB_RETENTION_DAYS=30     보존기간(일, 기본 30)
  PRUNE_APPLY=1              실제 삭제(미설정 = DRY_RUN)
  PRUNE_MAX=1000             1회 최대 삭제 수(폭주 방지)

usage:
  python scripts/prune_blobs.py                 # 미리보기
  PRUNE_APPLY=1 python scripts/prune_blobs.py   # 실삭제
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone


def _report_id_from_uri(uri: str) -> str:
    """`…/{thread_id}/{report_id}.md` → report_id."""
    name = uri.rsplit("/", 1)[-1]
    return name[:-3] if name.endswith(".md") else name


def run(*, days: int, apply: bool, limit: int, store, repo) -> dict:
    """정리 본체 — 반환: {"expired": n, "orphans": m, "deleted_blobs": k}."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")   # reports.created_at 과 같은 고정폭 형식
    expired = repo.list_expired(cutoff, limit=limit)

    orphans: list[str] = []
    total = 0
    for uri in store.iter_uris():
        total += 1
        if len(expired) + len(orphans) >= limit:
            break
        if repo.get(_report_id_from_uri(uri)) is None:
            orphans.append(uri)

    print(f"[prune-blobs] retention={days}d cutoff={cutoff[:10]} apply={apply} | "
          f"blob {total} · 만료 보고서 {len(expired)} · orphan {len(orphans)}")
    if not apply:
        for m in expired[:5]:
            print(f"  [DRY] 만료  {m.id} {m.created_at[:10]} {(m.title or '')[:30]}")
        for uri in orphans[:5]:
            print(f"  [DRY] orphan {uri}")
        print("[prune-blobs] DRY_RUN — 삭제 안 함. 실삭제: PRUNE_APPLY=1")
        return {"expired": len(expired), "orphans": len(orphans), "deleted_blobs": 0}

    # 배선 점검 — 스토어가 비었는데 만료 행이 blob 을 가리키면 cron 이 엉뚱한 위치를 보는 것
    # (2026-09-23 실측: medi-cron 에 BLOB_LOCAL_DIR 누락). 행만 지우고 파일을 남기지 않게 중단.
    if total == 0 and any(m.blob_uri for m in expired):
        raise SystemExit("[prune-blobs] blob 0개인데 만료 보고서가 blob 을 가리킴 — "
                         "BLOB_BACKEND/BLOB_LOCAL_DIR 배선 확인. 중단.")

    deleted_blobs = 0
    foreign: list[str] = []
    for m in expired:
        if m.blob_uri:
            try:
                if store.delete(m.blob_uri):
                    deleted_blobs += 1
            except ValueError:
                # 다른 환경의 경로(9/17 이전 로컬 dev 가 운영 PG 에 쓴 행: file://C:/…) —
                # 이 스토어엔 파일이 없다. 행만 지운다.
                foreign.append(m.id)
        repo.delete(m.id)          # 목록·제목·요약·인용까지 — 사이드바에서도 사라진다
    if foreign:
        print(f"[prune-blobs] 이 스토어 밖 경로 {len(foreign)}건 — 행만 삭제: {foreign[:5]}")
    for uri in orphans:
        if store.delete(uri):
            deleted_blobs += 1
    print(f"[prune-blobs] 보고서 {len(expired)}건 삭제 · blob {deleted_blobs}개 삭제 "
          f"(orphan {len(orphans)})")
    return {"expired": len(expired), "orphans": len(orphans),
            "deleted_blobs": deleted_blobs}


def main() -> int:
    # load_dotenv 는 여기(실행 시)로 한정 — 모듈 레벨이면 테스트가 이 모듈을
    # import 하는 순간 실 .env 전체가 pytest 프로세스에 로드돼 다른 테스트를
    # 오염시킴(실측: EMAIL_SERVER 누출 → test_notifications 실패, 2026-07-21).
    from dotenv import load_dotenv
    load_dotenv()

    from src.persistence import get_blob_store, get_reports_repo

    run(days=int(os.getenv("BLOB_RETENTION_DAYS") or "30"),
        apply=(os.getenv("PRUNE_APPLY") or "").strip() == "1",
        limit=int(os.getenv("PRUNE_MAX") or "1000"),
        store=get_blob_store(), repo=get_reports_repo())
    return 0


if __name__ == "__main__":
    sys.exit(main())
