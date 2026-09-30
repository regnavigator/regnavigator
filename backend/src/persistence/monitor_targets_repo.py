"""MonitorTargetsRepo — 고객사별 규제 모니터링 배송 설정.

로펌이 고객사(=`bookmarks.folder`)별로 관심 법령을 모아 두면, 그 폴더의 개정·폐지를
주기적으로 감지해 지정 수신자에게 리포트를 보낸다. **북마크 구조는 건드리지 않고**
폴더별 "배송 설정"만 이 테이블이 갖는다(2026-10-01).

UNIQUE(user_id, folder) — 한 담당자가 같은 고객사에 대해 설정을 둘 이상 두지 않는다.

dev = SQLite, prod = Postgres.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso

CADENCES = ("weekly", "monthly")

_EMAIL_RE = re.compile(r"^[^@\s]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def parse_recipients(raw) -> list[str]:
    """쉼표/줄바꿈 구분 문자열 또는 리스트 → 유효 이메일만, 순서 보존 dedup."""
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else re.split(r"[,\n;]+", str(raw))
    out, seen = [], set()
    for x in items:
        addr = str(x).strip()
        if not addr or addr in seen or not _EMAIL_RE.match(addr):
            continue
        seen.add(addr)
        out.append(addr)
    return out


@dataclass
class MonitorTarget:
    id: str
    user_id: str                     # 담당 변호사
    folder: str                      # bookmarks.folder 와 같은 값 = 고객사
    recipients: str                  # 쉼표 구분 이메일
    label: Optional[str] = None      # 고객사 표시명 (없으면 folder)
    cadence: str = "weekly"          # weekly | monthly
    send_weekday: int = 0            # 0=월 … 6=일 (weekly 전용)
    send_hour: int = 9               # KST
    enabled: int = 1
    last_sent_at: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["recipients"] = parse_recipients(self.recipients)
        d["enabled"] = bool(self.enabled)
        d["display_name"] = self.label or self.folder
        return d


class MonitorTargetsRepo(Protocol):
    def upsert(self, t: MonitorTarget) -> str: ...
    def get(self, user_id: str, target_id: str) -> Optional[MonitorTarget]: ...
    def list_for_user(self, user_id: str) -> list[MonitorTarget]: ...
    def list_enabled(self) -> list[MonitorTarget]: ...
    def delete(self, user_id: str, target_id: str) -> None: ...
    def mark_sent(self, target_id: str, at: Optional[str] = None) -> None: ...


_COLS = ("id", "user_id", "folder", "label", "recipients", "cadence",
         "send_weekday", "send_hour", "enabled", "last_sent_at", "created_at")

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS monitor_targets (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL,
  folder        TEXT NOT NULL,
  label         TEXT,
  recipients    TEXT NOT NULL,
  cadence       TEXT NOT NULL DEFAULT 'weekly',
  send_weekday  INTEGER NOT NULL DEFAULT 0,
  send_hour     INTEGER NOT NULL DEFAULT 9,
  enabled       INTEGER NOT NULL DEFAULT 1,
  last_sent_at  TEXT,
  created_at    TEXT NOT NULL,
  UNIQUE(user_id, folder)
);
CREATE INDEX IF NOT EXISTS idx_monitor_targets_user
  ON monitor_targets(user_id, created_at DESC);
"""


def _row_to_target(row) -> MonitorTarget:
    g = (lambda k: row[k]) if hasattr(row, "keys") else (lambda k: row[k])
    return MonitorTarget(**{c: g(c) for c in _COLS})


class SqliteMonitorTargetsRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def upsert(self, t: MonitorTarget) -> str:
        if not t.id:
            t.id = _new_id()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id FROM monitor_targets WHERE user_id = ? AND folder = ?",
                (t.user_id, t.folder),
            ).fetchone()
            if row:
                t.id = row["id"]
                c.execute(
                    """UPDATE monitor_targets SET label = ?, recipients = ?, cadence = ?,
                       send_weekday = ?, send_hour = ?, enabled = ? WHERE id = ?""",
                    (t.label, t.recipients, t.cadence, t.send_weekday,
                     t.send_hour, t.enabled, t.id),
                )
            else:
                c.execute(
                    f"INSERT INTO monitor_targets ({','.join(_COLS)}) "
                    f"VALUES ({','.join('?' * len(_COLS))})",
                    tuple(getattr(t, c_) for c_ in _COLS),
                )
        return t.id

    def get(self, user_id: str, target_id: str) -> Optional[MonitorTarget]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM monitor_targets WHERE id = ? AND user_id = ?",
                (target_id, user_id),
            ).fetchone()
        return _row_to_target(row) if row else None

    def list_for_user(self, user_id: str) -> list[MonitorTarget]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM monitor_targets WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [_row_to_target(r) for r in rows]

    def list_enabled(self) -> list[MonitorTarget]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM monitor_targets WHERE enabled = 1 ORDER BY created_at"
            ).fetchall()
        return [_row_to_target(r) for r in rows]

    def delete(self, user_id: str, target_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM monitor_targets WHERE id = ? AND user_id = ?",
                      (target_id, user_id))

    def mark_sent(self, target_id: str, at: Optional[str] = None) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE monitor_targets SET last_sent_at = ? WHERE id = ?",
                      (at or _utcnow_iso(), target_id))


class PostgresMonitorTargetsRepo:
    """Postgres 본체 구현 — Sqlite 와 동일 인터페이스."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg

        _pg.init_schema(dsn)

    def upsert(self, t: MonitorTarget) -> str:
        from . import _pg

        if not t.id:
            t.id = _new_id()
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """
                INSERT INTO monitor_targets
                  (id, user_id, folder, label, recipients, cadence,
                   send_weekday, send_hour, enabled, last_sent_at, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (user_id, folder) DO UPDATE SET
                  label = EXCLUDED.label, recipients = EXCLUDED.recipients,
                  cadence = EXCLUDED.cadence, send_weekday = EXCLUDED.send_weekday,
                  send_hour = EXCLUDED.send_hour, enabled = EXCLUDED.enabled
                RETURNING id
                """,
                (t.id, t.user_id, t.folder, t.label, t.recipients, t.cadence,
                 t.send_weekday, t.send_hour, t.enabled,
                 _pg._iso_to_dt(t.last_sent_at) if t.last_sent_at else None,
                 _pg._iso_to_dt(t.created_at)),
            )
            row = cur.fetchone()
        return row["id"] if row else t.id

    def _one(self, sql: str, args: tuple):
        from . import _pg

        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(sql, args)
            row = cur.fetchone()
        return _pg_row(row) if row else None

    def _many(self, sql: str, args: tuple):
        from . import _pg

        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        return [_pg_row(r) for r in rows]

    def get(self, user_id: str, target_id: str) -> Optional[MonitorTarget]:
        return self._one(
            "SELECT * FROM monitor_targets WHERE id = %s AND user_id = %s",
            (target_id, user_id))

    def list_for_user(self, user_id: str) -> list[MonitorTarget]:
        return self._many(
            "SELECT * FROM monitor_targets WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,))

    def list_enabled(self) -> list[MonitorTarget]:
        return self._many(
            "SELECT * FROM monitor_targets WHERE enabled = 1 ORDER BY created_at", ())

    def delete(self, user_id: str, target_id: str) -> None:
        from . import _pg

        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("DELETE FROM monitor_targets WHERE id = %s AND user_id = %s",
                        (target_id, user_id))

    def mark_sent(self, target_id: str, at: Optional[str] = None) -> None:
        from . import _pg

        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE monitor_targets SET last_sent_at = %s WHERE id = %s",
                        (_pg._iso_to_dt(at or _utcnow_iso()), target_id))


def _pg_row(row) -> MonitorTarget:
    def iso(v):
        return v.isoformat(timespec="seconds") if hasattr(v, "isoformat") else v

    return MonitorTarget(
        id=row["id"], user_id=row["user_id"], folder=row["folder"],
        label=row["label"], recipients=row["recipients"], cadence=row["cadence"],
        send_weekday=row["send_weekday"], send_hour=row["send_hour"],
        enabled=int(row["enabled"]), last_sent_at=iso(row["last_sent_at"]),
        created_at=iso(row["created_at"]),
    )
