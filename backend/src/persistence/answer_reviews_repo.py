"""AnswerReviewsRepo — 관리자 답변 검수(정답성 채점) 기록 (2026-09-17).

grounding·claim audit 은 "쓴 문장이 출처와 일치하나"까지만 잰다. **답이 맞는가**
(조문 오적용·핵심 조문 누락·시점 오류)는 사람이 봐야 한다 — 그 채점을 남긴다.

단위 = 최종 AI 답변 1건(`message_id`, feedback 과 같은 키). 검수자당 1행
(UNIQUE(message_id, reviewer) upsert) — 고쳐 채점하면 덮어쓴다. 여러 검수자의
채점은 공존한다(검수자 간 일치도를 나중에 잴 수 있게).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from ._common import SqliteRepoBase, new_id as _new_id, utcnow_iso as _utcnow_iso

VERDICTS = ("correct", "partial", "wrong", "unratable")
# 오류 유형 = 개선 우선순위의 축. retrieval_miss 가 많으면 ETL·랭킹,
# misapplied 가 많으면 프롬프트 — 어디를 고칠지가 이 분포에서 나온다.
ERROR_TYPES = (
    "retrieval_miss",   # 맞는 조문이 검색되지 않음
    "misapplied",       # 검색은 됐는데 조문을 잘못 적용·해석
    "fabricated",       # 출처에 없는 사실·조문 날조
    "outdated",         # 현행/시행예정 혼동·구법 인용
    "incomplete",       # 핵심 조문·예외 누락
    "other",
)


@dataclass
class AnswerReview:
    id: str
    thread_id: str
    message_id: str
    reviewer: str
    verdict: str
    error_types: list[str] = field(default_factory=list)
    note: Optional[str] = None
    # 채점 시점의 질문·답변 스냅샷(2026-09-18). 대화는 90일 뒤 지워지지만 채점한 턴은
    # 근거를 남겨야 정답률을 나중에 되짚을 수 있다. 저장되는 글은 입구 PII 게이트를
    # 지난 **마스킹본**(대화 저장본 그대로)이고, 사용자 식별자는 싣지 않는다.
    question_snapshot: Optional[str] = None
    answer_snapshot: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    def as_dict(self) -> dict:
        return asdict(self)


def validate(review: AnswerReview) -> None:
    if review.verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {review.verdict!r}")
    bad = [e for e in review.error_types if e not in ERROR_TYPES]
    if bad:
        raise ValueError(f"unknown error_types: {bad}")
    if not review.thread_id or not review.message_id or not review.reviewer:
        raise ValueError("thread_id·message_id·reviewer 는 필수입니다.")


class AnswerReviewsRepo(Protocol):
    def upsert(self, review: AnswerReview) -> str: ...
    def list_for_thread(self, thread_id: str) -> list[AnswerReview]: ...
    def list_since(self, since: Optional[str] = None, *, limit: int = 5000) -> list[AnswerReview]: ...
    def reviewed_message_ids(self) -> set[str]: ...


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS answer_reviews (
  id          TEXT PRIMARY KEY,
  thread_id   TEXT NOT NULL,
  message_id  TEXT NOT NULL,
  reviewer    TEXT NOT NULL,
  verdict     TEXT NOT NULL,
  error_types TEXT NOT NULL DEFAULT '[]',
  note        TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  UNIQUE (message_id, reviewer)
);
CREATE INDEX IF NOT EXISTS idx_answer_reviews_thread ON answer_reviews(thread_id);
CREATE INDEX IF NOT EXISTS idx_answer_reviews_updated ON answer_reviews(updated_at DESC);
"""


def _types_from_json(raw) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except Exception:  # noqa: BLE001
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


SNAPSHOT_MAX_CHARS = 20_000


def _clip(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return text[:SNAPSHOT_MAX_CHARS]


class SqliteAnswerReviewsRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def _post_init(self, conn) -> None:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(answer_reviews)").fetchall()}
        for col in ("question_snapshot", "answer_snapshot"):
            if col not in cols:
                conn.execute(f"ALTER TABLE answer_reviews ADD COLUMN {col} TEXT")

    def upsert(self, review: AnswerReview) -> str:
        validate(review)
        if not review.id:
            review.id = _new_id()
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO answer_reviews
                   (id, thread_id, message_id, reviewer, verdict, error_types,
                    note, created_at, updated_at, question_snapshot, answer_snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(message_id, reviewer) DO UPDATE SET
                     verdict = excluded.verdict,
                     error_types = excluded.error_types,
                     note = excluded.note,
                     updated_at = excluded.updated_at,
                     question_snapshot = COALESCE(excluded.question_snapshot, question_snapshot),
                     answer_snapshot = COALESCE(excluded.answer_snapshot, answer_snapshot)""",
                (review.id, review.thread_id, review.message_id, review.reviewer,
                 review.verdict, json.dumps(review.error_types), review.note,
                 review.created_at, review.updated_at,
                 _clip(review.question_snapshot), _clip(review.answer_snapshot)),
            )
            row = c.execute(
                "SELECT id FROM answer_reviews WHERE message_id = ? AND reviewer = ?",
                (review.message_id, review.reviewer)).fetchone()
        return row["id"]

    def list_for_thread(self, thread_id: str) -> list[AnswerReview]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM answer_reviews WHERE thread_id = ? ORDER BY updated_at DESC",
                (thread_id,)).fetchall()
        return [_row_to_review(r) for r in rows]

    def list_since(self, since: Optional[str] = None, *, limit: int = 5000) -> list[AnswerReview]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM answer_reviews WHERE updated_at >= ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (since or "", limit)).fetchall()
        return [_row_to_review(r) for r in rows]

    def reviewed_message_ids(self) -> set[str]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT DISTINCT message_id FROM answer_reviews").fetchall()
        return {r["message_id"] for r in rows}


def _row_to_review(row) -> AnswerReview:
    return AnswerReview(
        id=row["id"], thread_id=row["thread_id"], message_id=row["message_id"],
        reviewer=row["reviewer"], verdict=row["verdict"],
        error_types=_types_from_json(row["error_types"]), note=row["note"],
        question_snapshot=row["question_snapshot"], answer_snapshot=row["answer_snapshot"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


class PostgresAnswerReviewsRepo:
    """Postgres 본체 구현."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def upsert(self, review: AnswerReview) -> str:
        from . import _pg
        validate(review)
        if not review.id:
            review.id = _new_id()
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """
                INSERT INTO answer_reviews
                  (id, thread_id, message_id, reviewer, verdict, error_types,
                   note, created_at, updated_at, question_snapshot, answer_snapshot)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id, reviewer) DO UPDATE SET
                  verdict = EXCLUDED.verdict,
                  error_types = EXCLUDED.error_types,
                  note = EXCLUDED.note,
                  updated_at = EXCLUDED.updated_at,
                  question_snapshot = COALESCE(EXCLUDED.question_snapshot, answer_reviews.question_snapshot),
                  answer_snapshot = COALESCE(EXCLUDED.answer_snapshot, answer_reviews.answer_snapshot)
                RETURNING id
                """,
                (review.id, review.thread_id, review.message_id, review.reviewer,
                 review.verdict, json.dumps(review.error_types), review.note,
                 _pg._iso_to_dt(review.created_at), _pg._iso_to_dt(review.updated_at),
                 _clip(review.question_snapshot), _clip(review.answer_snapshot)),
            )
            return cur.fetchone()["id"]

    def list_for_thread(self, thread_id: str) -> list[AnswerReview]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT * FROM answer_reviews WHERE thread_id = %s ORDER BY updated_at DESC",
                (thread_id,))
            rows = cur.fetchall()
        return [_pg_row_to_review(r) for r in rows]

    def list_since(self, since: Optional[str] = None, *, limit: int = 5000) -> list[AnswerReview]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            if since:
                cur.execute(
                    "SELECT * FROM answer_reviews WHERE updated_at >= %s "
                    "ORDER BY updated_at DESC LIMIT %s",
                    (_pg._iso_to_dt(since), limit))
            else:
                cur.execute(
                    "SELECT * FROM answer_reviews ORDER BY updated_at DESC LIMIT %s",
                    (limit,))
            rows = cur.fetchall()
        return [_pg_row_to_review(r) for r in rows]

    def reviewed_message_ids(self) -> set[str]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT DISTINCT message_id FROM answer_reviews")
            rows = cur.fetchall()
        return {r["message_id"] for r in rows}


def _pg_row_to_review(row) -> AnswerReview:
    from . import _pg
    return AnswerReview(
        id=row["id"], thread_id=row["thread_id"], message_id=row["message_id"],
        reviewer=row["reviewer"], verdict=row["verdict"],
        error_types=_types_from_json(row["error_types"]), note=row["note"],
        question_snapshot=row.get("question_snapshot"),
        answer_snapshot=row.get("answer_snapshot"),
        created_at=_pg._dt_to_iso(row["created_at"]),
        updated_at=_pg._dt_to_iso(row["updated_at"]),
    )
