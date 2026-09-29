-- 001_init.sql — 초기 스키마 (users, reports, events, feedback)
-- Postgres 14+ 권장. 멱등 (IF NOT EXISTS).
--
-- 실행:
--   psql $REPORTS_PG_DSN -f db/migrations/001_init.sql
-- 또는 src.persistence._pg.init_schema(dsn) — Repos 인스턴스화 시 자동 호출.

CREATE TABLE IF NOT EXISTS users (
  id                            TEXT PRIMARY KEY,
  email                         TEXT NOT NULL UNIQUE,
  email_verified_at             TIMESTAMPTZ,
  is_admin                      BOOLEAN NOT NULL DEFAULT FALSE,
  daily_token_limit_override    BIGINT,
  monthly_token_limit_override  BIGINT,
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS reports (
  id              TEXT PRIMARY KEY,
  thread_id       TEXT NOT NULL,
  run_id          TEXT,
  mode            TEXT NOT NULL,
  kind            TEXT NOT NULL,
  status          TEXT NOT NULL,
  blob_uri        TEXT,
  title           TEXT,
  citations_json  JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at    TIMESTAMPTZ,
  error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_thread ON reports(thread_id, created_at DESC);

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
  rating      TEXT NOT NULL CHECK (rating IN ('thumbs_up', 'thumbs_down')),
  user_id     TEXT,
  thread_id   TEXT,
  message_id  TEXT,
  report_id   TEXT,
  comment     TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_thread  ON feedback(thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_user    ON feedback(user_id, created_at DESC);

-- LangGraph PostgresSaver의 checkpoint 테이블은 saver.setup()이 자동 생성 —
-- 별도 마이그레이션 X.
