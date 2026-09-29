"""persistence 공통 헬퍼 — SQLite repo 들이 공유하는 보일러플레이트.

5개 repo(`users/feedback/reports/events/report_runs`)가 동일하게 복제하던
시각 포맷·ID 생성·SQLite 커넥션/초기화 로직을 한곳으로 모은다.

- `utcnow_iso()` / `new_id()` : 모든 repo 공용.
- `SqliteRepoBase`           : 생성자·`_conn`·`_init` 골격. 하위 클래스는
  `_schema`(필수)와 선택적 `_extra_pragmas`·`_post_init` 만 지정.

Postgres 측은 SQL 방언 차이가 커서 이 base 를 쓰지 않는다(의도적 보류).
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utcnow_iso() -> str:
    # 고정폭 UTC ISO → SQLite TEXT 비교가 사전식=시간순.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id() -> str:
    return uuid.uuid4().hex


class SqliteRepoBase:
    """SQLite repo 공통 골격.

    하위 클래스 계약:
    - `_schema`        : `executescript` 로 적용할 DDL (필수, 클래스 속성).
    - `_extra_pragmas` : `_conn()` 에서 WAL 다음에 추가로 실행할 PRAGMA 들.
    - `_post_init(c)`  : 스키마 생성 직후 마이그레이션 훅(예: ADD COLUMN).
    """

    _schema: str = ""
    _extra_pragmas: tuple[str, ...] = ()

    def __init__(self, path: str = "./medi_reports.db"):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        # 호출별 연결이 SQLite WAL 환경에서 안전(공유 커넥션 재사용보다).
        c = sqlite3.connect(self.path, isolation_level=None, timeout=10.0)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL;")
        for pragma in self._extra_pragmas:
            c.execute(pragma)
        return c

    def _init(self) -> None:
        with self._lock, self._conn() as c:
            c.executescript(self._schema)
            self._post_init(c)

    def _post_init(self, conn: sqlite3.Connection) -> None:
        """스키마 생성 직후 호출되는 마이그레이션 훅. 기본은 no-op."""
