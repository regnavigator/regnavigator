"""medi-back FastAPI 미들웨어 — 인증·쿼터.

- auth: NextAuth JWT 검증 + user upsert + request.state.user_id 박기
- quota: 토큰 한도 체크 (S4 단계)
"""

from .auth import (
    AUTH_DEV_BYPASS_USER_ID,
    AuthMiddleware,
    get_current_user_id,
    get_current_user,
    require_admin,
)
from .quota import (
    QuotaMiddleware,
    effective_limits,
    usage_summary,
)
from .rate_limit import RateLimitMiddleware
from .security_headers import SecurityHeadersMiddleware

__all__ = [
    "AuthMiddleware",
    "AUTH_DEV_BYPASS_USER_ID",
    "QuotaMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "effective_limits",
    "usage_summary",
    "get_current_user_id",
    "get_current_user",
    "require_admin",
]
