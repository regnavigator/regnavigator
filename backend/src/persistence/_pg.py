"""PostgreSQL 공용 헬퍼 — connection pool, transaction, DDL.

Sqlite*Repo와 동일 인터페이스를 PG로 포팅. SQL 문법 차이(`?` → `%s`, INTEGER →
BIGINT, 등) 를 한 곳에 모아 흡수.

설치:
    pip install medi-back[prod]
또는:
    pip install "psycopg[binary,pool]>=3.2"

연결:
    REPORTS_PG_DSN=postgresql://user:pass@host:5432/medi
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Optional

_log = logging.getLogger(__name__)

_pool_lock = threading.Lock()
_pool = None  # 모듈 단위 singleton


def _get_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as e:
        raise RuntimeError(
            "psycopg + psycopg_pool 필요. `pip install medi-back[prod]` 실행."
        ) from e
    return psycopg, dict_row, ConnectionPool


def _guard_remote_pg_from_dev(dsn: str) -> None:
    """배포 이미지 밖(로컬 dev)에서 **원격** PG 에 붙는 것을 막는다 (2026-09-17).

    로컬 `.env` 가 운영 medi-postgres 를 가리킨 채 몇 달을 지냈다 — "로컬 테스트"로 돌린
    벤치가 운영에 스레드·이벤트를 쓰고, 부팅 시 `init_schema` 가 배포 전 DDL 을 운영에
    적용했으며, dev 서버는 운영의 단일 인스턴스 락을 두고 경쟁했다. 설정 실수 하나가
    조용히 운영 쓰기가 되는 구조라 연결 지점에서 막는다.

    - 배포 컨테이너(medi-back·medi-cron)는 이미지 ENV `APP_GIT_SHA` 가 있어 통과.
    - localhost PG(통합 테스트·로컬 docker)는 통과.
    - 의도적으로 운영에 붙는 운영 스크립트는 그 실행에서만 `ALLOW_REMOTE_PG=1`.
    """
    if (os.getenv("APP_GIT_SHA") or "").strip() or (os.getenv("ALLOW_REMOTE_PG") or "").strip() == "1":
        return
    host = dsn.split("@")[-1].split("/")[0].split(":")[0].strip().lower()
    if host in ("localhost", "127.0.0.1", "::1", "postgres", ""):
        return
    raise RuntimeError(
        f"로컬(dev) 프로세스가 원격 Postgres({host})에 연결하려 합니다 — 운영 DB 일 수 있어 막았습니다. "
        "로컬은 REPORTS_BACKEND=sqlite 를 쓰세요. 의도한 운영 작업이면 이 실행에만 ALLOW_REMOTE_PG=1 을 붙이세요."
    )


def get_pool(dsn: str, *, min_size: int = 2, max_size: int = 10):
    """ConnectionPool 모듈 singleton."""
    global _pool
    if _pool is not None:
        return _pool
    _guard_remote_pg_from_dev(dsn)
    with _pool_lock:
        if _pool is not None:
            return _pool
        _, _, ConnectionPool = _get_psycopg()
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"autocommit": True},
        )
        _pool.open()
        _pool.wait()
        _log.info("psycopg pool opened: %s", dsn.split("@")[-1])
    return _pool


@contextmanager
def pg_cursor(dsn: str):
    """`with pg_cursor(dsn) as cur:` 패턴 — dict_row factory."""
    _, dict_row, _ = _get_psycopg()
    pool = get_pool(dsn)
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur


# ---------------------------------------------------------------------------
# DDL — 모든 테이블 한 번에 생성. SQLite 스키마와 일치(타입만 PG화).
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS users (
  id                            TEXT PRIMARY KEY,
  email                         TEXT NOT NULL UNIQUE,
  email_verified_at             TIMESTAMPTZ,
  is_admin                      BOOLEAN NOT NULL DEFAULT FALSE,
  daily_token_limit_override    BIGINT,
  monthly_token_limit_override  BIGINT,
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at                    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS report_email_opt_in BOOLEAN NOT NULL DEFAULT TRUE;
-- 서비스 안내 메일 수신거부 — 정보통신망법 §50④ 수신거부 수단. 2026-09-10 도입→
-- 당일 철회(컬럼만 잔존)→2026-09-14 재도입(운영 결정 번복, 뉴스레터 푸터가 가리킴).
ALTER TABLE users ADD COLUMN IF NOT EXISTS notice_email_opt_in BOOLEAN NOT NULL DEFAULT TRUE;
-- 프로필(온보딩 입력, 2026-08-10) — admin 이용조회 표시용
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS affiliation TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS job_role TEXT;
-- 업데이트 팝업 마지막 확인 노트 id(2026-09-07) — 기기 무관 1회 노출
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_announcement_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_memo TEXT;
-- 계정 구분 라벨(2026-09-21) — staff|test|user, NULL=자동(src/account_class.py)
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_class TEXT;
-- 관리자 기능별 권한(2026-09-22) — 콤마 키, NULL=전 권한(src/admin_perms.py)
ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_perms TEXT;

CREATE TABLE IF NOT EXISTS reports (
  id              TEXT PRIMARY KEY,
  thread_id       TEXT NOT NULL,
  run_id          TEXT,
  mode            TEXT NOT NULL,
  kind            TEXT NOT NULL,
  status          TEXT NOT NULL,
  blob_uri        TEXT,
  title           TEXT,
  summary         TEXT,
  citations_json  JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at    TIMESTAMPTZ,
  error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_thread ON reports(thread_id, created_at DESC);
ALTER TABLE reports ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS filled_values TEXT;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS kept BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS alias TEXT;

CREATE TABLE IF NOT EXISTS events (
  id            TEXT PRIMARY KEY,
  ts            TIMESTAMPTZ NOT NULL,
  event_type    TEXT NOT NULL,
  user_id       TEXT,
  thread_id     TEXT,
  run_id        TEXT,
  message_id    TEXT,
  payload_json  JSONB,
  cost_usd      DOUBLE PRECISION,
  input_tokens  BIGINT,
  output_tokens BIGINT
);
CREATE INDEX IF NOT EXISTS idx_events_user_ts   ON events(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_thread    ON events(thread_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_type_ts   ON events(event_type, ts);

CREATE TABLE IF NOT EXISTS feedback (
  id          TEXT PRIMARY KEY,
  rating      TEXT NOT NULL CHECK (rating IN ('thumbs_up', 'thumbs_down', 'canceled')),
  user_id     TEXT,
  thread_id   TEXT,
  message_id  TEXT,
  report_id   TEXT,
  comment     TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- 기존 테이블의 CHECK 에 'canceled' 추가(2026-08-11) — DROP 후 재생성으로 멱등.
ALTER TABLE feedback DROP CONSTRAINT IF EXISTS feedback_rating_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_rating_check
  CHECK (rating IN ('thumbs_up', 'thumbs_down', 'canceled'));
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_thread  ON feedback(thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_user    ON feedback(user_id, created_at DESC);

-- 개인 근거 라이브러리(북마크). citation payload 를 통째로 보관(JSONB) — 원 대화가
-- 지워져도 근거 유지. UNIQUE(user_id, citation_id) 로 같은 근거 중복 방지(토글).
CREATE TABLE IF NOT EXISTS bookmarks (
  id             TEXT PRIMARY KEY,
  user_id        TEXT NOT NULL,
  citation_id    TEXT NOT NULL,
  citation_json  JSONB NOT NULL,
  note           TEXT,
  folder         TEXT,
  thread_id      TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, citation_id)
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id, created_at DESC);
ALTER TABLE bookmarks ADD COLUMN IF NOT EXISTS folder TEXT;

CREATE TABLE IF NOT EXISTS report_runs (
  idempotency_key TEXT PRIMARY KEY,
  thread_id       TEXT NOT NULL,
  user_id         TEXT NOT NULL,
  status          TEXT NOT NULL,
  run_id          TEXT,
  report_id       TEXT,
  started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at     TIMESTAMPTZ,
  error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_report_runs_thread
  ON report_runs(thread_id, started_at DESC);
-- 재설계(2026-07-24): 보고서 주제를 대화록이 아닌 run 에 저장 — 대화 오염 제거·재시작 복원 정확화
ALTER TABLE report_runs ADD COLUMN IF NOT EXISTS prompt TEXT;
ALTER TABLE report_runs ADD COLUMN IF NOT EXISTS purpose TEXT;

-- 자체 /chat 루프 thread 상태 (ADR-0001 Phase 1~3)
CREATE TABLE IF NOT EXISTS chat_threads (
  id                TEXT PRIMARY KEY,
  user_id           TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  selected_law_keys JSONB,
  summary_text      TEXT,
  summary_upto_seq  BIGINT,
  title             TEXT,
  pinned            BOOLEAN NOT NULL DEFAULT FALSE
);
ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS confidential_seen INTEGER NOT NULL DEFAULT 0;
ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'chat';
ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS workflow_json TEXT;
-- 사이드바 목록(list_for_user): user_id 필터 + pinned/updated_at 정렬 커버.
CREATE INDEX IF NOT EXISTS idx_chat_threads_user
  ON chat_threads(user_id, pinned DESC, updated_at DESC);
CREATE TABLE IF NOT EXISTS chat_messages (
  id         TEXT PRIMARY KEY,
  thread_id  TEXT NOT NULL,
  seq        BIGINT NOT NULL,
  data_json  JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- 본문 검색(search_messages)의 thread_id 조인 커버.
-- ⚠️ 인덱스는 반드시 대상 테이블 **뒤에**. 이 줄이 위에 있던 동안 빈 DB 에서는
-- relation does not exist 로 _DDL 배치 전체가 중단돼 아래 테이블(chat_steps·
-- beta_whitelist·app_settings)까지 생성되지 않았다. 운영 DB 는 테이블이 이미
-- 있어 IF NOT EXISTS 로 통과 — 재해복구·신규 리전에서만 터지는 상태였다(2026-08-04).
-- 기밀 단계 격리(2026-10-02) — 비기밀 턴의 컨텍스트에서 뺄 기준.
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS sensitive BOOLEAN NOT NULL DEFAULT FALSE;
-- 조합 중간 단계(2026-10-02) — 채팅에 렌더하지 않는다(컨텍스트에는 들어간다).
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_thread_seq
  ON chat_messages(thread_id, seq);
CREATE TABLE IF NOT EXISTS chat_steps (
  thread_id  TEXT NOT NULL,
  step_id    TEXT NOT NULL,
  data_json  JSONB NOT NULL,
  ts         BIGINT,
  PRIMARY KEY (thread_id, step_id)
);

-- 클로즈 베타 화이트리스트 (admin 관리 — env 는 부트스트랩)
CREATE TABLE IF NOT EXISTS beta_whitelist (
  entry      TEXT PRIMARY KEY,
  added_by   TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- 초대 발송 이력(2026-08-05) — 등록과 발송이 분리되면서 "누구에게 이미 보냈나"를
-- DB 가 알아야 한다. NULL = 아직 미발송.
ALTER TABLE beta_whitelist ADD COLUMN IF NOT EXISTS invited_at TIMESTAMPTZ;
ALTER TABLE beta_whitelist ADD COLUMN IF NOT EXISTS invited_by TEXT;

-- 런타임 앱 설정 KV (admin/운영 스크립트 관리) — 예: maintenance(점검 모드)
CREATE TABLE IF NOT EXISTS app_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT,
  updated_by TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 관리자 답변 검수(2026-09-17) — 최종 AI 답변 1건 × 검수자 1행(upsert).
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
  last_sent_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL,
  UNIQUE(user_id, folder)
);
CREATE INDEX IF NOT EXISTS idx_monitor_targets_user
  ON monitor_targets(user_id, created_at DESC);

-- 모니터링 스레드 재구성(2026-10-02) — docs/spec/monitor-threads-design.md
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

CREATE TABLE IF NOT EXISTS answer_reviews (
  id          TEXT PRIMARY KEY,
  thread_id   TEXT NOT NULL,
  message_id  TEXT NOT NULL,
  reviewer    TEXT NOT NULL,
  verdict     TEXT NOT NULL,
  error_types TEXT NOT NULL DEFAULT '[]',
  note        TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (message_id, reviewer)
);
ALTER TABLE answer_reviews ADD COLUMN IF NOT EXISTS question_snapshot TEXT;
ALTER TABLE answer_reviews ADD COLUMN IF NOT EXISTS answer_snapshot TEXT;
CREATE INDEX IF NOT EXISTS idx_answer_reviews_thread ON answer_reviews(thread_id);
CREATE INDEX IF NOT EXISTS idx_answer_reviews_updated ON answer_reviews(updated_at DESC);
"""


def close_pool() -> None:
    """풀 종료 — 프로세스 종료 시 1회(graceful close). 재호출 안전.

    이걸 안 하면 SIGTERM 때 소켓이 정리되지 않아 PG 쪽에 좀비 세션이 남는다.
    재배포가 잦으면 max_connections 를 압박한다(2026-08-04 감사 H-19).
    """
    global _pool
    pool, _pool = _pool, None
    # 풀이 닫히면 다음 사용 시 새 풀 — 스키마 확인도 다시 하게 표시를 지운다.
    reset_schema_cache()
    if pool is None:
        return
    try:
        pool.close()
    except Exception:  # noqa: BLE001 — 종료 경로
        pass


_schema_done: set[str] = set()
_schema_lock = threading.Lock()


def init_schema(dsn: str, *, force: bool = False) -> None:
    """모든 테이블 생성. 멱등(IF NOT EXISTS) + **프로세스당 1회**.

    리포지토리 9개가 각자 생성자에서 부르기 때문에 예전엔 220줄 DDL 이 최대 9번
    재실행됐다. 부팅이 느려지는 것도 문제지만, 더 나쁜 건 **DDL 실행이 리포지토리
    생성의 부작용**이라는 점 — 읽기 전용 스크립트가 리포를 하나 만들었다는 이유로
    운영 DB 에 DDL 을 친다(2026-08-04 감사 H-17).

    여기서는 같은 DSN 에 대해 한 번만 실제로 실행하도록 막는다. 명시적 스키마
    관리(마이그레이션 도구)로 옮기는 건 별건(H-16).
    """
    if not force:
        with _schema_lock:
            if dsn in _schema_done:
                return
    with pg_cursor(dsn) as cur:
        cur.execute(_DDL)
    with _schema_lock:
        _schema_done.add(dsn)
    _log.info("Postgres schema initialized")


def reset_schema_cache() -> None:
    """테스트 격리 — '이미 초기화됨' 표시 해제."""
    with _schema_lock:
        _schema_done.clear()


# ---------------------------------------------------------------------------
# 시간 변환 헬퍼 — 코드는 ISO 문자열 (UTC) 사용, PG는 TIMESTAMPTZ
# ---------------------------------------------------------------------------
def _iso_to_dt(s: Optional[str]):
    """ISO 8601 string → datetime (PG TIMESTAMPTZ에 대입). None passthrough."""
    if s is None:
        return None
    from datetime import datetime
    # 'YYYY-MM-DDTHH:MM:SS.ffffffZ' 형식 — fromisoformat은 'Z' 안 받음 → 보정
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _dt_to_iso(dt) -> Optional[str]:
    """datetime → ISO 8601 string. None passthrough."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if dt.tzinfo else (
        dt.isoformat() + "Z"
    )
