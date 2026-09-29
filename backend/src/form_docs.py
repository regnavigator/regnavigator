"""작성한 서식(서류, kind="doc")의 수명 규칙 (2026-09-18).

- 서식은 그것을 만든 **대화에 딸린다** — 대화가 삭제(사용자 삭제·90일 보존 정리)되면
  함께 지운다(cascade). 종전엔 대화만 지워지고 서식 행·기입값(개인정보)이 고아로 남았다.
- 예외: 사용자가 서식 목록에서 **보관**(`reports.kept`)한 서식은 독립 목록으로 남는다.
  소유 확인은 `report_runs.owner_of_report`(2차 근거)가 맡으므로 대화가 없어도 열린다.

reports 테이블과 threads 테이블은 저장소가 달라 DB FK cascade 를 걸 수 없다 —
삭제 경로 두 곳(`DELETE /chat/{tid}`·`scripts/prune_threads.py`)이 이 함수를 부른다.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def delete_thread_documents(thread_id: str) -> dict:
    """thread 의 서식 중 보관하지 않은 것을 지운다. 반환: {"deleted": n, "kept": m}."""
    from src.persistence import get_blob_store, get_report_runs_repo, get_reports_repo

    repo = get_reports_repo()
    runs = get_report_runs_repo()
    deleted = kept = 0
    for meta in repo.list_for_thread(thread_id, kind="doc"):
        if meta.kept:
            kept += 1
            continue
        if meta.blob_uri:
            try:
                get_blob_store().delete(meta.blob_uri)
            except Exception:  # noqa: BLE001 — 고아 blob 은 보존정책 스윕이 걷는다
                _log.info("doc cascade: blob 삭제 실패(무시) %s", meta.id)
        repo.delete(meta.id)
        try:
            runs.detach_report(meta.id)
        except Exception:  # noqa: BLE001
            _log.warning("doc cascade: run detach 실패 %s", meta.id, exc_info=True)
        deleted += 1
    if deleted or kept:
        _log.info("doc cascade thread=%s deleted=%d kept=%d", thread_id, deleted, kept)
    return {"deleted": deleted, "kept": kept}


def document_status(field_count: int, filled_count: int) -> str:
    """목록 표시용 작성 상태 — empty(미작성)·partial(작성 중)·done(완료)."""
    if filled_count <= 0:
        return "empty"
    if field_count > 0 and filled_count >= field_count:
        return "done"
    return "partial"
