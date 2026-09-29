"""UsersRepo — 회원 본체 메타.

NextAuth(medi-front)가 가입·로그인을 담당하고, JWT 검증 시 medi-back이 user를
upsert한다. 이 테이블은 회원 본체 비번·세션 정보가 아닌 quota·admin 플래그·
이메일 인증 시각만 보관.

dev = SQLite, prod = Postgres (stub).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from ._common import SqliteRepoBase, utcnow_iso as _utcnow_iso


@dataclass
class User:
    id: str
    email: str
    email_verified_at: Optional[str] = None
    is_admin: bool = False
    daily_token_limit_override: Optional[int] = None      # NULL = 시스템 기본값
    monthly_token_limit_override: Optional[int] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)
    # 보고서 완료 이메일 수신(사용자 선택, 기본 ON)
    report_email_opt_in: bool = True
    # 서비스 안내 메일 수신(기능 추가·변경 고지, 기본 ON). 2026-09-10 도입→당일
    # 철회했다가 2026-09-14 재도입(운영 결정 번복) — 뉴스레터 푸터가 가리키는 설정.
    # 마케팅 동의(legal_consent scopes)와는 별개 축 — 이건 서비스 고지용 거부다.
    notice_email_opt_in: bool = True
    # 회원탈퇴(자발적) 소프트삭제 시각 — NULL=활성. hard delete(법 제36조 파기,
    # scripts/erase_user.py)와 별개. 탈퇴 계정은 AuthMiddleware 가 403 차단.
    deleted_at: Optional[str] = None
    # 프로필(가입/온보딩 시 사용자 입력, 2026-08-10) — admin 이용조회 표시용.
    display_name: Optional[str] = None    # 표시 이름
    affiliation: Optional[str] = None     # 소속 (병원·회사·기관)
    job_role: Optional[str] = None        # 직군 (의사·RA/QA·컨설턴트 등)
    # 마지막으로 닫은 업데이트 팝업 노트 id(2026-09-07) — 서버 기억. localStorage 만
    # 믿으면 브라우저·기기마다 다시 뜬다("한 번 끄면 계속 뜬다" 신고).
    last_seen_announcement_id: Optional[str] = None
    # 관리자 식별 메모(2026-09-15) — 프로필을 입력하지 않은 기존 가입자를 관리자가
    # 알아볼 수 있게 관리자 화면에서만 기입·표시. 사용자 화면·내보내기에 노출하지 않는다.
    admin_memo: Optional[str] = None
    # 계정 구분 라벨(2026-09-21) — 관리자가 직접 지정: "staff"(운영진)·"test"(테스트)·
    # "user"(실사용자). NULL = 자동 판정(관리자→운영진, 오픈 전 가입→테스트, 그 외 실사용).
    # 판정 정본은 `src/account_class.py` — 통계·이용 조회·검수 큐가 전부 그걸 본다.
    account_class: Optional[str] = None
    # 관리자 기능별 권한(2026-09-22) — 콤마 구분 키(`src/admin_perms.PERM_KEYS`).
    # NULL = 전 권한(도입 전 관리자 하위호환). 루트 관리자는 이 값과 무관하게 전 권한.
    admin_perms: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


class UsersRepo(Protocol):
    def upsert(self, *, id: str, email: str, email_verified_at: Optional[str] = None,
               is_admin: Optional[bool] = None) -> User: ...
    def get(self, user_id: str) -> Optional[User]: ...
    def delete(self, user_id: str) -> None: ...
    def soft_delete(self, user_id: str) -> None: ...
    def restore(self, user_id: str) -> None: ...
    def get_by_email(self, email: str) -> Optional[User]: ...
    def list_all(self, *, limit: int = 100, offset: int = 0,
                 q: Optional[str] = None) -> list[User]: ...
    def update_quota(self, user_id: str, *,
                     daily_override: Optional[int] = None,
                     monthly_override: Optional[int] = None) -> None: ...
    def set_admin(self, user_id: str, is_admin: bool) -> None: ...
    def set_report_email_opt_in(self, user_id: str, opt_in: bool) -> None: ...
    def set_notice_email_opt_in(self, user_id: str, opt_in: bool) -> None: ...
    def set_last_seen_announcement(self, user_id: str, note_id: Optional[str]) -> None: ...
    def set_profile(self, user_id: str, *, display_name: Optional[str],
                    affiliation: Optional[str], job_role: Optional[str]) -> None: ...
    def set_admin_memo(self, user_id: str, memo: Optional[str]) -> None: ...
    def set_account_class(self, user_id: str, account_class: Optional[str]) -> None: ...
    def set_admin_perms(self, user_id: str, perms: Optional[str]) -> None: ...


def _email_like(q: str) -> str:
    """이메일 부분일치 검색용 LIKE 패턴 — 와일드카드(%·_)는 리터럴로 취급."""
    esc = q.strip().lower().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{esc}%"


_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
  id                            TEXT PRIMARY KEY,
  email                         TEXT NOT NULL UNIQUE,
  email_verified_at             TEXT,
  is_admin                      INTEGER NOT NULL DEFAULT 0,
  daily_token_limit_override    INTEGER,
  monthly_token_limit_override  INTEGER,
  created_at                    TEXT NOT NULL,
  updated_at                    TEXT NOT NULL,
  deleted_at                    TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""


class SqliteUsersRepo(SqliteRepoBase):
    _schema = _SCHEMA_SQLITE

    def _post_init(self, conn) -> None:
        # deleted_at 컬럼(회원탈퇴 소프트삭제) — 기존 dev DB 마이그레이션.
        try:
            conn.execute("ALTER TABLE users ADD COLUMN deleted_at TEXT")
        except Exception:
            pass  # 이미 존재
        try:
            conn.execute("ALTER TABLE users ADD COLUMN report_email_opt_in INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass  # 이미 존재
        try:
            conn.execute("ALTER TABLE users ADD COLUMN notice_email_opt_in INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass  # 이미 존재
        # 프로필 필드(온보딩 입력, 2026-08-10)
        for _col in ("display_name", "affiliation", "job_role", "last_seen_announcement_id",
                     "admin_memo", "account_class", "admin_perms"):
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {_col} TEXT")
            except Exception:
                pass  # 이미 존재

    def upsert(self, *, id: str, email: str, email_verified_at: Optional[str] = None,
               is_admin: Optional[bool] = None) -> User:
        now = _utcnow_iso()
        with self._lock, self._conn() as c:
            # email 이 *다른 id* 로 이미 존재하면(front/back id 불일치, email UNIQUE
            # 위반 유발) 그 행의 id 를 이번 클레임 id 로 정렬한 뒤 표준 upsert. FK 없음.
            c.execute(
                "UPDATE users SET id = ?, updated_at = ? WHERE email = ? AND id <> ?",
                (id, now, email, id),
            )
            existing = c.execute("SELECT * FROM users WHERE id = ?", (id,)).fetchone()
            if existing:
                # update changed fields
                new_verified = email_verified_at or existing["email_verified_at"]
                new_admin = int(is_admin) if is_admin is not None else existing["is_admin"]
                c.execute(
                    """UPDATE users SET email = ?, email_verified_at = ?,
                                       is_admin = ?, updated_at = ? WHERE id = ?""",
                    (email, new_verified, new_admin, now, id),
                )
            else:
                c.execute(
                    """INSERT INTO users
                       (id, email, email_verified_at, is_admin,
                        daily_token_limit_override, monthly_token_limit_override,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)""",
                    (id, email, email_verified_at, int(bool(is_admin)), now, now),
                )
            row = c.execute("SELECT * FROM users WHERE id = ?", (id,)).fetchone()
        return _row_to_user(row)

    def get(self, user_id: str) -> Optional[User]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None

    def delete(self, user_id: str) -> None:
        """정보주체 삭제 요구 이행(법 제36조) — `scripts/erase_user.py` 가 호출(하드)."""
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def soft_delete(self, user_id: str) -> None:
        """회원탈퇴(자발적) — deleted_at 마킹. 행·데이터 보존, 접근만 차단."""
        now = _utcnow_iso()
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE users SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, user_id),
            )

    def restore(self, user_id: str) -> None:
        """탈퇴 철회/관리자 복구 — deleted_at 해제."""
        now = _utcnow_iso()
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE users SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                (now, user_id),
            )

    def get_by_email(self, email: str) -> Optional[User]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return _row_to_user(row) if row else None

    def list_all(self, *, limit: int = 100, offset: int = 0,
                 q: Optional[str] = None) -> list[User]:
        with self._lock, self._conn() as c:
            if q:
                rows = c.execute(
                    "SELECT * FROM users WHERE email LIKE ? ESCAPE '\\' "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (_email_like(q), limit, offset),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        return [_row_to_user(r) for r in rows]

    def update_quota(self, user_id: str, *,
                     daily_override: Optional[int] = None,
                     monthly_override: Optional[int] = None) -> None:
        now = _utcnow_iso()
        with self._lock, self._conn() as c:
            c.execute(
                """UPDATE users SET
                     daily_token_limit_override   = COALESCE(?, daily_token_limit_override),
                     monthly_token_limit_override = COALESCE(?, monthly_token_limit_override),
                     updated_at                   = ?
                   WHERE id = ?""",
                (daily_override, monthly_override, now, user_id),
            )

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        now = _utcnow_iso()
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE users SET is_admin = ?, updated_at = ? WHERE id = ?",
                (int(bool(is_admin)), now, user_id),
            )

    def set_report_email_opt_in(self, user_id: str, opt_in: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE users SET report_email_opt_in = ?, updated_at = ? WHERE id = ?",
                (1 if opt_in else 0, _utcnow_iso(), user_id),
            )

    def set_notice_email_opt_in(self, user_id: str, opt_in: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE users SET notice_email_opt_in = ?, updated_at = ? WHERE id = ?",
                (1 if opt_in else 0, _utcnow_iso(), user_id),
            )

    def set_last_seen_announcement(self, user_id: str, note_id: Optional[str]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE users SET last_seen_announcement_id = ?, updated_at = ? WHERE id = ?",
                (note_id, _utcnow_iso(), user_id),
            )

    def set_profile(self, user_id: str, *, display_name: Optional[str],
                    affiliation: Optional[str], job_role: Optional[str]) -> None:
        """프로필 3필드를 통째로 갱신 — 폼 단위 저장(빈 값=NULL)."""
        with self._lock, self._conn() as c:
            c.execute(
                """UPDATE users SET display_name = ?, affiliation = ?,
                       job_role = ?, updated_at = ? WHERE id = ?""",
                (display_name, affiliation, job_role, _utcnow_iso(), user_id),
            )

    def set_admin_memo(self, user_id: str, memo: Optional[str]) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE users SET admin_memo = ? WHERE id = ?",
                      ((memo or "").strip() or None, user_id))

    def set_account_class(self, user_id: str, account_class: Optional[str]) -> None:
        """None = 자동 판정으로 되돌림."""
        with self._lock, self._conn() as c:
            c.execute("UPDATE users SET account_class = ?, updated_at = ? WHERE id = ?",
                      (account_class, _utcnow_iso(), user_id))

    def set_admin_perms(self, user_id: str, perms: Optional[str]) -> None:
        """None = 전 권한. 빈 문자열 = 권한 없음(관리자이되 메뉴 없음)."""
        with self._lock, self._conn() as c:
            c.execute("UPDATE users SET admin_perms = ?, updated_at = ? WHERE id = ?",
                      (perms, _utcnow_iso(), user_id))


def _row_to_user(row) -> User:
    keys = row.keys()
    return User(
        id=row["id"],
        email=row["email"],
        email_verified_at=row["email_verified_at"],
        is_admin=bool(row["is_admin"]),
        daily_token_limit_override=row["daily_token_limit_override"],
        monthly_token_limit_override=row["monthly_token_limit_override"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=(row["deleted_at"] if "deleted_at" in keys else None),
        report_email_opt_in=bool(row["report_email_opt_in"]) if "report_email_opt_in" in keys else True,
        notice_email_opt_in=bool(row["notice_email_opt_in"]) if "notice_email_opt_in" in keys else True,
        display_name=(row["display_name"] if "display_name" in keys else None),
        affiliation=(row["affiliation"] if "affiliation" in keys else None),
        job_role=(row["job_role"] if "job_role" in keys else None),
        last_seen_announcement_id=(row["last_seen_announcement_id"]
                                   if "last_seen_announcement_id" in keys else None),
        admin_memo=(row["admin_memo"] if "admin_memo" in keys else None),
        account_class=(row["account_class"] if "account_class" in keys else None),
        admin_perms=(row["admin_perms"] if "admin_perms" in keys else None),
    )


class PostgresUsersRepo:
    """Postgres 본체 구현 — Sqlite와 동일 인터페이스, PG 타입·SQL로 변환.

    sqlite의 INTEGER `is_admin`을 BOOLEAN으로, ISO 문자열 timestamps를
    TIMESTAMPTZ로 매핑.
    """

    def delete(self, user_id: str) -> None:
        """정보주체 삭제 요구 이행(법 제36조) — 하드."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

    def soft_delete(self, user_id: str) -> None:
        """회원탈퇴(자발적) — deleted_at 마킹."""
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE users SET deleted_at = NOW(), updated_at = NOW() WHERE id = %s",
                (user_id,),
            )

    def restore(self, user_id: str) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE users SET deleted_at = NULL, updated_at = NOW() WHERE id = %s",
                (user_id,),
            )

    def __init__(self, dsn: str):
        self.dsn = dsn
        from . import _pg
        _pg.init_schema(dsn)

    def upsert(self, *, id: str, email: str,
               email_verified_at: Optional[str] = None,
               is_admin: Optional[bool] = None) -> User:
        from . import _pg
        ev_dt = _pg._iso_to_dt(email_verified_at)
        with _pg.pg_cursor(self.dsn) as cur:
            # email 이 *다른 id* 로 이미 존재하면(front[medi_auth] 와 backend 의 id
            # 불일치 — email UNIQUE 위반 유발) 그 행의 id 를 이번 클레임 id(JWT sub,
            # 정본)로 정렬한 뒤 표준 upsert. FK 없음(user_id 는 loose TEXT) → 안전.
            cur.execute(
                "UPDATE users SET id = %s, updated_at = NOW() "
                "WHERE email = %s AND id <> %s",
                (id, email, id),
            )
            # is_admin 은 NOT NULL — 신규 행은 None→FALSE(기본), 기존 행은
            # None 이면 유지(COALESCE). INSERT 값과 UPDATE 값이 달라야 하므로
            # 파라미터를 분리해 두 번 바인딩(SQLite 구현과 동일 의미론).
            cur.execute(
                """
                INSERT INTO users
                  (id, email, email_verified_at, is_admin)
                VALUES (%s, %s, %s, COALESCE(%s, FALSE))
                ON CONFLICT (id) DO UPDATE SET
                  email             = EXCLUDED.email,
                  email_verified_at = COALESCE(EXCLUDED.email_verified_at, users.email_verified_at),
                  is_admin          = COALESCE(%s, users.is_admin),
                  updated_at        = NOW()
                RETURNING *
                """,
                (id, email, ev_dt, is_admin, is_admin),
            )
            row = cur.fetchone()
        return _pg_row_to_user(row)

    def get(self, user_id: str) -> Optional[User]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        return _pg_row_to_user(row) if row else None

    def get_by_email(self, email: str) -> Optional[User]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
        return _pg_row_to_user(row) if row else None

    def list_all(self, *, limit: int = 100, offset: int = 0,
                 q: Optional[str] = None) -> list[User]:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            if q:
                cur.execute(
                    "SELECT * FROM users WHERE email ILIKE %s ESCAPE '\\' "
                    "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (_email_like(q), limit, offset),
                )
            else:
                cur.execute(
                    "SELECT * FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            rows = cur.fetchall()
        return [_pg_row_to_user(r) for r in rows]

    def update_quota(self, user_id: str, *,
                     daily_override: Optional[int] = None,
                     monthly_override: Optional[int] = None) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """
                UPDATE users SET
                  daily_token_limit_override   = COALESCE(%s, daily_token_limit_override),
                  monthly_token_limit_override = COALESCE(%s, monthly_token_limit_override),
                  updated_at                   = NOW()
                WHERE id = %s
                """,
                (daily_override, monthly_override, user_id),
            )

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE users SET is_admin = %s, updated_at = NOW() WHERE id = %s",
                (bool(is_admin), user_id),
            )

    def set_report_email_opt_in(self, user_id: str, opt_in: bool) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE users SET report_email_opt_in = %s, updated_at = NOW() WHERE id = %s",
                (bool(opt_in), user_id),
            )

    def set_notice_email_opt_in(self, user_id: str, opt_in: bool) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE users SET notice_email_opt_in = %s, updated_at = NOW() WHERE id = %s",
                (bool(opt_in), user_id),
            )

    def set_last_seen_announcement(self, user_id: str, note_id: Optional[str]) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                "UPDATE users SET last_seen_announcement_id = %s, updated_at = NOW() WHERE id = %s",
                (note_id, user_id),
            )

    def set_profile(self, user_id: str, *, display_name: Optional[str],
                    affiliation: Optional[str], job_role: Optional[str]) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute(
                """UPDATE users SET display_name = %s, affiliation = %s,
                       job_role = %s, updated_at = NOW() WHERE id = %s""",
                (display_name, affiliation, job_role, user_id),
            )

    def set_admin_memo(self, user_id: str, memo: Optional[str]) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE users SET admin_memo = %s WHERE id = %s",
                        ((memo or "").strip() or None, user_id))

    def set_account_class(self, user_id: str, account_class: Optional[str]) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE users SET account_class = %s, updated_at = NOW() WHERE id = %s",
                        (account_class, user_id))

    def set_admin_perms(self, user_id: str, perms: Optional[str]) -> None:
        from . import _pg
        with _pg.pg_cursor(self.dsn) as cur:
            cur.execute("UPDATE users SET admin_perms = %s, updated_at = NOW() WHERE id = %s",
                        (perms, user_id))


def _pg_row_to_user(row) -> User:
    from . import _pg
    return User(
        id=row["id"],
        email=row["email"],
        email_verified_at=_pg._dt_to_iso(row["email_verified_at"]),
        is_admin=bool(row["is_admin"]),
        daily_token_limit_override=row["daily_token_limit_override"],
        monthly_token_limit_override=row["monthly_token_limit_override"],
        created_at=_pg._dt_to_iso(row["created_at"]),
        updated_at=_pg._dt_to_iso(row["updated_at"]),
        deleted_at=_pg._dt_to_iso(row.get("deleted_at")) if row.get("deleted_at") else None,
        report_email_opt_in=bool(row.get("report_email_opt_in", True)),
        notice_email_opt_in=bool(row.get("notice_email_opt_in", True)),
        display_name=row.get("display_name"),
        affiliation=row.get("affiliation"),
        job_role=row.get("job_role"),
        last_seen_announcement_id=row.get("last_seen_announcement_id"),
        admin_memo=row.get("admin_memo"),
        account_class=row.get("account_class"),
        admin_perms=row.get("admin_perms"),
    )
