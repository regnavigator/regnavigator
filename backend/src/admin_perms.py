"""관리자 기능별 권한(2026-09-22) — 관리자를 여럿 두되 기능마다 켜고 끈다.

규칙:
- **루트 관리자**(`ADMIN_EMAILS` ∪ `whitelist.ROOT_ADMIN_EMAILS`)는 항상 전 권한.
  권한 지정(다른 관리자의 is_admin·기능 체크박스)은 루트만 할 수 있다.
- DB 로 지정된 관리자(`users.is_admin`)는 `users.admin_perms` 에 적힌 기능만.
  NULL = 전 권한(이 기능 도입 전부터 관리자였던 계정의 하위호환). 새로 관리자로
  지정하면 빈 목록으로 시작한다 — 루트가 체크박스로 켠다.
- 라우트 → 권한 매핑은 이 파일의 `_ROUTE_RULES` **한 곳**. `require_admin` 이 요청
  경로(라우트 템플릿)로 찾는다. 매핑에 없는 `/admin/*` 는 루트 전용(fail-closed) —
  새 라우트를 만들고 매핑을 빠뜨리면 권한 관리자에게 조용히 열리지 않고 막힌다.
  `tests/test_admin_perms.py` 가 등록된 모든 `/admin/*` 라우트의 매핑을 검사한다.
"""

from __future__ import annotations

from typing import Iterable, Optional

#: (key, 라벨, 설명) — 프런트 체크박스·탭 가드가 이 순서·문구를 그대로 쓴다.
PERMS: tuple[tuple[str, str, str], ...] = (
    ("stats", "통계·이용 조회", "사용 통계·주간 이용·이용 조회(질문 목록)"),
    ("threads", "대화 원문·답변 검수", "사용자 대화 원문 열람과 검수"),
    ("reports", "보고서", "보고서 요청 목록·본문 열람"),
    ("users", "사용자 관리", "사용자 목록·한도·구분·메모·비활성화"),
    ("beta", "베타 초대", "화이트리스트·초대 메일"),
    ("feedback", "피드백", "피드백 목록·요약 메일"),
    ("pii", "PII 필터", "마스킹 단어 라벨링"),
    ("mail", "메일 발신", "공지 메일·뉴스레터·앱 내 알림·주간 보고 발송"),
    ("announcements", "업데이트 등록", "업데이트 내역(패치노트)·보고 노트"),
    ("settings", "설정·점검", "점검 모드·시스템 설정 조회"),
)
PERM_KEYS: tuple[str, ...] = tuple(k for k, _, _ in PERMS)
LABELS: dict[str, str] = {k: label for k, label, _ in PERMS}

#: 관리자면 누구나(권한과 무관) — 자기 권한 조회·공통 헤더용.
ANY = "*"
#: 루트 전용.
ROOT = "root"

# (메서드 or None, 라우트 템플릿 접두, 권한). **위에서부터 첫 일치** — 구체적인 규칙을 먼저.
_ROUTE_RULES: tuple[tuple[Optional[str], str, str], ...] = (
    (None, "/admin/me", ANY),
    (None, "/admin/data-scope", ANY),
    (None, "/admin/build", ANY),
    # 운영진 기능 설명서(2026-09-23) — 공지·업데이트를 쓰는 모든 관리자가 기본으로 본다.
    (None, "/admin/ops-manual", ANY),
    (None, "/admin/admins", ROOT),
    # 메일 발신
    (None, "/admin/notify", "mail"),
    (None, "/admin/notices", "mail"),
    (None, "/admin/newsletters", "mail"),
    (None, "/admin/users/{user_id}/notices", "mail"),
    ("POST", "/admin/weekly-report/send", "mail"),
    ("PATCH", "/admin/weekly-report/config", "mail"),
    # 업데이트 등록
    (None, "/admin/announcements", "announcements"),
    (None, "/admin/report-notes", "announcements"),
    # 통계
    (None, "/admin/stats", "stats"),
    (None, "/admin/weekly-report", "stats"),
    (None, "/admin/questions", "stats"),
    (None, "/admin/events", "stats"),
    # 대화·검수
    (None, "/admin/threads", "threads"),
    (None, "/admin/review-queue", "threads"),
    (None, "/admin/reviews", "threads"),
    (None, "/admin/reports", "reports"),
    (None, "/admin/users", "users"),
    (None, "/admin/whitelist", "beta"),
    (None, "/admin/invite-template", "beta"),
    (None, "/admin/feedback", "feedback"),
    (None, "/admin/pii-terms", "pii"),
    (None, "/admin/maintenance", "settings"),
    (None, "/admin/config", "settings"),
)


def perm_for_route(method: str, path: str) -> str:
    """라우트 템플릿 → 필요한 권한 키(또는 ANY/ROOT). 매핑 없으면 ROOT(fail-closed)."""
    m = (method or "").upper()
    for rm, prefix, perm in _ROUTE_RULES:
        if rm and rm != m:
            continue
        if path == prefix or path.startswith(prefix + "/"):
            return perm
    return ROOT


def root_emails() -> set[str]:
    from src.whitelist import admin_emails

    return admin_emails()


def is_root(user) -> bool:
    return bool(user) and (getattr(user, "email", "") or "").lower() in root_emails()


def parse(raw: Optional[str]) -> Optional[list[str]]:
    """저장값(콤마 문자열) → 키 목록. None = 전 권한(하위호환)."""
    if raw is None:
        return None
    return [k for k in (p.strip() for p in str(raw).split(",")) if k in PERM_KEYS]


def serialize(perms: Optional[Iterable[str]]) -> Optional[str]:
    """키 목록 → 저장값. 모르는 키는 ValueError. None = 전 권한."""
    if perms is None:
        return None
    keys = [str(p).strip() for p in perms if str(p).strip()]
    bad = [k for k in keys if k not in PERM_KEYS]
    if bad:
        raise ValueError(f"알 수 없는 권한: {', '.join(bad)} (가능: {', '.join(PERM_KEYS)})")
    # 정의 순서로 정렬·중복 제거 — 비교·표시가 안정적이게.
    return ",".join(k for k in PERM_KEYS if k in set(keys))


def effective(user) -> list[str]:
    """이 사용자가 실제로 가진 권한 키. 관리자가 아니면 []."""
    if not user:
        return []
    if is_root(user):
        return list(PERM_KEYS)
    if not getattr(user, "is_admin", False):
        return []
    got = parse(getattr(user, "admin_perms", None))
    return list(PERM_KEYS) if got is None else got


def allowed(user, perm: str) -> bool:
    if perm == ANY:
        return bool(user) and (getattr(user, "is_admin", False) or is_root(user))
    if perm == ROOT:
        return is_root(user)
    return perm in effective(user)


def catalog() -> list[dict]:
    return [{"key": k, "label": label, "desc": desc} for k, label, desc in PERMS]
