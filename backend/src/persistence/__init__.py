"""영속 레이어 — 보고서 본문(BlobStore) + 메타(ReportsRepo) 추상화.

env로 백엔드 스위치:
- `BLOB_BACKEND`     = local | gcs                 (기본: local)
- `BLOB_LOCAL_DIR`   = ./reports_blobs              (local 기본)
- `BLOB_GCS_BUCKET`  = medi-reports                 (gcs 사용 시)
- `REPORTS_BACKEND`  = sqlite | postgres            (기본: sqlite)
- `REPORTS_SQLITE_PATH` = ./medi_reports.db         (sqlite 기본)
- `REPORTS_PG_DSN`   = postgresql://... (postgres 사용 시)

dev = local + sqlite. production = gcs + postgres. 코드 변경 0줄 — env 한 줄.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .blobs import BlobStore, GCSBlobStore, LocalBlobStore
from .events_repo import (
    Event,
    EventsRepo,
    PostgresEventsRepo,
    SqliteEventsRepo,
    start_of_month_local_iso,
    start_of_month_utc_iso,
    start_of_today_local_iso,
    start_of_today_utc_iso,
)
from .answer_reviews_repo import (
    AnswerReview,
    AnswerReviewsRepo,
    PostgresAnswerReviewsRepo,
    SqliteAnswerReviewsRepo,
)
from .feedback_repo import (
    Feedback,
    FeedbackRepo,
    PostgresFeedbackRepo,
    SqliteFeedbackRepo,
)
from .bookmarks_repo import (
    Bookmark,
    BookmarksRepo,
    PostgresBookmarksRepo,
    SqliteBookmarksRepo,
)
from .report_runs_repo import (
    PostgresReportRunsRepo,
    ReportRun,
    ReportRunsRepo,
    SqliteReportRunsRepo,
)
from .reports_repo import (
    PostgresReportsRepo,
    ReportMeta,
    ReportsRepo,
    SqliteReportsRepo,
)
from .users_repo import (
    PostgresUsersRepo,
    SqliteUsersRepo,
    User,
    UsersRepo,
)


@lru_cache(maxsize=1)
def get_blob_store() -> BlobStore:
    backend = (os.getenv("BLOB_BACKEND") or "local").lower()
    if backend == "gcs":
        bucket = os.environ["BLOB_GCS_BUCKET"]
        return GCSBlobStore(bucket=bucket)
    if backend == "local":
        root = os.getenv("BLOB_LOCAL_DIR") or "./reports_blobs"
        return LocalBlobStore(root=root)
    raise ValueError(f"Unknown BLOB_BACKEND: {backend!r} (expected local|gcs)")


def _backend() -> str:
    return (os.getenv("REPORTS_BACKEND") or "sqlite").lower()


def _sqlite_path() -> str:
    return os.getenv("REPORTS_SQLITE_PATH") or "./medi_reports.db"


@lru_cache(maxsize=1)
def get_reports_repo() -> ReportsRepo:
    if _backend() == "postgres":
        return PostgresReportsRepo(dsn=os.environ["REPORTS_PG_DSN"])
    if _backend() == "sqlite":
        return SqliteReportsRepo(path=_sqlite_path())
    raise ValueError(f"Unknown REPORTS_BACKEND: {_backend()!r}")


@lru_cache(maxsize=1)
def get_users_repo() -> UsersRepo:
    if _backend() == "postgres":
        return PostgresUsersRepo(dsn=os.environ["REPORTS_PG_DSN"])
    if _backend() == "sqlite":
        return SqliteUsersRepo(path=_sqlite_path())
    raise ValueError(f"Unknown REPORTS_BACKEND: {_backend()!r}")


@lru_cache(maxsize=1)
def get_events_repo() -> EventsRepo:
    if _backend() == "postgres":
        return PostgresEventsRepo(dsn=os.environ["REPORTS_PG_DSN"])
    if _backend() == "sqlite":
        return SqliteEventsRepo(path=_sqlite_path())
    raise ValueError(f"Unknown REPORTS_BACKEND: {_backend()!r}")


@lru_cache(maxsize=1)
def get_feedback_repo() -> FeedbackRepo:
    if _backend() == "postgres":
        return PostgresFeedbackRepo(dsn=os.environ["REPORTS_PG_DSN"])
    if _backend() == "sqlite":
        return SqliteFeedbackRepo(path=_sqlite_path())
    raise ValueError(f"Unknown REPORTS_BACKEND: {_backend()!r}")


@lru_cache(maxsize=1)
def get_answer_reviews_repo() -> AnswerReviewsRepo:
    if _backend() == "postgres":
        return PostgresAnswerReviewsRepo(dsn=os.environ["REPORTS_PG_DSN"])
    if _backend() == "sqlite":
        return SqliteAnswerReviewsRepo(path=_sqlite_path())
    raise ValueError(f"Unknown REPORTS_BACKEND: {_backend()!r}")


@lru_cache(maxsize=1)
def get_bookmarks_repo() -> BookmarksRepo:
    if _backend() == "postgres":
        return PostgresBookmarksRepo(dsn=os.environ["REPORTS_PG_DSN"])
    if _backend() == "sqlite":
        return SqliteBookmarksRepo(path=_sqlite_path())
    raise ValueError(f"Unknown REPORTS_BACKEND: {_backend()!r}")


@lru_cache(maxsize=1)
def get_report_runs_repo() -> ReportRunsRepo:
    if _backend() == "postgres":
        return PostgresReportRunsRepo(dsn=os.environ["REPORTS_PG_DSN"])
    if _backend() == "sqlite":
        return SqliteReportRunsRepo(path=_sqlite_path())
    raise ValueError(f"Unknown REPORTS_BACKEND: {_backend()!r}")


__all__ = [
    "BlobStore",
    "ReportsRepo",
    "ReportMeta",
    "User",
    "UsersRepo",
    "Event",
    "EventsRepo",
    "AnswerReview",
    "AnswerReviewsRepo",
    "Feedback",
    "FeedbackRepo",
    "Bookmark",
    "BookmarksRepo",
    "get_bookmarks_repo",
    "ReportRun",
    "ReportRunsRepo",
    "start_of_today_utc_iso",
    "start_of_month_utc_iso",
    "start_of_today_local_iso",
    "start_of_month_local_iso",
    "get_blob_store",
    "get_reports_repo",
    "get_users_repo",
    "get_events_repo",
    "get_answer_reviews_repo",
    "get_feedback_repo",
    "get_report_runs_repo",
]
