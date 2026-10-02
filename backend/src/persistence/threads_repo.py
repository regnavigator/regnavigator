"""ThreadsRepo — 자체 `/chat` 루프의 thread 상태 영속 (ADR-0001 Phase 1).

langgraph checkpointer 를 대체한다. 저장 단위:
- `chat_messages`  : 직렬화된 langchain 메시지(human/ai/tool) — seq 오름차순이 대화.
- `chat_steps`     : Step dict (id 로 merge — `merge_steps_by_id` 의미론을 SQL upsert 로).
- `chat_threads`   : thread 메타 + `selected_law_keys`(keep_last_selection 의미론 —
                     None 이면 미변경, 리스트(빈 것 포함)면 교체).

메시지 직렬화는 langchain-core 표준 `message_to_dict`/`messages_from_dict` —
tool_calls·id 등 필드 보존. content 에 PII 가 없도록 **호출자(chat_loop)가 저장 전
스크럽**한다(at-rest 정책, PiiGate 와 동일).

백엔드: dev=SQLite (REPORTS_BACKEND 스위치 공유). Postgres 구현은 Phase 3
(보고서 잡러너 이전)에서 함께 — 그 전까지 postgres 백엔드에서 /chat PoC 호출 시
fail-fast (조용한 메모리/SQLite 폴백 금지 — checkpointer 와 동일 원칙).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict

from ._common import SqliteRepoBase, new_id, utcnow_iso


def match_excerpt(content: str, query: str, *, width: int = 42) -> str:
    """검색어 주변 발췌(양옆 width자, 말줄임). 없으면 앞부분.

    왜: 검색 결과가 제목만이면 비슷한 제목이 여러 개일 때 어느 대화인지 못
    고른다("의료기기 GMP …" 5건). 어디가 걸렸는지 보여야 결과가 쓸모 있다.
    """
    text = " ".join((content or "").split())
    if not text:
        return ""
    i = text.lower().find((query or "").lower().strip())
    if i < 0:
        return text[: width * 2] + ("…" if len(text) > width * 2 else "")
    start = max(0, i - width)
    end = min(len(text), i + len(query) + width)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def _content_of(data_json: str) -> str:
    """저장된 메시지 JSON → content 문자열(블록 리스트면 text 이어붙임)."""
    try:
        d = json.loads(data_json) if isinstance(data_json, str) else (data_json or {})
    except (ValueError, TypeError):
        return ""
    c = ((d.get("data") or {}).get("content")) if isinstance(d, dict) else None
    if isinstance(c, list):
        return "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


@dataclass
class ThreadState:
    """한 thread 의 복원된 상태 — chat_loop 가 소비하는 형태.

    `seqs` 는 `messages` 와 병렬(저장 seq) — 대화 압축이 컷 지점을 영속하는 데 씀.
    `summary_text`/`summary_upto_seq` 는 압축 요약: seq ≤ upto 인 메시지는 요약으로
    대체돼 프롬프트에서 빠진다(DB 원본은 보존).
    """

    thread_id: str
    messages: list[BaseMessage]
    steps: list[dict]
    selected_law_keys: list[str]
    seqs: list[int] = None  # type: ignore[assignment]
    summary_text: Optional[str] = None
    summary_upto_seq: Optional[int] = None
    #: `messages` 와 병렬 — 기밀 턴에서 나온 메시지인가. 비기밀 턴의 컨텍스트에서
    #: 뺄 때 쓴다. 과거 데이터는 전부 False(기밀 기능 도입 전).
    sensitive: list[bool] = None  # type: ignore[assignment]
    #: `messages` 와 병렬 — 조합의 중간 단계라 채팅에 렌더하지 않는 메시지인가.
    #: 모델 컨텍스트에는 **그대로 들어간다**(숨김은 렌더 계층의 일이다).
    hidden: list[bool] = None  # type: ignore[assignment]

    def as_tool_state(self) -> dict:
        """도구 코어(_count_tool_calls·step_start·번호매김)가 기대하는 state dict."""
        return {
            "messages": self.messages,
            "steps": self.steps,
            "selected_law_keys": self.selected_law_keys,
        }


# ── 기밀 메시지 at-rest 암호화 (2026-10-03) ─────────────────────────────────
#
# 감사: 서식 한 칸(`filled_values`)은 암호화하면서 **사건 사실관계 전문**인
# `chat_messages.data_json` 은 평문이었다. `sensitive=1` 행만 `field_crypto` 로
# 감싼다 — 비기밀 행은 그대로(검색 LIKE·관리자 조회가 걸려 있다).
#
# 저장 형태: `{"enc": "<암호문>"}` — PG 의 JSONB 컬럼과 호환되고, 읽을 때 키로
# 구분한다. 키가 없는 dev 는 `encrypt_text` 가 평문을 돌려주므로 그냥 dict 다.

def _dump_message(m: BaseMessage, sensitive: bool) -> str:
    raw = json.dumps(message_to_dict(m), ensure_ascii=False)
    if not sensitive:
        return raw
    from . import field_crypto

    enc = field_crypto.encrypt_text(raw)
    if enc == raw:  # 키 없음(dev) — 평문 그대로
        return raw
    return json.dumps({"enc": enc})


def _load_message(stored) -> dict:
    """저장값(str 또는 PG dict) → langchain 메시지 dict. 암호문이면 복호."""
    d = json.loads(stored) if isinstance(stored, str) else stored
    if isinstance(d, dict) and set(d.keys()) == {"enc"}:
        from . import field_crypto

        return json.loads(field_crypto.decrypt_text(d["enc"]) or "{}")
    return d


def _loads_workflow(raw) -> Optional[dict]:
    """저장된 조합 역직렬화 — 깨진 값은 조용히 None(기능만 꺼진다).

    스키마 정규화는 `src.workflow` 가 단일 진실원이다. 구버전(문자열 배열)도
    거기서 객체로 승격된다.
    """
    if not raw:
        return None
    from src.workflow import normalize

    try:
        return normalize(raw)
    except Exception:
        # 저장된 값이 상한을 넘더라도 읽기는 막지 않는다 — 조합만 안 보이면 된다.
        return None


class SqliteThreadsRepo(SqliteRepoBase):
    _schema = """
    CREATE TABLE IF NOT EXISTS chat_threads (
        id                TEXT PRIMARY KEY,
        user_id           TEXT,
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL,
        selected_law_keys TEXT
    );
    CREATE TABLE IF NOT EXISTS chat_messages (
        id         TEXT PRIMARY KEY,
        thread_id  TEXT NOT NULL,
        seq        INTEGER NOT NULL,
        data_json  TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_thread_seq
        ON chat_messages(thread_id, seq);
    CREATE TABLE IF NOT EXISTS chat_steps (
        thread_id  TEXT NOT NULL,
        step_id    TEXT NOT NULL,
        data_json  TEXT NOT NULL,
        ts         INTEGER,
        PRIMARY KEY (thread_id, step_id)
    );
    """

    def _post_init(self, conn) -> None:
        # 요약(Phase 2)·제목(FE 사이드바, Phase 4 준비) 컬럼 — dev DB 마이그레이션.
        for ddl in (
            "ALTER TABLE chat_threads ADD COLUMN summary_text TEXT",
            "ALTER TABLE chat_threads ADD COLUMN summary_upto_seq INTEGER",
            "ALTER TABLE chat_threads ADD COLUMN title TEXT",
            "ALTER TABLE chat_threads ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
            # 기밀 턴 이력(2026-10-01) — 한 번이라도 기밀로 처리된 스레드는 이후
            # 기밀을 끌 때 경고한다. 저장된 이전 대화가 통째로 상용 모델로 가기
            # 때문이다. 클라이언트만 믿으면 새로고침·다른 기기에서 뚫린다.
            "ALTER TABLE chat_threads ADD COLUMN confidential_seen INTEGER NOT NULL DEFAULT 0",
            # 스레드 종류(2026-10-02) — 'chat' | 'monitor'. 모니터링 대상 하나가
            # 스레드 하나다(docs/spec/monitor-threads-design.md).
            "ALTER TABLE chat_threads ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'",
            # 기밀 단계 격리(2026-10-02) — 이 메시지가 기밀 턴에서 나왔는가.
            #
            # 없으면 **단계별 기밀이 거짓말이 된다**: 비기밀 턴은 요청 컨텍스트로
            # 스레드 전체를 보내므로, 앞 기밀 단계 내용이 그대로 상용 모델로
            # 나간다. 이 컬럼이 그 필터의 기준이다.
            "ALTER TABLE chat_messages ADD COLUMN sensitive INTEGER NOT NULL DEFAULT 0",
            # 조합의 중간 단계(2026-10-02) — 채팅에 **렌더하지 않는다**.
            #
            # 조합은 단계마다 답을 쏟지 않고 마지막에 한 번만 종합해 보여 준다.
            # 단계를 숨은 턴으로 돌리면 검색 강제·인용 번호·기밀 라우팅을 그대로
            # 쓰면서 화면만 깨끗해진다. 지우는 게 아니라 접는 것 — "과정 보기"로
            # 펼쳐 볼 수 있다.
            "ALTER TABLE chat_messages ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0",
            # 기능 조합 워크플로(2026-10-02) — {"steps": [feature_id], "cursor": n}.
            # 스레드에 둔다: 새로고침·다른 기기에서도 진행 중인 단계가 살아야 한다.
            "ALTER TABLE chat_threads ADD COLUMN workflow_json TEXT",
            "CREATE INDEX IF NOT EXISTS idx_chat_threads_user "
            "ON chat_threads(user_id, pinned DESC, updated_at DESC)",
        ):
            try:
                conn.execute(ddl)
            except Exception:
                pass  # 이미 존재

    # ── thread ──────────────────────────────────────────────────────
    def ensure_thread(self, thread_id: str, *, user_id: Optional[str] = None) -> None:
        now = utcnow_iso()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO chat_threads (id, user_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at",
                (thread_id, user_id, now, now),
            )

    def get_state(self, thread_id: str) -> ThreadState:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT seq, data_json, COALESCE(sensitive, 0) AS sensitive, "
                "COALESCE(hidden, 0) AS hidden "
                "FROM chat_messages WHERE thread_id = ? ORDER BY seq",
                (thread_id,),
            ).fetchall()
            step_rows = c.execute(
                "SELECT data_json FROM chat_steps WHERE thread_id = ? "
                "ORDER BY COALESCE(ts, 0), step_id",
                (thread_id,),
            ).fetchall()
            t = c.execute(
                "SELECT selected_law_keys, summary_text, summary_upto_seq "
                "FROM chat_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        messages = messages_from_dict([_load_message(r["data_json"]) for r in rows])
        seqs = [int(r["seq"]) for r in rows]
        steps = [json.loads(r["data_json"]) for r in step_rows]
        selected: list[str] = []
        if t and t["selected_law_keys"]:
            try:
                selected = [k for k in json.loads(t["selected_law_keys"]) if k]
            except (json.JSONDecodeError, TypeError):
                selected = []
        return ThreadState(
            thread_id=thread_id, messages=messages, steps=steps,
            selected_law_keys=selected, seqs=seqs,
            summary_text=(t["summary_text"] if t else None),
            summary_upto_seq=(t["summary_upto_seq"] if t else None),
            sensitive=[bool(r["sensitive"]) for r in rows],
            hidden=[bool(r["hidden"]) for r in rows],
        )

    def set_summary(self, thread_id: str, text: str, upto_seq: int) -> None:
        """대화 압축 요약 영속 — seq ≤ upto_seq 메시지는 프롬프트에서 요약으로 대체."""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE chat_threads SET summary_text = ?, summary_upto_seq = ?, "
                "updated_at = ? WHERE id = ?",
                (text, int(upto_seq), utcnow_iso(), thread_id),
            )

    def set_selected_law_keys(
        self, thread_id: str, keys: Optional[list[str]]
    ) -> None:
        """keep_last_selection 의미론 — None=미변경(no-op), 리스트=교체(빈 리스트=해제)."""
        if keys is None:
            return
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE chat_threads SET selected_law_keys = ?, updated_at = ? "
                "WHERE id = ?",
                (json.dumps(list(keys), ensure_ascii=False), utcnow_iso(), thread_id),
            )

    # ── FE 조회 (사이드바·리로드) ──────────────────────────────────
    def get_meta(self, thread_id: str) -> Optional[dict]:
        """thread 메타 1건 — 소유자 검사·제목 표시용. 없으면 None."""
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id, user_id, title, created_at, updated_at, "
                "COALESCE(confidential_seen, 0) AS confidential_seen, "
                "COALESCE(kind, 'chat') AS kind "
                "FROM chat_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_kind(self, thread_id: str, kind: str) -> None:
        """스레드 종류 지정 — 'chat' | 'monitor' (2026-10-02)."""
        with self._lock, self._conn() as c:
            c.execute("UPDATE chat_threads SET kind = ? WHERE id = ?",
                      (kind, thread_id))

    def get_workflow(self, thread_id: str) -> Optional[dict]:
        """진행 중인 기능 조합 — {"steps": [...], "cursor": n}. 없으면 None."""
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT workflow_json FROM chat_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        return _loads_workflow(row["workflow_json"] if row else None)

    def set_workflow(self, thread_id: str, workflow: Optional[dict]) -> None:
        """조합 진행 상태 저장. None 이면 비운다(조합 종료)."""
        raw = json.dumps(workflow, ensure_ascii=False) if workflow else None
        with self._lock, self._conn() as c:
            c.execute("UPDATE chat_threads SET workflow_json = ? WHERE id = ?",
                      (raw, thread_id))

    def mark_confidential(self, thread_id: str) -> None:
        """이 스레드에 기밀 턴이 있었음을 기록한다(되돌리지 않는다)."""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE chat_threads SET confidential_seen = 1 WHERE id = ?",
                (thread_id,),
            )

    def set_title(self, thread_id: str, title: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE chat_threads SET title = ?, updated_at = ? WHERE id = ?",
                (title[:60], utcnow_iso(), thread_id),
            )

    def delete_thread(self, thread_id: str) -> None:
        """thread 완전 삭제 — 메시지·steps 포함(FE 사이드바 삭제)."""
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
            c.execute("DELETE FROM chat_steps WHERE thread_id = ?", (thread_id,))
            c.execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))

    def stale_thread_ids(self, *, cutoff_iso: str, limit: int = 5000) -> list[str]:
        """마지막 활동(updated_at)이 cutoff 이전인 thread id — 보존정리용."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id FROM chat_threads WHERE updated_at < ? LIMIT ?",
                (cutoff_iso, int(limit)),
            ).fetchall()
        return [r["id"] for r in rows]

    def list_for_user(self, user_id: Optional[str], *, limit: int = 50) -> list[dict]:
        """사용자의 thread 목록(최근 갱신순) — 사이드바용."""
        with self._lock, self._conn() as c:
            if user_id is None:  # dev 무인증 — 전체(로컬 개발 편의)
                rows = c.execute(
                    "SELECT id, user_id, title, created_at, updated_at, "
                    "COALESCE(pinned, 0) AS pinned, COALESCE(kind, 'chat') AS kind FROM chat_threads "
                    "ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT id, user_id, title, created_at, updated_at, "
                    "COALESCE(pinned, 0) AS pinned, COALESCE(kind, 'chat') AS kind FROM chat_threads WHERE user_id = ? "
                    "ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        # pinned 를 bool 로 정규화.
        out = []
        for r in rows:
            d = dict(r)
            d["pinned"] = bool(d.get("pinned"))
            out.append(d)
        return out

    def set_pinned(self, thread_id: str, pinned: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE chat_threads SET pinned = ? WHERE id = ?",
                (1 if pinned else 0, thread_id),
            )

    def list_admin(self, *, limit: int = 100, offset: int = 0,
                   since: Optional[str] = None,
                   exclude_prefixes: tuple = (),
                   require_user: bool = False,
                   exclude_user_ids: tuple = ()) -> tuple[list[dict], int]:
        """관리자 대화 목록(최근 갱신순) — 필터를 SQL 로 내려 페이지네이션.

        종전 라우트는 '최근 N개'를 먼저 뽑고 사후 필터해, 내부(qreg_·bench_)
        트래픽이 상한을 잡아먹으면 그보다 오래된 실사용 대화가 아예 안 읽혔다
        (2026-08-20). 반환: (rows, total) — total 은 같은 조건 전체 건수.
        """
        where, params = ["1=1"], []
        if since:
            where.append("updated_at >= ?")
            params.append(since)
        for p in exclude_prefixes:
            # LIKE 는 접두의 `_` 가 와일드카드 — SUBSTR 정확 일치로 거른다.
            where.append("SUBSTR(id, 1, ?) <> ?")
            params.extend([len(p), p])
        if require_user:
            # dev 우회 계정 제외(2026-08-27) — 로컬 e2e 산물이 실사용 목록에
            # 섞이던 재발 원인.
            where.append("user_id IS NOT NULL AND user_id <> 'dev-bypass-user'")
        if exclude_user_ids:
            # 내부 계정(운영진·테스트, account_class) 제외(2026-09-22) — 종전엔 접두·익명만
            # 걸러 관리자 본인 대화가 '실사용만' 목록에 섞였다.
            ids = list(exclude_user_ids)
            where.append(f"(user_id IS NULL OR user_id NOT IN ({','.join('?' * len(ids))}))")
            params.extend(ids)
        cond = " AND ".join(where)
        with self._lock, self._conn() as c:
            total = c.execute(
                f"SELECT COUNT(*) AS n FROM chat_threads WHERE {cond}",
                params,
            ).fetchone()["n"]
            rows = c.execute(
                f"SELECT id, user_id, title, created_at, updated_at "
                f"FROM chat_threads WHERE {cond} "
                f"ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*params, int(limit), int(offset)),
            ).fetchall()
        return [dict(r) for r in rows], int(total)

    def search_messages(self, user_id: Optional[str], query: str, *, limit: int = 30) -> list[dict]:
        """대화 본문(human/ai content)에 query 포함하는 thread — DISTINCT, 최근순.

        ⚠️ raw data_json LIKE 금지 — tool 메시지엔 검색 결과 법령 원문이 통째로
        들어 있어 2자 질의면 거의 모든 thread 가 매치, 사이드바 검색이 "풀린
        것처럼" 전체 목록이 복귀했다(실측 피드백 2026-07-24). 사용자가 실제로
        주고받은 human/ai content 만 대상으로 한다."""
        like = f"%{query}%"
        base = (
            "SELECT DISTINCT t.id, t.user_id, t.title, t.created_at, t.updated_at, "
            "COALESCE(t.pinned,0) AS pinned, COALESCE(t.kind, 'chat') AS kind "
            "FROM chat_threads t "
            "JOIN chat_messages m ON m.thread_id = t.id WHERE "
            "json_extract(m.data_json, '$.type') IN ('human','ai') "
            "AND json_extract(m.data_json, '$.data.content') LIKE ? AND "
        )
        tail = " ORDER BY pinned DESC, t.updated_at DESC LIMIT ?"
        with self._lock, self._conn() as c:
            if user_id is None:
                rows = c.execute(base + "1=1" + tail, (like, limit)).fetchall()
            else:
                rows = c.execute(
                    base + "t.user_id = ?" + tail,
                    (like, user_id, limit),
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["pinned"] = bool(d.get("pinned"))
            out.append(d)
        # 매칭 발췌 — thread 당 최근 1건. 제목만으론 어느 대화인지 못 고른다.
        if out:
            ids = [d["id"] for d in out]
            ph = ",".join("?" * len(ids))
            with self._lock, self._conn() as c:
                mrows = c.execute(
                    f"SELECT thread_id, data_json FROM chat_messages "
                    f"WHERE thread_id IN ({ph}) "
                    f"AND json_extract(data_json, '$.type') IN ('human','ai') "
                    f"AND json_extract(data_json, '$.data.content') LIKE ? "
                    f"ORDER BY seq DESC",
                    (*ids, like),
                ).fetchall()
            best: dict[str, str] = {}
            for m in mrows:
                tid = m["thread_id"]
                if tid not in best:
                    best[tid] = match_excerpt(_content_of(m["data_json"]), query)
            for d in out:
                d["match_snippet"] = best.get(d["id"], "")
        return out

    # ── messages ────────────────────────────────────────────────────
    def append_messages(self, thread_id: str, messages: list[BaseMessage],
                        *, sensitive: bool = False, hidden: bool = False) -> None:
        """메시지 적재.

        `sensitive=True` 면 기밀 턴 산출(비기밀 턴 컨텍스트에서 빠진다),
        `hidden=True` 면 조합의 중간 단계(채팅에 렌더하지 않는다).
        """
        if not messages:
            return
        now = utcnow_iso()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT COALESCE(MAX(seq), -1) AS mx FROM chat_messages "
                "WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            seq = int(row["mx"]) + 1
            for m in messages:
                c.execute(
                    "INSERT INTO chat_messages "
                    "(id, thread_id, seq, data_json, created_at, sensitive, hidden) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        getattr(m, "id", None) or new_id(),
                        thread_id,
                        seq,
                        _dump_message(m, sensitive),
                        now,
                        1 if sensitive else 0,
                        1 if hidden else 0,
                    ),
                )
                seq += 1
            c.execute(
                "UPDATE chat_threads SET updated_at = ? WHERE id = ?", (now, thread_id)
            )

    def message_created_at(self, thread_id: str) -> dict[str, str]:
        """메시지 id → 저장 시각(ISO). 관리자 뷰의 턴 소요시간 계산용(2026-09-15).

        get_state 가 돌려주는 langchain 메시지에는 created_at 이 없어 별도로 읽는다.
        """
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT id, created_at FROM chat_messages WHERE thread_id = ? ORDER BY seq",
                (thread_id,),
            ).fetchall()
        return {r["id"]: r["created_at"] for r in rows if r["id"]}

    def replace_message(self, thread_id: str, message: BaseMessage) -> bool:
        """같은 id 의 저장 메시지를 통째로 교체(seq 유지). 없으면 False.

        (2026-09-15) 스킬 판정 가드 — AI 메시지는 스트림 직후 저장되는데 가드
        문구는 그 뒤에 붙는다. 갱신하지 않으면 새로고침 본문·다음 턴 컨텍스트에
        EXEMPT 원문만 남는다.
        """
        mid = getattr(message, "id", None)
        if not mid:
            return False
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE chat_messages SET data_json = ? WHERE thread_id = ? AND id = ?",
                (json.dumps(message_to_dict(message), ensure_ascii=False), thread_id, mid),
            )
            return cur.rowcount > 0

    # ── steps ───────────────────────────────────────────────────────
    def merge_steps(self, thread_id: str, steps: list[dict]) -> None:
        """`merge_steps_by_id` 의미론 — 같은 step_id 는 필드 단위로 merge(나중 우선)."""
        if not steps:
            return
        with self._lock, self._conn() as c:
            for s in steps:
                sid = s.get("id")
                if not sid:
                    continue
                row = c.execute(
                    "SELECT data_json FROM chat_steps "
                    "WHERE thread_id = ? AND step_id = ?",
                    (thread_id, sid),
                ).fetchone()
                merged = {**(json.loads(row["data_json"]) if row else {}), **s}
                c.execute(
                    "INSERT INTO chat_steps (thread_id, step_id, data_json, ts) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(thread_id, step_id) DO UPDATE SET "
                    "data_json = excluded.data_json, ts = excluded.ts",
                    (
                        thread_id, sid,
                        json.dumps(merged, ensure_ascii=False),
                        merged.get("ts", merged.get("ended_at")),
                    ),
                )


class PostgresThreadsRepo:
    """Postgres 본체 구현 — Sqlite 와 동일 인터페이스 (`_pg` 헬퍼 사용)."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    # ── thread ──────────────────────────────────────────────────────
    def ensure_thread(self, thread_id: str, *, user_id: Optional[str] = None) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "INSERT INTO chat_threads (id, user_id) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET updated_at = NOW()",
                (thread_id, user_id),
            )

    def get_state(self, thread_id: str) -> ThreadState:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT seq, data_json, COALESCE(sensitive, FALSE) AS sensitive, "
                "COALESCE(hidden, FALSE) AS hidden "
                "FROM chat_messages WHERE thread_id = %s ORDER BY seq",
                (thread_id,),
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT data_json FROM chat_steps WHERE thread_id = %s "
                "ORDER BY COALESCE(ts, 0), step_id",
                (thread_id,),
            )
            step_rows = cur.fetchall()
            cur.execute(
                "SELECT selected_law_keys, summary_text, summary_upto_seq "
                "FROM chat_threads WHERE id = %s",
                (thread_id,),
            )
            t = cur.fetchone()
        # JSONB 는 psycopg 가 이미 파싱해 dict/list 로 반환.
        messages = messages_from_dict([_load_message(r["data_json"]) for r in rows])
        seqs = [int(r["seq"]) for r in rows]
        steps = [r["data_json"] for r in step_rows]
        selected = [k for k in ((t or {}).get("selected_law_keys") or []) if k]
        return ThreadState(
            thread_id=thread_id, messages=messages, steps=steps,
            selected_law_keys=selected, seqs=seqs,
            summary_text=(t or {}).get("summary_text"),
            summary_upto_seq=(t or {}).get("summary_upto_seq"),
            sensitive=[bool(r["sensitive"]) for r in rows],
            hidden=[bool(r["hidden"]) for r in rows],
        )

    def set_selected_law_keys(
        self, thread_id: str, keys: Optional[list[str]]
    ) -> None:
        if keys is None:
            return
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE chat_threads SET selected_law_keys = %s::jsonb, "
                "updated_at = NOW() WHERE id = %s",
                (json.dumps(list(keys), ensure_ascii=False), thread_id),
            )

    def set_summary(self, thread_id: str, text: str, upto_seq: int) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE chat_threads SET summary_text = %s, summary_upto_seq = %s, "
                "updated_at = NOW() WHERE id = %s",
                (text, int(upto_seq), thread_id),
            )

    def set_kind(self, thread_id: str, kind: str) -> None:
        """스레드 종류 지정 — 'chat' | 'monitor' (2026-10-02)."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE chat_threads SET kind = %s WHERE id = %s",
                        (kind, thread_id))

    def get_workflow(self, thread_id: str) -> Optional[dict]:
        """진행 중인 기능 조합 — {"steps": [...], "cursor": n}. 없으면 None."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT workflow_json FROM chat_threads WHERE id = %s",
                        (thread_id,))
            row = cur.fetchone()
        return _loads_workflow(dict(row)["workflow_json"] if row else None)

    def set_workflow(self, thread_id: str, workflow: Optional[dict]) -> None:
        """조합 진행 상태 저장. None 이면 비운다(조합 종료)."""
        from . import _pg
        raw = json.dumps(workflow, ensure_ascii=False) if workflow else None
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE chat_threads SET workflow_json = %s WHERE id = %s",
                        (raw, thread_id))

    def mark_confidential(self, thread_id: str) -> None:
        """이 스레드에 기밀 턴이 있었음을 기록한다(되돌리지 않는다)."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE chat_threads SET confidential_seen = 1 WHERE id = %s",
                (thread_id,),
            )

    # ── FE 조회 (사이드바·리로드) ──────────────────────────────────
    def get_meta(self, thread_id: str) -> Optional[dict]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT id, user_id, title, created_at, updated_at, "
                "COALESCE(confidential_seen, 0) AS confidential_seen, "
                "COALESCE(kind, 'chat') AS kind "
                "FROM chat_threads WHERE id = %s", (thread_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        row = dict(row)
        row["created_at"] = _pg._dt_to_iso(row["created_at"])
        row["updated_at"] = _pg._dt_to_iso(row["updated_at"])
        return row

    def set_title(self, thread_id: str, title: str) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE chat_threads SET title = %s, updated_at = NOW() WHERE id = %s",
                (title[:60], thread_id),
            )

    def delete_thread(self, thread_id: str) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("DELETE FROM chat_messages WHERE thread_id = %s", (thread_id,))
            cur.execute("DELETE FROM chat_steps WHERE thread_id = %s", (thread_id,))
            cur.execute("DELETE FROM chat_threads WHERE id = %s", (thread_id,))

    def stale_thread_ids(self, *, cutoff_iso: str, limit: int = 5000) -> list[str]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT id FROM chat_threads WHERE updated_at < %s LIMIT %s",
                (_pg._iso_to_dt(cutoff_iso), int(limit)),
            )
            rows = cur.fetchall()
        return [r["id"] for r in rows]

    def list_for_user(self, user_id: Optional[str], *, limit: int = 50) -> list[dict]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            if user_id is None:
                cur.execute(
                    "SELECT id, user_id, title, created_at, updated_at, "
                    "COALESCE(pinned, FALSE) AS pinned, COALESCE(kind, 'chat') AS kind "
                    "FROM chat_threads "
                    "ORDER BY pinned DESC, updated_at DESC LIMIT %s", (limit,),
                )
            else:
                cur.execute(
                    "SELECT id, user_id, title, created_at, updated_at, "
                    "COALESCE(pinned, FALSE) AS pinned, COALESCE(kind, 'chat') AS kind "
                    "FROM chat_threads WHERE user_id = %s "
                    "ORDER BY pinned DESC, updated_at DESC LIMIT %s", (user_id, limit),
                )
            rows = cur.fetchall()
        out = []
        for r in rows:
            r = dict(r)
            r["created_at"] = _pg._dt_to_iso(r["created_at"])
            r["updated_at"] = _pg._dt_to_iso(r["updated_at"])
            r["pinned"] = bool(r.get("pinned"))
            out.append(r)
        return out

    def set_pinned(self, thread_id: str, pinned: bool) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE chat_threads SET pinned = %s WHERE id = %s",
                (bool(pinned), thread_id),
            )

    def list_admin(self, *, limit: int = 100, offset: int = 0,
                   since: Optional[str] = None,
                   exclude_prefixes: tuple = (),
                   require_user: bool = False,
                   exclude_user_ids: tuple = ()) -> tuple[list[dict], int]:
        """관리자 대화 목록 — SQLite 구현과 동일 계약(사후 필터 절단 방지)."""
        from . import _pg
        where, params = ["TRUE"], []
        if since:
            where.append("updated_at >= %s")
            params.append(_pg._iso_to_dt(since))
        for p in exclude_prefixes:
            # LIKE 는 접두의 `_` 가 와일드카드 — SUBSTR 정확 일치로 거른다.
            where.append("SUBSTR(id, 1, %s) <> %s")
            params.extend([len(p), p])
        if require_user:
            where.append("user_id IS NOT NULL AND user_id <> 'dev-bypass-user'")
        if exclude_user_ids:
            where.append("(user_id IS NULL OR NOT (user_id = ANY(%s)))")
            params.append(list(exclude_user_ids))
        cond = " AND ".join(where)
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM chat_threads WHERE {cond}",
                params,
            )
            total = int(cur.fetchone()["n"])
            cur.execute(
                f"SELECT id, user_id, title, created_at, updated_at "
                f"FROM chat_threads WHERE {cond} "
                f"ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                (*params, int(limit), int(offset)),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            r = dict(r)
            r["created_at"] = _pg._dt_to_iso(r["created_at"])
            r["updated_at"] = _pg._dt_to_iso(r["updated_at"])
            out.append(r)
        return out, total

    def search_messages(self, user_id: Optional[str], query: str, *, limit: int = 30) -> list[dict]:
        """대화 본문(human/ai content)에 query 포함하는 thread — DISTINCT, 최근순.
        (SQLite 구현과 동일 이유로 raw JSON 매치 금지 — tool 메시지 원문 오탐.)"""
        from . import _pg
        like = f"%{query}%"
        base = (
            "SELECT DISTINCT t.id, t.user_id, t.title, t.created_at, t.updated_at, "
            "COALESCE(t.pinned,FALSE) AS pinned FROM chat_threads t "
            "JOIN chat_messages m ON m.thread_id = t.id WHERE "
            "m.data_json->>'type' IN ('human','ai') "
            "AND m.data_json#>>'{data,content}' ILIKE %s AND "
        )
        tail = " ORDER BY pinned DESC, t.updated_at DESC LIMIT %s"
        with _pg.pg_cursor(self.dsn) as cur:
            if user_id is None:
                cur.execute(base + "TRUE" + tail, (like, limit))
            else:
                cur.execute(
                    base + "t.user_id = %s" + tail,
                    (like, user_id, limit),
                )
            rows = cur.fetchall()
            out = []
            for r in rows:
                r = dict(r)
                r["created_at"] = _pg._dt_to_iso(r["created_at"])
                r["updated_at"] = _pg._dt_to_iso(r["updated_at"])
                r["pinned"] = bool(r.get("pinned"))
                out.append(r)
            # 매칭 발췌 — thread 당 최근 1건(SQLite 구현과 동일 계약).
            if out:
                cur.execute(
                    "SELECT thread_id, data_json FROM chat_messages "
                    "WHERE thread_id = ANY(%s) "
                    "AND data_json->>'type' IN ('human','ai') "
                    "AND data_json#>>'{data,content}' ILIKE %s "
                    "ORDER BY seq DESC",
                    ([d["id"] for d in out], like),
                )
                best: dict[str, str] = {}
                for m in cur.fetchall():
                    m = dict(m)
                    tid = m["thread_id"]
                    if tid not in best:
                        best[tid] = match_excerpt(_content_of(m["data_json"]), query)
                for d in out:
                    d["match_snippet"] = best.get(d["id"], "")
        return out

    # ── messages ────────────────────────────────────────────────────
    def append_messages(self, thread_id: str, messages: list[BaseMessage],
                        *, sensitive: bool = False, hidden: bool = False) -> None:
        """메시지 적재.

        `sensitive=True` 면 기밀 턴 산출(비기밀 턴 컨텍스트에서 빠진다),
        `hidden=True` 면 조합의 중간 단계(채팅에 렌더하지 않는다).
        """
        if not messages:
            return
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            # 스레드 행을 잠가 **같은 스레드의 동시 append 를 직렬화**한다(2026-10-03).
            # 종전엔 MAX(seq) 읽기와 INSERT 사이에 아무 보호가 없었다 — 보고서 잡과
            # 채팅 턴이 "진짜 병렬"(report_runner 주석)이라 seq 충돌·tool_use↔
            # tool_result 짝 파손이 운영에서만 났다(SQLite 는 self._lock 이 덮어
            # 테스트로 절대 재현 불가). pg_cursor 는 autocommit 이라 BEGIN 을 명시한다.
            cur.execute("BEGIN")
            cur.execute("SELECT 1 FROM chat_threads WHERE id = %s FOR UPDATE", (thread_id,))
            cur.execute(
                "SELECT COALESCE(MAX(seq), -1) AS mx FROM chat_messages "
                "WHERE thread_id = %s",
                (thread_id,),
            )
            seq = int(cur.fetchone()["mx"]) + 1
            for m in messages:
                cur.execute(
                    "INSERT INTO chat_messages "
                    "(id, thread_id, seq, data_json, sensitive, hidden) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                    (
                        getattr(m, "id", None) or new_id(),
                        thread_id, seq,
                        _dump_message(m, sensitive),
                        bool(sensitive), bool(hidden),
                    ),
                )
                seq += 1
            cur.execute(
                "UPDATE chat_threads SET updated_at = NOW() WHERE id = %s",
                (thread_id,),
            )
            cur.execute("COMMIT")

    def message_created_at(self, thread_id: str) -> dict[str, str]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "SELECT id, created_at FROM chat_messages WHERE thread_id = %s ORDER BY seq",
                (thread_id,),
            )
            rows = cur.fetchall()
        out: dict[str, str] = {}
        for r in rows:
            if r["id"]:
                ts = r["created_at"]
                out[r["id"]] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        return out

    def replace_message(self, thread_id: str, message: BaseMessage) -> bool:
        mid = getattr(message, "id", None)
        if not mid:
            return False
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE chat_messages SET data_json = %s::jsonb "
                "WHERE thread_id = %s AND id = %s",
                (json.dumps(message_to_dict(message), ensure_ascii=False), thread_id, mid),
            )
            return (cur.rowcount or 0) > 0

    # ── steps ───────────────────────────────────────────────────────
    def merge_steps(self, thread_id: str, steps: list[dict]) -> None:
        if not steps:
            return
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            # read-modify-write 를 행 잠금으로 보호(2026-10-03) — 채팅 턴과 보고서
            # 잡이 같은 step 을 동시에 merge 하면 한쪽 필드가 조용히 사라졌다.
            cur.execute("BEGIN")
            for s in steps:
                sid = s.get("id")
                if not sid:
                    continue
                cur.execute(
                    "SELECT data_json FROM chat_steps "
                    "WHERE thread_id = %s AND step_id = %s FOR UPDATE",
                    (thread_id, sid),
                )
                row = cur.fetchone()
                merged = {**((row or {}).get("data_json") or {}), **s}
                cur.execute(
                    "INSERT INTO chat_steps (thread_id, step_id, data_json, ts) "
                    "VALUES (%s, %s, %s::jsonb, %s) "
                    "ON CONFLICT (thread_id, step_id) DO UPDATE SET "
                    "data_json = excluded.data_json, ts = excluded.ts",
                    (
                        thread_id, sid,
                        json.dumps(merged, ensure_ascii=False),
                        merged.get("ts", merged.get("ended_at")),
                    ),
                )
            cur.execute("COMMIT")


# ── factory ─────────────────────────────────────────────────────────
_repo_lock = threading.Lock()
_repo: Any = None


def get_threads_repo():
    """REPORTS_BACKEND 스위치 공유 — sqlite(dev) | postgres(운영)."""
    global _repo
    with _repo_lock:
        if _repo is not None:
            return _repo
        import os

        backend = (os.getenv("REPORTS_BACKEND") or "sqlite").lower()
        if backend == "postgres":
            _repo = PostgresThreadsRepo(dsn=os.environ["REPORTS_PG_DSN"])
        elif backend == "sqlite":
            path = os.getenv("REPORTS_SQLITE_PATH") or "./medi_reports.db"
            _repo = SqliteThreadsRepo(path=path)
        else:
            raise ValueError(f"Unknown REPORTS_BACKEND: {backend!r}")
        return _repo


def reset_threads_repo_cache() -> None:
    """싱글턴 폐기 — 테스트 격리용(conftest 가 매 테스트 호출).

    다른 repo 는 `@lru_cache` 라 conftest 가 `cache_clear()` 로 일괄 비우는데,
    이 repo 만 모듈 전역이라 REPORTS_SQLITE_PATH 격리가 안 먹고 앞선 테스트의
    DB 를 계속 붙들고 있었다(2026-08-04).
    """
    global _repo
    with _repo_lock:
        _repo = None
