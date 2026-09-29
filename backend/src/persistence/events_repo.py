"""EventsRepo — 모든 사용 행위 추적.

event_type 값:
- query_start    : 사용자 질문 입력 시점 (분류·길이·자동 trigger 가드)
- llm_call       : LLM 호출 후 (input/output tokens, model, cost)
- tool_call      : 도구 호출 (qdrant/tavily, 결과 건수, latency)
- report_save    : 보고서 저장 (kind: rag/web/final)
- report_download: 보고서 .md 다운로드
- feedback       : 메시지·보고서 평가
- quota_blocked  : 토큰 한도 초과로 차단
- unverified_contact : 답변에 검증 불가 URL·전화 감지(운영자 신호 — 사용자 비노출)
- claim_audit    : 무인용 사실 audit(supported/contradicted/unverified 집계 — 환각률 측정)
- quality_regression : 골든셋 야간 회귀 요약(scripts/quality_regression.py — 품질 이력)

payload_json은 자유 형식. 분석 시 JSON 파싱.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso


@dataclass
class Event:
    id: str
    ts: str
    event_type: str
    user_id: Optional[str] = None
    thread_id: Optional[str] = None
    run_id: Optional[str] = None
    message_id: Optional[str] = None
    payload_json: Optional[str] = None
    cost_usd: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

    def as_dict(self) -> dict:
        d = asdict(self)
        if d.get("payload_json"):
            try:
                d["payload"] = json.loads(d["payload_json"])
            except Exception:
                d["payload"] = None
        return d


class EventsRepo(Protocol):
    def emit(self, event: Event) -> str: ...
    def get(self, event_id: str) -> Optional[Event]: ...
    def delete_for_user(self, user_id: str, *, keep_types: tuple = ()) -> int: ...
    def list_for_user(self, user_id: str, *,
                      event_type: Optional[str] = None,
                      since: Optional[str] = None,
                      limit: int = 100) -> list[Event]: ...
    def list_for_thread(self, thread_id: str, *, limit: int = 200) -> list[Event]: ...
    def count_older_than(self, *, cutoff_iso: str, types: tuple) -> int: ...
    def delete_older_than(self, *, cutoff_iso: str, types: tuple) -> int: ...
    def anonymize_older_than(self, *, cutoff_iso: str, types: tuple) -> int: ...
    def inactive_thread_ids(self, *, cutoff_iso: str, limit: int = 1000) -> list[str]: ...
    def list_by_type(
        self,
        event_type: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        exclude_user_ids: tuple = (),
        exclude_anonymous: bool = False,
    ) -> list[Event]: ...
    def count_by_type(
        self,
        event_type: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        exclude_user_ids: tuple = (),
        exclude_anonymous: bool = False,
    ) -> int:
        """list_by_type 과 동일 조건의 전체 건수 — 페이지네이션 total 용."""
        ...
    def sum_tokens_for_user(
        self, user_id: str, *, since: str
    ) -> tuple[int, int, float]:  # (input, output, cost_usd)
        ...
    def rollup(self, *, since: str, until: str) -> list[dict]:
        """[since, until) 구간을 (user_id, thread_id, event_type) 로 묶은 합계 —
        주간 집계(`src/usage_weekly.py`)용. 내부 계정·스레드 필터는 호출자가 Python 에서
        기존 규칙(`is_internal_thread`·account_class)으로 건다(SQL 로 복제하면 어긋난다)."""
        ...

    def daily_stats(self, *, since: str,
                    exclude_user_ids: tuple = (),
                    exclude_anonymous: bool = False) -> list[dict]:
        """일별 집계(관리자 통계) — [{day, llm_calls, active_users, input_tokens,
        output_tokens, cost_usd, quota_blocked, citation_reports}] 최신순.

        exclude_user_ids: 집계에서 뺄 사용자(관리자 트래픽 오염 방지, 2026-08-05).
        user_id 가 NULL 인 이벤트는 제외 대상이 아니다."""
        ...


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS events (
  id            TEXT PRIMARY KEY,
  ts            TEXT NOT NULL,
  event_type    TEXT NOT NULL,
  user_id       TEXT,
  thread_id     TEXT,
  run_id        TEXT,
  message_id    TEXT,
  payload_json  TEXT,
  cost_usd      REAL,
  input_tokens  INTEGER,
  output_tokens INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_user_ts   ON events(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_thread    ON events(thread_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_type_ts   ON events(event_type, ts);
"""


class SqliteEventsRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def delete_for_user(self, user_id: str, *, keep_types: tuple = ()) -> int:
        """사용자 이벤트 파기. keep_types(감사추적)는 보존."""
        q = "DELETE FROM events WHERE user_id = ?"
        args = [user_id]
        if keep_types:
            q += " AND event_type NOT IN (%s)" % ",".join("?" * len(keep_types))
            args += list(keep_types)
        with self._lock, self._conn() as c:
            return c.execute(q, args).rowcount

    def emit(self, event: Event) -> str:
        if not event.id:
            event.id = _new_id()
        if not event.ts:
            event.ts = _utcnow_iso()
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO events
                   (id, ts, event_type, user_id, thread_id, run_id, message_id,
                    payload_json, cost_usd, input_tokens, output_tokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.id, event.ts, event.event_type, event.user_id,
                    event.thread_id, event.run_id, event.message_id,
                    event.payload_json, event.cost_usd,
                    event.input_tokens, event.output_tokens,
                ),
            )
        return event.id

    def get(self, event_id: str) -> Optional[Event]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return _row_to_event(row) if row else None

    def list_for_user(self, user_id: str, *,
                      event_type: Optional[str] = None,
                      since: Optional[str] = None,
                      limit: int = 100) -> list[Event]:
        sql = "SELECT * FROM events WHERE user_id = ?"
        params: list = [user_id]
        if event_type:
            sql += " AND event_type = ?"; params.append(event_type)
        if since:
            sql += " AND ts >= ?"; params.append(since)
        sql += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
        with self._lock, self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_event(r) for r in rows]

    def list_for_thread(self, thread_id: str, *, limit: int = 200) -> list[Event]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM events WHERE thread_id = ? ORDER BY ts ASC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
        return [_row_to_event(r) for r in rows]

    def list_by_type(
        self,
        event_type: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        exclude_user_ids: tuple = (),
        exclude_anonymous: bool = False,
    ) -> list[Event]:
        # exclude_* 는 daily_stats 와 동일 의미(scope=real) — 파이썬 사후 필터는
        # LIMIT 이후에 걸려 오래된 실사용 이벤트가 창 밖으로 밀려난다(2026-08-20).
        cond, params = self._type_filter_sql(
            event_type, since=since, until=until,
            exclude_user_ids=exclude_user_ids,
            exclude_anonymous=exclude_anonymous)
        sql = f"SELECT * FROM events WHERE {cond}"
        if user_id:
            sql += " AND user_id = ?"; params.append(user_id)
        sql += " ORDER BY ts DESC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
        with self._lock, self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_event(r) for r in rows]

    @staticmethod
    def _type_filter_sql(event_type, *, since, until,
                         exclude_user_ids, exclude_anonymous):
        cond = "event_type = ?"
        params: list = [event_type]
        if since:
            cond += " AND ts >= ?"; params.append(since)
        if until:
            cond += " AND ts < ?"; params.append(until)
        if exclude_anonymous:
            cond += " AND user_id IS NOT NULL"
        if exclude_user_ids:
            ph = ",".join("?" * len(exclude_user_ids))
            null_ok = "" if exclude_anonymous else "user_id IS NULL OR "
            cond += f" AND ({null_ok}user_id NOT IN ({ph}))"
            params += list(exclude_user_ids)
        return cond, params

    def count_by_type(self, event_type, *, since=None, until=None,
                      exclude_user_ids: tuple = (),
                      exclude_anonymous: bool = False) -> int:
        cond, params = self._type_filter_sql(
            event_type, since=since, until=until,
            exclude_user_ids=exclude_user_ids,
            exclude_anonymous=exclude_anonymous)
        with self._lock, self._conn() as c:
            row = c.execute(
                f"SELECT COUNT(*) AS n FROM events WHERE {cond}", params
            ).fetchone()
        return int(row["n"])

    def sum_tokens_for_user(self, user_id: str, *, since: str) -> tuple[int, int, float]:
        with self._lock, self._conn() as c:
            row = c.execute(
                """SELECT
                     COALESCE(SUM(input_tokens), 0)  AS i,
                     COALESCE(SUM(output_tokens), 0) AS o,
                     COALESCE(SUM(cost_usd), 0.0)    AS c
                   FROM events
                   WHERE user_id = ? AND event_type = 'llm_call' AND ts >= ?""",
                (user_id, since),
            ).fetchone()
        return int(row["i"]), int(row["o"]), float(row["c"])

    def count_older_than(self, *, cutoff_iso: str, types: tuple) -> int:
        """보존기간 지난 건수(미리보기용)."""
        if not types:
            return 0
        ph = ",".join("?" * len(types))
        with self._lock, self._conn() as c:
            row = c.execute(
                f"SELECT COUNT(*) AS n FROM events "
                f"WHERE ts < ? AND event_type IN ({ph})",
                (cutoff_iso, *types),
            ).fetchone()
        return int(row["n"] or 0)

    def delete_older_than(self, *, cutoff_iso: str, types: tuple) -> int:
        """보존기간 지난 **내용 이벤트** 파기(질문·검색어 등 원문 파생 payload)."""
        if not types:
            return 0
        ph = ",".join("?" * len(types))
        with self._lock, self._conn() as c:
            return c.execute(
                f"DELETE FROM events WHERE ts < ? AND event_type IN ({ph})",
                (cutoff_iso, *types),
            ).rowcount

    def anonymize_older_than(self, *, cutoff_iso: str, types: tuple) -> int:
        """보존기간 지난 **지표 이벤트** 비식별화 — 식별자만 제거.

        토큰·비용·건수는 남겨 일별 통계(daily_stats)가 과거를 잃지 않게 한다.
        지우면 비용 추이·품질 이력이 통째로 사라지는데, 그 이력은 개인을
        식별하지 않고도 성립한다 — 식별자만 떼는 게 목적에 맞다.
        """
        if not types:
            return 0
        ph = ",".join("?" * len(types))
        with self._lock, self._conn() as c:
            return c.execute(
                f"UPDATE events SET user_id = NULL, thread_id = NULL, "
                f"message_id = NULL "
                f"WHERE ts < ? AND event_type IN ({ph}) AND user_id IS NOT NULL",
                (cutoff_iso, *types),
            ).rowcount
    def inactive_thread_ids(self, *, cutoff_iso: str, limit: int = 1000) -> list[str]:
        """마지막 활동(events.ts)이 cutoff_iso 이전인 thread_id — 체크포인트 보존 정리용."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                """SELECT thread_id FROM events
                   WHERE thread_id IS NOT NULL
                   GROUP BY thread_id HAVING MAX(ts) < ?
                   LIMIT ?""",
                (cutoff_iso, int(limit)),
            ).fetchall()
        return [r["thread_id"] for r in rows]

    def daily_stats(self, *, since: str,
                    exclude_user_ids: tuple = (),
                    exclude_anonymous: bool = False) -> list[dict]:
        """일별 집계(관리자 통계) — 최신일 우선. 날짜는 **사용자 타임존(기본 KST)** 기준
        (2026-09-21 — 종전 UTC 날짜라 주간 집계·쿼터의 "하루"와 어긋났다). [{day, llm_calls, active_users,
        input_tokens, output_tokens, cost_usd, quota_blocked, citation_reports}].

        exclude_anonymous: user_id 없는 이벤트 제외 — 운영에서 익명 llm_call 은
        벤치·스크립트(run_chat_turn 직접 호출) 트래픽뿐이다(/chat 은 JWT 필수).
        scope="real" 이 관리자 제외와 함께 켠다(2026-08-08).
        """
        where = "ts >= ?"
        args: list = [since]
        if exclude_anonymous:
            where += " AND user_id IS NOT NULL"
        if exclude_user_ids:
            ph = ",".join("?" * len(exclude_user_ids))
            null_ok = "" if exclude_anonymous else "user_id IS NULL OR "
            where += f" AND ({null_ok}user_id NOT IN ({ph}))"
            args += list(exclude_user_ids)
        off = _usage_offset_hours_sql()
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"""
                SELECT substr(datetime(ts, '{off} hours'), 1, 10) AS day,
                       SUM(CASE WHEN event_type='llm_call' THEN 1 ELSE 0 END) AS llm_calls,
                       COUNT(DISTINCT CASE WHEN event_type='llm_call' AND user_id IS NOT NULL
                                           THEN user_id END) AS active_users,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost_usd), 0) AS cost_usd,
                       SUM(CASE WHEN event_type='quota_blocked' THEN 1 ELSE 0 END) AS quota_blocked,
                       SUM(CASE WHEN event_type='citation_report' THEN 1 ELSE 0 END) AS citation_reports
                FROM events WHERE {where}
                GROUP BY 1 ORDER BY day DESC
                """,
                args,
            ).fetchall()
        return [dict(r) for r in rows]

    def rollup(self, *, since: str, until: str) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                """SELECT user_id, thread_id, event_type, COUNT(*) AS n,
                          COALESCE(SUM(input_tokens), 0) AS input_tokens,
                          COALESCE(SUM(output_tokens), 0) AS output_tokens,
                          COALESCE(SUM(cost_usd), 0) AS cost_usd
                   FROM events WHERE ts >= ? AND ts < ?
                   GROUP BY user_id, thread_id, event_type""",
                (since, until),
            ).fetchall()
        return [dict(r) for r in rows]


def _row_to_event(row) -> Event:
    return Event(
        id=row["id"],
        ts=row["ts"],
        event_type=row["event_type"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        run_id=row["run_id"],
        message_id=row["message_id"],
        payload_json=row["payload_json"],
        cost_usd=row["cost_usd"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
    )


# ---------------------------------------------------------------------------
# 시간 윈도우 헬퍼
# ---------------------------------------------------------------------------
def start_of_today_utc_iso() -> str:
    """오늘 0시 UTC ISO."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def start_of_month_utc_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


# ── 사용자 체감 달력일 경계(2026-08-05) ────────────────────────────────────
# `events.ts` 는 UTC ISO 로 저장되지만, **일일 한도의 "하루"는 사용자 기준**이어야
# 한다. UTC 자정을 쓰면 일일 쿼터가 KST 오전 9시에 리셋돼, 사용자는 아침에
# "어제 것이 안 지워졌다" 오전 9시에 "갑자기 0이 됐다"로 본다. 저장 포맷은 그대로
# 두고 **비교 기준만** 사용자 타임존 자정으로 옮긴다.
#
# zoneinfo 는 slim 이미지에서 tzdata 누락으로 죽을 수 있고 한국은 DST 가 없으므로
# 고정 오프셋을 쓴다. 다른 타임존 운영 시 env 로 조정.
def _usage_tz() -> timezone:
    try:
        hours = float((os.getenv("USAGE_DAY_UTC_OFFSET_HOURS") or "").strip() or "9")
    except ValueError:
        hours = 9.0
    return timezone(timedelta(hours=hours))


def _usage_offset_hours_sql() -> str:
    """SQL 에 끼울 시간 오프셋(숫자 문자열만 — env 값을 그대로 넣지 않는다)."""
    hours = _usage_tz().utcoffset(None).total_seconds() / 3600
    return f"{hours:+g}" if hours else "+0"


def _as_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def start_of_today_local_iso() -> str:
    """사용자 타임존(기본 KST) 자정을 UTC ISO 로 — 일일 쿼터 윈도우."""
    tz = _usage_tz()
    now = datetime.now(timezone.utc).astimezone(tz)
    return _as_utc_iso(now.replace(hour=0, minute=0, second=0, microsecond=0))


def start_of_month_local_iso() -> str:
    """사용자 타임존 월초 자정을 UTC ISO 로 — 월간 쿼터 윈도우."""
    tz = _usage_tz()
    now = datetime.now(timezone.utc).astimezone(tz)
    return _as_utc_iso(
        now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    )


class PostgresEventsRepo:
    """Postgres 본체 구현."""

    def delete_for_user(self, user_id: str, *, keep_types: tuple = ()) -> int:
        """사용자 이벤트 파기. keep_types(감사추적)는 보존."""
        from . import _pg
        q = "DELETE FROM events WHERE user_id = %s"
        args = [user_id]
        if keep_types:
            q += " AND event_type <> ALL(%s)"
            args.append(list(keep_types))
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(q, args)
            return cur.rowcount

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def emit(self, event: Event) -> str:
        from . import _pg
        if not event.id:
            event.id = _new_id()
        if not event.ts:
            event.ts = _utcnow_iso()
        ts_dt = _pg._iso_to_dt(event.ts)

        # payload_json: PG는 jsonb. str을 직접 캐스팅하도록 ::jsonb 사용.
        payload = event.payload_json
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """
                INSERT INTO events
                  (id, ts, event_type, user_id, thread_id, run_id, message_id,
                   payload_json, cost_usd, input_tokens, output_tokens)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                """,
                (event.id, ts_dt, event.event_type, event.user_id,
                 event.thread_id, event.run_id, event.message_id,
                 payload, event.cost_usd,
                 event.input_tokens, event.output_tokens),
            )
        return event.id

    def get(self, event_id: str) -> Optional[Event]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
        return _pg_row_to_event(row) if row else None

    def list_for_user(self, user_id: str, *,
                      event_type: Optional[str] = None,
                      since: Optional[str] = None,
                      limit: int = 100) -> list[Event]:
        from . import _pg
        sql = "SELECT * FROM events WHERE user_id = %s"
        params: list = [user_id]
        if event_type:
            sql += " AND event_type = %s"; params.append(event_type)
        if since:
            sql += " AND ts >= %s"; params.append(_pg._iso_to_dt(since))
        sql += " ORDER BY ts DESC LIMIT %s"; params.append(limit)
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_pg_row_to_event(r) for r in rows]

    def list_for_thread(self, thread_id: str, *, limit: int = 200) -> list[Event]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM events WHERE thread_id = %s ORDER BY ts ASC LIMIT %s",
                (thread_id, limit),
            )
            rows = cur.fetchall()
        return [_pg_row_to_event(r) for r in rows]

    def list_by_type(
        self,
        event_type: str,
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        exclude_user_ids: tuple = (),
        exclude_anonymous: bool = False,
    ) -> list[Event]:
        from . import _pg
        cond, params = self._type_filter_sql(
            event_type, since=since, until=until,
            exclude_user_ids=exclude_user_ids,
            exclude_anonymous=exclude_anonymous)
        sql = f"SELECT * FROM events WHERE {cond}"
        if user_id:
            sql += " AND user_id = %s"; params.append(user_id)
        sql += " ORDER BY ts DESC LIMIT %s OFFSET %s"
        params.extend([int(limit), int(offset)])
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_pg_row_to_event(r) for r in rows]

    @staticmethod
    def _type_filter_sql(event_type, *, since, until,
                         exclude_user_ids, exclude_anonymous):
        from . import _pg
        cond = "event_type = %s"
        params: list = [event_type]
        if since:
            cond += " AND ts >= %s"; params.append(_pg._iso_to_dt(since))
        if until:
            cond += " AND ts < %s"; params.append(_pg._iso_to_dt(until))
        if exclude_anonymous:
            cond += " AND user_id IS NOT NULL"
        if exclude_user_ids:
            ph = ",".join(["%s"] * len(exclude_user_ids))
            null_ok = "" if exclude_anonymous else "user_id IS NULL OR "
            cond += f" AND ({null_ok}user_id NOT IN ({ph}))"
            params += list(exclude_user_ids)
        return cond, params

    def count_by_type(self, event_type, *, since=None, until=None,
                      exclude_user_ids: tuple = (),
                      exclude_anonymous: bool = False) -> int:
        from . import _pg
        cond, params = self._type_filter_sql(
            event_type, since=since, until=until,
            exclude_user_ids=exclude_user_ids,
            exclude_anonymous=exclude_anonymous)
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM events WHERE {cond}", params)
            return int(cur.fetchone()["n"])

    def sum_tokens_for_user(self, user_id: str, *, since: str) -> tuple[int, int, float]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """
                SELECT
                  COALESCE(SUM(input_tokens), 0)  AS i,
                  COALESCE(SUM(output_tokens), 0) AS o,
                  COALESCE(SUM(cost_usd), 0.0)    AS c
                FROM events
                WHERE user_id = %s AND event_type = 'llm_call' AND ts >= %s
                """,
                (user_id, _pg._iso_to_dt(since)),
            )
            row = cur.fetchone()
        return int(row["i"]), int(row["o"]), float(row["c"])

    def count_older_than(self, *, cutoff_iso: str, types: tuple) -> int:
        """보존기간 지난 건수(미리보기용)."""
        if not types:
            return 0
        from . import _pg
        ph = ",".join(["%s"] * len(types))
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM events "
                f"WHERE ts < %s AND event_type IN ({ph})",
                (_pg._iso_to_dt(cutoff_iso), *types),
            )
            return int(dict(cur.fetchone())["n"] or 0)

    def delete_older_than(self, *, cutoff_iso: str, types: tuple) -> int:
        """보존기간 지난 **내용 이벤트** 파기(질문·검색어 등 원문 파생 payload)."""
        if not types:
            return 0
        from . import _pg
        ph = ",".join(["%s"] * len(types))
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                f"DELETE FROM events WHERE ts < %s AND event_type IN ({ph})",
                (_pg._iso_to_dt(cutoff_iso), *types),
            )
            return cur.rowcount

    def anonymize_older_than(self, *, cutoff_iso: str, types: tuple) -> int:
        """보존기간 지난 **지표 이벤트** 비식별화 — 식별자만 제거(집계는 보존)."""
        if not types:
            return 0
        from . import _pg
        ph = ",".join(["%s"] * len(types))
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                f"UPDATE events SET user_id = NULL, thread_id = NULL, "
                f"message_id = NULL "
                f"WHERE ts < %s AND event_type IN ({ph}) AND user_id IS NOT NULL",
                (_pg._iso_to_dt(cutoff_iso), *types),
            )
            return cur.rowcount
    def inactive_thread_ids(self, *, cutoff_iso: str, limit: int = 1000) -> list[str]:
        """마지막 활동(events.ts)이 cutoff_iso 이전인 thread_id — 체크포인트 보존 정리용."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """SELECT thread_id FROM events
                   WHERE thread_id IS NOT NULL
                   GROUP BY thread_id HAVING MAX(ts) < %s
                   LIMIT %s""",
                (_pg._iso_to_dt(cutoff_iso), int(limit)),
            )
            rows = cur.fetchall()
        return [r["thread_id"] for r in rows]


    def daily_stats(self, *, since: str,
                    exclude_user_ids: tuple = (),
                    exclude_anonymous: bool = False) -> list[dict]:
        """일별 집계(관리자 통계) — 최신일 우선. exclude_anonymous 의미는
        SQLite 구현 docstring 참고(익명 = 벤치·스크립트 트래픽)."""
        from . import _pg
        where = "ts >= %s"
        args: list = [_pg._iso_to_dt(since)]
        if exclude_anonymous:
            where += " AND user_id IS NOT NULL"
        if exclude_user_ids:
            ph = ",".join(["%s"] * len(exclude_user_ids))
            null_ok = "" if exclude_anonymous else "user_id IS NULL OR "
            where += f" AND ({null_ok}user_id NOT IN ({ph}))"
            args += list(exclude_user_ids)
        off = _usage_offset_hours_sql()
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                f"""
                SELECT to_char((ts AT TIME ZONE 'UTC') + interval '{off} hours', 'YYYY-MM-DD') AS day,
                       SUM(CASE WHEN event_type='llm_call' THEN 1 ELSE 0 END) AS llm_calls,
                       COUNT(DISTINCT CASE WHEN event_type='llm_call' AND user_id IS NOT NULL
                                           THEN user_id END) AS active_users,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost_usd), 0) AS cost_usd,
                       SUM(CASE WHEN event_type='quota_blocked' THEN 1 ELSE 0 END) AS quota_blocked,
                       SUM(CASE WHEN event_type='citation_report' THEN 1 ELSE 0 END) AS citation_reports
                FROM events WHERE {where}
                GROUP BY 1 ORDER BY day DESC
                """,
                args,
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            r = dict(r)
            r["cost_usd"] = float(r["cost_usd"] or 0)
            out.append(r)
        return out


    def rollup(self, *, since: str, until: str) -> list[dict]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """SELECT user_id, thread_id, event_type, COUNT(*) AS n,
                          COALESCE(SUM(input_tokens), 0) AS input_tokens,
                          COALESCE(SUM(output_tokens), 0) AS output_tokens,
                          COALESCE(SUM(cost_usd), 0) AS cost_usd
                   FROM events WHERE ts >= %s AND ts < %s
                   GROUP BY user_id, thread_id, event_type""",
                (_pg._iso_to_dt(since), _pg._iso_to_dt(until)),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            r = dict(r)
            r["cost_usd"] = float(r["cost_usd"] or 0)
            out.append(r)
        return out


def _pg_row_to_event(row) -> Event:
    from . import _pg
    import json
    payload = row["payload_json"]
    # jsonb는 dict로 옴 — events_repo.Event는 string을 기대하므로 직렬화
    payload_str = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    return Event(
        id=row["id"],
        ts=_pg._dt_to_iso(row["ts"]),
        event_type=row["event_type"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        run_id=row["run_id"],
        message_id=row["message_id"],
        payload_json=payload_str,
        cost_usd=row["cost_usd"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
    )
