"""Admin API — 사용자별 토큰 한도 통제, 사용량 조회."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from src.middleware import effective_limits, require_admin, usage_summary
from src.middleware.auth import ROOT_ADMIN_EMAILS
from src.middleware.quota import _system_daily_limit, _system_monthly_limit
from src.persistence import get_users_repo

_log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# 실사용 데이터 경계 (2026-08-03 베타 오픈)
# ---------------------------------------------------------------------------
# 이 시각 **이전**은 개발·e2e 테스트가 만든 데이터다. 섞어서 집계하면 "LLM 72회"
# 같은 숫자가 실제 이용자 지표처럼 보인다(초대 전날 72회는 전부 내부 테스트였다).
# 기본 조회는 실사용만 보고, `scope=all` 로 과거까지 볼 수 있게 한다.
# 경계 시각·계정 구분의 정본은 `src/account_class.py`(2026-09-21 이동).


# 내부 트래픽(스레드) 판정 — 정본은 `src/account_class.py`(2026-09-21 이동: 주간 집계
# 같은 서비스 코드가 라우트를 import 하지 않게). 기존 호출부·테스트 호환용 재노출.
from src.account_class import (  # noqa: E402,F401
    _INTERNAL_ID_PREFIXES,
    _INTERNAL_THREAD_PREFIXES,
    _INTERNAL_THREAD_PREFIXES_ALL,
    _REAL_THREAD_RE,
    _normalize_thread_id,
    is_internal_thread,
)

_re_irb = __import__("re").compile(r"IRB|DRB|심의|가명|연구계획")


def _launch_cutoff() -> str:
    """실사용 시작 시각(UTC ISO) — 정본은 `src/account_class.launch_cutoff`."""
    from src.account_class import launch_cutoff

    return launch_cutoff()


def _excluded_admin_user_ids(scope: str) -> frozenset:
    """scope=real 에서 뺄 **내부 계정**(운영진·테스트) id 집합.

    2026-08-05 도입 때는 관리자만 뺐다 — 오픈 전 가입 테스트 계정과 팀원 개인 계정이
    실사용 지표로 계속 샜다(2026-09-21 지적). 이제 `src/account_class.py` 가 관리자
    라벨 + 자동 규칙으로 판정하고, 이용 조회·통계·대화 목록·검수 큐가 같은 집합을 쓴다.
    scope="all" 은 탈출구(전부 포함).
    """
    if (scope or "real").lower() == "all":
        return frozenset()
    from src.account_class import internal_user_ids

    return internal_user_ids()


def _is_real_scope(scope: str) -> bool:
    return (scope or "real").lower() != "all"


def _drop_test_events(events: list, scope: str, excl: frozenset) -> list:
    """scope=real 이벤트 필터 — 관리자 + **익명(user_id 없음)** 제외 (2026-08-08).

    운영 /chat 은 JWT 필수라 실사용 이벤트엔 항상 user_id 가 있다. 익명 이벤트는
    벤치·스크립트가 run_chat_turn 을 직접 호출한 테스트 트래픽(예: 운영 컨테이너
    e2e `bench_…` 스레드) — 실사용 지표에서 뺀다. scope="all" 은 전부 포함.
    """
    if not _is_real_scope(scope):
        return events
    # 스레드 기준 내부 판정 합류(2026-08-28) — 대화 목록은 SQL 접두 필터가
    # 있는데 이벤트 목록은 사용자 규칙만 봐서, user_id 를 단 e2e 이벤트가
    # 이용 지표·질문 리스트로 샜다(e2e@internal 재발). 한 규칙으로 통일한다.
    return [ev for ev in events
            if ev.user_id and ev.user_id not in excl
            and not is_internal_thread(getattr(ev, "thread_id", None) or "",
                                       ev.user_id)]


def _scope_since(scope: str, since: str) -> str:
    """기간 계산으로 나온 `since` 에 실사용 경계를 얹는다.

    scope="real"(기본): 오픈 시각과 비교해 **늦은 쪽**을 쓴다 — days=30 을 줘도
    테스트 구간까지 거슬러 올라가지 않는다. scope="all": 그대로(과거 포함).
    """
    if (scope or "real").lower() == "all":
        return since
    cut = _launch_cutoff()
    return max(since, cut)


@router.get("/admin/me")
def admin_me(admin=Depends(require_admin)):
    """내 관리자 권한(2026-09-22) — 프런트가 탭·버튼을 권한별로 숨긴다.

    `catalog` 은 권한 정의(키·라벨·설명) — 사용자 관리의 체크박스가 같은 목록을 쓴다.
    화면 가드는 편의일 뿐, 실제 차단은 `require_admin` 이 라우트마다 한다.
    """
    from src import admin_perms as _perms

    return {"email": admin.email, "is_root": _perms.is_root(admin),
            "perms": _perms.effective(admin), "catalog": _perms.catalog()}


def _perm_fields(u) -> dict:
    """사용자 행에 붙는 관리자 권한 표시값."""
    from src import admin_perms as _perms

    root = _perms.is_root(u)
    return {
        "is_root_admin": root,
        # 실제 적용 권한(루트=전부, 관리자 아님=[]). 저장값 NULL(전 권한)과 구분하려면
        # admin_perms_all 을 본다.
        "admin_perms_list": _perms.effective(u),
        "admin_perms_all": root or (bool(getattr(u, "is_admin", False))
                                    and getattr(u, "admin_perms", None) is None),
    }


@router.get("/admin/data-scope")
def admin_data_scope(_admin=Depends(require_admin)):
    """실사용 경계 노출 — 프런트가 토글 라벨·안내에 쓴다."""
    return {"launch_at": _launch_cutoff(), "default_scope": "real"}


def _whitelist_classifier():
    """email → (allowed, source) 판정 함수를 **한 번만** 만들어 돌려준다.

    목록 렌더는 사용자 수만큼 호출되므로 env/DB 조회를 매 행마다 하면 안 된다.
    source: "admin"(운영자 항상 허용) | "env" | "db" | "domain:@x.com" | None.
    판정은 `src/whitelist.py` 가 정본 — 여기서 규칙을 다시 조립하면 조용히 어긋난다
    (2026-09-10 분리 전에는 실제로 같은 규칙이 세 벌이었다).
    """
    from src.whitelist import classifier

    return classifier()


_PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")


_OPS_MANUAL = Path(__file__).resolve().parents[2] / "docs" / "product" / "ops_feature_manual.md"


@router.get("/admin/ops-manual")
def admin_ops_manual(_admin=Depends(require_admin)):
    """운영진 기능 설명서(2026-09-23) — 원본 `docs/product/ops_feature_manual.md` 를 그대로 준다.

    관리자 화면 [운영 매뉴얼] 탭이 렌더한다. 원본이 하나라 문서를 고치면 배포와 함께
    화면도 바뀐다(따로 복사본을 두지 않는다). 이미지에 없으면 503 — Dockerfile COPY 확인.
    """
    try:
        text = _OPS_MANUAL.read_text(encoding="utf-8")
        updated = datetime.fromtimestamp(_OPS_MANUAL.stat().st_mtime, timezone.utc).isoformat()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="운영 매뉴얼 파일이 배포 이미지에 없습니다.")
    return {"markdown": text, "updated_at": updated}


@router.get("/admin/build")
def admin_build_info(_admin=Depends(require_admin)):
    """배포 식별(2026-09-15, "배포 시기 헷갈림") — 이미지 빌드 시각·커밋·프로세스 기동 시각.

    APP_GIT_SHA/APP_BUILD_TIME 은 Dockerfile ARG→ENV 로 박히고 deploy.yml 이 넘긴다.
    로컬 dev 나 옛 이미지는 unknown.
    """
    from src.prompts.supervisor import PROMPT_VERSION

    return {
        "git_sha": (os.getenv("APP_GIT_SHA") or "unknown"),
        "built_at": (os.getenv("APP_BUILD_TIME") or None),
        "started_at": _PROCESS_STARTED_AT,
        "prompt_version": PROMPT_VERSION,
    }


@router.get("/admin/users")
def admin_list_users(request: Request, _user=Depends(require_admin),
                     limit: int = 100, offset: int = 0, scope: str = "all",
                     q: str = ""):
    """admin 전용. 사용자 목록 + 누적 사용량(오늘/이달) + 베타 접근 상태.

    `q`: 이메일 부분일치 검색(DB 서버측) — 종전엔 프런트가 로드된 페이지에만
    필터를 걸어 51번째 이후 사용자는 검색해도 안 나왔다(2026-08-05).

    행마다 추가되는 필드:
      - `created_at`(가입일, 기존) · `deleted_at`(비활성 여부, 기존)
      - `whitelisted`: 화이트리스트로 명시 허용되는가
      - `whitelist_source`: admin|env|db|domain:@x.com|null (출처)
      - `can_access`: 지금 실제로 서비스를 쓸 수 있는가(게이트+탈퇴 반영)
    """
    users = get_users_repo().list_all(limit=limit, offset=offset,
                                      q=q.strip() or None)
    gate_active, classify = _whitelist_classifier()
    cut = _launch_cutoff()
    _emails = {e.strip().lower()
               for e in (os.getenv("ADMIN_EMAILS") or "").split(",") if e.strip()}
    from src.account_class import beta_listed_checker
    _listed = beta_listed_checker()
    # 마케팅 동의(2026-08-28) — 발송 대상 확인을 관리자 화면에서 바로.
    # 사용자별 최신 legal_consent 의 scopes 기준(notices.filter_… 와 동일 규칙).
    from src.notices import filter_marketing_consented
    _mk_emails = set(filter_marketing_consented(
        [u.email for u in users if u.email]))
    out = []
    for u in users:
        d, m = effective_limits(u)
        usage = usage_summary(u.id)
        allowed, source = classify(u.email)
        out.append({
            **u.as_dict(),
            "effective_daily_limit": d,
            "effective_monthly_limit": m,
            "usage": usage,
            "whitelisted": source is not None,
            "whitelist_source": source,
            "can_access": allowed and not u.deleted_at,
            # 계정 구분(2026-09-21) — 관리자 라벨 우선, 없으면 자동(관리자→운영진,
            # 오픈 전 가입→테스트). is_internal 이면 실사용 집계에서 빠진다.
            **_account_fields(u, cut, _emails, _listed),
            # 마케팅 메일 수신 동의(최신 동의 기록 기준) — 발송 전 확인용.
            "marketing_opt_in": bool(u.email and u.email in _mk_emails),
            # 보고서 완료 메일 수신(개인 설정)
            "report_email_opt_in": bool(getattr(u, "report_email_opt_in", True)),
            **_perm_fields(u),
        })
    if (scope or "real").lower() != "all":
        out = [u for u in out if not u["is_internal"]]
    return {"count": len(out), "users": out, "gate_active": gate_active,
            "scope": (scope or "real").lower(), "launch_at": cut}


def _account_fields(u, cut: str, emails: set, beta_listed=None) -> dict:
    from src import account_class as _ac

    cls, source = _ac.classify(u, cut=cut, admin_emails=emails, beta_listed=beta_listed)
    return {
        "account_class": cls,                    # 유효 구분(자동 포함)
        "account_class_label": _ac.LABELS[cls],
        "account_class_source": source,          # manual | auto:admin | auto:pre_launch | auto
        "account_class_manual": getattr(u, "account_class", None),
        "is_internal": cls != _ac.USER,
        # 하위호환 — 종전 필드. 이제 "내부 계정"과 같은 뜻.
        "is_test_account": cls != _ac.USER,
    }


@router.post("/admin/users/{user_id}/restore")
def admin_restore_user(user_id: str, _admin=Depends(require_admin)):
    """탈퇴(소프트삭제) 계정 복구 — deleted_at 해제. 다시 로그인 가능."""
    repo = get_users_repo()
    u = repo.get(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="user not found")
    repo.restore(user_id)
    return {"ok": True, "user_id": user_id, "restored": True}


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    request: Request,
    _admin=Depends(require_admin),
    daily_token_limit_override: Optional[int] = None,
    monthly_token_limit_override: Optional[int] = None,
    is_admin: Optional[bool] = None,
):
    """admin 전용. 사용자별 토큰 한도 / admin 권한 조정.

    JSON body **또는** query parameter 둘 다 수용 (프론트 admin 페이지는
    JSON body PATCH 를 보냄 — body 우선). 미지정 필드는 변경 안 함.
    한도 값 -1 = 시스템 기본값으로 리셋.

    주의: 영속층 update_quota 가 COALESCE 기반이라 override 를 NULL 로 되돌릴
    수 없다. 그래서 -1 은 "현재 시스템 기본값을 숫자로 박아 리셋"으로 처리한다
    (이후 env 기본값이 또 바뀌어도 추적 안 됨 — 진짜 NULL 리셋은 repo 확장 필요).
    """
    # JSON body 우선 (없거나 비-dict 면 무시 → 타입드 query param fallback).
    body: dict = {}
    try:
        raw = await request.body()
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                body = parsed
    except Exception:
        body = {}

    def _pick(key: str, fallback):
        return body[key] if key in body else fallback

    daily_in = _pick("daily_token_limit_override", daily_token_limit_override)
    monthly_in = _pick("monthly_token_limit_override", monthly_token_limit_override)
    admin_in = _pick("is_admin", is_admin)
    # 관리자·운영진 통합(2026-09-22) — 구분 '관리자'(staff) 선택 = 관리자 지정(권한 없음에서 시작).
    if str(body.get("account_class") or "").strip().lower() == "staff":
        body.pop("account_class")
        admin_in = True

    repo = get_users_repo()
    target = repo.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="user not found")

    # 관리자 지정·기능 권한은 루트 관리자만(2026-09-22) — '사용자 관리' 권한만 받은
    # 관리자가 스스로 권한을 넓히거나 다른 사람을 관리자로 만들지 못하게.
    from src import admin_perms as _perms
    perms_in_body = "admin_perms" in body
    if (admin_in is not None or perms_in_body) and not _perms.is_root(_admin):
        raise HTTPException(status_code=403,
                            detail="관리자 지정·권한 변경은 루트 관리자만 할 수 있습니다.")
    perms_value = None
    if perms_in_body:
        raw_perms = body.get("admin_perms")
        if raw_perms is not None and not isinstance(raw_perms, list):
            raise HTTPException(status_code=422,
                                detail="admin_perms 는 권한 키 배열 또는 null(전 권한)")
        try:
            perms_value = _perms.serialize(raw_perms)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    daily_override = None
    monthly_override = None
    if daily_in is not None:
        daily_override = (_system_daily_limit() if int(daily_in) == -1
                          else int(daily_in))
    if monthly_in is not None:
        monthly_override = (_system_monthly_limit() if int(monthly_in) == -1
                            else int(monthly_in))

    # update_quota 는 None 인자를 "변경 없음"(COALESCE)으로 취급 — 한쪽만
    # 넘겨도 다른 쪽은 보존되므로 단일 호출로 충분.
    if daily_override is not None or monthly_override is not None:
        repo.update_quota(
            user_id,
            daily_override=daily_override,
            monthly_override=monthly_override,
        )
    if admin_in is not None:
        was_admin = bool(target.is_admin)
        repo.set_admin(user_id, bool(admin_in))
        from src.account_class import invalidate as _inv_ac
        _inv_ac()  # 관리자 = 내부 계정 — 권한이 바뀌면 내부 계정 집합도 바뀐다
        if not perms_in_body and bool(admin_in) != was_admin:
            # 새로 지정 = 권한 없음에서 시작(루트가 체크박스로 켠다) · 해제 = 권한 비움.
            repo.set_admin_perms(user_id, "" if admin_in else None)
    if perms_in_body:
        repo.set_admin_perms(user_id, perms_value)

    # 관리자 식별 메모·프로필 기입(2026-09-15) — 프로필을 안 넣은 기존 가입자를
    # 관리자가 알아볼 수 있게. 프로필은 준 키만 바꾸고 나머지는 보존한다.
    # 계정 구분 라벨(2026-09-21) — "auto"/""/null = 자동 판정으로 되돌림.
    if "account_class" in body:
        from src import account_class as _ac
        _now_u = repo.get(user_id)  # 같은 요청의 관리자 지정·해제 반영 후 상태
        if _now_u.is_admin or _perms.is_root(_now_u):
            raise HTTPException(status_code=409, detail=(
                "관리자 계정은 구분을 바꿀 수 없습니다 — 관리자에서 해제하면 자동 판정으로 돌아갑니다."))
        try:
            repo.set_account_class(user_id, _ac.normalize(body.get("account_class")))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        _ac.invalidate()
    if "admin_memo" in body:
        memo = body.get("admin_memo")
        repo.set_admin_memo(user_id, str(memo)[:500] if memo is not None else None)
    if any(k in body for k in ("display_name", "affiliation", "job_role")):
        def _prof(k: str):
            if k in body:
                v = body.get(k)
                return (str(v).strip()[:120] or None) if v is not None else None
            return getattr(target, k, None)
        repo.set_profile(user_id, display_name=_prof("display_name"),
                         affiliation=_prof("affiliation"), job_role=_prof("job_role"))

    updated = repo.get(user_id)
    d, m = effective_limits(updated)
    return {
        **updated.as_dict(),
        **_account_fields(updated, _launch_cutoff(),
                          {e.strip().lower() for e in (os.getenv("ADMIN_EMAILS") or "").split(",")
                           if e.strip()}),
        "effective_daily_limit": d,
        "effective_monthly_limit": m,
        **_perm_fields(updated),
    }


@router.get("/admin/users/{user_id}/usage")
def admin_user_usage(user_id: str, _admin=Depends(require_admin)):
    """admin 전용. 사용자 누적 사용량 + 한도."""
    user = get_users_repo().get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    d, m = effective_limits(user)
    return {
        "user_id": user.id,
        "email": user.email,
        "effective_daily_limit": d,
        "effective_monthly_limit": m,
        "usage": usage_summary(user.id),
    }


# ---------------------------------------------------------------------------
# 클로즈 베타 화이트리스트 관리 (2026-07-14) — env 는 부트스트랩, DB 가 운영 관리.
# 게이트 규칙: env ∪ DB, ADMIN_EMAILS 항상 허용, 둘 다 비면 전면 허용.
# ---------------------------------------------------------------------------
_WL_ENTRY_RE = None  # lazy compile


def _valid_wl_entry(entry: str) -> bool:
    global _WL_ENTRY_RE
    if _WL_ENTRY_RE is None:
        import re
        # 이메일(간이) 또는 @도메인
        _WL_ENTRY_RE = re.compile(
            r"^(@[a-z0-9.-]+\.[a-z]{2,}|[^@\s]+@[a-z0-9.-]+\.[a-z]{2,})$"
        )
    return bool(_WL_ENTRY_RE.match(entry))


@router.get("/admin/stats/search-laws")
def admin_search_laws_stats(
    days: int = 30,
    limit: int = 30,
    scope: str = "real",
    _admin=Depends(require_admin),
):
    """이용자 검색에서 어떤 법령이 수집됐는지 집계 (events.rag_search).

    반환: 기간 내 검색 수·법령별 히트 랭킹(검색 등장 횟수 기준)·종별 분포·
    최다 검색 질의. 소스: 채팅 검색 + 보고서 수집(source=report).
    """
    import json as _json
    from collections import Counter
    from datetime import datetime, timedelta, timezone

    from src.persistence import get_events_repo

    since = _scope_since(scope, (datetime.now(timezone.utc)
                                 - timedelta(days=max(1, days))).isoformat())
    events = get_events_repo().list_by_type("rag_search", since=since, limit=20000)
    _excl = _excluded_admin_user_ids(scope)
    events = _drop_test_events(events, scope, _excl)

    total = len(events)
    law_hits: Counter = Counter()          # (law_id, law_title) → 히트 수
    law_searches: Counter = Counter()      # (law_id, law_title) → 등장 검색 수
    by_type: Counter = Counter()           # target_type → 히트 수
    queries: Counter = Counter()           # 정규화 질의 → 횟수
    users: set = set()
    for ev in events:
        try:
            d = _json.loads(ev.payload_json or "{}")
        except Exception:
            continue
        if ev.user_id:
            users.add(ev.user_id)
        q = (d.get("query") or "").strip()
        if q and q != "(pinned)":
            queries[q[:80]] += 1
        seen_laws = set()
        for h in d.get("hits") or []:
            key = (h.get("law_id") or "?", h.get("law_title") or "?")
            law_hits[key] += 1
            by_type[h.get("target_type") or "law"] += 1
            seen_laws.add(key)
        for key in seen_laws:
            law_searches[key] += 1

    top_laws = [
        {"law_id": k[0], "law_title": k[1],
         "hits": law_hits[k], "searches": law_searches[k]}
        for k, _ in law_searches.most_common(max(1, min(limit, 200)))
    ]
    return {
        "days": days,
        "total_searches": total,
        "unique_users": len(users),
        "top_laws": top_laws,
        "by_target_type": dict(by_type),
        "top_queries": [
            {"query": q, "count": c} for q, c in queries.most_common(20)
        ],
    }


@router.get("/admin/questions")
def admin_user_questions(
    days: int = 30,
    limit: int = 200,
    offset: int = 0,
    scope: str = "real",
    _admin=Depends(require_admin),
):
    """이용자 질문 리스트 — 질문 유형 분석·기능 개선용 (events.user_question).

    질문은 PII 마스킹본만 적재됨(chat_loop 턴 시작 시 emit). 최신순.

    페이지네이션(limit/offset + total/has_more, 2026-08-20): scope=real 필터
    (관리자·익명 제외)는 SQL 로 적용 — 종전 '조회 후 필터'는 관리자·스크립트
    이벤트가 창을 잡아먹어 오래된 실사용 질문이 목록에서 사라졌다.
    unique_users·top_questions 는 페이지가 아니라 기간 전체(최근 1000건 캡)
    기준 — 페이지를 넘겨도 랭킹이 흔들리지 않게.
    """
    import json as _json
    from collections import Counter
    from datetime import datetime, timedelta, timezone

    from src.persistence import get_events_repo

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    since = _scope_since(scope, since)
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    real = _is_real_scope(scope)
    _excl = tuple(_excluded_admin_user_ids(scope))
    repo = get_events_repo()
    total = repo.count_by_type(
        "user_question", since=since,
        exclude_user_ids=_excl, exclude_anonymous=real)
    events = repo.list_by_type(
        "user_question", since=since, limit=limit, offset=offset,
        exclude_user_ids=_excl, exclude_anonymous=real)
    if real:
        # 내부 스레드 이벤트 제거(2026-08-28) — SQL 은 사용자 규칙만 알아서
        # e2e 가 user_id 를 달면 통과한다. 페이지 안에서 걸러내고 total 을
        # 그만큼 줄인다(보고서 목록과 동일 패턴).
        kept = [ev for ev in events
                if not is_internal_thread(
                    getattr(ev, "thread_id", None) or "", ev.user_id)]
        total -= len(events) - len(kept)
        events = kept
    # 랭킹·유저 수 집계용 전체 창(캡 1000) — 첫 페이지가 전부면 재사용.
    if offset == 0 and len(events) >= total:
        stat_events = events
    else:
        stat_events = repo.list_by_type(
            "user_question", since=since, limit=1000,
            exclude_user_ids=_excl, exclude_anonymous=real)
        if real:
            stat_events = [ev for ev in stat_events
                           if not is_internal_thread(
                               getattr(ev, "thread_id", None) or "",
                               ev.user_id)]

    # 작성자 표시(운영자 요청 2026-08-10) — user_id → email·표시명·소속·직군 조인.
    # 고유 사용자만 1회 조회(요청당 수십 명 수준) + 실패는 미상으로(비차단).
    from src.persistence import get_users_repo
    _urepo = get_users_repo()
    _ucache: dict = {}

    def _user_info(uid):
        if not uid:
            return {}
        if uid not in _ucache:
            try:
                u = _urepo.get(str(uid))
            except Exception:
                u = None
            _ucache[uid] = {
                "email": getattr(u, "email", None),
                "display_name": getattr(u, "display_name", None),
                "affiliation": getattr(u, "affiliation", None),
                "job_role": getattr(u, "job_role", None),
                "admin_memo": getattr(u, "admin_memo", None),
            } if u else {}
        return _ucache[uid]

    items = []
    for ev in events:
        try:
            d = _json.loads(ev.payload_json or "{}")
        except Exception:
            continue
        items.append({
            "ts": ev.ts,
            "user_id": ev.user_id,
            "thread_id": ev.thread_id,
            "question": (d.get("question") or "").strip(),
            "forced_search": d.get("forced_search"),
            **_user_info(ev.user_id),
        })

    counter: Counter = Counter()
    users: set = set()
    for ev in stat_events:
        if ev.user_id:
            users.add(ev.user_id)
        try:
            q = (_json.loads(ev.payload_json or "{}").get("question") or "").strip()
        except Exception:
            continue
        if q:
            counter[q[:80]] += 1
    return {
        "days": days,
        "total": total,
        "count": len(items),
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "unique_users": len(users),
        "items": items,
        "top_questions": [
            {"question": q, "count": c} for q, c in counter.most_common(20)
        ],
    }


@router.get("/admin/stats/claim-audit")
def admin_claim_audit_stats(
    days: int = 30,
    sample_limit: int = 30,
    scope: str = "real",
    _admin=Depends(require_admin),
):
    """무인용 사실 audit 집계(events.claim_audit) — 환각률 관측.

    답변의 check-worthy 사실을 source 지지 여부로 판정한 결과(supported/contradicted/
    unverified)를 기간 합산. unsupported_rate=(contradicted+unverified)/total.
    samples = 최근 contradicted/unverified 사실(정성 점검용).
    """
    import json as _json
    from datetime import datetime, timedelta, timezone

    from src.persistence import get_events_repo

    since = _scope_since(scope, (datetime.now(timezone.utc)
                                 - timedelta(days=max(1, days))).isoformat())
    events = get_events_repo().list_by_type("claim_audit", since=since, limit=20000)
    _excl = _excluded_admin_user_ids(scope)
    events = _drop_test_events(events, scope, _excl)

    turns = total = supported = contradicted = unverified = 0
    users: set = set()
    cap = max(1, min(sample_limit, 200))
    samples: list = []
    for ev in events:
        try:
            d = _json.loads(ev.payload_json or "{}")
        except Exception:
            continue
        turns += 1
        if ev.user_id:
            users.add(ev.user_id)
        total += int(d.get("total") or 0)
        supported += int(d.get("supported") or 0)
        contradicted += int(d.get("contradicted") or 0)
        unverified += int(d.get("unverified") or 0)
        for s in d.get("samples") or []:
            if len(samples) < cap:
                samples.append({
                    "ts": ev.ts,
                    "thread_id": ev.thread_id,
                    "verdict": s.get("verdict"),
                    "claim": s.get("claim"),
                })
    denom = total or 1
    return {
        "days": days,
        "turns_audited": turns,
        "unique_users": len(users),
        "total_claims": total,
        "supported": supported,
        "contradicted": contradicted,
        "unverified": unverified,
        "supported_rate": round(supported / denom, 4) if total else None,
        "unsupported_rate": round((contradicted + unverified) / denom, 4) if total else None,
        "samples": samples,
    }


@router.get("/admin/reports")
def admin_list_reports(limit: int = 50, offset: int = 0,
                       scope: str = "real", tab: str = "deep",
                       _admin=Depends(require_admin)):
    """admin 전용. 보고서 요청(run) 목록 — 상태·실패 사유·이메일 발송 결과.

    배경(2026-08-21): 베타 보고서 3연속 실패(writer 400)를 사용자 신고로야
    알았고, 발송 여부는 컨테이너 로그로도 확인 불가였다. run(report_runs) 을
    reports(제목)·users(이메일)·events(report_email 발송 결과)와 조인해
    요청→생성→발송 전 구간을 한 화면에서 본다.
    """
    import json as _json

    from src.persistence import get_report_runs_repo

    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    rows, total = get_report_runs_repo().list_admin(limit=limit, offset=offset)
    items = []
    real = _is_real_scope(scope)
    # 계정 축(운영진·테스트) — 스레드 접두만 봐서 관리자·테스트 계정 보고서가 '실사용'에
    # 섞였다(2026-09-22 신고). 통계·대화 목록과 같은 집합. 표시용 플래그라 scope 무관하게 계산.
    from src.account_class import internal_user_ids
    _internal_uids = internal_user_ids()
    for r in rows:
        # 내부(e2e·벤치·야간회귀) 보고서는 기본 목록에서 제외 — 실사용 결과에
        # 섞여 보이던 것(2026-08-26). scope=all 이면 표시하되 플래그를 단다.
        internal = (is_internal_thread(r.get("thread_id"), r.get("user_id"))
                    or (r.get("user_id") in _internal_uids))
        if real and internal:
            total -= 1
            continue
        # 고아 run 숨김(2026-08-28) — 산출물(reports 행)이 삭제된 완료 run.
        # 사용자 삭제·중복 정리 후 "(제목 없음)·본문 없음" 행이 목록에 남아
        # "이런 건 지울 수 없냐"는 지적. run 이력은 보존하되(사용량 근거)
        # 기본 목록에서만 제외 — 내부 포함(scope=all) 체크 시엔 보인다.
        _orphan = (r.get("status") == "completed" and r.get("report_id")
                   and r.get("report_status") is None)
        if real and _orphan:
            total -= 1
            continue
        # 탭 분리(2026-08-27): 서류(kind=doc)는 심층 보고서가 아니다 — 한
        # 목록에 섞여 "전부 뒤죽박죽"이던 것. IRB·DRB 산출물은 제목·요청문
        # 키워드로 분류(전용 provenance 컬럼은 후속).
        _kind = str(r.get("report_kind") or "")
        _text = f"{r.get('report_title') or ''} {r.get('prompt') or ''}"
        _is_doc = _kind == "doc"
        _is_irb = _is_doc and bool(
            _re_irb.search(_text))
        _row_tab = "irb" if _is_irb else ("doc" if _is_doc else "deep")
        if tab in ("deep", "doc", "irb") and _row_tab != tab:
            total -= 1
            continue
        # 작성 모델·분량 — writer 교체가 잦아 품질 비교에 필수(2026-08-26).
        writer_model, report_chars, cites_used, total_s = None, None, None, None
        qraw = r.get("quality_event")
        if qraw:
            try:
                q = qraw if isinstance(qraw, dict) else _json.loads(qraw)
                writer_model = q.get("writer_model")
                report_chars = q.get("chars")
                cites_used = q.get("cites_used")
                total_s = q.get("total_s")
            except Exception:  # noqa: BLE001 — 표시만 생략
                pass
        email_status, email_error = None, None
        raw = r.get("email_event")
        if raw:
            try:
                p = raw if isinstance(raw, dict) else _json.loads(raw)
                email_status = "sent" if p.get("ok") else "failed"
                email_error = p.get("error")
            except Exception:  # noqa: BLE001 — 이벤트 파싱 실패는 표시만 생략
                email_status = None
        items.append({
            "idempotency_key": r["idempotency_key"],
            "thread_id": r["thread_id"],
            "user_id": r.get("user_id"),
            "user_email": r.get("user_email"),
            "user_display_name": r.get("user_display_name"),
            "user_admin_memo": r.get("user_admin_memo"),
            "status": r["status"],
            "error": r.get("error"),
            "prompt": (r.get("prompt") or "")[:120],
            "purpose": r.get("purpose"),
            "report_id": r.get("report_id"),
            "report_title": r.get("report_title"),
            "report_status": r.get("report_status"),
            "email_status": email_status,      # sent | failed | None(기록 없음)
            "email_error": email_error,
            "writer_model": writer_model,      # 어떤 모델이 썼나
            "report_chars": report_chars,      # 분량(자)
            "cites_used": cites_used,          # 본문 인용 수
            "elapsed_s": total_s,              # 생성 소요(초)
            "internal": internal,              # 내부 트래픽(e2e·벤치)
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
        })
    return {
        "count": len(items),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "runs": items,
    }


@router.get("/admin/reports/{report_id}/content")
def admin_report_content(report_id: str, _admin=Depends(require_admin)):
    """admin 전용. 보고서 **본문**(마크다운) 조회 — 화면에서 바로 읽기.

    배경(2026-08-26): 관리자 화면에 요청·상태·발송만 있어 "무엇이 쓰였는지"를
    보려면 사용자 계정으로 들어가거나 DB 를 뒤져야 했다. 품질 점검(모델 교체
    전후 비교·인용 적정성)이 화면에서 끝나야 한다.

    소유권 검사 없음 — require_admin 이 이미 관리자만 통과시킨다.
    본문 조회이므로 **개인정보가 실릴 수 있는 대화 원문과 달리** 보고서
    산출물만 반환한다(blob 만료 시 409).
    """
    import json as _json

    from src.persistence import get_blob_store, get_reports_repo

    meta = get_reports_repo().get(report_id)
    if not meta:
        raise HTTPException(status_code=404, detail="report not found")
    if not meta.blob_uri:
        raise HTTPException(
            status_code=409,
            detail="본문 보관기간(30일)이 지났거나 아직 생성 전입니다")
    try:
        body = get_blob_store().get(meta.blob_uri)
    except Exception as e:  # noqa: BLE001 — 상세는 서버 로그로(내부정보 차단)
        logging.getLogger(__name__).exception(
            "admin report content 실패 id=%s: %s", report_id, e)
        raise HTTPException(status_code=500, detail="report body unavailable")
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    try:
        cites = _json.loads(meta.citations_json or "[]")
    except ValueError:
        cites = []
    return {
        "report_id": report_id,
        "thread_id": meta.thread_id,
        "title": meta.title,
        "status": meta.status,
        "kind": meta.kind,
        "created_at": meta.created_at,
        "chars": len(body),
        "citation_count": len(cites),
        "citations": [
            {"number": c.get("number"), "title": c.get("title"),
             "publisher": c.get("publisher"), "url": c.get("url"),
             "verified": c.get("verified")}
            for c in cites if isinstance(c, dict)
        ],
        "markdown": body,
    }


@router.get("/admin/threads")
def admin_list_threads(limit: int = 100, offset: int = 0, scope: str = "real",
                       _admin=Depends(require_admin)):
    """admin 전용. 전체 사용자 대화 thread 목록(최근 갱신순) — 원문 뷰어 진입.

    소유자 검사 없이 전 사용자 대화를 대상으로 함(운영 모니터링용). 목록만 —
    본문은 GET /admin/threads/{id} 에서.

    페이지네이션(limit/offset + total/has_more, 2026-08-20): 실사용 필터
    (오픈 경계·내부 접두·익명)는 repo `list_admin` 이 SQL 로 적용한다 —
    종전 '최근 N개 조회 후 필터'는 내부 트래픽이 상한을 잡아먹어 그보다
    오래된 실사용 대화가 목록에서 통째로 사라졌다.
    """
    from src.persistence.threads_repo import get_threads_repo

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    real = _is_real_scope(scope)
    rows, total = get_threads_repo().list_admin(
        limit=limit, offset=offset,
        since=_launch_cutoff() if real else None,
        exclude_prefixes=_INTERNAL_THREAD_PREFIXES_ALL if real else (),
        # /chat 은 JWT 필수 — 익명 thread 는 전부 스크립트 산물(is_internal_thread).
        require_user=real,
        # 내부 계정(운영진·테스트) — 통계·이용 조회와 같은 집합(2026-09-22 누락 수정).
        exclude_user_ids=tuple(_excluded_admin_user_ids(scope)),
    )
    if real:
        # SQL 접두 필터가 못 거르는 잔여(비-hex `t_` 이름·@internal 계정)를
        # 파이썬 규칙으로 마저 거른다(2026-08-28) — 규칙의 정본은
        # is_internal_thread 하나다.
        kept = [r for r in rows
                if not is_internal_thread(r.get("id") or "", r.get("user_id"))]
        total -= len(rows) - len(kept)
        rows = kept
    users = AdminUserLookup()
    return {
        "count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(rows) < total,
        "scope": "real" if real else "all",
        "launch_at": _launch_cutoff(),
        "threads": [
            {
                "thread_id": r["id"],
                "user_id": r.get("user_id"),
                **users.prefixed(r.get("user_id")),
                "title": r.get("title"),
                "created_at": r.get("created_at"),
                "updated_at": r.get("updated_at"),
            }
            for r in rows
        ],
    }


@router.get("/admin/threads/{thread_id}")
def admin_get_thread(thread_id: str, _admin=Depends(require_admin)):
    """admin 전용. 특정 thread 전체 대화 원문(질문+AI답변+tool 호출).

    본문은 PII 마스킹본만 적재됨(at-rest 정책 — chat_loop 저장 전 스크럽).
    /chat/{id}/state 와 동일한 _message_view 직렬화 재사용.
    """
    from src.persistence.threads_repo import get_threads_repo
    from src.routes.chat import _message_view

    repo = get_threads_repo()
    meta = repo.get_meta(thread_id)
    if not meta:
        raise HTTPException(status_code=404, detail="thread not found")
    state = repo.get_state(thread_id)
    views = [_message_view(m) for m in state.messages]
    try:
        stamps = repo.message_created_at(thread_id)
    except Exception:  # noqa: BLE001 — 시각이 없어도 원문 뷰어는 떠야 한다
        _log.exception("message_created_at 실패 — 소요시간 없이 표시")
        stamps = {}
    turns = annotate_turn_elapsed(views, stamps)
    return {
        "thread_id": thread_id,
        "user_id": meta.get("user_id"),
        **AdminUserLookup().prefixed(meta.get("user_id")),
        "title": meta.get("title"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "messages": views,
        "turns": turns,
        "steps": state.steps,
        "selected_law_keys": state.selected_law_keys,
    }


class AdminUserLookup:
    """관리자 화면용 사용자 표기 — 이메일·프로필·**관리자 식별 메모**를 한 모양으로(2026-09-18).

    프로필을 입력하지 않은 가입자는 이메일(또는 id 조각)만 보여 누구인지 알 수 없었다. 관리자가
    사용자 관리에서 붙인 `admin_memo` 를 이용 조회·대화 원문·보고서·검수 큐에도 같이 싣는다.
    요청 1건 안에서 같은 사용자를 반복 조회하지 않게 캐시한다. 관리자 응답 전용 — 사용자
    응답(`/me/*`)에는 메모를 싣지 않는다.
    """

    FIELDS = ("email", "display_name", "affiliation", "job_role", "admin_memo")

    def __init__(self):
        from src.persistence import get_users_repo
        self._repo = get_users_repo()
        self._cache: dict = {}

    def get(self, uid) -> dict:
        if not uid:
            return {}
        key = str(uid)
        if key not in self._cache:
            try:
                u = self._repo.get(key)
            except Exception:  # noqa: BLE001 — 표기 실패가 목록을 막으면 안 된다
                u = None
            self._cache[key] = ({f: getattr(u, f, None) for f in self.FIELDS} if u else {})
        return self._cache[key]

    def prefixed(self, uid, prefix: str = "user_") -> dict:
        """`user_email`·`user_display_name`·`user_admin_memo` … 형태(행에 평평하게 붙일 때)."""
        return {f"{prefix}{k}": v for k, v in self.get(uid).items()}


def _parse_iso(ts) -> Optional[datetime]:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def annotate_turn_elapsed(views: list[dict], stamps: dict[str, str]) -> list[dict]:
    """메시지 뷰에 created_at 과 턴 소요시간을 붙인다(2026-09-15, 관리자 요청).

    턴 = human 메시지부터 그 뒤 첫 **최종 AI 답변**(tool_calls 없는 ai)까지.
    AI 메시지는 스트림이 끝난 직후 저장되므로 그 created_at 이 '답변 완성 시각'
    이다(grounding·claim audit 은 그 뒤 비차단). 사용자가 체감한 대기시간과
    수 초 이내로 같다. 최종 답변 뷰에 `elapsed_s`, 반환값은 턴 요약 목록.
    """
    turns: list[dict] = []
    cur_human: Optional[dict] = None
    cur_start: Optional[datetime] = None
    for v in views:
        ts = stamps.get(v.get("id") or "")
        if ts:
            v["created_at"] = ts
        if v.get("type") == "human":
            cur_human, cur_start = v, _parse_iso(ts)
            continue
        if v.get("type") == "ai" and not v.get("tool_calls") and cur_human is not None:
            end = _parse_iso(ts)
            if cur_start and end:
                elapsed = round(max(0.0, (end - cur_start).total_seconds()), 1)
                v["elapsed_s"] = elapsed
                turns.append({
                    "human_id": cur_human.get("id"), "ai_id": v.get("id"),
                    "started_at": cur_human.get("created_at"), "ended_at": ts,
                    "elapsed_s": elapsed,
                })
            cur_human, cur_start = None, None
    return turns


@router.get("/admin/whitelist")
def admin_list_whitelist(_admin=Depends(require_admin)):
    """화이트리스트 전체 — env(읽기전용) + DB(편집 가능) 출처 구분."""
    import os

    from src.persistence.whitelist_repo import get_whitelist_repo

    raw = (os.getenv("BETA_WHITELIST_EMAILS") or "").strip()
    env_entries = sorted(
        {e.strip().lower() for e in raw.split(",") if e.strip()}
    ) if raw else []
    db_rows = get_whitelist_repo().list()

    # 가입 여부를 함께 싣는다(2026-08-05). `invited_at` 은 **이 기능이 생긴 뒤**의
    # 발송만 안다 — 그 전에 베타 공지를 받고 이미 쓰고 있는 사람도 전부 '미발송'
    # 으로 보인다. 그 상태로 [초대 발송]을 누르면 며칠째 쓰던 사용자에게
    # "베타 서비스를 시작합니다"가 날아간다. 가입 시각이 그 오발송을 막는 신호다.
    joined = _joined_at_by_email()
    for r in db_rows:
        r["joined_at"] = joined.get((r.get("entry") or "").lower())

    from src.middleware.auth import _beta_whitelist
    return {
        # BETA_GATE=1 이면 목록이 비어도 게이트 활성 — 판정 함수가 진실원.
        "gate_active": _beta_whitelist() is not None,
        "env_entries": env_entries,   # .env 수정으로만 변경 가능 — UI 는 읽기전용 표시
        "db_entries": db_rows,        # [{entry, added_by, created_at, invited_at, joined_at}]
    }


def _joined_at_by_email() -> dict[str, str]:
    """이메일(소문자) → 가입 시각. 목록 렌더용이라 **한 번에** 읽는다.

    행마다 get_by_email 을 부르면 PG 왕복이 항목 수만큼 늘어난다
    (`_whitelist_classifier` 와 같은 이유).
    """
    try:
        users = get_users_repo().list_all(limit=10000)
    except Exception:  # noqa: BLE001 — 목록 조회 실패가 화이트리스트 화면을 막지 않게
        _log.exception("가입자 조회 실패 — 가입 배지 없이 표시된다")
        return {}
    return {
        (u.email or "").strip().lower(): u.created_at
        for u in users if u.email and getattr(u, "deleted_at", None) is None
    }


@router.post("/admin/whitelist", status_code=201)
def admin_add_whitelist(request: Request, body: dict,
                        admin=Depends(require_admin)):
    """항목 추가 — 단건(`entry`) 또는 벌크(`entries`: CSV/줄바꿈 문자열 or 배열).

    이메일(a@b.com) 또는 @도메인. 즉시 반영(게이트 캐시 무효화).
    벌크는 유효 항목만 추가하고 무효 항목은 `invalid` 로 돌려줌(부분 성공).
    """
    from src.middleware.auth import invalidate_whitelist_cache
    from src.persistence.whitelist_repo import get_whitelist_repo

    raw = body.get("entries")
    if raw is not None:
        if isinstance(raw, str):
            import re as _re
            items = [e for e in _re.split("[,;" + chr(10) + chr(13) + "]+", raw) if e.strip()]
        elif isinstance(raw, list):
            items = [str(e) for e in raw]
        else:
            raise HTTPException(status_code=422, detail="entries 는 CSV 문자열 또는 배열")
    else:
        items = [str(body.get("entry") or "")]

    import os as _os

    added_by = getattr(request.state, "user_email", None)
    repo = get_whitelist_repo()

    # 중복 판정 기준 3종(2026-08-01) — 종전엔 전부 '추가됨'으로 뭉뚱그려
    # 벌크 100건에 "100건 추가"라고 답했다(실제 신규는 몇 건뿐일 수 있음).
    _raw_env = (_os.getenv("BETA_WHITELIST_EMAILS") or "").strip()
    env_set = {e.strip().lower() for e in _raw_env.split(",") if e.strip()}
    existing = repo.entries()
    # 이미 등록된 @도메인 — 그 도메인 이메일은 개별 추가해도 이미 통과한다
    # (auth._beta_allowed 가 도메인 매칭). 중복이므로 알려준다.
    covered_domains = {d for d in (existing | env_set) if d.startswith("@")}

    added: list[str] = []          # 실제로 새로 들어간 것
    duplicate: list[str] = []      # DB 에 이미 있던 것
    already_in_env: list[str] = []  # .env 로 이미 허용 중(DB 추가는 무의미)
    covered_by_domain: list[str] = []  # 등록된 @도메인이 이미 커버
    invalid: list[str] = []
    for it in items:
        e = it.strip().lower()
        if not _valid_wl_entry(e):
            invalid.append(it.strip())
            continue
        if e in env_set:
            already_in_env.append(e)
            continue
        dom = f"@{e.rsplit('@', 1)[-1]}" if "@" in e and not e.startswith("@") else None
        if dom and dom in covered_domains:
            covered_by_domain.append(e)
            continue
        (added if repo.add(e, added_by=added_by) else duplicate).append(e)

    if not (added or duplicate or already_in_env or covered_by_domain) and invalid:
        raise HTTPException(
            status_code=422,
            detail=f"유효한 항목 없음 — 이메일(a@b.com)/@도메인 형식: {invalid[:5]}",
        )
    if added:
        invalidate_whitelist_cache()   # 실제 변경이 있을 때만

    # 등록은 발송하지 않는다(2026-08-05). 초대는 관리자가 화면에서 **한 건씩**
    # 버튼으로 보낸다 — POST /admin/whitelist/{entry}/invite. 자동 발송은 벌크
    # 붙여넣기 한 번에 되돌릴 수 없는 메일이 무더기로 나가는 구조라 걷어냈다.
    return {
        "ok": True,
        "added": added,
        "duplicate": duplicate,
        "already_in_env": already_in_env,
        "covered_by_domain": covered_by_domain,
        "invalid": invalid,
        **({"entry": added[0]} if len(added) == 1 and raw is None else {}),
    }


@router.get("/admin/invite-template")
def admin_get_invite_template(_admin=Depends(require_admin)):
    """지금 발송하면 나갈 초대 메일 내용(수정본 있으면 수정본)."""
    from src import notices

    return notices.get_invite_template()


@router.put("/admin/invite-template")
async def admin_put_invite_template(request: Request,
                                    _admin=Depends(require_admin)):
    """초대 메일 제목·본문 수정(2026-08-28) — 다음 발송부터 즉시 적용.

    body: {"subject", "body"} — 둘 다 필수. 가입 URL 은 CTA 버튼이 항상
    붙으므로 본문에서 빠져도 가입 경로는 유지된다.
    """
    from src import notices

    data = await request.json()
    subject = str(data.get("subject") or "").strip()
    body = str(data.get("body") or "").strip()
    if not subject or not body:
        raise HTTPException(status_code=422, detail="subject·body 둘 다 필요합니다.")
    if len(subject) > 200 or len(body) > 8000:
        raise HTTPException(status_code=422, detail="제목 200자·본문 8000자 이내로 입력하세요.")
    notices.set_invite_template(subject, body,
                                updated_by=getattr(request.state, "user_email", None))
    return notices.get_invite_template()


@router.post("/admin/invite-template/preview")
async def admin_preview_invite_template(request: Request,
                                        _admin=Depends(require_admin)):
    """편집 중 내용의 실제 메일 HTML(2026-08-28) — 저장 없이 확인.

    body: {"subject"?, "body"?} — 생략하면 현재 저장본(없으면 기본 문구).
    """
    from src import notices

    data = await request.json()
    tpl = notices.get_invite_template()
    subject = str(data.get("subject") or tpl["subject"]).strip()[:200]
    body = str(data.get("body") or tpl["body"]).strip()[:8000]
    html = notices.render_notice_html(
        subject=subject, body_text=body,
        cta_url=notices.SIGNUP_URL, cta_label="계정 만들기")
    return {"html": html, "subject": subject}


@router.post("/admin/invite-template/test")
async def admin_test_invite_template(request: Request,
                                     _admin=Depends(require_admin)):
    """관리자 본인 주소로 1통 테스트 발송 — invited_at 미기록(집계 무영향).

    body: {"subject"?, "body"?} — 생략하면 현재 저장본.
    """
    from src import notices

    me = getattr(request.state, "user_email", None)
    if not me:
        raise HTTPException(status_code=422, detail="관리자 이메일을 확인할 수 없습니다.")
    data = await request.json()
    tpl = notices.get_invite_template()
    subject = str(data.get("subject") or tpl["subject"]).strip()[:200]
    body = str(data.get("body") or tpl["body"]).strip()[:8000]
    import asyncio

    # SMTP 는 동기 — 루프에서 직접 부르면 SSE 가 함께 멈춘다(규약 §7).
    res = await asyncio.to_thread(
        notices.send_notice,
        subject=f"[테스트] {subject}", body_text=body, emails=[me],
        cta_url=notices.SIGNUP_URL, cta_label="계정 만들기")
    if not res.get("sent"):
        raise HTTPException(
            status_code=502,
            detail="발송 실패 — SMTP 설정을 확인하세요." if res.get("smtp_configured")
            else "SMTP 미설정 환경입니다(발송 stub).")
    return {"ok": True, "to": me}


@router.delete("/admin/invite-template")
def admin_reset_invite_template(request: Request, _admin=Depends(require_admin)):
    """수정본 폐기 — 기본 문구(2026-08-03 실발송본 계승)로 복원."""
    from src import notices

    notices.reset_invite_template(updated_by=getattr(request.state, "user_email", None))
    return notices.get_invite_template()


@router.post("/admin/whitelist/{entry}/invite")
def admin_send_whitelist_invite(entry: str, request: Request,
                                body: Optional[dict] = None,
                                _admin=Depends(require_admin)):
    """이 항목 **한 건**에 베타 초대 메일 발송 + 발송 시각 기록.

    수동 1건 발송인 이유: 메일은 되돌릴 수 없다. 등록에 딸려 자동으로 나가면
    벌크 붙여넣기 한 번이 곧 무더기 발송이 된다. 누구에게 보냈는지는
    `invited_at` 이 들고 있고, 화면의 미발송/발송완료 구분이 그 위에 얹힌다.

    **기존 가입자 보호**: 이미 계정이 있는 주소로는 기본적으로 나가지 않는다
    (409). `invited_at` 은 이 기능이 생긴 뒤의 발송만 알기 때문에, 그 전에
    베타 공지를 받고 며칠째 쓰고 있는 사람도 '미발송'으로 보인다 — 그대로
    누르면 사용 중인 사용자에게 "베타 서비스를 시작합니다"가 날아간다.
    정말 보내려면 `{"force": true}`.

    이미 보낸 항목도 다시 보낼 수 있다(재발송은 관리자의 명시적 선택) —
    응답의 `resent` 로 어느 쪽이었는지 알려준다.
    """
    from src.persistence.whitelist_repo import get_whitelist_repo

    e = (entry or "").strip().lower()
    repo = get_whitelist_repo()
    row = repo.get(e)
    if not row:
        raise HTTPException(status_code=404, detail="화이트리스트에 없는 항목입니다.")
    if not ("@" in e and not e.startswith("@")):
        # `@도메인` 은 수신자가 없다 — 그 도메인 사용자는 로그인 시점에 통과한다.
        raise HTTPException(
            status_code=422,
            detail="도메인 항목(@example.com)에는 보낼 주소가 없습니다. "
                   "개별 이메일을 등록해 초대해 주세요.")

    force = bool((body or {}).get("force"))
    member = get_users_repo().get_by_email(e)
    if member and getattr(member, "deleted_at", None) is None and not force:
        raise HTTPException(
            status_code=409,
            detail=f"이미 가입한 사용자입니다(가입 {(member.created_at or '')[:10]}). "
                   f"초대 메일은 서비스 시작 안내라 사용 중인 분께는 어색합니다. "
                   f"그래도 보내려면 force 로 다시 요청하세요.")

    from src import notices

    sent_by = getattr(request.state, "user_email", None)
    try:
        res = notices.send_beta_invite([e], invited_by=sent_by)
    except Exception as ex:  # noqa: BLE001 — 조용한 실패 금지(CLAUDE.md §6)
        _log.exception("베타 초대 발송 실패: %s", e)
        raise HTTPException(status_code=502,
                            detail=f"발송 실패: {str(ex)[:150]}") from ex

    if not res.get("sent"):
        # 발송 실패면 invited_at 을 찍지 않는다 — 안 간 메일을 '보냄'으로
        # 기록하면 화면이 거짓을 말하고, 그 사람은 영영 초대받지 못한다.
        raise HTTPException(
            status_code=502,
            detail="발송 실패 — SMTP 설정과 발신 주소(SMTP_FROM/EMAIL_FROM)를 확인하세요.")

    repo.mark_invited(e, invited_by=sent_by)
    after = repo.get(e) or {}
    return {
        "ok": True,
        "entry": e,
        "resent": bool(row.get("invited_at")),
        "forced_member": bool(member),   # 가입자에게 강제 발송했음을 응답에 남긴다
        "invited_at": after.get("invited_at"),
        "invited_by": after.get("invited_by"),
        "smtp_configured": res.get("smtp_configured", False),
    }


@router.delete("/admin/whitelist/{entry}")
def admin_remove_whitelist(entry: str, _admin=Depends(require_admin)):
    """항목 삭제(DB 만 — env 항목은 .env 에서). 즉시 반영, 기발급 JWT 도 차단."""
    from src.middleware.auth import invalidate_whitelist_cache
    from src.persistence.whitelist_repo import get_whitelist_repo

    removed = get_whitelist_repo().remove(entry)
    if not removed:
        raise HTTPException(status_code=404, detail="entry not found (env 항목은 .env 에서 제거)")
    invalidate_whitelist_cache()
    return {"ok": True, "entry": entry.strip().lower()}


# ---------------------------------------------------------------------------
# 시스템 설정 조회 (읽기전용) — ENV_REGISTRY 단일 진실원의 admin 뷰.
# secret 은 값 미노출(set/unset 만). 변경은 .env(.docker) + 재기동 — 화면은 가시화만.
# ---------------------------------------------------------------------------
@router.get("/admin/config")
def admin_config(_admin=Depends(require_admin)):
    import os

    from src.config import ENV_REGISTRY

    groups: dict[str, list[dict]] = {}
    for s in ENV_REGISTRY:
        raw = os.getenv(s.key)
        item = {
            "key": s.key,
            "doc": s.doc,
            "default": s.default,
            "secret": s.secret,
            "prod_required": s.prod_required,
            "is_set": raw is not None and raw.strip() != "",
            # secret 은 값 자체를 절대 반환하지 않음
            "value": None if s.secret else (raw if raw is not None else None),
        }
        groups.setdefault(s.group, []).append(item)
    return {"groups": groups}


# ---------------------------------------------------------------------------
# 점검(유지보수) 모드 — 매일 4시 데이터 갱신 등 정비 중 일반 사용자 차단.
# 켜지면 AuthMiddleware 가 비관리자 API 요청을 503. 관리자는 통과(해제·확인).
# 상태는 app_settings DB('maintenance', JSON) — 재기동 생존. 4시 크론은
# scripts/maintenance.py 로 자동 on/off 가능(DB 직접 → 서버 TTL≤5s 반영).
# ---------------------------------------------------------------------------
@router.get("/admin/maintenance")
def admin_get_maintenance(_admin=Depends(require_admin)):
    """현재 점검 상태 — 수동 플래그 + 예약(매일 반복 시간대) + effective active."""
    from src.maintenance import default_message, default_tz, get_state

    from src.maintenance import FEATURES, _FEATURE_DEFAULT_MESSAGE
    from src.writer_status import writer_reachable

    st = dict(get_state())
    st["default_message"] = default_message()
    st["default_tz"] = default_tz()
    st["feature_names"] = list(FEATURES)
    st["feature_default_messages"] = dict(_FEATURE_DEFAULT_MESSAGE)
    st["writer_up"] = writer_reachable()
    return st


@router.post("/admin/maintenance")
def admin_set_maintenance(body: dict, request: Request,
                          _admin=Depends(require_admin)):
    """점검 모드 설정. 두 트리거(효과=둘 중 하나라도 참):

    - 수동: body `{active: bool, message?: str}` — active=True 면 즉시 503.
    - 예약: body `{schedule: {enabled, start:"HH:MM", end:"HH:MM", tz?}, message?}`
      — 매일 반복 시간대. 서버가 그 시간에 자동 on/off(크론 불필요).

    - 기능 단위(2026-09-07): body `{features: {reports: {paused: bool, message?: str}}}`
      — 그 기능만 중단(보고서 POST 503 + 프런트 배너), 채팅은 정상.

    둘 다 body 에 있으면 둘 다 반영. 즉시 캐시 무효화.
    """
    from src.maintenance import set_feature_pause, set_schedule, set_state

    by = getattr(request.state, "user_email", None)
    message = body.get("message")
    message = message if isinstance(message, str) else None
    touched = False

    if "schedule" in body:
        sch = body.get("schedule") or {}
        if not isinstance(sch, dict):
            raise HTTPException(status_code=422, detail="schedule 은 객체여야 합니다.")
        try:
            set_schedule(
                enabled=bool(sch.get("enabled")),
                start=sch.get("start"),
                end=sch.get("end"),
                tz=sch.get("tz"),
                message=message,
                updated_by=by,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        touched = True

    if "active" in body:
        set_state(bool(body.get("active")), message=message, updated_by=by)
        touched = True

    if "features" in body:
        feats = body.get("features") or {}
        if not isinstance(feats, dict):
            raise HTTPException(status_code=422, detail="features 는 객체여야 합니다.")
        for name, cfg in feats.items():
            cfg = cfg if isinstance(cfg, dict) else {"paused": bool(cfg)}
            fmsg = cfg.get("message")
            try:
                set_feature_pause(str(name), bool(cfg.get("paused")),
                                  message=fmsg if isinstance(fmsg, str) else None,
                                  updated_by=by)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
        touched = True

    if not touched:
        raise HTTPException(
            status_code=422,
            detail="active(수동)·schedule(예약)·features(기능 단위) 중 하나는 필요합니다.",
        )

    from src.maintenance import get_state
    return {"ok": True, **get_state()}


@router.get("/admin/stats")
def admin_stats(days: int = 30, scope: str = "real", _admin=Depends(require_admin)):
    """일별 사용 통계 (2026-07-15) — events 테이블 집계.

    반환: {"days": N, "daily": [{day, llm_calls, active_users, input_tokens,
    output_tokens, cost_usd, quota_blocked, citation_reports}], "totals": {...}}
    """
    from datetime import datetime, timedelta, timezone

    from src.persistence import get_events_repo

    days = min(max(1, days), 180)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT00:00:00.000000Z"
    )
    since = _scope_since(scope, since)
    daily = get_events_repo().daily_stats(
        since=since, exclude_user_ids=tuple(_excluded_admin_user_ids(scope)),
        exclude_anonymous=_is_real_scope(scope))
    totals = {
        "llm_calls": sum(d["llm_calls"] or 0 for d in daily),
        "input_tokens": sum(d["input_tokens"] or 0 for d in daily),
        "output_tokens": sum(d["output_tokens"] or 0 for d in daily),
        "cost_usd": round(sum(d["cost_usd"] or 0 for d in daily), 4),
        "quota_blocked": sum(d["quota_blocked"] or 0 for d in daily),
        "citation_reports": sum(d["citation_reports"] or 0 for d in daily),
    }
    # 계측 건전성(2026-08-05) — usage 를 못 뽑으면 llm_call 이 아예 안 박히고
    # 위 집계와 일일 쿼터가 **조용히** 과소계상된다. 숫자를 믿기 전에 볼 값.
    # miss_ratio 는 프로세스 기동 이후 누계(재시작 시 리셋).
    from src.observability.token_logger import usage_miss_stats

    # 같은 기간의 실사용·내부·전체 비교(2026-09-21 "전체와 실사용이 확실히 구분되게").
    # 표 아래 선택 scope 의 일별 행과 별개로, 세 범위를 한 규칙(usage_weekly.compute_range —
    # 주간 집계와 같은 함수)으로 나란히 준다. 기간은 요청 기간 그대로(오픈 경계로 자르지 않음).
    from src.usage_weekly import METRICS, compute_range

    breakdown = None
    try:
        raw_since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT00:00:00.000000Z")
        breakdown = compute_range(raw_since, datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"))
    except Exception:  # noqa: BLE001 — 비교표 실패가 일별 통계를 막지 않게(로그는 남김)
        _log.warning("admin_stats breakdown 실패", exc_info=True)

    return {"days": days, "daily": daily, "totals": totals,
            "breakdown": breakdown, "metrics": METRICS,
            "usage_capture": usage_miss_stats()}


@router.post("/admin/users/{user_id}/soft-delete")
def admin_soft_delete_user(user_id: str, _admin=Depends(require_admin)):
    """회원 비활성화(소프트삭제) — 접근 즉시 차단, 데이터는 보유기간 정책대로.
    복구는 기존 POST /admin/users/{id}/restore. (완전 파기는 scripts/erase_user.py)"""
    repo = get_users_repo()
    target = repo.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="user not found")
    # ⚠️ 이 가드는 원래 `admin_in is False`(PATCH 의 지역변수)를 참조해 **모든**
    # 비활성화 요청이 NameError→500 이었다. 여기선 강등이 아니라 비활성화이므로
    # 루트 관리자면 무조건 거부한다(자기잠금 방지).
    if (target.email or "").lower() in ROOT_ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="루트 관리자는 비활성화할 수 없습니다.")
    repo.soft_delete(user_id)
    return {"ok": True, "user_id": user_id, "deleted": True}


@router.get("/admin/events/summary")
def admin_events_summary(
    days: int = 30,
    scope: str = "real",
    _admin=Depends(require_admin),
):
    """적재만 되고 조회처가 없던 이벤트들의 관측 창구(2026-08-11).

    타입별 카운트 + 최근 샘플 3건(payload 앞부분). 대상: model_ab(LLM A/B 배정),
    skill_verdict(IRB/DRB 판정 — 전체 덤프는 scripts/export_skill_verdicts.py),
    unverified_contact(링크·연락처 날조 신호), report_quality(보고서 품질 지표),
    report_download(보고서 다운로드).
    """
    import json as _json
    from datetime import datetime, timedelta, timezone

    from src.persistence import get_events_repo

    _TYPES = ("model_ab", "skill_verdict", "unverified_contact",
              "report_quality", "report_download")
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    since = _scope_since(scope, since)
    _excl = _excluded_admin_user_ids(scope)
    repo = get_events_repo()

    out = {}
    for t in _TYPES:
        events = _drop_test_events(
            repo.list_by_type(t, since=since, limit=1000), scope, _excl)
        samples = []
        for ev in events[:3]:
            try:
                p = _json.loads(ev.payload_json or "{}")
            except Exception:  # noqa: BLE001
                p = {}
            samples.append({"ts": ev.ts, "user_id": ev.user_id,
                            "payload": _json.dumps(p, ensure_ascii=False)[:300]})
        out[t] = {"count": len(events),
                  "unique_users": len({e.user_id for e in events if e.user_id}),
                  "samples": samples}
    return {"days": days, "types": out}


@router.post("/admin/notify")
async def admin_notify(request: Request, _admin=Depends(require_admin)):
    """관리자 공지 이메일.

    body: {
      subject, body,                 # 필수(본문은 plain text)
      body_html?,                    # 선택 — 있으면 HTML 대안 파트 동봉
      to?: "all"|"admins"|"whitelisted"|"beta_testers"|[emails],
      dry_run?: bool                 # true 면 발송 안 하고 수신자만 돌려줌
    }

    - to 미지정=all(비활성/탈퇴 제외 전체 회원)
    - `whitelisted` = 화이트리스트로 명시 허용된 **가입 회원**
    - `beta_testers` = 화이트리스트 항목 전체(아직 가입 안 한 초대자 포함,
      @도메인 항목은 개별 주소가 없으므로 제외)
    - 개별 발송(BCC 아님 — 수신자 간 주소는 서로 보이지 않음)
    - SMTP 미설정 시 stub(로그만) → sent 는 올라가지만 실제 발송은 없음

    추가 옵션:
      marketing?: bool — true 면 **marketing 동의자에게만** 발송(법 §50 사전동의).
        서비스 고지(기본 false)는 동의 불요. dry_run 으로 필터 결과 확인 가능.
      template?: "branded"(기본, 서비스 테마 HTML) | "plain"(평문만)
      cta_url?/cta_label?: 본문 아래 버튼(branded 템플릿에서만)
      send_at?: ISO8601 — 주면 **즉시 발송 대신 예약**(스케줄러가 발송)
      preview?: bool — 발송·예약 없이 렌더된 HTML 을 돌려줌(템플릿 확인용)
    """
    from src.notices import (filter_marketing_consented, filter_notice_optout,
                             honors_notice_optout, parse_send_at,
                             render_notice_html, resolve_recipients,
                             schedule_notice, send_notice)
    from src.observability.notifications import is_configured

    payload = await request.json()
    subject = str(payload.get("subject") or "").strip()
    body_text = str(payload.get("body") or "").strip()
    body_html = str(payload.get("body_html") or "").strip() or None
    if not subject or not body_text:
        raise HTTPException(status_code=422, detail="subject, body 필요")
    to = payload.get("to") or "all"
    dry_run = bool(payload.get("dry_run"))
    template = str(payload.get("template") or "branded")
    cta_url = str(payload.get("cta_url") or "").strip() or None
    cta_label = str(payload.get("cta_label") or "").strip() or None
    # 회신 주소 — 미지정 시 env(NOTICE_REPLY_TO). From 은 발송 도메인이라
    # 이게 없으면 "메일로 문의하세요" 안내가 무의미해진다.
    reply_to = str(payload.get("reply_to") or "").strip() or None

    if payload.get("preview"):
        # 수신자 해석 없이 템플릿만 — "어떻게 보이나"만 확인하는 경로.
        return {"ok": True, "preview": True,
                "html": body_html or render_notice_html(
                    subject=subject, body_text=body_text,
                    cta_url=cta_url, cta_label=cta_label)}

    # 수신자 해석은 DB 조회(동기) — 이벤트 루프에서 직접 돌리지 않는다.
    emails = await asyncio.to_thread(resolve_recipients, to)
    # 마케팅성 공지 — legal_consent 최신 scopes 에 marketing 동의한 사용자만.
    # (수집만 하고 소비 0 이던 동의 항목의 배선, 2026-08-11)
    marketing = bool(payload.get("marketing"))
    if marketing:
        emails = await asyncio.to_thread(filter_marketing_consented, emails)
    # 서비스 안내 메일 수신거부자 제외(2026-09-14 재도입) — 마케팅 여부와 무관.
    excluded_optout = 0
    if honors_notice_optout(to):
        before = len(emails)
        emails = await asyncio.to_thread(filter_notice_optout, emails)
        excluded_optout = before - len(emails)
    if not emails:
        raise HTTPException(status_code=422, detail=(
            "마케팅 동의 수신자 없음" if marketing else "수신자 없음"))

    if dry_run:
        return {"ok": True, "dry_run": True, "requested": len(emails),
                "sent": 0, "recipients": emails, "failed": [],
                "excluded_optout": excluded_optout,
                "smtp_configured": is_configured()}

    raw_send_at = str(payload.get("send_at") or "").strip()
    if raw_send_at:
        try:
            when = parse_send_at(raw_send_at)
        except ValueError as e:
            raise HTTPException(status_code=422,
                                detail=f"send_at 형식 오류(ISO8601): {e}") from e
        item = schedule_notice(
            subject=subject, body_text=body_text, to=to, send_at=when,
            body_html=body_html, template=template,
            cta_url=cta_url, cta_label=cta_label, reply_to=reply_to,
            created_by=getattr(request.state, "user_email", None),
            marketing=marketing,
        )
        return {"ok": True, "scheduled": True, "notice": item,
                # 지금 기준 예상 수신자 — 프리셋은 발송 시점에 다시 해석된다.
                "requested": len(emails), "recipients": emails,
                "smtp_configured": is_configured()}

    # ⚠️ send_notice 는 수신자 수만큼 **순차 SMTP**(각 최대 15초 타임아웃).
    # 이벤트 루프에서 돌리면 100명 공지 = 서버 전체가 수 분간 무응답이 된다
    # (워커 1개 고정이라 SSE·헬스체크까지 전부 멈춤). 예약 발송 경로는 이미
    # api.py 의 asyncio.to_thread(run_due) 로 처리돼 있었고 즉시 발송만
    # 어긋나 있었다 — 규약을 맞춘다(2026-08-04 감사 C-3).
    # 첨부(2026-08-19) — `[{filename, content_b64, mime?}]`. 홍보물 PDF 동봉용.
    # 수신자 수만큼 반복 전송되므로 합계 상한을 둔다(SMTP 거부·지연 방지).
    attachments = _parse_notice_attachments(payload.get("attachments"))

    res = await asyncio.to_thread(
        lambda: send_notice(subject=subject, body_text=body_text, emails=emails,
                            body_html=body_html, template=template,
                            cta_url=cta_url, cta_label=cta_label,
                            reply_to=reply_to, attachments=attachments)
    )
    return {"ok": True, "requested": len(emails), "recipients": emails, **res}


_NOTICE_ATTACH_MAX_MB = 8.0


def _parse_notice_attachments(raw) -> list[tuple[str, bytes, str]]:
    """`[{filename, content_b64, mime?}]` → send_email 첨부 튜플.

    합계 상한 8MB — 첨부는 **수신자 수만큼 반복 전송**되므로, 큰 파일은 메일이
    거부되거나(수신 서버 상한) 발송이 수 분간 늘어진다. 초과분은 422 로 거절해
    "보냈는데 일부만 도착"하는 상태를 만들지 않는다.
    """
    import base64

    if not raw:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="attachments 는 배열이어야 합니다.")
    out: list[tuple[str, bytes, str]] = []
    total = 0
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="attachments 항목은 객체여야 합니다.")
        name = str(item.get("filename") or "").strip()
        b64 = str(item.get("content_b64") or "")
        if not name or not b64:
            raise HTTPException(status_code=422,
                                detail="attachments 항목에 filename·content_b64 필요")
        try:
            data = base64.b64decode(b64, validate=True)
        except Exception:
            raise HTTPException(status_code=422,
                                detail=f"{name}: content_b64 디코딩 실패") from None
        total += len(data)
        if total > _NOTICE_ATTACH_MAX_MB * 1024 * 1024:
            raise HTTPException(
                status_code=422,
                detail=f"첨부 합계가 {_NOTICE_ATTACH_MAX_MB:.0f}MB 를 초과합니다.")
        mime = str(item.get("mime") or "application/octet-stream")
        out.append((name, data, mime))
    return out


@router.get("/admin/notify/scheduled")
def admin_list_scheduled_notices(_admin=Depends(require_admin)):
    """예약 공지 목록(발송 예정 시각 오름차순). 발송된 건도 결과와 함께 남는다."""
    from src.notices import list_scheduled

    return {"items": list_scheduled()}


@router.delete("/admin/notify/scheduled/{notice_id}")
def admin_cancel_scheduled_notice(notice_id: str, _admin=Depends(require_admin)):
    """미발송 예약 취소. 이미 발송된 건은 404(되돌릴 수 없음)."""
    from src.notices import cancel_scheduled

    if not cancel_scheduled(notice_id):
        raise HTTPException(status_code=404,
                            detail="예약을 찾을 수 없거나 이미 발송됨")
    return {"ok": True, "id": notice_id, "canceled": True}


# ---------------------------------------------------------------------------
# PII 마스킹 개선리스트 (2026-08-13) — 마스킹 단어 전수 자동 수집 + 라벨링.
# 채팅에서 NER 마스킹된 **모든 단어**가 여기 쌓인다(신고분은 reported 플래그).
# 신고는 선보고 후조치(즉시 마스킹 제외) — correct 라벨로 되돌린다.
# 구조적 PII 형식은 수집·신고·wrong 라벨 어느 경로로도 등재·허용 불가.
# ---------------------------------------------------------------------------
@router.get("/admin/pii-terms")
def admin_list_pii_terms(status: Optional[str] = None,
                         reported_only: bool = False,
                         _admin=Depends(require_admin)):
    """마스킹 단어 개선리스트 — 라벨링 대상 목록(최신 관측순).

    Query:
      - status: unlabeled(자동 수집·미라벨) | reported(신고됨·미라벨 — 즉시 적용 중)
                | correct(정탐 확정) | wrong(오탐 확정). 미지정=전체.
      - reported_only: true 면 사용자 신고분만("신고한 것만 따로 체크").

    항목: {term, status, unmasked(현재 마스킹 제외 여부), placeholder,
    count(관측 수), reported, report_count, label, comment, created_at,
    last_seen_at, labeled_at, labeled_by}
    """
    from src.guardrail import pii_terms

    if status is not None and status not in ("unlabeled", "reported",
                                             "correct", "wrong"):
        raise HTTPException(
            status_code=422,
            detail="status 는 unlabeled|reported|correct|wrong")
    items = pii_terms.list_terms(status, reported_only=reported_only)
    return {"count": len(items), "items": items}


@router.get("/admin/pii-terms/context")
def admin_pii_term_context(term: str, _admin=Depends(require_admin)):
    """라벨링 보조 — 단어가 관측된 대화에서 가림 표시가 들어간 질문의 앞뒤(2026-09-21).

    대화는 가린 상태로만 저장되므로 원문 복원이 아니라 가림 자리 주변 문맥이다.
    """
    from src.guardrail import pii_terms

    try:
        return pii_terms.contexts(term)
    except KeyError:
        raise HTTPException(status_code=404, detail="목록에 없는 단어입니다.")


@router.post("/admin/pii-terms/{term}")
def admin_label_pii_term(term: str, body: dict, request: Request,
                         _admin=Depends(require_admin)):
    """마스킹 단어 라벨링 — body {label: "correct"|"wrong"}.

    correct = 제대로 필터함(진짜 개인정보) — 마스킹 유지, 신고돼 있었다면 즉시
    마스킹 복귀(재신고로 안 되살아남).
    wrong = 틀리게 필터함(오탐) — 마스킹 영구 제외(검색에 그대로 들어감).
    """
    from src.guardrail import pii_terms

    verdict = str((body or {}).get("label") or "").strip()
    by = getattr(request.state, "user_email", None)
    try:
        entry = pii_terms.label(term, verdict, labeled_by=by)
    except pii_terms.TermRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except KeyError:
        raise HTTPException(status_code=404, detail="목록에 없는 단어입니다.")
    return {"ok": True, **entry}


@router.delete("/admin/pii-terms/{term}")
def admin_remove_pii_term(term: str, request: Request,
                          _admin=Depends(require_admin)):
    """목록에서 제거(라벨 철회 포함) — wrong 이었다면 즉시 다시 마스킹 대상."""
    from src.guardrail import pii_terms

    if not pii_terms.remove(term, removed_by=getattr(request.state,
                                                     "user_email", None)):
        raise HTTPException(status_code=404, detail="목록에 없는 단어입니다.")
    return {"ok": True, "term": term.strip()}


# ---------------------------------------------------------------------------
# 패치노트 공지 (2026-08-13) — "매일 개선한다"를 보여주는 창구.
# 발행하면 GET /announcements/latest 가 바뀌고, 프런트는 로그인 후 최초 접속 시
# 안 본 노트(id 비교, localStorage)를 팝업 1회 띄운다. DB(app_settings) 기반 —
# 배포 없이 발행·수정.
# ---------------------------------------------------------------------------
@router.get("/admin/announcements")
def admin_list_announcements(limit: int = 100, _admin=Depends(require_admin)):
    """관리 화면용 전체 목록 — 숨긴 노트 포함(재노출 버튼이 필요).

    사용자 라우트 `GET /announcements` 는 2026-09-02 부터 공개+숨김 제외라
    admin 은 이쪽을 쓴다.
    """
    from src.announcements import list_notes

    from src.announcements import feature_order, FEATURES

    items = list_notes(limit, include_hidden=True)
    return {"count": len(items), "items": items,
            "features": feature_order(include_hidden=True), "feature_presets": list(FEATURES)}


@router.post("/admin/announcements", status_code=201)
def admin_publish_announcement(body: dict, request: Request,
                               _admin=Depends(require_admin)):
    """패치노트 발행 — body {title, items: [str,...], date?: "YYYY-MM-DD", version?: "v0.8.0", feature?: "심층 보고서"}.

    feature = 기능 영역(announcements.FEATURES 권장, ≤30자) — 게시판 탭·배지(2026-09-07).

    items = 개선사항 불릿 목록(각 ≤200자, 최대 20개). 최근 20건 보관.
    """
    from src.announcements import publish

    title = str((body or {}).get("title") or "").strip()
    items = (body or {}).get("items")
    if not title or not isinstance(items, list) or not items:
        raise HTTPException(status_code=422, detail="title, items(배열) 필요")
    try:
        note = publish(title=title, items=[str(i) for i in items],
                       date=str((body or {}).get("date") or "").strip() or None,
                       version=str((body or {}).get("version") or "").strip() or None,
                       feature=str((body or {}).get("feature") or "").strip() or None,
                       popup=bool((body or {}).get("popup", True)),
                       created_by=getattr(request.state, "user_email", None))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ok": True, "announcement": note}


@router.patch("/admin/announcements/{note_id}")
async def admin_patch_announcement(note_id: str, request: Request,
                                   _admin=Depends(require_admin)):
    """노출 금지/재노출 — body {"hidden": true|false}.

    삭제(영구)와 구분되는 옵션(2026-08-28 운영자 요청): 기록은 남기되 사용자
    팝업(latest)에서만 뺀다. 숨긴 게 최신이면 그 이전 노트가 latest 가 된다.
    """
    from src.announcements import set_hidden, set_popup

    body = await request.json()
    if "hidden" not in (body or {}) and "popup" not in (body or {}):
        raise HTTPException(status_code=422, detail="hidden(bool) 또는 popup(bool) 필요")
    by = getattr(request.state, "user_email", None)
    out: dict = {"ok": True, "id": note_id}
    # hidden = 게시판·팝업 모두에서 내림 / popup = 팝업만 끔(게시판엔 남김). 서로 독립(2026-09-18).
    if "hidden" in body:
        if not set_hidden(note_id, bool(body["hidden"]), updated_by=by):
            raise HTTPException(status_code=404, detail="announcement not found")
        out["hidden"] = bool(body["hidden"])
    if "popup" in body:
        if not set_popup(note_id, bool(body["popup"]), updated_by=by):
            raise HTTPException(status_code=404, detail="announcement not found")
        out["popup"] = bool(body["popup"])
    return out


@router.delete("/admin/announcements/{note_id}")
def admin_delete_announcement(note_id: str, request: Request,
                              _admin=Depends(require_admin)):
    """발행 철회 — 최신 건을 지우면 그 이전 노트가 latest 가 된다."""
    from src.announcements import delete

    if not delete(note_id, removed_by=getattr(request.state,
                                              "user_email", None)):
        raise HTTPException(status_code=404, detail="announcement not found")
    return {"ok": True, "id": note_id}


@router.post("/admin/feedback/digest")
async def admin_feedback_digest(request: Request, _admin=Depends(require_admin)):
    """기간 피드백 취합 → 관리자 이메일 발송. body: { days?: 7, to?: email }.

    수집: 자유 코멘트(@feedback) + 평가(thumbs) + 인용 신고. to 미지정 시 요청한
    관리자 이메일. 반환에 요약 포함(이메일 미설정 stub 여도 내용 확인 가능).
    """
    import json as _json
    from datetime import datetime, timedelta, timezone
    from src.observability.notifications import send_email
    from src.persistence import get_events_repo

    payload = await request.json() if (request.headers.get("content-length") or "0") != "0" else {}
    days = max(1, min(int(payload.get("days") or 7), 90))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    ev = get_events_repo()
    frees = ev.list_by_type("user_feedback", since=since, limit=500)
    rates = ev.list_by_type("feedback", since=since, limit=500)
    reports = ev.list_by_type("citation_report", since=since, limit=500)
    # PII 오탐 신고 — 선보고 후조치 구조라 신고 즉시 마스킹이 풀린다. 다이제스트에
    # 실어 사후 검토(/admin/pii-terms)를 놓치지 않게 한다(2026-08-13).
    pii_reports = ev.list_by_type("pii_report", since=since, limit=500)

    lines = [f"[MEDIREG] 최근 {days}일 피드백 요약", ""]
    ups = sum(1 for r in rates if '"rating": "thumbs_up"' in (r.payload_json or ""))
    downs = len(rates) - ups
    lines.append(f"평가: 👍 {ups} / 👎 {downs} · 인용 신고 {len(reports)}건 · "
                 f"자유 코멘트 {len(frees)}건 · PII 오탐 신고 {len(pii_reports)}건")
    lines.append("")
    if pii_reports:
        lines.append("── PII 오탐 신고 (즉시 적용됨 — /admin/pii-terms 에서 검토) ──")
        for r in pii_reports[:30]:
            try:
                pl = _json.loads(r.payload_json or "{}")
            except ValueError:
                continue
            lines.append(f"- [{(r.ts or '')[:10]}] '{pl.get('term','')}' "
                         f"({pl.get('placeholder') or '?'} 치환됨)")
        lines.append("")
    if frees:
        lines.append("── 자유 코멘트 ──")
        for r in frees[:30]:
            try:
                c = _json.loads(r.payload_json or "{}").get("comment", "")
            except ValueError:
                c = ""
            lines.append(f"- [{(r.ts or '')[:10]}] {c[:200]}")
    if reports:
        lines.append("")
        lines.append("── 인용 신고 ──")
        for r in reports[:30]:
            try:
                pl = _json.loads(r.payload_json or "{}")
                lines.append(f"- [{(r.ts or '')[:10]}] [{pl.get('citation_number')}] "
                             f"{pl.get('citation_title','')[:60]} — {pl.get('reason') or '(사유 없음)'}")
            except ValueError:
                pass
    body_text = chr(10).join(lines)

    to = str(payload.get("to") or "").strip() or getattr(request.state, "user_email", None)
    # SMTP 는 동기 + 최대 15초 타임아웃 — 이벤트 루프 밖에서(C-3).
    sent = bool(to) and await asyncio.to_thread(
        send_email, to=to, subject=f"[MEDIREG] 피드백 요약 ({days}일)",
        body_text=body_text)
    return {"ok": True, "days": days, "to": to, "sent": bool(sent),
            "counts": {"thumbs_up": ups, "thumbs_down": downs,
                       "citation_reports": len(reports), "comments": len(frees)},
            "summary": body_text}
