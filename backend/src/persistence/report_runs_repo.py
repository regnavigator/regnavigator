"""ReportRunsRepo — 보고서 파이프라인 멱등성 락.

보고서 트리거(프론트 명시 플래그)는 `idempotency_key` 를 들고 온다. 같은
키로 들어온 중복(더블클릭·네트워크 재시도)은 진행 중/완료된 run 을 재사용
하고, 새 키만 ~300초짜리 파이프라인을 신규 기동한다.

원자성: `INSERT ... ON CONFLICT(idempotency_key) DO NOTHING` (SQLite·PG 동등).
스테일(=`running` 인데 deadline+여유 초과 = 죽은 run)은 조건부 UPDATE 로만
reclaim — `completed`/`failed` 은 reclaim 안 함(결정적: 기존 상태 그대로 반환).

dev = SQLite, prod = Postgres (reports/users 와 같은 medi-postgres).
기존 `*_repo.py` 패턴 그대로.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from ._common import SqliteRepoBase, utcnow_iso as _utcnow_iso

# running 인데 이보다 오래면 죽은 run 으로 보고 reclaim 허용. 실소요 상한 기준:
# 큐 대기 + 정비창 대기(REPORT_MAINT_WAIT_MAX_S=2700) + writer 2회(각 1800s)
# + 수집(300s). 정책(2026-07-24): writer 초장기 허용·챗 우선 — 기본 3시간.
# 구 값 400s 는 gather deadline 만 반영한 것 — 정상 작성 중인 잡이 stale 로
# 오판돼 "생성 실패" 표시되는 원인이었다(2026-07-24 실측).
DEFAULT_STALE_AFTER_S = int((os.getenv("REPORT_STALE_AFTER_S") or "").strip() or "10800")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    # 고정폭 UTC ISO → SQLite TEXT 비교가 사전식=시간순 (started_at < cut 안전).
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class ReportRun:
    idempotency_key: str
    thread_id: str
    user_id: str
    status: str                       # 'running' | 'completed' | 'failed'
    run_id: Optional[str] = None
    report_id: Optional[str] = None
    started_at: str = ""
    finished_at: Optional[str] = None
    error: Optional[str] = None
    # 보고서 주제(트리거 프롬프트)·목적 템플릿 — 재설계(2026-07-24): 대화록에
    # human 메시지로 끼우던 것을 run 에 저장(대화 오염 제거·재시작 복원 정확화).
    prompt: Optional[str] = None
    purpose: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


class ReportRunsRepo(Protocol):
    def acquire(self, *, idempotency_key: str, thread_id: str, user_id: str,
                stale_after_s: int = DEFAULT_STALE_AFTER_S,
                prompt: Optional[str] = None, purpose: Optional[str] = None,
                ) -> tuple[bool, Optional[ReportRun]]:
        """(획득여부, 기존run). True=신규/스테일reclaim → 파이프라인 기동.
        False=살아있는 running 또는 completed/failed → 기존 그대로 반환."""
        ...

    def get(self, idempotency_key: str) -> Optional[ReportRun]: ...

    def finish(self, idempotency_key: str, *, status: str,
               report_id: Optional[str] = None, run_id: Optional[str] = None,
               error: Optional[str] = None) -> None: ...

    def sweep_stale(self, *, older_than_s: int = DEFAULT_STALE_AFTER_S) -> int:
        """죽은 running 일괄 failed 처리(선택적 cron). 처리 건수 반환."""
        ...

    def list_running(self) -> list[ReportRun]:
        """status='running' 전부 — 재시작 시 orphan 재기동용."""
        ...

    def latest_running_for_thread(self, thread_id: str) -> Optional[ReportRun]:
        """이 thread 의 가장 최근 running run — FE 새로고침 후 진행 복원용."""
        ...

    def list_admin(self, *, limit: int = 100,
                   offset: int = 0) -> tuple[list[dict], int]:
        """관리자 목록 — 최근 시작순 + 총건수. reports/users/events 조인으로
        제목·이메일·발송 결과까지 한 번에(전 테이블 동일 DB — dev 단일 SQLite
        파일 / prod 단일 PG). 발송 결과는 events(report_email) 최신 1건."""
        ...

    def all_draft_report_ids(self) -> list[str]:
        """purpose='document_draft' 로 완료된 모든 report_id — 레거시 종별
        교정(final→doc) 마이그레이션용(2026-08-27)."""
        ...

    def latest_draft_report_for_thread(self, thread_id: str) -> Optional[str]:
        """최신 완료 서류 초안 run 의 report_id (턴 대조 패스 게이트)."""
        ...

    def owner_of_report(self, report_id: str) -> Optional[str]:
        """이 보고서를 만든 사용자 id. 없으면 None.

        보고서 소유권의 2차 근거. 1차는 소속 thread 의 user_id 지만,
        `prune_threads.py` 가 보관기간 지난 thread 를 지우면서 reports 는 남기므로
        (threads_repo.delete_thread 는 reports 를 건드리지 않는다) 시간이 지나면
        thread 로는 소유자를 확인할 수 없다. 그때 정당한 소유자까지 차단하지 않도록
        run 기록을 본다.
        """
        ...

    def document_report_ids_for_user(self, user_id: str, *,
                                     limit: int = 50) -> list[str]:
        """사용자가 만든 서류(document_draft) report_id — 최신순, 중복 제거.
        reports 테이블엔 user_id 가 없어 run 기록이 사용자↔서류의 유일한 고리다
        (2026-09-18, 작성 서식 다시 보기)."""
        ...

    def delete_for_user(self, user_id: str) -> int:
        """정보주체 삭제 요구 이행 — 그 사용자의 실행 이력(요청 문구 포함) 전부."""
        ...

    def report_ids_for_user(self, user_id: str) -> list[str]:
        """그 사용자가 만든 보고서·서식 id 전부(대화가 지워진 보관 서식 포함)."""
        ...

    def detach_report(self, report_id: str) -> int:
        """삭제된 보고서를 가리키는 run 의 report_id 를 비운다(행은 남김 —
        사용량·관측 근거). `latest_draft_report_for_thread` 가 지운 서류를
        계속 집지 않게 하는 용도. 영향 행 수 반환."""
        ...

    def runs_between(self, *, since: str, until: str) -> list[dict]:
        """[since, until) 에 시작한 run — 주간 집계용(보고서·서류 건수).
        [{user_id, thread_id, purpose, status}]."""
        ...


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS report_runs (
  idempotency_key TEXT PRIMARY KEY,
  thread_id       TEXT NOT NULL,
  user_id         TEXT NOT NULL,
  status          TEXT NOT NULL,
  run_id          TEXT,
  report_id       TEXT,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  error           TEXT,
  prompt          TEXT,
  purpose         TEXT
);
CREATE INDEX IF NOT EXISTS idx_report_runs_thread
  ON report_runs(thread_id, started_at DESC);
"""


def _row_to_run(row) -> ReportRun:
    keys = row.keys()
    return ReportRun(
        idempotency_key=row["idempotency_key"],
        thread_id=row["thread_id"],
        user_id=row["user_id"],
        status=row["status"],
        run_id=row["run_id"],
        report_id=row["report_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        # 구 DB(컬럼 없음) 호환 — _post_init ALTER 전 조회 방어.
        prompt=(row["prompt"] if "prompt" in keys else None),
        purpose=(row["purpose"] if "purpose" in keys else None),
    )


class SqliteReportRunsRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def _post_init(self, conn) -> None:
        # 기존 DB 에 prompt/purpose 컬럼 없으면 ADD (2026-07-24 재설계).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(report_runs)").fetchall()}
        for col in ("prompt", "purpose"):
            if col not in cols:
                conn.execute(f"ALTER TABLE report_runs ADD COLUMN {col} TEXT")

    def acquire(self, *, idempotency_key, thread_id, user_id,
                stale_after_s=DEFAULT_STALE_AFTER_S,
                prompt=None, purpose=None):
        now_iso = _utcnow_iso()
        stale_cut_iso = _iso(_utcnow() - timedelta(seconds=stale_after_s))
        # 단일 프로세스(langgraph dev) — RLock + 단일 커넥션으로 시퀀스 보호.
        with self._lock, self._conn() as c:
            # 1) 신규: 충돌 없으면 삽입(원자적). rowcount==1 → 획득.
            cur = c.execute(
                """INSERT INTO report_runs
                     (idempotency_key, thread_id, user_id, status, started_at,
                      prompt, purpose)
                   VALUES (?, ?, ?, 'running', ?, ?, ?)
                   ON CONFLICT(idempotency_key) DO NOTHING""",
                (idempotency_key, thread_id, user_id, now_iso, prompt, purpose),
            )
            if cur.rowcount == 1:
                return True, None
            # 2) 충돌: 죽은 running(스테일) 이면 조건부 UPDATE 로 reclaim.
            #    prompt/purpose 는 기존 값 보존(COALESCE — 복원 재기동은 None 전달).
            cur = c.execute(
                """UPDATE report_runs
                     SET status='running', started_at=?, run_id=NULL,
                         report_id=NULL, finished_at=NULL, error=NULL,
                         prompt=COALESCE(?, prompt), purpose=COALESCE(?, purpose)
                   WHERE idempotency_key=?
                     AND status='running' AND started_at < ?""",
                (now_iso, prompt, purpose, idempotency_key, stale_cut_iso),
            )
            if cur.rowcount == 1:
                return True, None
            # 3) 살아있는 running / completed / failed → 기존 그대로 반환.
            row = c.execute(
                "SELECT * FROM report_runs WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        return False, (_row_to_run(row) if row else None)

    def get(self, idempotency_key):
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM report_runs WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        return _row_to_run(row) if row else None

    def finish(self, idempotency_key, *, status, report_id=None,
               run_id=None, error=None):
        # idempotent: 'running' 인 row 만 transition. 두 번째 호출·sweep_stale
        # 경합·노드 분할 시 중복 finish 모두 자연 no-op (SQL rowcount=0).
        with self._lock, self._conn() as c:
            c.execute(
                """UPDATE report_runs SET
                     status=?, finished_at=?,
                     report_id=COALESCE(?, report_id),
                     run_id=COALESCE(?, run_id),
                     error=COALESCE(?, error)
                   WHERE idempotency_key=? AND status='running'""",
                (status, _utcnow_iso(), report_id, run_id,
                 (error[:1000] if error else None), idempotency_key),
            )

    def sweep_stale(self, *, older_than_s=DEFAULT_STALE_AFTER_S):
        cut_iso = _iso(_utcnow() - timedelta(seconds=older_than_s))
        with self._lock, self._conn() as c:
            cur = c.execute(
                """UPDATE report_runs
                     SET status='failed', error='stale', finished_at=?
                   WHERE status='running' AND started_at < ?""",
                (_utcnow_iso(), cut_iso),
            )
            return cur.rowcount or 0

    def list_running(self):
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM report_runs WHERE status='running' "
                "ORDER BY started_at ASC",
            ).fetchall()
        return [_row_to_run(r) for r in rows]

    def latest_running_for_thread(self, thread_id):
        with self._lock, self._conn() as c:
            row = c.execute(
                """SELECT * FROM report_runs
                   WHERE thread_id=? AND status='running'
                   ORDER BY started_at DESC LIMIT 1""",
                (thread_id,),
            ).fetchone()
        return _row_to_run(row) if row else None

    def all_draft_report_ids(self):
        with self._lock, self._conn() as c:
            rows = c.execute(
                """SELECT DISTINCT report_id FROM report_runs
                   WHERE purpose='document_draft' AND report_id IS NOT NULL"""
            ).fetchall()
        return [r["report_id"] for r in rows]

    def latest_draft_report_for_thread(self, thread_id):
        """스레드의 최신 완료 서류 초안(document_draft) report_id — 없으면 None.
        채팅 턴 대조 패스의 게이트(있을 때만 발동 — 평상시 비용 0)."""
        with self._lock, self._conn() as c:
            row = c.execute(
                """SELECT report_id FROM report_runs
                   WHERE thread_id=? AND purpose='document_draft'
                     AND status='completed' AND report_id IS NOT NULL
                   ORDER BY started_at DESC LIMIT 1""",
                (thread_id,),
            ).fetchone()
        return row["report_id"] if row else None

    def owner_of_report(self, report_id):
        if not report_id:
            return None
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT user_id FROM report_runs WHERE report_id=? "
                "ORDER BY started_at DESC LIMIT 1",
                (report_id,),
            ).fetchone()
        return row["user_id"] if row else None

    def document_report_ids_for_user(self, user_id, *, limit=50):
        with self._lock, self._conn() as c:
            rows = c.execute(
                """SELECT report_id, MAX(started_at) AS last_at FROM report_runs
                   WHERE user_id=? AND purpose='document_draft'
                     AND status='completed' AND report_id IS NOT NULL
                   GROUP BY report_id ORDER BY last_at DESC LIMIT ?""",
                (str(user_id), int(limit)),
            ).fetchall()
        return [r["report_id"] for r in rows]

    def delete_for_user(self, user_id):
        with self._lock, self._conn() as c:
            return int(c.execute("DELETE FROM report_runs WHERE user_id=?",
                                 (user_id,)).rowcount or 0)

    def report_ids_for_user(self, user_id):
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT DISTINCT report_id FROM report_runs "
                             "WHERE user_id=? AND report_id IS NOT NULL", (user_id,)).fetchall()
        return [r[0] for r in rows]

    def detach_report(self, report_id):
        if not report_id:
            return 0
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE report_runs SET report_id=NULL WHERE report_id=?",
                (report_id,))
            return int(cur.rowcount or 0)

    def runs_between(self, *, since, until):
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT user_id, thread_id, purpose, status FROM report_runs "
                "WHERE started_at >= ? AND started_at < ?", (since, until)).fetchall()
        return [dict(r) for r in rows]

    def list_admin(self, *, limit=100, offset=0):
        # SQLite 스키마는 repo 별 지연 초기화 — 조인 대상 테이블(users/reports/
        # events)이 아직 없을 수 있어(테스트·신규 dev DB) 먼저 보장한다.
        from . import get_events_repo, get_reports_repo, get_users_repo
        get_users_repo(); get_reports_repo(); get_events_repo()
        with self._lock, self._conn() as c:
            rows = c.execute(
                _LIST_ADMIN_SQL.replace("%s", "?"), (limit, offset),
            ).fetchall()
            total = c.execute("SELECT COUNT(*) FROM report_runs").fetchone()[0]
        return [dict(r) for r in rows], int(total)


# 관리자 목록 SQL — SQLite/PG 공용(placeholder 만 치환). 발송 결과는 상관
# 서브쿼리로 최신 1건만(같은 report 재발송 시 행 중복 방지). 조인 대상
# 테이블이 없거나 행이 없어도 LEFT JOIN 이라 run 자체는 항상 나온다.
_LIST_ADMIN_SQL = """
SELECT r.idempotency_key, r.thread_id, r.user_id, r.status, r.error,
       r.run_id, r.report_id, r.prompt, r.purpose,
       r.started_at, r.finished_at,
       u.email AS user_email,
       u.display_name AS user_display_name, u.admin_memo AS user_admin_memo,
       rp.title AS report_title, rp.status AS report_status,
       rp.kind AS report_kind,
       (SELECT e.payload_json FROM events e
         WHERE e.event_type = 'report_email' AND e.run_id = r.report_id
         ORDER BY e.ts DESC LIMIT 1) AS email_event,
       -- 작성 모델·분량(2026-08-26) — writer 를 자주 교체하므로 어떤 모델이
       -- 쓴 보고서인지 화면에서 바로 보여야 품질 비교가 된다.
       -- (report_quality 이벤트의 run_id 에 report_id 를 채워 조인 — email 과 동일)
       (SELECT e.payload_json FROM events e
         WHERE e.event_type = 'report_quality' AND e.run_id = r.report_id
         ORDER BY e.ts DESC LIMIT 1) AS quality_event
  FROM report_runs r
  LEFT JOIN users u ON u.id = r.user_id
  LEFT JOIN reports rp ON rp.id = r.report_id
 ORDER BY r.started_at DESC
 LIMIT %s OFFSET %s
"""


class PostgresReportRunsRepo:
    """PG 구현 — Sqlite 와 동일 인터페이스. 원자성은 단일 statement 의
    row-level 잠금 + ON CONFLICT 로 멀티워커에서도 안전."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def acquire(self, *, idempotency_key, thread_id, user_id,
                stale_after_s=DEFAULT_STALE_AFTER_S,
                prompt=None, purpose=None):
        from . import _pg
        now = _utcnow()
        stale_cut = now - timedelta(seconds=stale_after_s)
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """INSERT INTO report_runs
                     (idempotency_key, thread_id, user_id, status, started_at,
                      prompt, purpose)
                   VALUES (%s, %s, %s, 'running', %s, %s, %s)
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING idempotency_key""",
                (idempotency_key, thread_id, user_id, now, prompt, purpose),
            )
            if cur.fetchone():
                return True, None
            cur.execute(
                """UPDATE report_runs
                     SET status='running', started_at=%s, run_id=NULL,
                         report_id=NULL, finished_at=NULL, error=NULL,
                         prompt=COALESCE(%s, prompt),
                         purpose=COALESCE(%s, purpose)
                   WHERE idempotency_key=%s
                     AND status='running' AND started_at < %s
                   RETURNING idempotency_key""",
                (now, prompt, purpose, idempotency_key, stale_cut),
            )
            if cur.fetchone():
                return True, None
            cur.execute(
                "SELECT * FROM report_runs WHERE idempotency_key=%s",
                (idempotency_key,),
            )
            row = cur.fetchone()
        return False, (_pg_row_to_run(row) if row else None)

    def get(self, idempotency_key):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM report_runs WHERE idempotency_key=%s",
                (idempotency_key,),
            )
            row = cur.fetchone()
        return _pg_row_to_run(row) if row else None

    def finish(self, idempotency_key, *, status, report_id=None,
               run_id=None, error=None):
        # idempotent: 'running' 인 row 만 transition (SQLite 와 동일 의미).
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """UPDATE report_runs SET
                     status=%s, finished_at=NOW(),
                     report_id=COALESCE(%s, report_id),
                     run_id=COALESCE(%s, run_id),
                     error=COALESCE(%s, error)
                   WHERE idempotency_key=%s AND status='running'""",
                (status, report_id, run_id,
                 (error[:1000] if error else None), idempotency_key),
            )

    def sweep_stale(self, *, older_than_s=DEFAULT_STALE_AFTER_S):
        from . import _pg
        cut = _utcnow() - timedelta(seconds=older_than_s)
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """UPDATE report_runs
                     SET status='failed', error='stale', finished_at=NOW()
                   WHERE status='running' AND started_at < %s""",
                (cut,),
            )
            return cur.rowcount or 0

    def list_running(self):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM report_runs WHERE status='running' "
                "ORDER BY started_at ASC",
            )
            rows = cur.fetchall()
        return [_pg_row_to_run(r) for r in rows]

    def latest_running_for_thread(self, thread_id):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """SELECT * FROM report_runs
                   WHERE thread_id=%s AND status='running'
                   ORDER BY started_at DESC LIMIT 1""",
                (thread_id,),
            )
            row = cur.fetchone()
        return _pg_row_to_run(row) if row else None

    def all_draft_report_ids(self):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """SELECT DISTINCT report_id FROM report_runs
                   WHERE purpose='document_draft' AND report_id IS NOT NULL""")
            rows = cur.fetchall()
        return [r["report_id"] for r in rows]

    def latest_draft_report_for_thread(self, thread_id):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """SELECT report_id FROM report_runs
                   WHERE thread_id=%s AND purpose='document_draft'
                     AND status='completed' AND report_id IS NOT NULL
                   ORDER BY started_at DESC LIMIT 1""",
                (thread_id,))
            row = cur.fetchone()
        return row["report_id"] if row else None

    def owner_of_report(self, report_id):
        if not report_id:
            return None
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT user_id FROM report_runs WHERE report_id=%s "
                "ORDER BY started_at DESC LIMIT 1",
                (report_id,),
            )
            row = cur.fetchone()
        return row["user_id"] if row else None

    def document_report_ids_for_user(self, user_id, *, limit=50):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """SELECT report_id, MAX(started_at) AS last_at FROM report_runs
                   WHERE user_id=%s AND purpose='document_draft'
                     AND status='completed' AND report_id IS NOT NULL
                   GROUP BY report_id ORDER BY last_at DESC LIMIT %s""",
                (str(user_id), int(limit)))
            rows = cur.fetchall()
        return [r["report_id"] for r in rows]

    def delete_for_user(self, user_id):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("DELETE FROM report_runs WHERE user_id=%s", (user_id,))
            return int(cur.rowcount or 0)

    def report_ids_for_user(self, user_id):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT DISTINCT report_id FROM report_runs "
                        "WHERE user_id=%s AND report_id IS NOT NULL", (user_id,))
            rows = cur.fetchall()
        return [r["report_id"] for r in rows]

    def detach_report(self, report_id):
        if not report_id:
            return 0
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE report_runs SET report_id=NULL WHERE report_id=%s",
                (report_id,))
            return int(cur.rowcount or 0)

    def runs_between(self, *, since, until):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT user_id, thread_id, purpose, status FROM report_runs "
                "WHERE started_at >= %s AND started_at < %s",
                (_pg._iso_to_dt(since), _pg._iso_to_dt(until)))
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def list_admin(self, *, limit=100, offset=0):
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(_LIST_ADMIN_SQL, (limit, offset))
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS n FROM report_runs")
            total = cur.fetchone()["n"]
        out = []
        for r in rows:
            d = dict(r)
            # PG datetime → iso 문자열(SQLite 와 응답 형태 통일).
            for k in ("started_at", "finished_at"):
                if d.get(k) is not None and not isinstance(d[k], str):
                    d[k] = d[k].isoformat()
            out.append(d)
        return out, int(total)


def _pg_row_to_run(row) -> ReportRun:
    from . import _pg
    return ReportRun(
        idempotency_key=row["idempotency_key"],
        thread_id=row["thread_id"],
        user_id=row["user_id"],
        status=row["status"],
        run_id=row["run_id"],
        report_id=row["report_id"],
        started_at=_pg._dt_to_iso(row["started_at"]),
        finished_at=_pg._dt_to_iso(row["finished_at"]),
        error=row["error"],
        prompt=row.get("prompt"),
        purpose=row.get("purpose"),
    )
