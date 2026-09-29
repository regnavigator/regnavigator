"""PG 스키마 DDL 순서 회귀 — 2026-08-04 감사 C-2.

사고: `CREATE INDEX ... ON chat_messages` 가 `CREATE TABLE chat_messages` 보다
**위**에 있었다. `init_schema` 는 `_DDL` 전체를 한 번의 execute 로 보내므로 빈
DB 에서는 그 줄이 `relation does not exist` 로 실패하고 배치 전체가 중단 —
아래 테이블(chat_steps·beta_whitelist·app_settings)까지 생성되지 않았다.

운영 DB 는 테이블이 이미 있어 `IF NOT EXISTS` 로 통과했기 때문에 **재해복구·
신규 리전·fresh CI 에서만** 터지는 상태였다. PG 통합 테스트는 MEDI_TEST_PG_DSN
있을 때만 도는 skip 이라 CI 가 이 경로를 한 번도 실행하지 않는다 → 실 DB 없이
DDL 텍스트만으로 순서를 검증한다.
"""
from __future__ import annotations

import re


def _statements() -> list[str]:
    from src.persistence._pg import _DDL

    out = []
    for raw in _DDL.split(";"):
        s = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("--")
        ).strip()
        if s:
            out.append(s)
    return out


def test_every_index_and_alter_follows_its_table():
    created: set[str] = set()
    violations: list[str] = []

    for s in _statements():
        m = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", s, re.I)
        if m:
            created.add(m.group(1))
            continue

        m = re.match(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS \w+\s+ON (\w+)", s, re.I | re.S)
        if m and m.group(1) not in created:
            violations.append(f"INDEX before TABLE {m.group(1)}: {s.splitlines()[0]}")

        m = re.match(r"ALTER TABLE (\w+)", s, re.I)
        if m and m.group(1) not in created:
            violations.append(f"ALTER before TABLE {m.group(1)}: {s.splitlines()[0]}")

    assert not violations, (
        "DDL 순서 오류 — 빈 DB 에서 init_schema 가 통째로 실패한다:\n  "
        + "\n  ".join(violations)
    )


def test_ddl_covers_expected_tables():
    """테이블이 누락되거나 이름이 바뀌면 위 순서 검사가 조용히 무의미해지는 것 방지."""
    created = {
        m.group(1)
        for s in _statements()
        if (m := re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", s, re.I))
    }
    expected = {
        "users", "events", "feedback", "reports", "report_runs", "bookmarks",
        "chat_threads", "chat_messages", "chat_steps", "beta_whitelist",
        "app_settings",
    }
    assert expected <= created, f"DDL 에서 사라진 테이블: {sorted(expected - created)}"
