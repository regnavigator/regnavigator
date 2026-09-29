"""ReportsRepo — 보고서 메타 영속.

인터페이스 1개, 구현 2개:
- `SqliteReportsRepo`: dev — 단일 파일 DB
- `PostgresReportsRepo`: production — Cloud SQL Postgres

스키마: schema.sql 참조.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from . import field_crypto
from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso


@dataclass
class ReportMeta:
    """보고서 한 건의 메타. citations_json은 list[dict]를 직렬화한 문자열.

    summary: 본문 `## 개요` 섹션에서 추출한 요약(`tools/reports._extract_summary`).
    **소비처는 UI**(사이드바 목록·우측 패널) — 채팅↔보고서 완전 분리(2026-07-25)
    이후 채팅 system message 로 주입하지 않는다(구 주석의 `read_report` 도구는
    실재하지 않았다 — 채팅 도구는 qdrant_search·tavily_search·ask_clarify 3개).
    """

    id: str
    thread_id: str
    mode: str           # fast | deep
    kind: str           # final | rag | web
    status: str         # running | done | error
    blob_uri: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    citations_json: Optional[str] = None
    run_id: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    # 서류 초안(document_draft) 기입값 — {"항목명": "값"} JSON 직렬화(2026-08-24).
    # 채팅 턴 대조 패스·/documents fill 이 merge_filled_values 로 갱신.
    filled_values: Optional[str] = None
    # 보관(스크랩) — 사용자가 서식 목록에서 보관한 서류는 원 대화가 삭제·만료돼도
    # 남는다(2026-09-18). 보관하지 않은 서류는 대화와 함께 지워진다(cascade).
    kept: bool = False
    # 사용자가 붙인 별명 — 같은 서식을 여러 번 쓸 때 구분용(2026-09-18). 원 제목(title)은 보존.
    alias: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


class ReportsRepo(Protocol):
    def create(self, meta: ReportMeta) -> str: ...
    def update_status(
        self,
        report_id: str,
        *,
        status: str,
        blob_uri: Optional[str] = None,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        citations: Optional[list] = None,
        error_message: Optional[str] = None,
    ) -> None: ...
    def get(self, report_id: str) -> Optional[ReportMeta]: ...
    def merge_filled_values(self, report_id: str, values: dict) -> dict: ...
    def clear_blob_uri(self, report_id: str) -> None: ...
    def delete(self, report_id: str) -> bool: ...
    def list_expired(self, cutoff_iso: str, *, limit: int) -> list[ReportMeta]: ...
    def set_kind(self, report_id: str, kind: str) -> None: ...
    def set_kept(self, report_id: str, kept: bool) -> None: ...
    def set_alias(self, report_id: str, alias: Optional[str]) -> None: ...
    def list_for_thread(
        self,
        thread_id: str,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[ReportMeta]: ...


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS reports (
  id              TEXT PRIMARY KEY,
  thread_id       TEXT NOT NULL,
  run_id          TEXT,
  mode            TEXT NOT NULL,
  kind            TEXT NOT NULL,
  status          TEXT NOT NULL,
  blob_uri        TEXT,
  title           TEXT,
  summary         TEXT,
  citations_json  TEXT,
  created_at      TEXT NOT NULL,
  completed_at    TEXT,
  error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_thread ON reports(thread_id, created_at DESC);
"""


def _ensure_summary_column_sqlite(conn: sqlite3.Connection) -> None:
    """기존 DB에 없는 컬럼 ADD — IF NOT EXISTS 부재 회피."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(reports)").fetchall()}
    if "summary" not in cols:
        conn.execute("ALTER TABLE reports ADD COLUMN summary TEXT")
    if "filled_values" not in cols:
        conn.execute("ALTER TABLE reports ADD COLUMN filled_values TEXT")
    if "kept" not in cols:
        conn.execute("ALTER TABLE reports ADD COLUMN kept INTEGER NOT NULL DEFAULT 0")
    if "alias" not in cols:
        conn.execute("ALTER TABLE reports ADD COLUMN alias TEXT")


class SqliteReportsRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE
    _extra_pragmas = ("PRAGMA foreign_keys=ON;",)

    def _post_init(self, conn: sqlite3.Connection) -> None:
        _ensure_summary_column_sqlite(conn)

    def create(self, meta: ReportMeta) -> str:
        if not meta.id:
            meta.id = _new_id()
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO reports
                   (id, thread_id, run_id, mode, kind, status,
                    blob_uri, title, summary, citations_json,
                    created_at, completed_at, error_message, filled_values)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    meta.id, meta.thread_id, meta.run_id, meta.mode, meta.kind,
                    meta.status, meta.blob_uri, meta.title, meta.summary,
                    meta.citations_json,
                    meta.created_at, meta.completed_at, meta.error_message,
                    field_crypto.encrypt_text(meta.filled_values),
                ),
            )
        return meta.id

    def update_status(
        self,
        report_id: str,
        *,
        status: str,
        blob_uri: Optional[str] = None,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        citations: Optional[list] = None,
        error_message: Optional[str] = None,
    ) -> None:
        completed_at = _utcnow_iso() if status in ("done", "error") else None
        citations_json = json.dumps(citations, ensure_ascii=False) if citations is not None else None
        with self._lock, self._conn() as c:
            c.execute(
                """UPDATE reports SET
                     status = ?,
                     blob_uri = COALESCE(?, blob_uri),
                     title = COALESCE(?, title),
                     summary = COALESCE(?, summary),
                     citations_json = COALESCE(?, citations_json),
                     completed_at = COALESCE(?, completed_at),
                     error_message = COALESCE(?, error_message)
                   WHERE id = ?""",
                (status, blob_uri, title, summary, citations_json,
                 completed_at, error_message, report_id),
            )

    def clear_blob_uri(self, report_id: str) -> None:
        """보존정책으로 blob 삭제 후 호출 — 메타는 남기고 uri 만 비움(다운로드 409)."""
        with self._lock, self._conn() as c:
            c.execute("UPDATE reports SET blob_uri = NULL WHERE id = ?", (report_id,))

    def delete(self, report_id: str) -> bool:
        """사용자 요청 삭제(2026-08-27) — 행 자체를 지운다. 반환: 존재했는가."""
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            return cur.rowcount > 0

    def list_expired(self, cutoff_iso: str, *, limit: int) -> list[ReportMeta]:
        """보존기간 만료 보고서(`created_at` < cutoff) — 작성한 서식(kind=doc)은 제외
        (서식 수명은 대화 cascade·보관이 정한다). 보존정리(`prune_blobs`) 전용."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM reports WHERE kind != 'doc' AND created_at < ? "
                "ORDER BY created_at LIMIT ?", (cutoff_iso, int(limit))).fetchall()
        return [_row_to_meta(r) for r in rows]

    def set_kind(self, report_id: str, kind: str) -> None:
        """레거시 종별 교정(final→doc 마이그레이션) 전용."""
        with self._lock, self._conn() as c:
            c.execute("UPDATE reports SET kind = ? WHERE id = ?",
                      (kind, report_id))

    def set_kept(self, report_id: str, kept: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE reports SET kept = ? WHERE id = ?",
                      (1 if kept else 0, report_id))

    def set_alias(self, report_id: str, alias: Optional[str]) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE reports SET alias = ? WHERE id = ?",
                      ((alias or None), report_id))

    def merge_filled_values(self, report_id, values):
        """읽기-병합-쓰기(락 하에) — 기존 값 위에 새 값 얹기. 병합본 반환."""
        import json as _json
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT filled_values FROM reports WHERE id=?", (report_id,)
            ).fetchone()
            if row is None:
                return {}
            try:
                cur = _json.loads(
                    field_crypto.decrypt_text(row["filled_values"]) or "{}")
            except (ValueError, TypeError):
                cur = {}
            cur.update({k: v for k, v in (values or {}).items() if v})
            # 저장은 항상 암호문(field_crypto) — 레거시 평문 행도 여기서 승격.
            c.execute("UPDATE reports SET filled_values=? WHERE id=?",
                      (field_crypto.encrypt_text(
                          _json.dumps(cur, ensure_ascii=False)), report_id))
        return cur

    def get(self, report_id: str) -> Optional[ReportMeta]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return _row_to_meta(row) if row else None

    def list_for_thread(
        self,
        thread_id: str,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[ReportMeta]:
        clauses = ["thread_id = ?"]
        params: list = [thread_id]
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        sql = (
            f"SELECT * FROM reports WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self._lock, self._conn() as c:
            rows = c.execute(sql, tuple(params)).fetchall()
        return [_row_to_meta(r) for r in rows]


def _row_opt(row, col: str):
    try:
        return row[col]
    except (IndexError, KeyError):
        return None


def _row_kept(row) -> bool:
    try:
        return bool(row["kept"])
    except (IndexError, KeyError):
        return False


def _row_to_meta(row) -> ReportMeta:
    # summary 컬럼이 ALTER 전 DB에서 누락 가능 — sqlite3.Row는 KeyError 던짐
    try:
        summary = row["summary"]
    except (IndexError, KeyError):
        summary = None
    try:
        filled_values = field_crypto.decrypt_text(row["filled_values"])
    except (IndexError, KeyError):
        filled_values = None
    return ReportMeta(
        id=row["id"],
        thread_id=row["thread_id"],
        run_id=row["run_id"],
        mode=row["mode"],
        kind=row["kind"],
        status=row["status"],
        blob_uri=row["blob_uri"],
        title=row["title"],
        summary=summary,
        citations_json=row["citations_json"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        error_message=row["error_message"],
        filled_values=filled_values,
        kept=_row_kept(row),
        alias=_row_opt(row, "alias"),
    )


class PostgresReportsRepo:
    """Postgres 본체 구현."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def create(self, meta: ReportMeta) -> str:
        from . import _pg
        if not meta.id:
            meta.id = _new_id()
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """
                INSERT INTO reports
                  (id, thread_id, run_id, mode, kind, status, blob_uri, title,
                   summary, citations_json, created_at, completed_at, error_message,
                   filled_values)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                """,
                (meta.id, meta.thread_id, meta.run_id, meta.mode, meta.kind,
                 meta.status, meta.blob_uri, meta.title, meta.summary,
                 meta.citations_json,
                 _pg._iso_to_dt(meta.created_at),
                 _pg._iso_to_dt(meta.completed_at),
                 meta.error_message,
                 field_crypto.encrypt_text(meta.filled_values)),
            )
        return meta.id

    def update_status(
        self, report_id: str, *,
        status: str,
        blob_uri: Optional[str] = None,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        citations: Optional[list] = None,
        error_message: Optional[str] = None,
    ) -> None:
        from . import _pg
        completed_at = _utcnow_iso() if status in ("done", "error") else None
        citations_json = json.dumps(citations, ensure_ascii=False) if citations is not None else None
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """
                UPDATE reports SET
                  status         = %s,
                  blob_uri       = COALESCE(%s, blob_uri),
                  title          = COALESCE(%s, title),
                  summary        = COALESCE(%s, summary),
                  citations_json = COALESCE(%s::jsonb, citations_json),
                  completed_at   = COALESCE(%s, completed_at),
                  error_message  = COALESCE(%s, error_message)
                WHERE id = %s
                """,
                (status, blob_uri, title, summary, citations_json,
                 _pg._iso_to_dt(completed_at), error_message, report_id),
            )

    def clear_blob_uri(self, report_id: str) -> None:
        """보존정책으로 blob 삭제 후 호출 — 메타는 남기고 uri 만 비움(다운로드 409)."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE reports SET blob_uri = NULL WHERE id = %s", (report_id,))

    def delete(self, report_id: str) -> bool:
        """사용자 요청 삭제(2026-08-27) — 행 자체를 지운다. 반환: 존재했는가."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("DELETE FROM reports WHERE id = %s", (report_id,))
            return cur.rowcount > 0

    def list_expired(self, cutoff_iso: str, *, limit: int) -> list[ReportMeta]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM reports WHERE kind <> 'doc' AND created_at < %s "
                "ORDER BY created_at LIMIT %s",
                (_pg._iso_to_dt(cutoff_iso), int(limit)))
            rows = cur.fetchall()
        return [_pg_row_to_meta(r) for r in rows]

    def set_kind(self, report_id: str, kind: str) -> None:
        """레거시 종별 교정(final→doc 마이그레이션) 전용."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE reports SET kind = %s WHERE id = %s",
                        (kind, report_id))

    def set_kept(self, report_id: str, kept: bool) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE reports SET kept = %s WHERE id = %s",
                        (bool(kept), report_id))

    def set_alias(self, report_id: str, alias: Optional[str]) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE reports SET alias = %s WHERE id = %s",
                        ((alias or None), report_id))

    def merge_filled_values(self, report_id, values):
        """트랜잭션 내 읽기-병합-쓰기(row lock) — 병합본 반환."""
        import json as _json
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT filled_values FROM reports WHERE id=%s FOR UPDATE",
                (report_id,))
            row = cur.fetchone()
            if row is None:
                return {}
            try:
                merged = _json.loads(
                    field_crypto.decrypt_text(row.get("filled_values")) or "{}")
            except (ValueError, TypeError):
                merged = {}
            merged.update({k: v for k, v in (values or {}).items() if v})
            cur.execute("UPDATE reports SET filled_values=%s WHERE id=%s",
                        (field_crypto.encrypt_text(
                            _json.dumps(merged, ensure_ascii=False)), report_id))
        return merged

    def get(self, report_id: str) -> Optional[ReportMeta]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT * FROM reports WHERE id = %s", (report_id,))
            row = cur.fetchone()
        return _pg_row_to_meta(row) if row else None

    def list_for_thread(
        self,
        thread_id: str,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[ReportMeta]:
        from . import _pg
        clauses = ["thread_id = %s"]
        params: list = [thread_id]
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        sql = (
            f"SELECT * FROM reports WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [_pg_row_to_meta(r) for r in rows]


def _pg_row_to_meta(row) -> ReportMeta:
    from . import _pg
    citations = row["citations_json"]
    citations_str = json.dumps(citations, ensure_ascii=False) if citations is not None else None
    return ReportMeta(
        id=row["id"],
        thread_id=row["thread_id"],
        run_id=row["run_id"],
        mode=row["mode"],
        kind=row["kind"],
        status=row["status"],
        blob_uri=row["blob_uri"],
        title=row["title"],
        summary=row.get("summary"),
        citations_json=citations_str,
        created_at=_pg._dt_to_iso(row["created_at"]),
        completed_at=_pg._dt_to_iso(row["completed_at"]),
        error_message=row["error_message"],
        filled_values=field_crypto.decrypt_text(row.get("filled_values")),
        kept=bool(row.get("kept")),
        alias=row.get("alias"),
    )
