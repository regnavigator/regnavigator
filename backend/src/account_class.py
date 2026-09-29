"""계정 구분 — 관리자·테스트·실사용자 판정의 **단일 정본** (2026-09-21).

배경: "실사용" 지표에 관리자·테스트 계정이 계속 섞였다. 화면마다 기준이 달랐다 —
이용 조회·통계·대화 목록은 관리자만 빼고(오픈 전 가입 테스트 계정은 통과),
검수 큐는 따로 오픈 전 가입까지 뺐다. 그래서 같은 기간인데 화면마다 숫자가 달랐고,
팀원이 개인 메일로 만든 계정은 어느 규칙에도 안 걸렸다.

규칙(우선순위):
  1. 관리자(`is_admin` 또는 `ADMIN_EMAILS`) → staff(표시 '관리자'). 라벨로 덮을 수 없다.
     2026-09-22 통합: 종전엔 '운영진' 라벨(account_class=staff)과 관리자 권한(is_admin)이 따로라
     "관리자인데 실사용자", "운영진인데 관리자 아님" 같은 조합이 생겼다. 이제 내부 팀원 = 관리자
     하나로 — 관리 화면이 필요 없는 팀원은 **권한 없는 관리자**로 둔다(`src/admin_perms.py`).
     예전 수동 '운영진' 라벨은 부팅 때 `migrate_staff_labels` 가 실사용자 라벨로 되돌린다 —
     관리자로 둘 계정은 운영자가 직접 지정한다(운영자 결정 2026-09-22).
  2. 관리자가 직접 붙인 라벨(`users.account_class`) — test|user.
  3. 자동: 베타 오픈(`SERVICE_LAUNCH_AT`) 전 가입 **이면서 베타 화이트리스트에 없음** → test
     (오픈 전에 가입했어도 초대된 베타 테스터는 실사용자다 — 2026-09-21 운영 실측: 오픈 전 가입 10명 중
     4명이 8/2 초대 메일을 받은 베타 테스터였고 오픈 후 질문 114건. 가입일만 보면 이들이 '테스트'로 빠졌다.
     초대 기록이 없는 개발 계정(`*@onbox.local`·`@example.com` 등)만 테스트로 남는다.)
  4. 그 외 → user(실사용자)

"내부" = staff ∪ test. 실사용 집계(scope=real)는 내부 계정을 뺀다. 스레드 단위 내부
판정(e2e·벤치 접두, 익명)은 `routes.admin.is_internal_thread` 가 계속 맡는다 — 이 모듈은
**사람(계정)** 축만 본다.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

STAFF = "staff"
TEST = "test"
USER = "user"
CLASSES = (STAFF, TEST, USER)
LABELS = {STAFF: "관리자", TEST: "테스트", USER: "실사용자"}
#: 수동 라벨로 지정 가능한 값 — 관리자(staff)는 권한(is_admin)으로만 정해진다.
MANUAL_CLASSES = (TEST, USER)

_LAUNCH_DEFAULT = "2026-08-03T00:00:00+09:00"
_CACHE_TTL_S = 30.0

_lock = threading.Lock()
_cache: Optional[tuple[tuple, float, frozenset, str]] = None


# ── 스레드 축: 스크립트·e2e 가 만든 대화 (routes/admin 에서 이동, 2026-09-21) ──

# 내부 트래픽 thread_id 접두 — 벤치·야간 회귀·e2e·리플레이가 만든 대화.
# `/chat` 은 JWT 필수라 **user_id 가 없는 thread 는 전부 스크립트 산물**이지만,
# 접두까지 함께 보는 이유는 관리자 계정으로 돌린 e2e 도 걸러내기 위함이다.
# (2026-08-19: 야간 회귀 qreg_* 16건/일이 '실사용 대화'로 집계되던 것 수정)
_INTERNAL_THREAD_PREFIXES = ("qreg_", "bench_", "e2e_", "hrep_", "hrep2_", "lat_")
# 스레드 id 는 `t_` 접두로도 만들어진다(`t_e2e_doc_…`, `t_qreg_…`). 접두만 보면
# 이것들이 전부 실사용으로 샌다 — 실제로 관리자 화면에 e2e 대화·보고서가
# 섞여 나왔다(2026-08-26). 정규화 후 판정한다.
_INTERNAL_ID_PREFIXES = ("t_", "thread_", "rpt_")


# SQL 제외용 — 접두 목록에 `t_`·`thread_` 변형을 미리 펼쳐 둔다(LIKE 기반
# 쿼리는 정규화를 못 하므로). 대화 원문 목록이 이걸 쓴다.
_INTERNAL_THREAD_PREFIXES_ALL = _INTERNAL_THREAD_PREFIXES + tuple(
    pre + p for pre in ("t_", "thread_") for p in _INTERNAL_THREAD_PREFIXES
)


def _normalize_thread_id(thread_id: str) -> str:
    tid = str(thread_id or "")
    for p in _INTERNAL_ID_PREFIXES:
        if tid.startswith(p):
            return tid[len(p):]
    return tid


# 실사용 thread id = `t_` + hex(uuid 유래). `t_kindtest1` 처럼 사람이 지은
# 이름(비-hex 문자 포함)은 스크립트 산물이다. 길이를 강제하지 않는 이유:
# 레거시 축약 id(t_1398cbb0 등)를 오판하지 않기 위해.
_REAL_THREAD_RE = re.compile(r"^t_[0-9a-f]{6,}$")


def is_internal_thread(thread_id: str, user_id=None) -> bool:
    """운영 지표에서 제외할 내부(스크립트) 대화인가."""
    tid = str(thread_id or "")
    # dev 무인증 우회 계정 — 로컬 TestClient e2e 가 이 계정으로 돌아 운영
    # 집계에 섞였다(2026-08-27 재발: t_kindtest1 등. 접두 목록에 없는 임의
    # 이름이라 통과). 사용자 기준으로 원천 차단.
    uid = str(user_id or "")
    if uid == "dev-bypass-user":
        return True
    # e2e 전용 계정 관례(2026-08-28) — 스크립트가 임의 user_id 를 달고 돌면
    # 사용자 규칙(관리자·익명)을 다 통과한다. `…@internal` 은 실메일이 될 수
    # 없는 예약 도메인으로 내부 취급.
    if uid.lower().endswith("@internal"):
        return True
    if tid.startswith(_INTERNAL_THREAD_PREFIXES):
        return True
    if _normalize_thread_id(tid).startswith(_INTERNAL_THREAD_PREFIXES):
        return True
    # 실사용 thread id 는 전부 `t_` + 32-hex(uuid). `t_kindtest1` 같은
    # 사람이 지은 이름은 스크립트 산물이다 — 접두 목록의 구멍을 형태로 막는다.
    if tid.startswith("t_") and not _REAL_THREAD_RE.match(tid):
        return True
    # 익명 = 인증 없이 run_chat_turn 을 직접 부른 스크립트뿐(/chat 은 JWT 필수).
    return user_id is None


# ── 계정 축 ──

def launch_cutoff() -> str:
    """실사용 시작 시각(UTC ISO). env `SERVICE_LAUNCH_AT` 로 조정."""
    raw = (os.getenv("SERVICE_LAUNCH_AT") or "").strip() or _LAUNCH_DEFAULT
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.fromisoformat(_LAUNCH_DEFAULT)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _admin_emails() -> set[str]:
    return {e.strip().lower()
            for e in (os.getenv("ADMIN_EMAILS") or "").split(",") if e.strip()}


def _created_iso(u) -> str:
    """created_at 을 launch_cutoff 와 같은 형식(UTC ISO)으로 — SQLite 는 `…Z`,
    PG 는 `+00:00` 이라 문자열 비교가 형식 차이로 어긋나지 않게 파싱해서 맞춘다."""
    raw = str(getattr(u, "created_at", "") or "")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return raw


def beta_listed_checker():
    """email → 베타 화이트리스트(env·DB·도메인)에 올라 있는가. 목록 판정용으로 한 번만 만든다.
    관리자 허용(source="admin")은 제외 — 관리자는 규칙 2 가 먼저 처리한다."""
    from src.whitelist import classifier

    _active, cls = classifier()

    def listed(email: Optional[str]) -> bool:
        src = cls(email)[1]
        return bool(src) and src != "admin"

    return listed


def classify(u, *, cut: Optional[str] = None,
             admin_emails: Optional[set[str]] = None,
             beta_listed=None) -> tuple[str, str]:
    """→ (class, source). source: "manual" | "auto:admin" | "auto:pre_launch" |
    "auto:beta_invited"(오픈 전 가입이지만 베타 초대 명단) | "auto"."""
    emails = _admin_emails() if admin_emails is None else admin_emails
    email = (getattr(u, "email", "") or "").lower()
    if getattr(u, "is_admin", False) or email in emails:
        return STAFF, "auto:admin"
    manual = (getattr(u, "account_class", None) or "").strip()
    if manual in CLASSES:
        # staff 수동 라벨은 이관 전 잔재 — 내부로 유지(이관 후엔 나오지 않는다)
        return manual, "manual"
    if _created_iso(u) < (cut or launch_cutoff()):
        listed = beta_listed if beta_listed is not None else beta_listed_checker()
        if listed(email):
            return USER, "auto:beta_invited"
        return TEST, "auto:pre_launch"
    return USER, "auto"


def normalize(value) -> Optional[str]:
    """PATCH 입력 → 저장값. ""·None·"auto" = 자동(NULL). test|user 만 수동 지정.

    staff(관리자)는 라벨이 아니라 권한 — 라우트가 is_admin 지정으로 처리한다(루트만).
    """
    v = (str(value).strip().lower() if value is not None else "")
    if v in ("", "auto", "none", "null"):
        return None
    if v not in MANUAL_CLASSES:
        raise ValueError(f"account_class 는 {'|'.join(MANUAL_CLASSES)}|auto 중 하나"
                         " (관리자는 사용자 편집의 '관리자로 지정')")
    return v


def migrate_staff_labels() -> int:
    """예전 수동 '운영진' 라벨 → 실사용자(2026-09-22 통합, 멱등).

    운영자 결정: 자동으로 관리자로 올리지 않는다 — 관리자로 둘 팀원은 사용자 관리에서 직접
    지정한다. 관리자가 아닌 계정은 'user' 라벨, 이미 관리자면 라벨만 지운다. 바꾼 계정 수 반환.
    """
    from src.persistence import get_users_repo

    repo = get_users_repo()
    moved = 0
    for u in repo.list_all(limit=100000):
        if (getattr(u, "account_class", None) or "") != STAFF:
            continue
        repo.set_account_class(u.id, None if u.is_admin else USER)
        moved += 1
    if moved:
        invalidate()
    return moved


def _cache_key() -> tuple:
    # 판정 입력이 바뀌면(저장소 교체·env 변경) 캐시를 쓰지 않는다 — 테스트가 저장소를
    # 갈아끼우거나 운영자가 ADMIN_EMAILS·SERVICE_LAUNCH_AT 을 바꾼 직후에도 정확.
    from src.persistence import get_users_repo

    return (id(get_users_repo()), launch_cutoff(), tuple(sorted(_admin_emails())))


def _compute() -> tuple[frozenset, str]:
    from src.persistence import get_users_repo

    cut = launch_cutoff()
    emails = _admin_emails()
    listed = beta_listed_checker()
    internal = frozenset(
        u.id for u in get_users_repo().list_all(limit=100000)
        if classify(u, cut=cut, admin_emails=emails, beta_listed=listed)[0] != USER)
    fp = hashlib.sha1(",".join(sorted(internal)).encode()).hexdigest()[:12]
    return internal, fp


def internal_user_ids() -> frozenset:
    """운영진·테스트 계정 id 집합(TTL 캐시). 라벨 변경 시 `invalidate()`."""
    global _cache
    now = time.monotonic()
    key = _cache_key()
    with _lock:
        if _cache and _cache[0] == key and now - _cache[1] < _CACHE_TTL_S:
            return _cache[2]
    ids, fp = _compute()
    with _lock:
        _cache = (key, now, ids, fp)
    return ids


def fingerprint() -> str:
    """내부 계정 집합의 지문 — 저장된 주간 집계가 지금 라벨과 같은 기준인지 판별."""
    internal_user_ids()
    with _lock:
        return _cache[3] if _cache else ""


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None
