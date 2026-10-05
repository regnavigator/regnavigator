"""TaskTemplatesRepo — 직무(task) 템플릿 (2026-10-06).

기능연계를 **이름 붙여 저장**한 것. `FEATURES.md` §11-b 가 처음부터 선언한 그대로 —
"task 는 조합 객체에 이름을 붙여 따로 저장하는 것"이다. 사용자 단위.

저장하는 것은 단계의 **기능 id 와 기밀 여부뿐**이다. 값(사실관계·쟁점)과 파일은 사건마다
다르고, 저장하면 다음 사건에서 지난 사건의 사실관계가 프롬프트에 섞인다(기밀 격리 위반
소지). 파일은 스레드 소속이라 옮길 수도 없다. 불러올 때 대화 내용으로 다시 채운다.

dev = SQLite, prod = Postgres(`_PgRepoBase` 어댑터 — 본체 복제 금지).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from ._common import SqliteRepoBase
from ._common import new_id as _new_id
from ._common import utcnow_iso as _utcnow_iso
from .contacts_repo import _PgRepoBase

#: 사용자당 상한 — 목록이 이걸 넘으면 첫 화면 타일이 의미를 잃는다.
MAX_PER_USER = 50
MAX_NAME_LEN = 80


@dataclass
class TaskTemplate:
    id: str
    user_id: str
    name: str
    #: [{"fn": str, "confidential": bool}, …] — 값·파일 없음
    steps: list[dict]
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "steps": self.steps,
                "created_at": self.created_at, "updated_at": self.updated_at}


class TaskTemplatesRepo(Protocol):
    def create(self, user_id: str, name: str, steps: list[dict]) -> TaskTemplate: ...
    def list_for_user(self, user_id: str) -> list[TaskTemplate]: ...
    def count_for_user(self, user_id: str) -> int: ...
    def rename(self, user_id: str, template_id: str, name: str) -> bool: ...
    def delete(self, user_id: str, template_id: str) -> bool: ...


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS task_templates (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    name       TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_templates_user
    ON task_templates(user_id, updated_at DESC);
"""


def strip_for_template(steps: list[dict]) -> list[dict]:
    """조합 단계 → 템플릿 단계. 값·파일·done 을 버리고 fn·confidential 만 남긴다."""
    out: list[dict] = []
    for st in steps or []:
        if not isinstance(st, dict):
            continue
        fn = str(st.get("fn") or "").strip()
        if fn:
            out.append({"fn": fn[:64], "confidential": bool(st.get("confidential"))})
    return out


def _row(r) -> TaskTemplate:
    try:
        steps = json.loads(r["steps_json"] or "[]")
    except (ValueError, TypeError):
        steps = []
    return TaskTemplate(
        id=r["id"], user_id=r["user_id"], name=r["name"],
        steps=steps if isinstance(steps, list) else [],
        created_at=r["created_at"] or "", updated_at=r["updated_at"] or "",
    )


class SqliteTaskTemplatesRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def create(self, user_id: str, name: str, steps: list[dict]) -> TaskTemplate:
        t = TaskTemplate(id=f"tt_{_new_id()[:12]}", user_id=user_id,
                         name=name.strip()[:MAX_NAME_LEN], steps=strip_for_template(steps))
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO task_templates "
                "(id, user_id, name, steps_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t.id, t.user_id, t.name, json.dumps(t.steps, ensure_ascii=False),
                 t.created_at, t.updated_at),
            )
        return t

    def list_for_user(self, user_id: str) -> list[TaskTemplate]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM task_templates WHERE user_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (user_id, MAX_PER_USER),
            ).fetchall()
        return [_row(r) for r in rows]

    def count_for_user(self, user_id: str) -> int:
        with self._lock, self._conn() as c:
            r = c.execute(
                "SELECT COUNT(*) AS n FROM task_templates WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(r["n"] if r else 0)

    def rename(self, user_id: str, template_id: str, name: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE task_templates SET name = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (name.strip()[:MAX_NAME_LEN], _utcnow_iso(), template_id, user_id),
            )
            return bool(getattr(cur, "rowcount", 0))

    def delete(self, user_id: str, template_id: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM task_templates WHERE id = ? AND user_id = ?",
                (template_id, user_id))
            return bool(getattr(cur, "rowcount", 0))


class PostgresTaskTemplatesRepo(_PgRepoBase, SqliteTaskTemplatesRepo):
    """PG 구현 — SQLite 본체를 그대로 쓰고 커서만 PG 로 바꾼다(`workflow_files_repo` 와 동일)."""
