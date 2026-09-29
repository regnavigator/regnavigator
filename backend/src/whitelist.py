"""클로즈 베타 화이트리스트 **정책** — 단일 진실원 (2026-09-10).

## 왜 분리했나

같은 판정 규칙이 세 곳에 흩어져 있었다:

| 위치 | 용도 | 문제 |
|---|---|---|
| `middleware/auth._beta_allowed` | 요청 게이팅(허용/차단) | 정본이지만 출처를 안 알려줌 |
| `routes/admin._whitelist_classifier` | 관리 화면 표시(출처까지) | **같은 규칙을 재조립** — docstring 이 스스로 "auth 와 같아야 한다"고 적고 있었다 |
| `notices.resolve_recipients` | 공지 수신자 해석 | 위 라우트 함수를 import → **`notices → routes.admin → notices` 순환** |

서비스(`notices`)가 라우트(`routes.admin`)를 의존하는 계층 역전이었고, 규칙이
세 벌이라 하나만 고치면 조용히 어긋난다. 판정을 여기로 올리고 셋이 이걸 쓴다.

## 규칙

항목은 이메일(`a@b.com`) 또는 도메인(`@company.com` — 그 도메인 전체 허용).
출처는 env(`BETA_WHITELIST_EMAILS`) ∪ DB(admin 화면 관리). `ADMIN_EMAILS` 는
언제나 허용한다(운영자 잠금 방지). env·DB 가 모두 비면 게이트 자체가 꺼지지만,
`BETA_GATE=1` 이면 빈 목록이어도 활성(= 관리자 외 전면 차단).

DB 조회는 TTL 캐시를 탄다 — 목록 렌더는 사용자 수만큼 판정하므로 매 건 조회하면
안 된다. DB 장애 시에는 env 만으로 판정한다(로그인 전체가 막히면 안 된다).
"""
from __future__ import annotations

import os
import time
from typing import Optional

#: DB 화이트리스트 캐시 — admin 이 추가/삭제하면 `invalidate_cache()` 로 즉시 반영.
_TTL_S = 30.0
_CACHE: dict = {"entries": None, "at": 0.0}


def invalidate_cache() -> None:
    """admin 이 화이트리스트를 바꾼 직후 호출 — TTL 을 기다리지 않게."""
    _CACHE["entries"] = None
    _CACHE["at"] = 0.0
    # 베타 명단은 계정 구분(오픈 전 가입 + 초대 = 실사용자)의 입력이다 — 함께 무효화.
    try:
        from src.account_class import invalidate as _inv_ac
        _inv_ac()
    except Exception:  # noqa: BLE001 — 캐시 무효화 실패는 TTL(30s)로 수렴
        pass


#: 루트 관리자 — env 와 무관하게 항상 admin(불변). 강등·비활성화 불가.
#: `middleware/auth.ROOT_ADMIN_EMAILS` 가 이걸 재수출한다(기존 import 호환).
def _root_admins() -> frozenset[str]:
    from src.config import env_nonempty
    return frozenset(e.strip().lower() for e in env_nonempty("ROOT_ADMIN_EMAILS").split(",") if e.strip())


ROOT_ADMIN_EMAILS: frozenset[str] = _root_admins()


def admin_emails() -> set[str]:
    """ADMIN_EMAILS ∪ 루트 관리자. 루트를 빠뜨리면 운영자가 잠긴다."""
    raw = (os.getenv("ADMIN_EMAILS") or "").strip()
    return {e.strip().lower() for e in raw.split(",") if e.strip()} | set(ROOT_ADMIN_EMAILS)


def env_entries() -> set[str]:
    raw = (os.getenv("BETA_WHITELIST_EMAILS") or "").strip()
    return {e.strip().lower() for e in raw.split(",") if e.strip()} if raw else set()


def db_entries() -> set[str]:
    now = time.monotonic()
    if _CACHE["entries"] is not None and now - _CACHE["at"] < _TTL_S:
        return _CACHE["entries"]
    try:
        from src.persistence.whitelist_repo import get_whitelist_repo

        entries = get_whitelist_repo().entries()
    except Exception:  # noqa: BLE001 — DB 장애가 로그인 전체를 막으면 안 됨(env 만 사용)
        entries = set()
    _CACHE["entries"] = entries
    _CACHE["at"] = now
    return entries


def merged_entries() -> Optional[set[str]]:
    """env ∪ DB. None = 게이트 꺼짐(전면 허용). `BETA_GATE=1` 이면 빈 집합이어도 활성."""
    merged = env_entries() | db_entries()
    if (os.getenv("BETA_GATE") or "").strip() in ("1", "true", "yes"):
        return merged
    return merged or None


def gate_active() -> bool:
    return merged_entries() is not None


def classifier():
    """`(gate_active, classify)` — 목록 판정용. env/DB/admin 조회를 **한 번만** 한다.

    `classify(email) -> (allowed, source)`,
    source: `"admin"` | `"env"` | `"db"` | `"domain:@x.com"` | None.
    """
    active = gate_active()
    env_set = env_entries()
    db_set = db_entries()
    admins = admin_emails()

    def classify(email: Optional[str]) -> tuple[bool, Optional[str]]:
        e = (email or "").strip().lower()
        if not e:
            return (not active, None)
        if e in admins:
            return True, "admin"
        if e in env_set:
            return True, "env"
        if e in db_set:
            return True, "db"
        domain = "@" + e.rsplit("@", 1)[-1] if "@" in e else ""
        if domain and (domain in env_set or domain in db_set):
            return True, f"domain:{domain}"
        # 게이트가 꺼져 있으면 화이트리스트에 없어도 접근은 된다(등록 여부만 False).
        return (not active), None

    return active, classify


def allowed(email: str) -> bool:
    """단건 판정 — 요청 게이팅용(`AuthMiddleware`)."""
    return classifier()[1](email)[0]
