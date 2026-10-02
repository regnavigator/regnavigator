"""ContactsRepo — 수신자 주소록 (2026-10-02).

종전 수신자는 쉼표 구분 문자열이었다. 보낼 때마다 주소를 다시 타이핑하면 오타가
**그대로 외부로 나간다** — 규제 리포트가 엉뚱한 사람에게 가는 사고다.

`last_used_at` 으로 최근 사용 순 정렬 — 주소록이 커져도 쓰던 사람이 위에 온다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso
from .monitor_targets_repo import parse_recipients


@dataclass
class Contact:
    id: str
    user_id: str
    email: str
    name: Optional[str] = None
    org: Optional[str] = None
    last_used_at: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["display"] = self.name or self.email
        return d


class ContactsRepo(Protocol):
    def upsert(self, c: Contact) -> str: ...
    def search(self, user_id: str, q: str = "", limit: int = 50) -> list[Contact]: ...
    def touch(self, user_id: str, emails: list[str]) -> None: ...
    def delete(self, user_id: str, contact_id: str) -> bool: ...


_COLS = ("id", "user_id", "email", "name", "org", "last_used_at", "created_at")

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS contacts (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL,
  email        TEXT NOT NULL,
  name         TEXT,
  org          TEXT,
  last_used_at TEXT,
  created_at   TEXT NOT NULL,
  UNIQUE(user_id, email)
);
CREATE INDEX IF NOT EXISTS idx_contacts_user
  ON contacts(user_id, last_used_at DESC);
"""


def _row(r) -> Contact:
    return Contact(**{c: r[c] for c in _COLS})


class SqliteContactsRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def upsert(self, ct: Contact) -> str:
        if not parse_recipients(ct.email):
            raise ValueError("유효한 이메일이 아닙니다")
        ct.email = ct.email.strip()
        if not ct.id:
            ct.id = _new_id()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id FROM contacts WHERE user_id = ? AND email = ?",
                (ct.user_id, ct.email)).fetchone()
            if row:
                ct.id = row["id"]
                # 이름·소속은 **덮어쓰지 않는다** — 빈 값으로 지워지면 안 된다.
                c.execute(
                    "UPDATE contacts SET name = COALESCE(?, name), "
                    "org = COALESCE(?, org) WHERE id = ?",
                    (ct.name or None, ct.org or None, ct.id))
            else:
                c.execute(
                    f"INSERT INTO contacts ({','.join(_COLS)}) "
                    f"VALUES ({','.join('?' * len(_COLS))})",
                    tuple(getattr(ct, k) for k in _COLS))
        return ct.id

    def search(self, user_id: str, q: str = "", limit: int = 50) -> list[Contact]:
        sql = "SELECT * FROM contacts WHERE user_id = ?"
        args: list = [user_id]
        t = (q or "").strip()
        if t:
            sql += " AND (email LIKE ? OR COALESCE(name,'') LIKE ? OR COALESCE(org,'') LIKE ?)"
            args += [f"%{t}%"] * 3
        # 최근 사용 → 이름 순. NULL 은 뒤로.
        sql += (" ORDER BY CASE WHEN last_used_at IS NULL THEN 1 ELSE 0 END, "
                "last_used_at DESC, COALESCE(name, email) LIMIT ?")
        args.append(int(limit))
        with self._lock, self._conn() as c:
            return [_row(r) for r in c.execute(sql, tuple(args)).fetchall()]

    def touch(self, user_id: str, emails: list[str]) -> None:
        addrs = parse_recipients(emails)
        if not addrs:
            return
        now = _utcnow_iso()
        with self._lock, self._conn() as c:
            for a in addrs:
                # 처음 보는 주소는 자동 등록 — 보낸 곳은 주소록에 남아야 한다.
                c.execute(
                    "INSERT INTO contacts (id, user_id, email, last_used_at, created_at) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(user_id, email) "
                    "DO UPDATE SET last_used_at = excluded.last_used_at",
                    (_new_id(), user_id, a, now, now))

    def delete(self, user_id: str, contact_id: str) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM contacts WHERE id = ? AND user_id = ?",
                             (contact_id, user_id)).rowcount > 0


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


class PostgresContactsRepo(_PgRepoBase, SqliteContactsRepo):
    """Postgres 구현 — SQLite 본체를 그대로 쓰고 커서만 PG 로 바꾼다."""
