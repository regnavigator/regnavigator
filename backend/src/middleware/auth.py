"""NextAuth JWT 검증 + user upsert 미들웨어.

흐름:
1. `Authorization: Bearer <jwt>` 헤더 추출
2. `NEXTAUTH_SECRET`로 HS256 검증 (만료·서명)
3. 페이로드에서 sub(user_id) / email / email_verified 추출
4. users 테이블에 upsert (admin email이면 is_admin=true 자동 부여)
5. `request.state.user_id` / `request.state.user_email` / `request.state.is_admin` 박음
6. 라우트 핸들러는 이를 읽어 권한·격리에 사용

dev 모드:
- `NEXTAUTH_SECRET` 미설정 → 미들웨어 통과만 허용. user_id=None.
- 또는 `AUTH_DEV_BYPASS_USER=<email>` 지정 → 그 이메일로 user upsert 후 통과.

운영:
- 인증 필수 라우트는 `Depends(get_current_user_id)` 또는 `require_admin`.
- 헬스체크·suggestions는 무인증 공개 그대로 (라우트 단에서 결정).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.observability import usage_context
from src.persistence import User, get_users_repo

_log = logging.getLogger(__name__)

AUTH_DEV_BYPASS_USER_ID = "dev-bypass-user"


# 화이트리스트 판정은 `src/whitelist.py` 가 정본이다(2026-09-10 분리).
# 종전엔 이 규칙이 세 곳(여기·routes/admin·notices)에 흩어져 있었고, 서비스가
# 라우트를 import 하는 순환(`notices → routes.admin → notices`)까지 있었다.
# 아래 이름들은 **기존 호출부 호환용 위임**이다 — 새 코드는 `src.whitelist` 를 직접 쓸 것.
from src import whitelist as _wl  # noqa: E402

ROOT_ADMIN_EMAILS = _wl.ROOT_ADMIN_EMAILS
invalidate_whitelist_cache = _wl.invalidate_cache


def _admin_email_set() -> set[str]:
    return _wl.admin_emails()


def _db_whitelist() -> set[str]:
    return _wl.db_entries()


def _beta_whitelist() -> Optional[set[str]]:
    return _wl.merged_entries()


def _beta_allowed(email: str) -> bool:
    return _wl.allowed(email)


def _decode_jwt(token: str, secret: str) -> dict:
    """NextAuth JWT 검증 — HS256 / 서명 + 만료 체크.

    JWT 클레임 호환 — sub/email/email_verified.
    """
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status_code=401, detail="JWT expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid JWT: {e}") from e


def _upsert_from_claims(claims: dict) -> User:
    sub = claims["sub"]
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="JWT missing email claim")
    # 클로즈 베타 게이트 — 화이트리스트 밖이면 users upsert 전에 차단(행도 안 남김).
    # JWT 가 유효해도(=front 가입을 우회해도) 백엔드가 최종 거부. 매 요청 검사라
    # 리스트에서 빼면 기발급 JWT 도 즉시 차단된다.
    if not _beta_allowed(email):
        raise HTTPException(
            status_code=403,
            detail="클로즈 베타 대상이 아닙니다. 참여를 원하시면 운영팀에 문의해주세요.",
        )
    verified_at = None
    if claims.get("email_verified"):
        from src.persistence.users_repo import _utcnow_iso
        verified_at = _utcnow_iso()
    # env 는 **부트스트랩 전용** — 목록에 있으면 admin 을 부여하되, 없다고 해서
    # 뺏지는 않는다(None = 변경 없음).
    #
    # 예전엔 매 요청 `is_admin = email in _admin_email_set()` 를 True/False 로
    # 항상 넘겨 upsert 가 덮어썼다. 그래서 `PATCH /admin/users/{id}` 로 부여한
    # 권한이 **그 사용자의 다음 요청 한 번**에 false 로 돌아갔다 — 운영자는
    # "권한을 줬다"고 믿는데 실제로는 취소된 상태(2026-08-04 감사 H-4).
    # 진실원을 DB 로 두고 env 는 승격만 한다. 강등은 PATCH 로(단, env 에 남아
    # 있으면 다음 로그인에 다시 승격되므로 env 에서도 빼야 한다).
    is_admin = True if email in _admin_email_set() else None
    user = get_users_repo().upsert(
        id=sub, email=email,
        email_verified_at=verified_at,
        is_admin=is_admin,
    )
    # 회원탈퇴(소프트삭제) 계정은 접근 차단 — upsert 는 deleted_at 을 건드리지
    # 않으므로(되살리지 않음) 여기서 검사. 재가입은 관리자 복구 또는 신규 sub.
    if getattr(user, "deleted_at", None):
        raise HTTPException(
            status_code=403,
            detail="탈퇴한 계정입니다. 재가입을 원하시면 운영팀에 문의해주세요.",
        )
    return user


def _dev_bypass_user_or_none() -> Optional[User]:
    """`AUTH_DEV_BYPASS_USER=<email>` 있으면 그 이메일로 user upsert. dev only."""
    email = (os.getenv("AUTH_DEV_BYPASS_USER") or "").strip().lower()
    if not email:
        return None
    is_admin = email in _admin_email_set()
    return get_users_repo().upsert(
        id=AUTH_DEV_BYPASS_USER_ID,
        email=email,
        email_verified_at=None,
        is_admin=is_admin,
    )


# ---------------------------------------------------------------------------
# Starlette/FastAPI 미들웨어
# ---------------------------------------------------------------------------
# 보호되지 않는 라우트(공개) — 헤더 없어도 401 안 던짐.
PUBLIC_PATH_PREFIXES = (
    "/healthz",
    "/readyz",      # 의존성 readiness — LB/모니터가 인증 없이 폴링
    "/load",        # 서버 혼잡 표시 — 프런트가 배지용으로 폴링(인증 전에도 노출)
    "/legal",       # 법적 고지 정본 — 로그인 전에도 상시 노출(약관 동의 화면)
    "/beta",        # 가입 시점 화이트리스트 확인 — 로그인 전 호출(boolean 만)
    "/announcements",  # 업데이트 내역 — 랜딩 게시판(/updates)이 비로그인으로 열람(2026-09-02)
    "/suggestions",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """모든 요청에 대해 JWT 검증을 시도. 통과 시 request.state.user_* 박음.

    - 공개 라우트(`PUBLIC_PATH_PREFIXES`)는 검증 건너뜀.
    - dev 모드(`NEXTAUTH_SECRET` 없음): 모든 요청 통과. user_id=None.
    - dev bypass(`AUTH_DEV_BYPASS_USER=<email>` 설정): 그 이메일로 자동 로그인 user 발급.
    - 운영: 헤더 누락·검증 실패 → 401.
    """

    async def dispatch(self, request: Request, call_next):
        # CORS preflight (OPTIONS) — 인증 없이 통과시켜 CORSMiddleware 가 응답 헤더를 붙이도록.
        # FastAPI 미들웨어 실행 순서상 AuthMiddleware 가 CORSMiddleware 보다 먼저 돌기 때문에
        # 여기서 막으면 브라우저 preflight 가 401 로 떨어져 CORS 위반 진단을 받는다.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # 공개 라우트 — 검증 X
        if any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        secret = (os.getenv("NEXTAUTH_SECRET") or "").strip()

        # dev 모드 — 인증 비활성
        if not secret:
            bypass = _dev_bypass_user_or_none()
            request.state.user_id = bypass.id if bypass else None
            request.state.user_email = bypass.email if bypass else None
            request.state.is_admin = bypass.is_admin if bypass else False
            usage_context.bind(user_id=request.state.user_id)
            blocked = _maintenance_block_or_none(request.state.is_admin)
            if blocked is not None:
                return blocked
            return await call_next(request)

        auth_header = request.headers.get("authorization") or request.headers.get(
            "Authorization"
        )
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return _error_401("Authorization header required")

        token = auth_header[len("Bearer "):].strip()
        try:
            claims = _decode_jwt(token, secret)
            user = _upsert_from_claims(claims)
        except HTTPException as e:
            # 401(검증 실패)·403(베타 화이트리스트) — status 보존.
            return _error_json(e.status_code, e.detail)

        request.state.user_id = user.id
        request.state.user_email = user.email
        request.state.is_admin = user.is_admin
        # LLM 토큰 귀속의 기준점 — 이 요청에서 파생되는 모든 LLM 호출(auto-title·
        # 커버리지 판정·압축 요약 등 config 를 안 넘기는 곳 포함)이 이 값을
        # 물려받는다. contextvar 는 call_next 이후 태스크로 복사된다.
        usage_context.bind(user_id=user.id)

        blocked = _maintenance_block_or_none(user.is_admin)
        if blocked is not None:
            return blocked

        return await call_next(request)


def _maintenance_block_or_none(is_admin: bool) -> Optional[Response]:
    """점검 모드면 비관리자 요청을 503 으로 거절. 관리자는 통과(해제·확인).

    공개 라우트(health·load·legal·beta)는 dispatch 초반에 이미 반환되므로 여기
    도달하지 않는다 → 점검 중에도 프런트가 상태 폴링·점검 화면 표시 가능.
    """
    if is_admin:
        return None
    try:
        from src.maintenance import public_status
        st = public_status()
    except Exception:  # noqa: BLE001 — 점검 조회 실패가 서비스를 막으면 안 됨
        return None
    if not st.get("active"):
        return None
    import json
    return Response(
        content=json.dumps(
            {"detail": st.get("message") or "서버 점검 중입니다.",
             "maintenance": True},
            ensure_ascii=False,
        ),
        status_code=503,
        media_type="application/json",
        headers={"Retry-After": "600"},
    )


def _error_json(status_code: int, detail: str) -> Response:
    import json
    return Response(
        content=json.dumps({"detail": detail}, ensure_ascii=False),
        status_code=status_code,
        media_type="application/json",
    )


def _error_401(detail: str) -> Response:
    return _error_json(401, detail)


# ---------------------------------------------------------------------------
# 라우트 핸들러용 dependency
# ---------------------------------------------------------------------------
def get_current_user_id(request: Request) -> Optional[str]:
    """request.state에 박힌 user_id 반환. dev bypass·미들웨어 통과 시 채워짐."""
    return getattr(request.state, "user_id", None)


def get_current_user(request: Request) -> Optional[User]:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        return None
    return get_users_repo().get(uid)


def _route_template(request: Request) -> str:
    """매칭된 라우트의 경로 템플릿(`/admin/users/{user_id}`) — 권한 매핑 키."""
    route = request.scope.get("route")
    return (getattr(route, "path_format", None) or getattr(route, "path", None)
            or request.url.path)


def require_admin(request: Request) -> User:
    """admin 라우트용 dependency — 비admin이면 403, 기능 권한 없으면 403.

    기능별 권한(2026-09-22): 라우트 → 권한 매핑은 `src/admin_perms.py` 한 곳.
    루트 관리자는 전 권한, 그 외 관리자는 `users.admin_perms` 에 켜진 기능만.
    """
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    from src import admin_perms as _perms

    need = _perms.perm_for_route(request.method, _route_template(request))
    if not _perms.allowed(user, need):
        label = "루트 관리자" if need == _perms.ROOT else _perms.LABELS.get(need, need)
        raise HTTPException(status_code=403,
                            detail=f"'{label}' 권한이 없습니다 — 루트 관리자에게 요청하세요.")
    return user
