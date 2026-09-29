"""BookmarksRepo — 개인 근거 라이브러리.

RA/QA·컨설턴트가 답변에서 특정 인용(조문·별표/서식·판례)을 프로젝트별로 저장해
반복 재활용하도록. 사용자 스코프, citation payload(JSON)를 통째로 보관해 원 대화가
지워져도 근거는 남는다. UNIQUE(user_id, citation_id)로 같은 근거 중복 방지(토글).

dev = SQLite, prod = Postgres.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso


@dataclass
class Bookmark:
    id: str
    user_id: str
    citation_id: str            # dedup 키 (Citation.id)
    citation_json: str          # Citation payload 전체(JSON 문자열)
    note: Optional[str] = None  # 사용자 메모(프로젝트·용도)
    folder: Optional[str] = None  # 폴더/프로젝트명 (평평한 1단계)
    thread_id: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)

    def as_dict(self) -> dict:
        d = asdict(self)
        # citation 은 파싱해서 객체로 노출(프런트 편의).
        try:
            d["citation"] = json.loads(self.citation_json) if self.citation_json else None
        except (ValueError, TypeError):
            d["citation"] = None
        d.pop("citation_json", None)
        return d


class BookmarksRepo(Protocol):
    def create(self, bm: Bookmark) -> str: ...
    def list_for_user(self, user_id: str, *, limit: int = 200, offset: int = 0) -> list[Bookmark]: ...
    def delete(self, user_id: str, bookmark_id: str) -> None: ...
    def delete_by_citation(self, user_id: str, citation_id: str) -> None: ...
    def set_folder(self, user_id: str, bookmark_id: str, folder: Optional[str]) -> None: ...
    def set_note(self, user_id: str, bookmark_id: str, note: Optional[str]) -> None: ...


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS bookmarks (
  id             TEXT PRIMARY KEY,
  user_id        TEXT NOT NULL,
  citation_id    TEXT NOT NULL,
  citation_json  TEXT NOT NULL,
  note           TEXT,
  folder         TEXT,
  thread_id      TEXT,
  created_at     TEXT NOT NULL,
  UNIQUE(user_id, citation_id)
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id, created_at DESC);
"""


class SqliteBookmarksRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def _post_init(self, conn) -> None:
        try:
            conn.execute("ALTER TABLE bookmarks ADD COLUMN folder TEXT")
        except Exception:
            pass  # 이미 존재

    def create(self, bm: Bookmark) -> str:
        if not bm.id:
            bm.id = _new_id()
        with self._lock, self._conn() as c:
            # 같은 근거 재저장은 무시(멱등) — 기존 id 반환.
            existing = c.execute(
                "SELECT id FROM bookmarks WHERE user_id = ? AND citation_id = ?",
                (bm.user_id, bm.citation_id),
            ).fetchone()
            if existing:
                return existing["id"]
            c.execute(
                """INSERT INTO bookmarks
                   (id, user_id, citation_id, citation_json, note, folder, thread_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (bm.id, bm.user_id, bm.citation_id, bm.citation_json,
                 bm.note, bm.folder, bm.thread_id, bm.created_at),
            )
        return bm.id

    def list_for_user(self, user_id: str, *, limit: int = 200, offset: int = 0) -> list[Bookmark]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM bookmarks WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
        return [_row_to_bookmark(r) for r in rows]

    def delete(self, user_id: str, bookmark_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "DELETE FROM bookmarks WHERE id = ? AND user_id = ?",
                (bookmark_id, user_id),
            )

    def delete_by_citation(self, user_id: str, citation_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "DELETE FROM bookmarks WHERE user_id = ? AND citation_id = ?",
                (user_id, citation_id),
            )

    def set_folder(self, user_id: str, bookmark_id: str, folder: Optional[str]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE bookmarks SET folder = ? WHERE id = ? AND user_id = ?",
                (folder, bookmark_id, user_id),
            )

    def set_note(self, user_id: str, bookmark_id: str, note: Optional[str]) -> None:
        """메모 수정/삭제(None=삭제) — write-once 였던 갭 해소(2026-08-11)."""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE bookmarks SET note = ? WHERE id = ? AND user_id = ?",
                (note, bookmark_id, user_id),
            )


def _row_to_bookmark(row) -> Bookmark:
    return Bookmark(
        id=row["id"],
        user_id=row["user_id"],
        citation_id=row["citation_id"],
        citation_json=row["citation_json"],
        note=row["note"],
        folder=(row["folder"] if "folder" in row.keys() else None),
        thread_id=row["thread_id"],
        created_at=row["created_at"],
    )


class PostgresBookmarksRepo:
    """Postgres 본체 구현 — Sqlite 와 동일 인터페이스."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def create(self, bm: Bookmark) -> str:
        from . import _pg
        if not bm.id:
            bm.id = _new_id()
        with _pg.pg_cursor(self.dsn) as cur:
            # UNIQUE(user_id, citation_id) 충돌 시 무시하고 기존 id 반환(멱등 토글).
            cur.execute(
                """
                INSERT INTO bookmarks
                  (id, user_id, citation_id, citation_json, note, folder, thread_id, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                ON CONFLICT (user_id, citation_id) DO NOTHING
                RETURNING id
                """,
                (bm.id, bm.user_id, bm.citation_id, bm.citation_json,
                 bm.note, bm.folder, bm.thread_id, _pg._iso_to_dt(bm.created_at)),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur.execute(
                "SELECT id FROM bookmarks WHERE user_id = %s AND citation_id = %s",
                (bm.user_id, bm.citation_id),
            )
            existing = cur.fetchone()
        return existing["id"] if existing else bm.id

    def list_for_user(self, user_id: str, *, limit: int = 200, offset: int = 0) -> list[Bookmark]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM bookmarks WHERE user_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (user_id, limit, offset),
            )
            rows = cur.fetchall()
        return [_pg_row_to_bookmark(r) for r in rows]

    def delete(self, user_id: str, bookmark_id: str) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "DELETE FROM bookmarks WHERE id = %s AND user_id = %s",
                (bookmark_id, user_id),
            )

    def delete_by_citation(self, user_id: str, citation_id: str) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "DELETE FROM bookmarks WHERE user_id = %s AND citation_id = %s",
                (user_id, citation_id),
            )

    def set_folder(self, user_id: str, bookmark_id: str, folder: Optional[str]) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE bookmarks SET folder = %s WHERE id = %s AND user_id = %s",
                (folder, bookmark_id, user_id),
            )

    def set_note(self, user_id: str, bookmark_id: str, note: Optional[str]) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE bookmarks SET note = %s WHERE id = %s AND user_id = %s",
                (note, bookmark_id, user_id),
            )


def _pg_row_to_bookmark(row) -> Bookmark:
    from . import _pg
    cj = row["citation_json"]
    if not isinstance(cj, str):
        cj = json.dumps(cj, ensure_ascii=False)  # JSONB → str
    return Bookmark(
        id=row["id"],
        user_id=row["user_id"],
        citation_id=row["citation_id"],
        citation_json=cj,
        note=row["note"],
        folder=row.get("folder"),
        thread_id=row["thread_id"],
        created_at=_pg._dt_to_iso(row["created_at"]),
    )
