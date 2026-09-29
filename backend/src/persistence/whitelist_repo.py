"""클로즈 베타 화이트리스트 repo — admin 화면에서 관리 (env 는 부트스트랩).

항목: 소문자 이메일(`a@b.com`) 또는 도메인(`@company.com`). 유효 검사는
라우트(admin)에서. `AuthMiddleware._beta_allowed` 가 env ∪ DB 합집합으로
게이트한다(짧은 TTL 캐시 — 변경은 admin 라우트가 invalidate).

초대 발송 이력(`invited_at`·`invited_by`, 2026-08-05): 초대는 등록과 분리된
**수동 1건 발송**이다. 누구에게 이미 보냈는지를 DB 가 알아야 관리자가 중복
발송하거나 빠뜨리지 않는다 — 화면의 "미발송/발송완료" 구분이 이 값에 얹힌다.
"""

from __future__ import annotations

import threading
from typing import Optional

from ._common import SqliteRepoBase, utcnow_iso


class SqliteWhitelistRepo(SqliteRepoBase):
    _schema = """
    CREATE TABLE IF NOT EXISTS beta_whitelist (
        entry      TEXT PRIMARY KEY,
        added_by   TEXT,
        created_at TEXT NOT NULL,
        invited_at TEXT,
        invited_by TEXT
    );
    """

    def _post_init(self, conn) -> None:
        # 기존 DB 에 초대 이력 컬럼 없으면 ADD (2026-08-05).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(beta_whitelist)").fetchall()}
        for col in ("invited_at", "invited_by"):
            if col not in cols:
                conn.execute(f"ALTER TABLE beta_whitelist ADD COLUMN {col} TEXT")

    def list(self) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT entry, added_by, created_at, invited_at, invited_by "
                "FROM beta_whitelist ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def entries(self) -> set[str]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT entry FROM beta_whitelist").fetchall()
        return {r["entry"] for r in rows}

    def add(self, entry: str, *, added_by: Optional[str] = None) -> bool:
        """신규 삽입이면 True, 이미 있어 무시됐으면 False.

        반환값이 없으면 호출자가 '이미 있던 항목'을 신규로 집계한다 —
        벌크 100건 붙여넣기에 "100건 추가"라고 답하던 문제(2026-08-01).
        """
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO beta_whitelist (entry, added_by, created_at) "
                "VALUES (?, ?, ?) ON CONFLICT(entry) DO NOTHING",
                (entry.strip().lower(), added_by, utcnow_iso()),
            )
            return cur.rowcount > 0

    def mark_invited(self, entry: str, *, invited_by: Optional[str] = None,
                     at: Optional[str] = None) -> bool:
        """초대 발송 성공 시각 기록. 항목이 없으면 False.

        `at` — 과거 공지 이력 이관용(ISO). 미지정이면 지금. 화면이 발송일을
        보여주므로, 이관한 건에 오늘 날짜를 찍으면 화면이 거짓을 말한다.
        """
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE beta_whitelist SET invited_at = ?, invited_by = ? "
                "WHERE entry = ?",
                (at or utcnow_iso(), invited_by, entry.strip().lower()),
            )
            return cur.rowcount > 0

    def get(self, entry: str) -> Optional[dict]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT entry, added_by, created_at, invited_at, invited_by "
                "FROM beta_whitelist WHERE entry = ?",
                (entry.strip().lower(),),
            ).fetchone()
        return dict(row) if row else None

    def remove(self, entry: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM beta_whitelist WHERE entry = ?",
                (entry.strip().lower(),),
            )
            return cur.rowcount > 0


class PostgresWhitelistRepo:
    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def list(self) -> list[dict]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT entry, added_by, created_at, invited_at, invited_by "
                "FROM beta_whitelist ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            r = dict(r)
            r["created_at"] = _pg._dt_to_iso(r["created_at"])
            r["invited_at"] = (_pg._dt_to_iso(r["invited_at"])
                               if r.get("invited_at") else None)
            out.append(r)
        return out

    def entries(self) -> set[str]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT entry FROM beta_whitelist")
            return {r["entry"] for r in cur.fetchall()}

    def add(self, entry: str, *, added_by: Optional[str] = None) -> bool:
        """신규 삽입이면 True, 이미 있어 무시됐으면 False(SQLite 판과 동일 계약)."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "INSERT INTO beta_whitelist (entry, added_by) VALUES (%s, %s) "
                "ON CONFLICT (entry) DO NOTHING",
                (entry.strip().lower(), added_by),
            )
            return cur.rowcount > 0

    def mark_invited(self, entry: str, *, invited_by: Optional[str] = None,
                     at: Optional[str] = None) -> bool:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE beta_whitelist "
                "SET invited_at = COALESCE(%s::timestamptz, NOW()), invited_by = %s "
                "WHERE entry = %s",
                (at, invited_by, entry.strip().lower()),
            )
            return cur.rowcount > 0

    def get(self, entry: str) -> Optional[dict]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT entry, added_by, created_at, invited_at, invited_by "
                "FROM beta_whitelist WHERE entry = %s",
                (entry.strip().lower(),),
            )
            row = cur.fetchone()
        if not row:
            return None
        r = dict(row)
        r["created_at"] = _pg._dt_to_iso(r["created_at"])
        r["invited_at"] = _pg._dt_to_iso(r["invited_at"]) if r.get("invited_at") else None
        return r

    def remove(self, entry: str) -> bool:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "DELETE FROM beta_whitelist WHERE entry = %s",
                (entry.strip().lower(),),
            )
            return cur.rowcount > 0


_repo_lock = threading.Lock()
_repo = None


def get_whitelist_repo():
    global _repo
    with _repo_lock:
        if _repo is not None:
            return _repo
        import os

        backend = (os.getenv("REPORTS_BACKEND") or "sqlite").lower()
        if backend == "postgres":
            _repo = PostgresWhitelistRepo(dsn=os.environ["REPORTS_PG_DSN"])
        elif backend == "sqlite":
            path = os.getenv("REPORTS_SQLITE_PATH") or "./medi_reports.db"
            _repo = SqliteWhitelistRepo(path=path)
        else:
            raise ValueError(f"Unknown REPORTS_BACKEND: {backend!r}")
        return _repo


def reset_whitelist_repo_cache() -> None:
    """테스트 전용 — 팩토리 캐시 리셋."""
    global _repo
    with _repo_lock:
        _repo = None
