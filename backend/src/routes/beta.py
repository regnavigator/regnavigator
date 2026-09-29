"""공개 베타 게이트 확인 — 가입 시점 화이트리스트 검사 (2026-07-15).

medi-front 의 가입 3경로(signup-init·magic-link 발송·signIn 콜백)가 이 엔드포인트로
"이 이메일이 가입 가능한가"를 물어 **백엔드 화이트리스트(env ∪ DB, admin 관리)를
단일 진실원**으로 쓴다. 로그인 전 호출이라 무인증(공개) — 단, 전체 목록은 절대
반환하지 않고 boolean 만(열거 방지). AuthMiddleware `PUBLIC_PATH_PREFIXES` 에 `/beta`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.post("/beta/check")
def beta_check(request: Request, body: dict):
    """{email} → {allowed, gate_active}. 목록 자체는 노출하지 않음(boolean 만)."""
    email = str(body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="email 필요")
    from src.middleware.auth import _beta_allowed, _beta_whitelist

    return {
        "allowed": _beta_allowed(email),
        "gate_active": _beta_whitelist() is not None,
    }
