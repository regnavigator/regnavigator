"""Blob 보존정책 — iter_uris·delete(경로방어) + clear_blob_uri + prune 판별."""
from __future__ import annotations

import pytest

from src.persistence.blobs import LocalBlobStore


def test_iter_uris_lists_only_md(tmp_path):
    s = LocalBlobStore(str(tmp_path))
    s.put("t1/r1.md", "본문")
    s.put("t2/r2.md", "본문")
    (tmp_path / "t1" / "noise.txt").write_text("x", encoding="utf-8")
    uris = sorted(s.iter_uris())
    assert len(uris) == 2
    assert all(u.startswith("file://") and u.endswith(".md") for u in uris)


def test_delete_removes_and_is_idempotent(tmp_path):
    s = LocalBlobStore(str(tmp_path))
    uri = s.put("t1/r1.md", "본문")
    assert s.delete(uri) is True
    assert s.delete(uri) is False          # 이미 없음 → 멱등
    assert list(s.iter_uris()) == []


def test_delete_cleans_empty_thread_dir(tmp_path):
    s = LocalBlobStore(str(tmp_path))
    uri = s.put("t1/r1.md", "본문")
    s.delete(uri)
    assert not (tmp_path / "t1").exists()  # 빈 디렉토리 정리


def test_delete_rejects_outside_root(tmp_path):
    s = LocalBlobStore(str(tmp_path / "root"))
    outside = tmp_path / "secret.md"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        s.delete(f"file://{outside.as_posix()}")
    assert outside.exists()                # 삭제 안 됨


def test_delete_rejects_non_local_uri(tmp_path):
    s = LocalBlobStore(str(tmp_path))
    with pytest.raises(ValueError):
        s.delete("gs://bucket/x.md")


def test_report_id_parsed_from_uri():
    from scripts.prune_blobs import _report_id_from_uri
    assert _report_id_from_uri("file:///a/b/tid/rid123.md") == "rid123"
    assert _report_id_from_uri("gs://bkt/tid/rid456.md") == "rid456"


def test_clear_blob_uri_keeps_meta(tmp_path, monkeypatch):
    """만료 정리 후 메타(제목)는 남고 blob_uri 만 비워진다 → /download 는 409."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "t.db"))
    from src.persistence.reports_repo import ReportMeta, SqliteReportsRepo

    repo = SqliteReportsRepo(str(tmp_path / "t.db"))
    rid = repo.create(ReportMeta(id="", thread_id="t1", mode="deep", kind="final",
                                 status="done", blob_uri="file:///x.md", title="제목"))
    repo.clear_blob_uri(rid)
    meta = repo.get(rid)
    assert meta.blob_uri is None
    assert meta.title == "제목" and meta.status == "done"



def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    from src.persistence.reports_repo import SqliteReportsRepo
    return LocalBlobStore(str(tmp_path / "blobs")), SqliteReportsRepo(str(tmp_path / "t.db"))


def _add(repo, store, rid, kind, created_at, kept=False):
    from src.persistence.reports_repo import ReportMeta
    uri = store.put(f"t1/{rid}.md", "본문")
    repo.create(ReportMeta(id=rid, thread_id="t1", mode="deep", kind=kind, status="done",
                           blob_uri=uri, title=rid, created_at=created_at, kept=kept))
    return uri


OLD, NEW = "2020-01-01T00:00:00.000000Z", "2999-01-01T00:00:00.000000Z"


def test_expired_report_fully_deleted(tmp_path, monkeypatch):
    """만료 보고서는 blob 과 메타 행(목록·제목)까지 삭제 — 사이드바에서도 사라진다."""
    from scripts.prune_blobs import run
    store, repo = _setup(tmp_path, monkeypatch)
    _add(repo, store, "old", "final", OLD)
    _add(repo, store, "fresh", "final", NEW)
    r = run(days=30, apply=True, limit=100, store=store, repo=repo)
    assert r["expired"] == 1
    assert repo.get("old") is None
    assert repo.get("fresh") is not None
    assert len(list(store.iter_uris())) == 1


def test_form_documents_never_expire(tmp_path, monkeypatch):
    """서식(kind=doc)은 보관 여부와 무관하게 30일 스윕 제외 — 수명은 대화 cascade 가 정함."""
    from scripts.prune_blobs import run
    store, repo = _setup(tmp_path, monkeypatch)
    _add(repo, store, "doc_kept", "doc", OLD, kept=True)
    _add(repo, store, "doc_live", "doc", OLD)
    run(days=30, apply=True, limit=100, store=store, repo=repo)
    assert repo.get("doc_kept").blob_uri and repo.get("doc_live").blob_uri
    assert len(list(store.iter_uris())) == 2


def test_dry_run_deletes_nothing_and_orphans_swept(tmp_path, monkeypatch):
    from scripts.prune_blobs import run
    store, repo = _setup(tmp_path, monkeypatch)
    _add(repo, store, "old", "final", OLD)
    store.put("t9/ghost.md", "잔재")
    r = run(days=30, apply=False, limit=100, store=store, repo=repo)
    assert (r["expired"], r["orphans"]) == (1, 1)
    assert repo.get("old") is not None and len(list(store.iter_uris())) == 2
    run(days=30, apply=True, limit=100, store=store, repo=repo)
    assert list(store.iter_uris()) == []


def test_foreign_blob_uri_row_still_deleted(tmp_path, monkeypatch):
    """다른 환경 경로(로컬 dev 가 운영 PG 에 쓴 행)는 파일 없이 행만 지운다 — 루프가 멈추지 않는다."""
    from scripts.prune_blobs import run
    from src.persistence.reports_repo import ReportMeta
    store, repo = _setup(tmp_path, monkeypatch)
    repo.create(ReportMeta(id="alien", thread_id="t", mode="deep", kind="final", status="done",
                           blob_uri="file://C:/elsewhere/t/alien.md", created_at=OLD))
    _add(repo, store, "old", "final", OLD)
    run(days=30, apply=True, limit=100, store=store, repo=repo)
    assert repo.get("alien") is None and repo.get("old") is None
    assert list(store.iter_uris()) == []


def test_empty_store_with_blob_rows_aborts(tmp_path, monkeypatch):
    """스토어가 비었는데 행이 blob 을 가리키면 배선 오류 — 행을 지우지 않고 중단."""
    from scripts.prune_blobs import run
    from src.persistence.reports_repo import ReportMeta
    store, repo = _setup(tmp_path, monkeypatch)
    repo.create(ReportMeta(id="r", thread_id="t", mode="deep", kind="final", status="done",
                           blob_uri="file:///app/data/blobs/t/r.md", created_at=OLD))
    with pytest.raises(SystemExit):
        run(days=30, apply=True, limit=100, store=store, repo=repo)
    assert repo.get("r") is not None
