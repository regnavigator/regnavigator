"""사용자 프로필(표시명·소속·직군) — repo 저장 + admin 이용조회 조인."""
from __future__ import annotations

import pytest

from src.persistence.users_repo import SqliteUsersRepo


@pytest.fixture()
def repo(tmp_path):
    return SqliteUsersRepo(str(tmp_path / "users.db"))


def test_set_profile_roundtrip(repo):
    repo.upsert(id="u1", email="doc@hospital.kr")
    repo.set_profile("u1", display_name="김의사", affiliation="화순전남대병원",
                     job_role="의사")
    u = repo.get("u1")
    assert (u.display_name, u.affiliation, u.job_role) == (
        "김의사", "화순전남대병원", "의사")


def test_set_profile_null_clears(repo):
    repo.upsert(id="u1", email="doc@hospital.kr")
    repo.set_profile("u1", display_name="김의사", affiliation="A병원", job_role=None)
    repo.set_profile("u1", display_name=None, affiliation=None, job_role=None)
    u = repo.get("u1")
    assert (u.display_name, u.affiliation, u.job_role) == (None, None, None)


def test_existing_db_migration(tmp_path):
    """구 스키마 DB 에 _post_init ALTER 가 프로필 컬럼을 추가한다."""
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE users (
             id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
             email_verified_at TEXT, is_admin INTEGER NOT NULL DEFAULT 0,
             daily_token_limit_override INTEGER, monthly_token_limit_override INTEGER,
             created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute(
        "INSERT INTO users VALUES ('u1','a@b.c',NULL,0,NULL,NULL,'t','t')")
    conn.commit()
    conn.close()

    repo = SqliteUsersRepo(str(db))
    u = repo.get("u1")
    assert u.affiliation is None  # 컬럼 생겼고 기본 NULL
    repo.set_profile("u1", display_name=None, affiliation="B제약", job_role="RA")
    assert repo.get("u1").affiliation == "B제약"
