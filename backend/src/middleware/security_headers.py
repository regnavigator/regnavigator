"""보안 응답 헤더 — XSS·clickjacking·MIME-sniff 방어.

env:
- `SECURITY_HEADERS_DISABLE=1` — 모든 헤더 비활성 (dev·테스트)
- `STRICT_TRANSPORT_SECURITY` — 운영 HTTPS면 활성 (`max-age=31536000; includeSubDomains`)
- `CSP` — 옵션 (커스텀 CSP 박을 때만)

기본 헤더:
| 헤더 | 값 | 효과 |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | MIME sniff 차단 |
| `X-Frame-Options` | `DENY` | clickjacking |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | referrer 누설 ↓ |
| `Permissions-Policy` | `accelerometer=(), camera=(), geolocation=(), microphone=()` | 권한 자동 거부 |
| `X-DNS-Prefetch-Control` | `off` | dns prefetch 누설 ↓ |
| `Strict-Transport-Security` | env 설정 시 | HTTPS 강제 |
| `Content-Security-Policy` | env 설정 시 | XSS 방어 |
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware


def _default_headers() -> dict[str, str]:
    h = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        ),
        "X-DNS-Prefetch-Control": "off",
    }
    hsts = os.getenv("STRICT_TRANSPORT_SECURITY")
    if hsts:
        h["Strict-Transport-Security"] = hsts
    csp = os.getenv("CSP")
    if csp:
        h["Content-Security-Policy"] = csp
    return h


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """모든 응답에 보안 헤더 부착. SSE 스트리밍에도 안전 (Content-Type 변경 X)."""

    def __init__(self, app):
        super().__init__(app)
        self.disabled = os.getenv("SECURITY_HEADERS_DISABLE") == "1"
        self.headers = _default_headers()

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if self.disabled:
            return response
        # 사용자가 같은 헤더를 명시 set했다면 그대로 두고 누락된 것만 채움
        for k, v in self.headers.items():
            if k not in response.headers:
                response.headers[k] = v
        return response
