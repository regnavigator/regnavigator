"""MonitorWatchRepo — 모니터링 스레드의 **관찰 조문** (2026-10-02).

종전엔 `bookmarks.folder` 가 관찰 단위였다. 그러면 조문을 **이미 알고 있어야**
관찰이 시작되는데, 그 조문을 찾는 것이 이 도구의 본업이다. 그래서 관찰 단위를
스레드로 옮기고(설계: `docs/spec/monitor-threads-design.md`) 그 스레드가 무엇을
보고 있는지를 이 테이블이 갖는다.

`citation_json` 을 통째로 들고 있는 이유: `amendments.detect_with_status()` 가
북마크 모양 객체를 받는다. 같은 모양이면 개정 판정기를 **그대로** 재사용할 수
있고 조문 메타를 다시 조회하지 않아도 된다.

제거는 soft delete(`removed_at`) — 왜 뺐는지가 기록으로 남아야 한다. 같은 조문을
뺐다 넣었다 하는 일이 실제로 생긴다.

dev = SQLite, prod = Postgres.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso

#: 누가 넣었나 — 'ai'(대화 제안 승인) | 'user'(직접) | 'file'(첨부에서 추출)
ADDED_BY = ("ai", "user", "file")


@dataclass
class WatchItem:
    id: str
    thread_id: str
    article_key: str
    citation_json: str
    added_by: str = "user"
    reason: Optional[str] = None
    added_at: str = field(default_factory=_utcnow_iso)
    removed_at: Optional[str] = None

    def citation(self) -> dict:
        try:
            d = json.loads(self.citation_json)
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("citation_json", None)
        d["citation"] = self.citation()
        d["title"] = d["citation"].get("title") or self.article_key
        return d


class MonitorWatchRepo(Protocol):
    def add(self, item: WatchItem) -> str: ...
    def remove(self, thread_id: str, article_key: str) -> bool: ...
    def list_for_thread(self, thread_id: str,
                        include_removed: bool = False) -> list[WatchItem]: ...
    def list_all_active(self) -> list[WatchItem]: ...
    def count_for_thread(self, thread_id: str) -> int: ...
    def delete_thread(self, thread_id: str) -> int: ...


_COLS = ("id", "thread_id", "article_key", "citation_json", "added_by",
         "reason", "added_at", "removed_at")

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS monitor_watch (
  id            TEXT PRIMARY KEY,
  thread_id     TEXT NOT NULL,
  article_key   TEXT NOT NULL,
  citation_json TEXT NOT NULL,
  added_by      TEXT NOT NULL DEFAULT 'user',
  reason        TEXT,
  added_at      TEXT NOT NULL,
  removed_at    TEXT,
  UNIQUE(thread_id, article_key)
);
CREATE INDEX IF NOT EXISTS idx_monitor_watch_thread
  ON monitor_watch(thread_id, removed_at);
"""


def _row(r) -> WatchItem:
    return WatchItem(**{c: r[c] for c in _COLS})


class SqliteMonitorWatchRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def add(self, item: WatchItem) -> str:
        if not item.id:
            item.id = _new_id()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id FROM monitor_watch WHERE thread_id = ? AND article_key = ?",
                (item.thread_id, item.article_key),
            ).fetchone()
            if row:
                # 다시 넣기 = 되살리기. 메타도 최신으로 갱신한다.
                item.id = row["id"]
                c.execute(
                    "UPDATE monitor_watch SET removed_at = NULL, citation_json = ?, "
                    "added_by = ?, reason = ?, added_at = ? WHERE id = ?",
                    (item.citation_json, item.added_by, item.reason,
                     item.added_at, item.id),
                )
            else:
                c.execute(
                    f"INSERT INTO monitor_watch ({','.join(_COLS)}) "
                    f"VALUES ({','.join('?' * len(_COLS))})",
                    tuple(getattr(item, k) for k in _COLS),
                )
        return item.id

    def remove(self, thread_id: str, article_key: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE monitor_watch SET removed_at = ? "
                "WHERE thread_id = ? AND article_key = ? AND removed_at IS NULL",
                (_utcnow_iso(), thread_id, article_key),
            )
            return cur.rowcount > 0

    def list_for_thread(self, thread_id: str,
                        include_removed: bool = False) -> list[WatchItem]:
        q = "SELECT * FROM monitor_watch WHERE thread_id = ?"
        if not include_removed:
            q += " AND removed_at IS NULL"
        q += " ORDER BY added_at"
        with self._lock, self._conn() as c:
            return [_row(r) for r in c.execute(q, (thread_id,)).fetchall()]

    def list_all_active(self) -> list[WatchItem]:
        with self._lock, self._conn() as c:
            return [_row(r) for r in c.execute(
                "SELECT * FROM monitor_watch WHERE removed_at IS NULL "
                "ORDER BY thread_id, added_at").fetchall()]

    def count_for_thread(self, thread_id: str) -> int:
        with self._lock, self._conn() as c:
            return int(c.execute(
                "SELECT COUNT(*) n FROM monitor_watch "
                "WHERE thread_id = ? AND removed_at IS NULL",
                (thread_id,)).fetchone()["n"])

    def delete_thread(self, thread_id: str) -> int:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM monitor_watch WHERE thread_id = ?",
                             (thread_id,)).rowcount


# ── Postgres ────────────────────────────────────────────────────────────────
#
# SQLite 구현과 **쿼리가 같고 방언만 다르다**(placeholder `?`→`%s`,
# `INSERT OR ...` 없음). 그래서 본체를 복제하지 않고 커서만 바꿔 끼운다 —
# 복제하면 한쪽만 고치는 사고가 난다(이 저장소에서 실제로 겪은 패턴).

class _PgCursorShim:
    """sqlite3 커서처럼 보이게 감싼다 — `?` 를 `%s` 로, row 를 dict 접근으로."""

    def __init__(self, cur):
        self._cur = cur
        self.rowcount = 0

    def execute(self, sql, args=()):
        self._cur.execute(sql.replace("?", "%s"), tuple(args))
        self.rowcount = self._cur.rowcount
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _PgRepoBase:
    """`SqliteRepoBase` 와 같은 `self._lock` / `self._conn()` 계약을 제공한다."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        import threading

        from . import _pg

        self._lock = threading.RLock()
        _pg.init_schema(dsn)
        self._init_extra()

    def _init_extra(self) -> None:
        """PG 스키마는 `_pg.init_schema` 가 만든다 — 여기선 할 일 없음."""

    def _conn(self):
        from contextlib import contextmanager

        from . import _pg

        @contextmanager
        def _cm():
            with _pg.pg_cursor(self.dsn) as cur:
                yield _PgCursorShim(cur)

        return _cm()


class PostgresMonitorWatchRepo(_PgRepoBase, SqliteMonitorWatchRepo):
    """Postgres 구현 — SQLite 본체를 그대로 쓰고 커서만 PG 로 바꾼다."""
