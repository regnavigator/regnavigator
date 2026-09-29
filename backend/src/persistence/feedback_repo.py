"""FeedbackRepo — 답변·보고서 만족도 평가.

events 테이블에도 동일 쓰기를 emit하지만(분석 일관성), 이 테이블은 1:1 영속·
조회 효율을 위해 별도 보관 (메시지·보고서 단위 thumbs_up/down + comment).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso


@dataclass
class Feedback:
    id: str
    rating: str               # "thumbs_up" | "thumbs_down"
    user_id: Optional[str] = None
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    report_id: Optional[str] = None
    comment: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)

    def as_dict(self) -> dict:
        return asdict(self)


class FeedbackRepo(Protocol):
    def create(self, fb: Feedback) -> str: ...
    def get(self, feedback_id: str) -> Optional[Feedback]: ...
    def list_for_message(self, message_id: str) -> list[Feedback]: ...
    def list_for_thread(self, thread_id: str) -> list[Feedback]: ...
    def list_between(self, *, since: str, until: str) -> list[Feedback]:
        """[since, until) 에 남긴 평가 — 주간 보고서용(오래된 것부터)."""
        ...

    def delete_for_user(self, user_id: str) -> int:
        """정보주체 삭제 요구 이행(scripts/erase_user.py) — 그 사용자의 평가 전부."""
        ...


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS feedback (
  id          TEXT PRIMARY KEY,
  rating      TEXT NOT NULL,
  user_id     TEXT,
  thread_id   TEXT,
  message_id  TEXT,
  report_id   TEXT,
  comment     TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_thread  ON feedback(thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_user    ON feedback(user_id, created_at DESC);
"""


class SqliteFeedbackRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def create(self, fb: Feedback) -> str:
        if not fb.id:
            fb.id = _new_id()
        # 'canceled' = 👍/👎 재클릭 취소(append-only last-wins 계약, API.md §feedback).
        # 라우트는 받는데 repo 가 거부해 500 + 취소 유실이던 배선 오류(2026-08-11 발견).
        if fb.rating not in ("thumbs_up", "thumbs_down", "canceled"):
            raise ValueError(
                f"rating must be 'thumbs_up'|'thumbs_down'|'canceled', got {fb.rating!r}")
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO feedback
                   (id, rating, user_id, thread_id, message_id, report_id, comment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (fb.id, fb.rating, fb.user_id, fb.thread_id, fb.message_id,
                 fb.report_id, fb.comment, fb.created_at),
            )
        return fb.id

    def get(self, feedback_id: str) -> Optional[Feedback]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        return _row_to_feedback(row) if row else None

    def delete_for_user(self, user_id: str) -> int:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM feedback WHERE user_id = ?", (user_id,)).rowcount

    def list_for_message(self, message_id: str) -> list[Feedback]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM feedback WHERE message_id = ? ORDER BY created_at DESC",
                (message_id,),
            ).fetchall()
        return [_row_to_feedback(r) for r in rows]

    def list_for_thread(self, thread_id: str) -> list[Feedback]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM feedback WHERE thread_id = ? ORDER BY created_at DESC",
                (thread_id,),
            ).fetchall()
        return [_row_to_feedback(r) for r in rows]

    def list_between(self, *, since: str, until: str) -> list[Feedback]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM feedback WHERE created_at >= ? AND created_at < ? "
                "ORDER BY created_at", (since, until)).fetchall()
        return [_row_to_feedback(r) for r in rows]


def _row_to_feedback(row) -> Feedback:
    return Feedback(
        id=row["id"],
        rating=row["rating"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        message_id=row["message_id"],
        report_id=row["report_id"],
        comment=row["comment"],
        created_at=row["created_at"],
    )


class PostgresFeedbackRepo:
    """Postgres 본체 구현."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def delete_for_user(self, user_id: str) -> int:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("DELETE FROM feedback WHERE user_id = %s", (user_id,))
            return cur.rowcount

    def create(self, fb: Feedback) -> str:
        from . import _pg
        if not fb.id:
            fb.id = _new_id()
        # 'canceled' 포함 — SQLite 구현과 동일(위 주석 참조).
        if fb.rating not in ("thumbs_up", "thumbs_down", "canceled"):
            raise ValueError(
                f"rating must be 'thumbs_up'|'thumbs_down'|'canceled', got {fb.rating!r}")
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """
                INSERT INTO feedback
                  (id, rating, user_id, thread_id, message_id, report_id, comment, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (fb.id, fb.rating, fb.user_id, fb.thread_id,
                 fb.message_id, fb.report_id, fb.comment,
                 _pg._iso_to_dt(fb.created_at)),
            )
        return fb.id

    def get(self, feedback_id: str) -> Optional[Feedback]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT * FROM feedback WHERE id = %s", (feedback_id,))
            row = cur.fetchone()
        return _pg_row_to_feedback(row) if row else None

    def list_for_message(self, message_id: str) -> list[Feedback]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM feedback WHERE message_id = %s ORDER BY created_at DESC",
                (message_id,),
            )
            rows = cur.fetchall()
        return [_pg_row_to_feedback(r) for r in rows]

    def list_for_thread(self, thread_id: str) -> list[Feedback]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM feedback WHERE thread_id = %s ORDER BY created_at DESC",
                (thread_id,),
            )
            rows = cur.fetchall()
        return [_pg_row_to_feedback(r) for r in rows]

    def list_between(self, *, since: str, until: str) -> list[Feedback]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM feedback WHERE created_at >= %s AND created_at < %s "
                "ORDER BY created_at", (_pg._iso_to_dt(since), _pg._iso_to_dt(until)))
            rows = cur.fetchall()
        return [_pg_row_to_feedback(r) for r in rows]


def _pg_row_to_feedback(row) -> Feedback:
    from . import _pg
    return Feedback(
        id=row["id"],
        rating=row["rating"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        message_id=row["message_id"],
        report_id=row["report_id"],
        comment=row["comment"],
        created_at=_pg._dt_to_iso(row["created_at"]),
    )
