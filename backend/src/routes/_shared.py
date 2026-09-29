"""routes 공용 헬퍼 — 여러 라우터가 공유하는 인증·직렬화·시각 유틸."""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import HTTPException


def _check_auth(authorization: Optional[str]) -> None:
    """보고서 라우트 토큰 검사. `API_TOKEN` 미설정 시 dev 모드(통과)."""
    expected = os.getenv("API_TOKEN")
    if not expected:
        return  # dev 모드 — 인증 비활성
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")
    if authorization[len("Bearer "):] != expected:
        raise HTTPException(status_code=403, detail="Invalid token")


def assert_thread_access(thread_id: str, request) -> None:
    """thread 소유자만 통과. 불일치·미존재는 404(존재 비노출).

    `routes/chat.py:_owned_meta_or_404` 와 같은 정책 — 그쪽은 메타를 돌려주고
    신규 생성(allow_missing)을 다루므로 별도 유지.
    """
    from src.persistence.threads_repo import get_threads_repo

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        return  # dev 무인증(NEXTAUTH_SECRET 미설정) — 로컬 개발 편의
    meta = get_threads_repo().get_meta(thread_id)
    owner = meta.get("user_id") if meta else None
    if owner is None or str(owner) != str(user_id):
        raise HTTPException(status_code=404, detail="thread not found")


def assert_report_access(meta, request) -> None:
    """보고서 소유권 — 소유자만 통과. 불일치·불명은 404(존재 비노출).

    소유자 판정은 두 근거를 순서대로 본다:
      ① 소속 thread 의 `user_id` — 정상 경로.
      ② `report_runs.user_id`(run 기록) — thread 가 없을 때의 2차 근거.
         `prune_threads.py:62` 가 보관기간 지난 thread 를 지우면서 reports 는
         남기므로, ①만 보면 **정당한 소유자가 오래된 보고서에서 잠긴다**.

    ⚠️ 둘 다로도 확인이 안 되면 **차단**한다(fail-open 금지). `delete_thread` 는
    reports 를 지우지 않으므로, 통과시키면 "대화 삭제 = 보고서 전체 공개"가 된다.

    사고 배경(2026-08-04 감사): 조회 3라우트(list/get/download)에 소유권 검사가
    아예 없어 로그인한 누구나 report_id 만 알면 타인 보고서 전문을 받을 수 있었다.
    유일한 검사이던 `_check_auth` 는 API_TOKEN 미설정 시 무조건 통과라 no-op.
    """
    from src.persistence import get_report_runs_repo
    from src.persistence.threads_repo import get_threads_repo

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        return  # dev 무인증

    thread_id = getattr(meta, "thread_id", None)
    owner = None
    if thread_id:
        tmeta = get_threads_repo().get_meta(thread_id)
        owner = tmeta.get("user_id") if tmeta else None
    if owner is None:
        try:
            owner = get_report_runs_repo().owner_of_report(getattr(meta, "id", None))
        except Exception:  # 조회 실패를 통과로 바꾸지 않는다 — owner=None 유지
            owner = None

    if owner is None or str(owner) != str(user_id):
        raise HTTPException(status_code=404, detail="report not found")


def _meta_dict(meta) -> dict:
    """ReportMeta → JSON 직렬화 dict (citations_json 컬럼을 파싱해 펼침)."""
    d = meta.as_dict()
    cit = d.pop("citations_json", None)
    d["citations"] = json.loads(cit) if cit else None
    return d


def _utcnow_iso_safe() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
