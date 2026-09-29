"""주간 이용 집계 + 스냅샷 저장 (2026-09-21).

운영자 요청: "사용 통계는 1주일 단위로 정리해서 이용 데이터를 저장하고, 전주와 비교".

- 주 = **사용자 타임존(기본 KST) 월요일 00:00 ~ 다음 월요일 00:00**. 일별 통계
  (`daily_stats`)도 같은 타임존 날짜라 주간 합 = 일별 합.
- 범위 3개를 같은 규칙으로 동시에 계산한다:
    real     = 실사용 — 내부 계정(`src/account_class.py`)·익명·내부 스레드 제외
    internal = 내부 — real 을 뺀 나머지(관리자·테스트·스크립트)
    all      = 전체
  필터는 관리자 화면(`routes.admin._drop_test_events`)과 **같은 판정 함수**(`account_class`)를 쓴다 — SQL 로
  복제하면 조용히 어긋난다(doc_kinds·커버리지 매핑 드리프트 선례).
- 끝난 주는 app_settings `usage_weekly:v1:<YYYY-MM-DD>` 에 저장한다. 이벤트·대화는
  보관기간(90일) 뒤 정리되므로, 스냅샷이 장기 추이의 유일한 원본이 된다.
- 스냅샷엔 저장 당시 내부 계정 집합의 지문(`account_class.fingerprint`)을 남긴다.
  이후 라벨을 바꾸면 `stale=True` 로 표시하고, 재계산은 운영자가 명시적으로 한다
  (자동으로 덮으면 이미 지워진 이벤트 구간의 기록이 0 으로 바뀔 수 있다).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

_log = logging.getLogger(__name__)

KEY_PREFIX = "usage_weekly:v1:"
SCOPES = ("real", "internal", "all")

# 화면·CSV 에 쓰는 지표 정의(순서 = 표시 순서). kind: count|users|usd
METRICS: list[dict] = [
    {"key": "active_users", "label": "활성 사용자", "kind": "users",
     "desc": "그 주에 질문을 1회 이상 한 계정 수"},
    {"key": "returning_users", "label": "재방문 사용자", "kind": "users",
     "desc": "전주에도 질문한 활성 사용자"},
    {"key": "new_users", "label": "신규 가입", "kind": "users", "desc": "그 주 가입 계정"},
    {"key": "questions", "label": "질문", "kind": "count", "desc": "채팅 질문 수"},
    {"key": "threads", "label": "대화", "kind": "count", "desc": "질문이 있었던 대화 수"},
    {"key": "reports", "label": "심층 보고서 요청", "kind": "count", "desc": "보고서 실행 시작"},
    {"key": "reports_completed", "label": "보고서 완료", "kind": "count", "desc": ""},
    {"key": "documents", "label": "서식 작성", "kind": "count", "desc": "서식·서류 작성 시작"},
    {"key": "doc_fills", "label": "서식 기입", "kind": "count", "desc": "채팅으로 서식 칸 채움"},
    {"key": "feedback", "label": "피드백", "kind": "count", "desc": "👍👎·의견"},
    {"key": "citation_reports", "label": "인용 신고", "kind": "count", "desc": ""},
    {"key": "llm_calls", "label": "LLM 호출", "kind": "count", "desc": ""},
    {"key": "tokens", "label": "토큰", "kind": "count", "desc": "입력+출력"},
    {"key": "cost_usd", "label": "LLM 비용", "kind": "usd", "desc": "USD, 캐시 할인 미반영"},
]


def _tz() -> timezone:
    from src.persistence.events_repo import _usage_tz

    return _usage_tz()


def _utc_iso(dt: datetime) -> str:
    # events·report_runs 의 SQLite 저장 형식과 같은 고정폭(사전식=시간순)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def current_week_start(now: Optional[datetime] = None) -> date:
    now = now or datetime.now(timezone.utc)
    return week_start_of(now.astimezone(_tz()).date())


def launch_week() -> date:
    """베타 오픈이 속한 주의 월요일 — 이보다 이른 주는 추이·목록에서 뺀다."""
    from src.account_class import launch_cutoff

    return week_start_of(datetime.fromisoformat(launch_cutoff()).astimezone(_tz()).date())


def week_bounds(ws: date) -> tuple[str, str]:
    """주 시작일(현지) → [since, until) UTC ISO."""
    start = datetime(ws.year, ws.month, ws.day, tzinfo=_tz())
    return _utc_iso(start), _utc_iso(start + timedelta(days=7))


def _empty() -> dict:
    return {m["key"]: 0 for m in METRICS}


def _is_real(user_id, thread_id, internal_ids: frozenset) -> bool:
    from src.account_class import is_internal_thread

    return bool(user_id) and user_id not in internal_ids and not is_internal_thread(
        thread_id or "", user_id)


def _active_real_users(rows: list[dict], internal_ids: frozenset) -> set:
    return {r["user_id"] for r in rows
            if r["event_type"] == "user_question" and _is_real(r["user_id"], r["thread_id"], internal_ids)}


def compute_week(ws: date) -> dict:
    """한 주의 3개 범위 지표. 저장하지 않는다(→ `snapshot_week`)."""
    since, until = week_bounds(ws)
    prev_since, _ = week_bounds(ws - timedelta(days=7))
    return compute_range(since, until, prev_since=prev_since)


def compute_range(since: str, until: str, *, prev_since: Optional[str] = None) -> dict:
    """[since, until) 의 3개 범위(real·internal·all) 지표. 통계 화면의 기간 비교에도 쓴다.

    prev_since: 주면 [prev_since, since) 활성 사용자와 겹치는 수를 returning_users 로.
    """
    from src import account_class
    from src.persistence import get_events_repo, get_report_runs_repo, get_users_repo

    internal_ids = account_class.internal_user_ids()
    rows = get_events_repo().rollup(since=since, until=until)
    prev_rows = (get_events_repo().rollup(since=prev_since, until=since)
                 if prev_since else [])

    out = {sc: _empty() for sc in SCOPES}
    act = {sc: set() for sc in SCOPES}
    thr = {sc: set() for sc in SCOPES}
    for r in rows:
        real = _is_real(r["user_id"], r["thread_id"], internal_ids)
        for sc in ("all", "real" if real else "internal"):
            m, n, et = out[sc], int(r["n"] or 0), r["event_type"]
            if et == "user_question":
                m["questions"] += n
                if r["user_id"]:
                    act[sc].add(r["user_id"])
                if r["thread_id"]:
                    thr[sc].add(r["thread_id"])
            elif et == "llm_call":
                m["llm_calls"] += n
            elif et in ("user_feedback", "feedback"):
                m["feedback"] += n
            elif et == "citation_report":
                m["citation_reports"] += n
            elif et == "doc_fill":
                m["doc_fills"] += n
            m["tokens"] += int(r["input_tokens"] or 0) + int(r["output_tokens"] or 0)
            m["cost_usd"] += float(r["cost_usd"] or 0)

    # 재방문 = 이번 주 활성 ∩ 전주 활성. 전주 활성도 같은 범위 규칙으로.
    prev_all = {r["user_id"] for r in prev_rows if r["event_type"] == "user_question" and r["user_id"]}
    prev_real = _active_real_users(prev_rows, internal_ids)
    prev = {"all": prev_all, "real": prev_real, "internal": prev_all - prev_real}
    for sc in SCOPES:
        out[sc]["active_users"] = len(act[sc])
        out[sc]["threads"] = len(thr[sc])
        out[sc]["returning_users"] = len(act[sc] & prev[sc])

    for run in get_report_runs_repo().runs_between(since=since, until=until):
        real = _is_real(run.get("user_id"), run.get("thread_id"), internal_ids)
        doc = (run.get("purpose") or "") == "document_draft"
        for sc in ("all", "real" if real else "internal"):
            if doc:
                out[sc]["documents"] += 1
            else:
                out[sc]["reports"] += 1
                if run.get("status") == "completed":
                    out[sc]["reports_completed"] += 1

    for u in get_users_repo().list_all(limit=100000):
        created = account_class._created_iso(u)
        if not (week_bounds_iso_cmp(since) <= created < week_bounds_iso_cmp(until)):
            continue
        sc = "internal" if u.id in internal_ids else "real"
        out[sc]["new_users"] += 1
        out["all"]["new_users"] += 1

    for sc in SCOPES:
        out[sc]["cost_usd"] = round(out[sc]["cost_usd"], 4)
    return out


def week_bounds_iso_cmp(utc_iso_z: str) -> str:
    """`…Z` 고정폭 → account_class._created_iso 와 같은 `+00:00` 형식(문자열 비교용)."""
    return datetime.fromisoformat(utc_iso_z.replace("Z", "+00:00")).isoformat()


def _settings():
    from src.persistence.settings_repo import get_settings_repo

    return get_settings_repo()


def load_snapshot(ws: date) -> Optional[dict]:
    raw = _settings().get(KEY_PREFIX + ws.isoformat())
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        _log.warning("usage_weekly 스냅샷 손상 — 재계산 대상: %s", ws)
        return None


def snapshot_week(ws: date, *, by: Optional[str] = None) -> dict:
    """끝난 주를 계산해 저장(덮어씀). 진행 중인 주는 저장하지 않는다."""
    from src import account_class

    if ws >= current_week_start():
        raise ValueError("진행 중인 주는 저장하지 않는다")
    snap = {
        "week_start": ws.isoformat(),
        "week_end": (ws + timedelta(days=6)).isoformat(),
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprint": account_class.fingerprint(),
        "scopes": compute_week(ws),
    }
    _settings().set(KEY_PREFIX + ws.isoformat(), json.dumps(snap, ensure_ascii=False),
                    updated_by=by)
    return snap


def weekly_series(weeks: int = 12, *, earliest: Optional[date] = None) -> list[dict]:
    """최신 주부터 `weeks` 개. 끝난 주는 스냅샷(없으면 계산·저장), 이번 주는 실시간.

    earliest: 이보다 이른 주는 건너뛴다(베타 오픈 이전 등).
    """
    from src import account_class

    fp = account_class.fingerprint()
    cur = current_week_start()
    out = []
    for i in range(max(1, min(weeks, 52))):
        ws = cur - timedelta(days=7 * i)
        if earliest and ws + timedelta(days=7) <= earliest:
            break
        if i == 0:
            out.append({"week_start": ws.isoformat(),
                        "week_end": (ws + timedelta(days=6)).isoformat(),
                        "partial": True, "stored": False, "stale": False,
                        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "scopes": compute_week(ws)})
            continue
        snap = load_snapshot(ws)
        if snap is None:
            try:
                snap = snapshot_week(ws, by="auto")
            except Exception:  # noqa: BLE001 — 한 주 실패가 화면 전체를 막지 않게
                _log.warning("usage_weekly 계산 실패 %s", ws, exc_info=True)
                continue
        out.append({**snap, "partial": False, "stored": True,
                    "stale": bool(snap.get("fingerprint")) and snap.get("fingerprint") != fp})
    return out


def ensure_recent_snapshots(n: int = 2) -> int:
    """직전 n 개의 끝난 주 스냅샷이 없으면 만든다(부팅·주기 작업). 만든 개수."""
    cur = current_week_start()
    made = 0
    for i in range(1, n + 1):
        ws = cur - timedelta(days=7 * i)
        if load_snapshot(ws) is None:
            snapshot_week(ws, by="auto")
            made += 1
    return made
