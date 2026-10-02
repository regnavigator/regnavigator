"""WorkflowFilesRepo — 조합 단계에 붙인 첨부 본문 (2026-10-02).

채팅 첨부(`POST /files/extract`)는 **무상태**다 — 추출 텍스트를 프런트가 들고 있다가
전송 때만 보낸다. 조합은 그럴 수 없다: 단계를 짜 놓고 나중에 돌리거나, 짜다 말고
새로고침하거나, 다른 기기에서 이어서 하기 때문이다(사용자 선택: "스레드에 보관").

그래서 추출 텍스트를 여기 둔다. 사건 파일 원문이므로 **반드시 암호화**한다 —
`reports_repo` 의 `filled_values` 와 같은 `field_crypto` 경로를 쓴다.

파일 자체(원본 바이너리)는 여전히 저장하지 않는다. 추출된 텍스트만 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from . import field_crypto
from ._common import SqliteRepoBase
from ._common import new_id as _new_id
from ._common import utcnow_iso as _utcnow_iso
from .contacts_repo import _PgRepoBase


@dataclass
class WorkflowFile:
    id: str
    thread_id: str
    name: str
    chars: int
    text: str = ""
    created_at: str = field(default_factory=_utcnow_iso)

    def as_meta(self) -> dict:
        """조합 JSON 에 실리는 형태 — **본문은 빼고** 메타만."""
        return {"id": self.id, "name": self.name, "chars": self.chars}


class WorkflowFilesRepo(Protocol):
    def put(self, thread_id: str, name: str, text: str) -> WorkflowFile: ...
    def get_many(self, thread_id: str, ids: list[str]) -> list[WorkflowFile]: ...
    def delete(self, thread_id: str, file_id: str) -> bool: ...
    def delete_thread(self, thread_id: str) -> int: ...


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS workflow_files (
    id         TEXT PRIMARY KEY,
    thread_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    chars      INTEGER NOT NULL DEFAULT 0,
    text_enc   TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_workflow_files_thread
    ON workflow_files(thread_id);
"""


class SqliteWorkflowFilesRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def put(self, thread_id: str, name: str, text: str) -> WorkflowFile:
        f = WorkflowFile(id=f"wff_{_new_id()[:12]}", thread_id=thread_id,
                         name=name[:200], chars=len(text or ""), text=text or "")
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO workflow_files "
                "(id, thread_id, name, chars, text_enc, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f.id, f.thread_id, f.name, f.chars,
                 field_crypto.encrypt_text(f.text), f.created_at),
            )
        return f

    def get_many(self, thread_id: str, ids: list[str]) -> list[WorkflowFile]:
        """id 순서가 아니라 **요청한 순서**로 돌려준다 — 첨부 순서가 곧 맥락이다."""
        want = [i for i in dict.fromkeys(ids) if i]
        if not want:
            return []
        qs = ",".join("?" * len(want))
        with self._lock, self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM workflow_files "
                f"WHERE thread_id = ? AND id IN ({qs})",
                (thread_id, *want),
            ).fetchall()
        by_id = {
            r["id"]: WorkflowFile(
                id=r["id"], thread_id=r["thread_id"], name=r["name"],
                chars=int(r["chars"] or 0),
                text=field_crypto.decrypt_text(r["text_enc"]) or "",
                created_at=r["created_at"] or "",
            )
            for r in rows
        }
        return [by_id[i] for i in want if i in by_id]

    def delete(self, thread_id: str, file_id: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM workflow_files WHERE thread_id = ? AND id = ?",
                (thread_id, file_id))
            return bool(getattr(cur, "rowcount", 0))

    def delete_thread(self, thread_id: str) -> int:
        """스레드 삭제 시 함께 지운다 — 사건 파일이 고아로 남으면 안 된다."""
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM workflow_files WHERE thread_id = ?", (thread_id,))
            return int(getattr(cur, "rowcount", 0) or 0)


class PostgresWorkflowFilesRepo(_PgRepoBase, SqliteWorkflowFilesRepo):
    """PG 구현 — SQLite 본체를 그대로 쓰고 커서만 PG 로 바꾼다.

    `contacts_repo` 와 같은 어댑터를 재사용한다. 본문을 복제하면 한쪽만 고쳐져
    운영에서만 깨진다(`set_kind` 에서 겪은 전례).
    """
