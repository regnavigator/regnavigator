"""런타임 앱 설정 KV repo — admin 화면·운영 스크립트가 관리.

env(부팅 시점 고정)와 달리 **재기동 없이** 켜고 끄는 노브용. 첫 사용처는
점검 모드(maintenance) — 값은 JSON 문자열로 저장(구조 자유). 진실원은 DB,
읽기 측(`src/maintenance.py`)은 짧은 TTL 캐시로 매 요청 DB 조회를 피한다.

멀티프로세스 주의(CLAUDE.md §7): 워커는 1개이므로 프로세스 로컬 캐시로 충분.
외부 프로세스(4시 갱신 크론의 `scripts/maintenance.py`)가 DB 를 직접 쓰면
서버 캐시는 TTL 만료 후(≤5s) 반영된다.
"""

from __future__ import annotations

import threading
from typing import Optional

from ._common import SqliteRepoBase, utcnow_iso


class SqliteSettingsRepo(SqliteRepoBase):
    _schema = """
    CREATE TABLE IF NOT EXISTS app_settings (
        key        TEXT PRIMARY KEY,
        value      TEXT,
        updated_by TEXT,
        updated_at TEXT NOT NULL
    );
    """

    def get(self, key: str) -> Optional[str]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: Optional[str], *, updated_by: Optional[str] = None) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO app_settings (key, value, updated_by, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                "value = excluded.value, updated_by = excluded.updated_by, "
                "updated_at = excluded.updated_at",
                (key, value, updated_by, utcnow_iso()),
            )


class PostgresSettingsRepo:
    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def get(self, key: str) -> Optional[str]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        return (dict(row)["value"] if row else None)

    def set(self, key: str, value: Optional[str], *, updated_by: Optional[str] = None) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "INSERT INTO app_settings (key, value, updated_by, updated_at) "
                "VALUES (%s, %s, %s, NOW()) ON CONFLICT (key) DO UPDATE SET "
                "value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                "updated_at = NOW()",
                (key, value, updated_by),
            )


_repo_lock = threading.Lock()
_repo = None


def get_settings_repo():
    global _repo
    with _repo_lock:
        if _repo is not None:
            return _repo
        import os

        backend = (os.getenv("REPORTS_BACKEND") or "sqlite").lower()
        if backend == "postgres":
            _repo = PostgresSettingsRepo(dsn=os.environ["REPORTS_PG_DSN"])
        elif backend == "sqlite":
            path = os.getenv("REPORTS_SQLITE_PATH") or "./medi_reports.db"
            _repo = SqliteSettingsRepo(path=path)
        else:
            raise ValueError(f"Unknown REPORTS_BACKEND: {backend!r}")
        return _repo


def reset_settings_repo_cache() -> None:
    """테스트 전용 — 팩토리 캐시 리셋."""
    global _repo
    with _repo_lock:
        _repo = None
