"""토큰 한도 체크.

dispatch:
1. 사용자 요청 진입 시점에 오늘/이달 누적 input+output 토큰 합계 조회
2. 사용자별 override 한도 또는 시스템 기본값과 비교
3. 둘 중 하나라도 초과하면 429 + quota_blocked event emit

쿼터 검사 라우트: LLM 호출이 일어나는 라우트 — `POST /chat` · `POST /chat/{tid}/auto-title` ·
`POST /reports`. 그 외는 통과. (구 langgraph `/threads/*/runs*` 는 2026-07-14 은퇴 — 패턴은
2026-09-22 제거. 남아 있는 동안 테스트가 그 죽은 경로로 차단을 검증해, 실제 경로 검증이 비어 있었다.)
공개 라우트(/healthz, /suggestions, /docs)와 admin 라우트는 검사 스킵.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.persistence import (
    Event,
    User,
    get_events_repo,
    get_users_repo,
    start_of_today_local_iso,
    start_of_month_local_iso,
)

_log = logging.getLogger(__name__)


def _system_daily_limit() -> int:
    # 2026-08-05: 10,000,000 → **2,000,000**.
    #
    # 종전 1000만은 실사용의 30배라 429 가 **날 수 없는** 값이었다(쿼터가 장식).
    # 그렇다고 조이는 게 능사도 아니다 — 지금 규모(활성 2~6명, 하루 총비용 $1
    # 미만)에서 이 한도의 역할은 배급이 아니라 **폭주·남용 차단기**다. 정상
    # 파워유저의 하루가 $10 인데 그를 막는 손실이 그 $10 보다 크다.
    #
    # 실측(실사용자-일 52건, dev·e2e 제외): 중앙값 15.4만 · p90 79.3만 ·
    # p95 92.0만 · p99 339만 · 최대 395만. 100만 토큰당 $1.66.
    # 200만 = p95 의 2배 여유. 과거 데이터에서 3.8%(2명)만 초과 — 보고서를
    # 여러 건 돌린 날은 통과시키고 폭주만 잡는다. 사용자당 일 손실 상한 $3.3.
    #
    # 100만으로 잡으면 p95 에 거의 붙어 정상 사용을 자른다. 게다가 같은 날
    # 토큰 회계 누락(15%·미계측 3경로)을 고쳐 같은 사용 패턴도 더 높게 집계된다.
    # 개별 사용자는 admin 의 daily_token_limit_override 로 올린다.
    #
    # 2026-08-19: 200만 → **2,000만**(운영 판단 — 베타 동안 사실상 무제한).
    # 지금 목표는 배급이 아니라 **폭주·남용 차단기**뿐이다. 실측 p90 79.3만
    # 대비 25배·중앙값의 130배라 정상 사용은 어떤 패턴으로도 걸리지 않고,
    # 무한 루프·키 유출 같은 사고만 하루 손실 ~$33 선에서 끊는다.
    # **한도 자체를 제거하지 않는 이유**: 차단기가 사라지면 사고 비용에 상한이
    # 없고, 나중에 과금 전략을 붙일 때 계측·경로가 이미 살아 있어야 한다.
    # 사용량이 붙으면 그때 실측으로 다시 조인다(플랜별 한도·초과 과금 등).
    return int((os.getenv("DEFAULT_DAILY_TOKEN_LIMIT") or "").strip() or "20000000")


def _system_monthly_limit() -> int:
    # 기본값 상향 (2026-07-22): 20000000 → 1000000000(1000M). env 미설정 시 적용.
    return int((os.getenv("DEFAULT_MONTHLY_TOKEN_LIMIT") or "").strip() or "1000000000")


def effective_limits(user: User) -> tuple[int, int]:
    """사용자별 override가 있으면 그 값, 없으면 시스템 기본값.

    값 `0` = **무제한**(차단 안 함). 특정 사용자·환경에만 한도를 완전히 푸는
    용도(데모 계정 등) — 시스템 기본값을 0 으로 두는 것은 권장하지 않는다
    (폭주 사고에 상한이 사라진다).
    """
    daily = (user.daily_token_limit_override
             if user.daily_token_limit_override is not None
             else _system_daily_limit())
    monthly = (user.monthly_token_limit_override
               if user.monthly_token_limit_override is not None
               else _system_monthly_limit())
    return daily, monthly


def usage_summary(user_id: str) -> dict:
    """사용자 한 명의 일/월 누적 사용량 조회."""
    repo = get_events_repo()
    daily_in, daily_out, daily_cost = repo.sum_tokens_for_user(
        user_id, since=start_of_today_local_iso()
    )
    monthly_in, monthly_out, monthly_cost = repo.sum_tokens_for_user(
        user_id, since=start_of_month_local_iso()
    )
    return {
        "daily_input_tokens": daily_in,
        "daily_output_tokens": daily_out,
        "daily_total_tokens": daily_in + daily_out,
        "daily_cost_usd": round(daily_cost, 6),
        "monthly_input_tokens": monthly_in,
        "monthly_output_tokens": monthly_out,
        "monthly_total_tokens": monthly_in + monthly_out,
        "monthly_cost_usd": round(monthly_cost, 6),
    }


# 쿼터 검사 대상 path 패턴 — LLM 호출이 일어나는 곳만.
_QUOTA_PATH_PATTERNS = (
    "/chat",      # 자체 SSE 채팅 루프 (ADR-0001 Phase 1)
    "/reports",   # POST /reports 보고서 트리거 (Phase 3) — GET 류는 아래에서 제외
)


def _is_quota_path(path: str, method: str = "GET") -> bool:
    if not any(path.startswith(p) for p in _QUOTA_PATH_PATTERNS):
        return False
    if path == "/chat":
        return method.upper() == "POST"  # 자체 SSE 루프 — LLM 호출
    if path.startswith("/chat/"):
        # LLM 을 부르는 건 auto-title 뿐 — 목록/state 조회는 쿼터 초과여도 허용
        # (초과 사용자가 자기 대화를 못 여는 것 방지).
        return path.endswith("/auto-title") and method.upper() == "POST"
    if path == "/reports":
        return method.upper() == "POST"  # 트리거만 — 목록/메타 GET 은 제외
    return False  # /reports/{id}·/reports/{id}/download 등 조회


class QuotaMiddleware(BaseHTTPMiddleware):
    """LLM 호출 라우트 진입 시 사용자 누적 토큰 vs 한도 체크."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not _is_quota_path(path, request.method):
            return await call_next(request)

        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            # 인증 비활성(dev) — 쿼터도 비활성
            return await call_next(request)

        repo_users = get_users_repo()
        user = repo_users.get(user_id)
        if not user:
            # auth 미들웨어가 통과시켰는데 user 없음 — 일관성 깨짐.
            return await call_next(request)

        daily_limit, monthly_limit = effective_limits(user)

        repo_events = get_events_repo()
        d_in, d_out, _ = repo_events.sum_tokens_for_user(
            user_id, since=start_of_today_local_iso()
        )
        m_in, m_out, _ = repo_events.sum_tokens_for_user(
            user_id, since=start_of_month_local_iso()
        )
        daily_used = d_in + d_out
        monthly_used = m_in + m_out

        # limit == 0 은 무제한(effective_limits 참조) — 차단 판정에서 제외.
        if daily_limit > 0 and daily_used >= daily_limit:
            return _quota_blocked_response(
                user_id=user_id, period="daily",
                used=daily_used, limit=daily_limit,
            )
        if monthly_limit > 0 and monthly_used >= monthly_limit:
            return _quota_blocked_response(
                user_id=user_id, period="monthly",
                used=monthly_used, limit=monthly_limit,
            )

        response = await call_next(request)

        # 응답 헤더에 잔여량 표시 — 프런트가 진행 상황 보여줄 수 있게
        response.headers["X-Quota-Daily-Used"] = str(daily_used)
        response.headers["X-Quota-Daily-Limit"] = str(daily_limit)
        response.headers["X-Quota-Monthly-Used"] = str(monthly_used)
        response.headers["X-Quota-Monthly-Limit"] = str(monthly_limit)
        return response


def _quota_blocked_response(*, user_id: str, period: str,
                            used: int, limit: int) -> JSONResponse:
    # quota_blocked event emit
    try:
        get_events_repo().emit(Event(
            id="", ts="",
            event_type="quota_blocked",
            user_id=user_id,
            payload_json=json.dumps({
                "period": period, "used": used, "limit": limit,
            }, ensure_ascii=False),
        ))
    except Exception as e:
        _log.warning("quota_blocked event emit failed: %s", e)

    msg_kr = (
        f"오늘 사용량 한도({limit:,} 토큰)에 도달했습니다. 내일 다시 이용 가능합니다."
        if period == "daily"
        else f"이번 달 사용량 한도({limit:,} 토큰)에 도달했습니다. 다음 달 1일에 초기화됩니다."
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": msg_kr,
            "period": period,
            "tokens_used": used,
            "tokens_limit": limit,
        },
    )
