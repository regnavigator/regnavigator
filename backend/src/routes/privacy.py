"""정보주체 권리 + 국외이전 동의 — 개인정보보호법 이행.

개인정보처리방침이 **약속한 것을 코드가 실제로 하도록** 하는 라우트. 방침에 적고
구현하지 않으면 허위 고지가 된다.

| 법 | 요구 | 구현 |
|---|---|---|
| 제28조의8 | **국외이전 동의** (질의가 Anthropic·OpenAI 등 미국으로 감) | `POST /me/consent` 로 동의 기록(버전·시각). `GET /me/consent` 로 현재 상태 |
| 제35조 | 열람 요구 | `GET /me/data` — 보관 중인 내 데이터 요약 |
| 제36·37조 | 삭제·처리정지 요구 | `POST /me/erase` — 요청 접수 + ops 알림 → `scripts/erase_user.py` 로 파기 |

동의는 별도 테이블 없이 `events`(event_type=`legal_consent`)에 기록한다 — 스키마
변경 없이 감사 추적(누가·언제·어느 버전)이 남는다.

`LEGAL_VERSION` 이 오르면 `GET /me/consent` 가 `needs_consent=true` 를 반환해
프런트가 재동의를 받는다.

⚠️ 경로 주의: `/legal` 은 **공개 prefix**(인증 우회)라 동의 엔드포인트를 그 아래 두면
user_id 가 안 박힌다 → `/me/consent` 로 둔다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.legal import LEGAL_VERSION
from src.persistence import get_events_repo, get_users_repo
from src.persistence.events_repo import Event
from src.routes._shared import _check_auth

_log = logging.getLogger(__name__)
router = APIRouter()

CONSENT_EVENT = "legal_consent"
ERASE_EVENT = "erasure_request"
WITHDRAW_EVENT = "account_withdraw"


def _uid(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(status_code=401, detail="인증 필요")
    return str(uid)


def _latest_consent(user_id: str) -> Optional[dict]:
    evs = get_events_repo().list_for_user(user_id, event_type=CONSENT_EVENT, limit=1)
    if not evs:
        return None
    try:
        payload = json.loads(evs[0].payload_json or "{}")
    except ValueError:
        payload = {}
    return {"version": payload.get("version"), "agreed_at": evs[0].ts,
            "scopes": payload.get("scopes") or []}


@router.get("/me/consent")
def consent_status(request: Request, authorization: Optional[str] = Header(None)):
    """현재 동의 상태 — `needs_consent` 면 프런트가 동의 화면을 띄운다."""
    _check_auth(authorization)
    cur = _latest_consent(_uid(request))
    agreed = _is_agreed(cur)
    return JSONResponse({
        "current_version": LEGAL_VERSION,
        "agreed_version": cur["version"] if cur else None,
        "agreed_at": cur["agreed_at"] if cur else None,
        "agreed_scopes": cur["scopes"] if cur else [],
        "required_scopes": list(REQUIRED_SCOPES),
        "needs_consent": not agreed,
    })


#: 동의 항목 — 국외이전은 **별도 동의**라 분리(법 제28조의8). marketing 은 선택.
REQUIRED_SCOPES = ("terms", "transfer")
OPTIONAL_SCOPES = ("marketing",)


def _is_agreed(cur: Optional[dict]) -> bool:
    """최신 버전 + **필수 항목 전부** 동의해야 통과(하나만 빠져도 재동의)."""
    return bool(cur and cur["version"] == LEGAL_VERSION
                and all(s in cur["scopes"] for s in REQUIRED_SCOPES))


#: 동의 확인 캐시(user_id → 확인 시각) — /chat 마다 이벤트를 읽지 않게. 동의 철회 경로가
#: 없어 긍정만 캐시한다. 고지 버전이 바뀌면 배포(=프로세스 재시작)로 비워진다.
_CONSENT_OK: dict[str, float] = {}
_CONSENT_TTL_S = 600.0

CONSENT_REQUIRED_DETAIL = ("서비스 이용 동의가 필요합니다. 화면의 '서비스 이용 동의' 창에서 "
                           "동의한 뒤 다시 시도해주세요. 창이 보이지 않으면 새로고침해 주세요.")


def require_consent(request: Request) -> None:
    """동의 없는 이용 차단(2026-09-23) — 질문·보고서 요청 입구에서 부른다.

    종전엔 동의 확인이 프런트 게이트뿐이라(조회 실패 시 통과) 동의 없이도 쓸 수 있었다.
    관리자는 예외(운영·점검). `CONSENT_ENFORCE=0` 이면 끈다(테스트·긴급 우회).
    동기 DB 읽기 — async 라우트에서는 `asyncio.to_thread` 로 부를 것.
    """
    if (os.getenv("CONSENT_ENFORCE") or "1").strip() == "0":
        return
    if getattr(request.state, "is_admin", False):
        return
    uid = getattr(request.state, "user_id", None)
    if not uid:
        return  # 인증은 호출부 책임
    uid = str(uid)
    now = time.monotonic()
    if now - _CONSENT_OK.get(uid, -_CONSENT_TTL_S) < _CONSENT_TTL_S:
        return
    if _is_agreed(_latest_consent(uid)):
        _CONSENT_OK[uid] = now
        return
    raise HTTPException(status_code=403, detail=CONSENT_REQUIRED_DETAIL)


@router.post("/me/consent")
async def give_consent(request: Request, authorization: Optional[str] = Header(None)):
    """동의 기록 — 프런트 가입 화면의 체크박스를 **서버에 영속**한다.

    body: `{"version": "...", "scopes": ["terms", "transfer", "marketing"?]}`
    필수 `terms`(약관·개인정보) + `transfer`(국외이전, 법 제28조의8) 둘 다 없으면 400.

    ⚠️ 이 엔드포인트가 없던 동안 프런트는 체크박스를 **화면에서만** 받고 아무데도
    저장하지 않았다 — 동의 사실을 입증할 수 없는 상태였다.
    """
    _check_auth(authorization)
    uid = _uid(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    version = str(body.get("version") or LEGAL_VERSION)
    if version != LEGAL_VERSION:
        raise HTTPException(status_code=409,
                            detail=f"고지 버전 불일치(current={LEGAL_VERSION})")

    raw = body.get("scopes")
    scopes = [str(s) for s in raw] if isinstance(raw, list) else list(REQUIRED_SCOPES)
    missing = [s for s in REQUIRED_SCOPES if s not in scopes]
    if missing:
        raise HTTPException(status_code=400, detail=f"필수 동의 누락: {missing}")
    scopes = [s for s in scopes if s in REQUIRED_SCOPES + OPTIONAL_SCOPES]

    get_events_repo().emit(Event(
        id="", ts="", event_type=CONSENT_EVENT, user_id=uid,
        payload_json=json.dumps({"version": version, "scopes": scopes},
                                ensure_ascii=False),
    ))
    _CONSENT_OK.pop(uid, None)  # 다음 요청에서 새로 확인
    _log.info("legal_consent 기록: user=%s version=%s scopes=%s", uid, version, scopes)
    return JSONResponse({"ok": True, "version": version, "scopes": scopes})


@router.get("/me/data")
def my_data(request: Request, authorization: Optional[str] = Header(None)):
    """열람 요구(법 제35조) — 보관 중인 내 데이터 요약."""
    _check_auth(authorization)
    uid = _uid(request)
    user = get_users_repo().get(uid)
    events = get_events_repo().list_for_user(uid, limit=1000)
    return JSONResponse({
        "user": {"id": uid, "email": getattr(user, "email", None),
                 "created_at": getattr(user, "created_at", None)},
        "consent": _latest_consent(uid),
        "counts": {"events": len(events)},
        "retention": {
            "대화": "마지막 활동 후 90일 — 대화 속 인용 함께 삭제",
            "심층 보고서": "생성 후 30일 — 목록·제목·내용 모두 삭제",
            "작성한 서식": "대화와 함께 삭제 — 보관한 서식은 유지",
            "회원 정보": "탈퇴 후 비활성 보관, 삭제 요청 시 파기",
        },
        # 개인정보처리방침 §5 와 일치해야 한다(LangSmith 는 2026-09-10 제거).
        "국외이전": ["Anthropic(미국)", "OpenAI(미국)", "Tavily(미국)"],
        "notice": "상세는 GET /legal 및 개인정보처리방침 참조",
    })


@router.post("/me/erase")
async def request_erasure(request: Request, authorization: Optional[str] = Header(None)):
    """삭제·처리정지 요구(법 제36·37조) 접수 → ops 알림 → 운영자가 파기 실행.

    즉시 파기하지 않는 이유: 체크포인트·blob·이벤트에 걸친 파기는 되돌릴 수 없어
    오작동 시 피해가 크다. 접수는 **감사 추적**으로 남고(`erasure_request` 이벤트),
    운영자가 `python scripts/erase_user.py <user_id> --apply` 로 실행한다.
    """
    _check_auth(authorization)
    uid = _uid(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    reason = str(body.get("reason") or "")

    get_events_repo().emit(Event(
        id="", ts="", event_type=ERASE_EVENT, user_id=uid,
        payload_json=json.dumps({"reason": reason[:500]}, ensure_ascii=False),
    ))
    try:
        from src.observability.alerts import send_ops_alert
        # webhook 은 동기 httpx(타임아웃 5초) — 이벤트 루프 밖에서(C-3).
        await asyncio.to_thread(
            send_ops_alert, "개인정보 삭제 요구 접수",
            f"user_id={uid} reason={reason[:200]}",
            severity="warning", dedup_key=f"erase:{uid}")
    except Exception as e:  # noqa: BLE001 — 알림 실패가 접수를 막으면 안 됨
        _log.warning("삭제요구 알림 실패: %s", e)

    _log.info("erasure_request 접수: user=%s", uid)
    return JSONResponse({"ok": True, "status": "accepted",
                         "note": "지체 없이 처리되며, 완료 시 이메일로 통지됩니다."})


@router.post("/me/withdraw")
async def withdraw_account(request: Request, authorization: Optional[str] = Header(None)):
    """회원탈퇴(자발적) — **소프트삭제**. deleted_at 마킹 후 즉시 접근 차단.

    개인정보 완전 파기(법 제36조)와는 별개: 데이터·대화는 보존 정책에 따라
    유지되고(부정사용 조사·법정 보존·복구 대비), 계정 접근만 막힌다. 완전
    파기를 원하면 `POST /me/erase`(별도 절차). 관리자 복구 가능
    (`POST /admin/users/{id}/restore`).
    """
    _check_auth(authorization)
    uid = _uid(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    reason = str(body.get("reason") or "")

    get_users_repo().soft_delete(uid)
    get_events_repo().emit(Event(
        id="", ts="", event_type=WITHDRAW_EVENT, user_id=uid,
        payload_json=json.dumps({"reason": reason[:500]}, ensure_ascii=False),
    ))
    _log.info("account_withdraw(soft): user=%s", uid)
    return JSONResponse({"ok": True, "status": "withdrawn",
                         "note": "탈퇴 처리됐습니다. 로그아웃됩니다."})


@router.get("/me/prefs")
def get_my_prefs(request: Request):
    """내 설정 조회 — 이메일 수신 설정(보고서 완료 · 서비스 안내)."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    from src.persistence import get_users_repo
    u = get_users_repo().get(str(user_id))
    return {"report_email_opt_in": bool(getattr(u, "report_email_opt_in", True)) if u else True,
            # 서비스 안내 메일 수신(2026-09-14 재도입) — 기능 추가·변경 고지 메일 거부 수단
            "notice_email_opt_in": bool(getattr(u, "notice_email_opt_in", True)) if u else True,
            # 업데이트 팝업 마지막 확인(2026-09-07) — 프런트는 localStorage 와 OR 로 판단
            "last_seen_announcement_id": getattr(u, "last_seen_announcement_id", None) if u else None}


@router.get("/me/profile")
def get_my_profile(request: Request):
    """내 프로필 조회 — 표시명·소속·직군 (온보딩 폼 초기값 + 미입력 판별용)."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    from src.persistence import get_users_repo
    u = get_users_repo().get(str(user_id))
    return {
        "display_name": getattr(u, "display_name", None) if u else None,
        "affiliation": getattr(u, "affiliation", None) if u else None,
        "job_role": getattr(u, "job_role", None) if u else None,
        # 온보딩 폼 노출 판별 — 소속이 비어 있으면 아직 미입력
        "completed": bool(u and getattr(u, "affiliation", None)),
    }


@router.put("/me/profile")
async def put_my_profile(request: Request):
    """내 프로필 저장 — body: {display_name?, affiliation?, job_role?} (문자열, 각 ≤80자).

    폼 단위 전체 저장(부분 PATCH 아님) — 빈 문자열은 NULL 로 정규화.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.json()

    def _norm(key: str):
        v = body.get(key)
        if v is None:
            return None
        if not isinstance(v, str):
            raise HTTPException(status_code=422, detail=f"{key} 는 문자열이어야 합니다")
        v = v.strip()
        if len(v) > 80:
            raise HTTPException(status_code=422, detail=f"{key} 는 80자 이내여야 합니다")
        return v or None

    fields = {k: _norm(k) for k in ("display_name", "affiliation", "job_role")}
    from src.persistence import get_users_repo
    get_users_repo().set_profile(str(user_id), **fields)
    return {"ok": True, **fields}


@router.patch("/me/prefs")
async def patch_my_prefs(request: Request):
    """내 설정 변경.

    body: { report_email_opt_in?: bool, notice_email_opt_in?: bool,
            last_seen_announcement_id?: str }
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.json()
    from src.persistence import get_users_repo
    out: dict = {"ok": True}
    v = body.get("report_email_opt_in")
    if "report_email_opt_in" in body:
        if not isinstance(v, bool):
            raise HTTPException(status_code=422, detail="report_email_opt_in(bool) 필요")
        get_users_repo().set_report_email_opt_in(str(user_id), v)
        out["report_email_opt_in"] = v
    if "notice_email_opt_in" in body:
        nv = body.get("notice_email_opt_in")
        if not isinstance(nv, bool):
            raise HTTPException(status_code=422, detail="notice_email_opt_in(bool) 필요")
        get_users_repo().set_notice_email_opt_in(str(user_id), nv)
        out["notice_email_opt_in"] = nv
    if "last_seen_announcement_id" in body:
        nid = body.get("last_seen_announcement_id")
        if nid is not None and (not isinstance(nid, str) or len(nid) > 64):
            raise HTTPException(status_code=422, detail="last_seen_announcement_id(str≤64) 필요")
        get_users_repo().set_last_seen_announcement(str(user_id), nid or None)
        out["last_seen_announcement_id"] = nid or None
    if len(out) == 1:
        raise HTTPException(status_code=422, detail="변경할 필드가 없습니다")
    return out
