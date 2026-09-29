"""프런트가 발급한 JWT를 백엔드 NEXTAUTH_SECRET으로 검증해 호환성 확인.

usage:
    # 토큰 인자로
    python scripts/verify_jwt.py "eyJhbGc..."

    # stdin으로 (curl·복붙 편리)
    echo "eyJhbGc..." | python scripts/verify_jwt.py

    # 환경변수 NEXTAUTH_SECRET이 설정돼 있어야 함
    NEXTAUTH_SECRET=<frontend와 동일> python scripts/verify_jwt.py "eyJ..."

성공 출력:
    [ok] header: {alg=HS256, typ=JWT}
    [ok] signature 검증 통과
    [ok] claims: sub=user-..., email=admin@..., exp=2026-..., email_verified=True
    [ok] admin? True (ADMIN_EMAILS 매칭)
    [ok] 백엔드 _decode_jwt 동일 결과 - PyJWT decode 통과

실패 시 어디서 깨졌는지 명시:
    [!] signature 검증 실패 - secret 불일치
    [!] expired - exp가 과거
    [!] alg 다름 - 받은 알고리즘 ≠ HS256
    [!] sub/email 클레임 누락
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad and pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def _peek_header_payload(token: str) -> tuple[dict, dict]:
    """서명 검증 없이 header·payload 디코드 - 진단용."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"JWT는 3 segments (header.payload.sig). 받은 segment: {len(parts)} → JWE 가능성 (NextAuth 기본)")
    header = json.loads(_b64url_decode(parts[0]))
    payload = json.loads(_b64url_decode(parts[1]))
    return header, payload


def main() -> int:
    if len(sys.argv) >= 2:
        token = sys.argv[1].strip()
    else:
        token = sys.stdin.read().strip()

    if not token:
        print("[!] 토큰 입력 필요 - 인자 또는 stdin", file=sys.stderr)
        return 2

    # Bearer prefix 자동 제거
    if token.lower().startswith("bearer "):
        token = token[len("bearer "):].strip()

    secret = (os.getenv("NEXTAUTH_SECRET") or "").strip()
    if not secret:
        print("[!] NEXTAUTH_SECRET env 미설정 - 백엔드와 같은 값 박아야 검증 가능", file=sys.stderr)
        return 2

    print(f"== JWT 검증 ==")
    print(f"  token (앞 60자): {token[:60]}...")
    print(f"  secret length: {len(secret)} bytes")

    # 0) 형식 - 3 segment JWS 확인
    try:
        header, payload = _peek_header_payload(token)
    except Exception as e:
        print(f"[!] {e}")
        return 1

    print(f"[ok] header: {header}")
    if header.get("alg") != "HS256":
        print(f"[!] alg = {header.get('alg')} - 백엔드는 HS256만 받음. jose.SignJWT({{...}}).setProtectedHeader({{alg:'HS256'}}) 확인.")
        return 1

    # 1) PyJWT 검증 (백엔드 _decode_jwt와 동일 로직)
    try:
        import jwt as pyjwt
    except ImportError:
        print("[!] PyJWT 미설치 - `pip install pyjwt`")
        return 2

    try:
        claims = pyjwt.decode(
            token, secret, algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
        print(f"[ok] signature 검증 통과")
    except pyjwt.ExpiredSignatureError:
        exp_age = int(time.time()) - payload.get("exp", 0)
        print(f"[!] expired - exp가 {exp_age}초 전")
        return 1
    except pyjwt.InvalidSignatureError:
        print(f"[!] signature 검증 실패 - secret 불일치 (양쪽 NEXTAUTH_SECRET 같은지 다시 확인)")
        return 1
    except pyjwt.MissingRequiredClaimError as e:
        print(f"[!] required claim 누락: {e}")
        return 1
    except Exception as e:
        print(f"[!] 검증 실패: {type(e).__name__}: {e}")
        return 1

    # 2) 클레임 미리보기
    sub = claims.get("sub")
    email = claims.get("email")
    email_verified = claims.get("email_verified")
    exp = claims.get("exp")
    print(f"[ok] claims:")
    print(f"     sub:            {sub}")
    print(f"     email:          {email}")
    print(f"     email_verified: {email_verified}")
    if exp:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(exp, tz=timezone.utc)
        remaining = exp - int(time.time())
        print(f"     exp:            {dt.isoformat()} (남은 {remaining}초)")

    if not sub:
        print(f"[!] sub 클레임 누락 - 백엔드 user_upsert 실패할 것")
        return 1
    if not email:
        print(f"[!] email 클레임 누락 - 백엔드 401 (JWT missing email claim)")
        return 1

    # 3) 백엔드 _decode_jwt 동일 함수 직접 호출
    sys.path.insert(0, ".")
    try:
        from src.middleware.auth import _decode_jwt, _admin_email_set
    except ImportError as e:
        print(f"[!] 백엔드 모듈 import 실패: {e}")
        return 1

    try:
        backend_claims = _decode_jwt(token, secret)
    except Exception as e:
        print(f"[!] 백엔드 _decode_jwt 실패: {e}")
        return 1
    print(f"[ok] 백엔드 _decode_jwt 동일 결과 - PyJWT decode 통과")

    # 4) admin 매칭
    admins = _admin_email_set()
    if admins:
        is_admin = (email or "").lower() in admins
        print(f"[ok] admin? {is_admin} (ADMIN_EMAILS={sorted(admins)})")
    else:
        print(f"     admin? 판정 불가 - ADMIN_EMAILS env 미설정")

    print(f"\n→ 호환성 OK. 백엔드 /me/usage·/threads/* 모두 통과해야 정상.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
