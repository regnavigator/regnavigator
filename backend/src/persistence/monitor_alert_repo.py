"""MonitorAlertRepo — 감지된 규제 변경의 **적재** (2026-10-02).

종전 개정 감지는 조회형이었다. 화면을 떠나면 사라지고, 다음에 열면 같은 변경을
또 보여 준다. 적재해야 ①"알람만 모아 보기"가 가능하고 ②같은 변경을 두 번
알리지 않는다.

`UNIQUE(thread_id, article_key, kind, detected_at)` — 같은 날 같은 종류의 변경은
한 번만. 날짜가 바뀌면 새 알람이다(재개정은 실제로 새 사건이다).

**DB 가 죽어 있을 때는 알람을 만들지 않는다**(호출자 책임). "변경 없음"과
"확인 못 함"을 구분하는 기존 규율과 같다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso

#: 변경 종류 — amendments.detect 의 판정과 1:1
ALERT_KINDS = ("repealed", "pending", "amended", "effective_date")


@dataclass
class Alert:
    id: str
    thread_id: str
    article_key: str
    kind: str
    summary: str
    payload_json: str = "{}"
    detected_at: str = field(default_factory=_utcnow_iso)
    read_at: Optional[str] = None
    dismissed_at: Optional[str] = None

    def as_dict(self) -> dict:
        d = asdict(self)
        try:
            d["payload"] = json.loads(self.payload_json)
        except ValueError:
            d["payload"] = {}
        d.pop("payload_json", None)
        d["unread"] = self.read_at is None
        return d


class MonitorAlertRepo(Protocol):
    def add(self, a: Alert) -> Optional[str]: ...
    def list_for_user(self, thread_ids: list[str], *, unread_only: bool = False,
                      kind: Optional[str] = None, limit: int = 100) -> list[Alert]: ...
    def list_for_thread(self, thread_id: str, *, since: Optional[str] = None,
                        limit: int = 200) -> list[Alert]: ...
    def unread_counts(self, thread_ids: list[str]) -> dict[str, int]: ...
    def mark_read(self, alert_id: str) -> bool: ...
    def dismiss(self, alert_id: str) -> bool: ...
    def mark_thread_read(self, thread_id: str) -> int: ...
    def delete_thread(self, thread_id: str) -> int: ...
    def summary_for_threads(self, thread_ids: list[str]) -> dict[str, dict]: ...


_COLS = ("id", "thread_id", "article_key", "kind", "summary", "payload_json",
         "detected_at", "read_at", "dismissed_at")

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS monitor_alert (
  id           TEXT PRIMARY KEY,
  thread_id    TEXT NOT NULL,
  article_key  TEXT NOT NULL,
  kind         TEXT NOT NULL,
  summary      TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  detected_at  TEXT NOT NULL,
  read_at      TEXT,
  dismissed_at TEXT,
  UNIQUE(thread_id, article_key, kind, detected_at)
);
CREATE INDEX IF NOT EXISTS idx_monitor_alert_thread
  ON monitor_alert(thread_id, detected_at DESC);
"""


def _row(r) -> Alert:
    return Alert(**{c: r[c] for c in _COLS})


class SqliteMonitorAlertRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def add(self, a: Alert) -> Optional[str]:
        """새 알람이면 id, 이미 있으면 None — 호출자가 '새로 감지된 수'를 센다."""
        if not a.id:
            a.id = _new_id()
        with self._lock, self._conn() as c:
            dup = c.execute(
                "SELECT id FROM monitor_alert WHERE thread_id = ? AND article_key = ? "
                "AND kind = ? AND detected_at = ?",
                (a.thread_id, a.article_key, a.kind, a.detected_at),
            ).fetchone()
            if dup:
                return None
            c.execute(
                f"INSERT INTO monitor_alert ({','.join(_COLS)}) "
                f"VALUES ({','.join('?' * len(_COLS))})",
                tuple(getattr(a, k) for k in _COLS),
            )
        return a.id

    def list_for_user(self, thread_ids, *, unread_only=False, kind=None,
                      limit=100) -> list[Alert]:
        if not thread_ids:
            return []
        ph = ",".join("?" * len(thread_ids))
        q = (f"SELECT * FROM monitor_alert WHERE thread_id IN ({ph}) "
             "AND dismissed_at IS NULL")
        args = list(thread_ids)
        if unread_only:
            q += " AND read_at IS NULL"
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        q += " ORDER BY detected_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock, self._conn() as c:
            return [_row(r) for r in c.execute(q, tuple(args)).fetchall()]

    def list_for_thread(self, thread_id, *, since=None, limit=200) -> list[Alert]:
        q = "SELECT * FROM monitor_alert WHERE thread_id = ? AND dismissed_at IS NULL"
        args: list = [thread_id]
        if since:
            q += " AND detected_at >= ?"
            args.append(since)
        q += " ORDER BY detected_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock, self._conn() as c:
            return [_row(r) for r in c.execute(q, tuple(args)).fetchall()]

    def unread_counts(self, thread_ids) -> dict[str, int]:
        if not thread_ids:
            return {}
        ph = ",".join("?" * len(thread_ids))
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT thread_id, COUNT(*) n FROM monitor_alert "
                f"WHERE thread_id IN ({ph}) AND read_at IS NULL "
                f"AND dismissed_at IS NULL GROUP BY thread_id",
                tuple(thread_ids),
            ).fetchall()
        return {r["thread_id"]: int(r["n"]) for r in rows}

    def summary_for_threads(self, thread_ids) -> dict[str, dict]:
        """대시보드 카드 재료(2026-10-06) — 스레드별 **미해제** 알람 집계. N+1 금지(GROUP BY 2회).

        반환: {tid: {"changed_count", "unread_alerts", "kinds": {kind: n},
                     "latest_alert": {"summary","kind","detected_at"} | None,
                     "last_alert_at": str | None}}
        """
        if not thread_ids:
            return {}
        ph = ",".join("?" * len(thread_ids))
        out: dict[str, dict] = {
            t: {"changed_count": 0, "unread_alerts": 0, "kinds": {},
                "latest_alert": None, "last_alert_at": None} for t in thread_ids}
        with self._lock, self._conn() as c:
            for r in c.execute(
                f"SELECT thread_id, kind, COUNT(*) n, SUM(CASE WHEN read_at IS NULL THEN 1 ELSE 0 END) u "
                f"FROM monitor_alert WHERE thread_id IN ({ph}) AND dismissed_at IS NULL "
                f"GROUP BY thread_id, kind", tuple(thread_ids)).fetchall():
                d = out[r["thread_id"]]
                d["changed_count"] += int(r["n"]); d["unread_alerts"] += int(r["u"] or 0)
                d["kinds"][r["kind"]] = int(r["n"])
            # 최신 1건 — 스레드별 MAX(detected_at) 행. 같은 날 여러 건이면 아무거나(요약 1줄 용도).
            for r in c.execute(
                f"SELECT a.thread_id, a.summary, a.kind, a.detected_at FROM monitor_alert a "
                f"JOIN (SELECT thread_id, MAX(detected_at) m FROM monitor_alert "
                f"      WHERE thread_id IN ({ph}) AND dismissed_at IS NULL GROUP BY thread_id) x "
                f"ON a.thread_id = x.thread_id AND a.detected_at = x.m "
                f"WHERE a.dismissed_at IS NULL", tuple(thread_ids)).fetchall():
                d = out[r["thread_id"]]
                if d["latest_alert"] is None:
                    d["latest_alert"] = {"summary": r["summary"], "kind": r["kind"],
                                         "detected_at": r["detected_at"]}
                    d["last_alert_at"] = r["detected_at"]
        return out

    def _stamp(self, alert_id: str, col: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                f"UPDATE monitor_alert SET {col} = ? WHERE id = ? AND {col} IS NULL",
                (_utcnow_iso(), alert_id))
            return cur.rowcount > 0

    def mark_read(self, alert_id: str) -> bool:
        return self._stamp(alert_id, "read_at")

    def dismiss(self, alert_id: str) -> bool:
        return self._stamp(alert_id, "dismissed_at")

    def mark_thread_read(self, thread_id: str) -> int:
        with self._lock, self._conn() as c:
            return c.execute(
                "UPDATE monitor_alert SET read_at = ? "
                "WHERE thread_id = ? AND read_at IS NULL",
                (_utcnow_iso(), thread_id)).rowcount

    def delete_thread(self, thread_id: str) -> int:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM monitor_alert WHERE thread_id = ?",
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


class PostgresMonitorAlertRepo(_PgRepoBase, SqliteMonitorAlertRepo):
    """Postgres 구현 — SQLite 본체를 그대로 쓰고 커서만 PG 로 바꾼다."""
