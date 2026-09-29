"""답변 검수 큐(2026-09-17) — 어떤 턴을 사람이 볼지 고른다.

전수 검수는 불가능하니 두 갈래로 뽑는다.

- **신호 표본**: 이미 적재되는 위험 신호(인용 미검증·claim audit 지적·👎·인용 오류
  신고·강제검색인데 인용 없음·검색 0건)에 점수를 매겨 위에서부터. 결함 **탐지**용.
- **무작위 표본**: `message_id` 해시로 고정 비율. 신호와 **독립**으로 뽑아야 서비스
  정답률을 말할 수 있다 — 신호 표본의 오답률은 편향돼 있어 그 용도로 못 쓴다.
  해시라 새로고침해도 표본이 바뀌지 않고, 통계 시점에 같은 식으로 재판정된다.

순수 함수 모듈 — DB 접근은 라우트(`routes/admin_reviews.py`)가 하고 여기엔 결과만
넘긴다(테스트가 DB 없이 돈다).
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Optional

_CITE_RE = re.compile(r"\[(\d{1,3})\]")

# 신호별 가중치 — 값의 크기는 "사람이 먼저 봐야 하는 정도"의 순서만 뜻한다.
SIGNAL_WEIGHTS = {
    "citation_report": 5,     # 사용자가 인용 오류를 직접 신고
    "thumbs_down": 4,
    "identifier_mismatch": 4, # 서식·별표 번호가 근거에 없음/공란(결정적 대조 — 오탐 거의 없음)
    "claim_contradicted": 4,  # 출처와 모순되는 무인용 사실
    "no_citation": 3,         # 강제검색 턴인데 답변에 인용이 없음
    "search_empty": 3,        # 검색 0건
    "low_verified": 2,        # 인용 검증률 저조
    "claim_unverified": 1,
    "truncated": 1,
}
_LOW_VERIFIED_THRESHOLD = 0.7
_SKILL_TOOLS = frozenset({"load_skill", "read_skill_reference"})


_MAX_DT = datetime.max.replace(tzinfo=timezone.utc)


def _parse_ts(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def in_random_sample(message_id: str, pct: int) -> bool:
    """`message_id` 해시 기반 고정 표본 — 같은 id 는 항상 같은 판정."""
    if pct <= 0 or not message_id:
        return False
    h = int(hashlib.sha1(message_id.encode("utf-8")).hexdigest()[:8], 16)
    return h % 100 < min(pct, 100)


def build_turns(views: list[dict], stamps: dict[str, str], steps: list[dict]) -> list[dict]:
    """메시지 뷰 → 턴 목록. 턴 = human 부터 그 뒤 첫 최종 AI 답변(tool_calls 없는 ai).

    보고서 개요 등 `kind` 가 붙은 AI 메시지는 일반 답변이 아니라 건너뛴다.
    """
    steps_by_human: dict[str, list[dict]] = {}
    for st in steps or []:
        hid = st.get("source_message_id")
        if hid:
            steps_by_human.setdefault(hid, []).append(st)

    turns: list[dict] = []
    cur: Optional[dict] = None
    tools_called: list[str] = []
    skill_seen = False  # 스킬은 스티키 — 한 번 로드되면 이후 턴에도 부착된다
    for v in views:
        if v.get("type") == "human":
            cur, tools_called = v, []
            continue
        if v.get("type") == "ai" and v.get("tool_calls"):
            tools_called.extend(v["tool_calls"])
            skill_seen = skill_seen or bool(_SKILL_TOOLS & set(v["tool_calls"]))
            continue
        if (v.get("type") == "ai" and not v.get("tool_calls")
                and not v.get("kind") and cur is not None):
            answer = v.get("content") or ""
            cites: list[dict] = []
            for st in steps_by_human.get(cur.get("id") or "", []):
                cites.extend(c for c in (st.get("citations") or []) if isinstance(c, dict))
            used = {int(n) for n in _CITE_RE.findall(answer)}
            used_cites = [c for c in cites if c.get("number") in used]
            checked = [c for c in used_cites if "verified" in c]
            verified = sum(1 for c in checked if c.get("verified"))
            turns.append({
                "human_id": cur.get("id"),
                "message_id": v.get("id"),
                "question": cur.get("content") or "",
                "answer": answer,
                "started_at": stamps.get(cur.get("id") or ""),
                "ended_at": stamps.get(v.get("id") or ""),
                "truncated": bool(v.get("truncated")),
                "searched": bool(steps_by_human.get(cur.get("id") or "")),
                "tools_called": sorted(set(tools_called)),
                "skill_sticky": skill_seen,
                "citations_retrieved": len(cites),
                "citations_used": len(used_cites),
                "citations_checked": len(checked),
                "citations_verified": verified,
                "verified_rate": round(verified / len(checked), 3) if checked else None,
            })
            cur = None
    return turns


def attach_window_events(turns: list[dict], events: list[dict]) -> None:
    """`message_id` 없는 이벤트(rag_search·user_question)를 시각 창으로 턴에 붙인다.

    창 = [턴 시작, 다음 턴 시작). 이벤트 dict: {type, ts, payload}.
    """
    # 메시지 시각(threads_repo)과 이벤트 시각(events_repo)은 백엔드에 따라 표기가
    # 다를 수 있다("Z" vs "+00:00") — 문자열 비교 대신 파싱해서 비교한다.
    ordered = sorted(((_parse_ts(t.get("started_at")), t) for t in turns),
                     key=lambda p: (p[0] is None, p[0] or _MAX_DT))
    ordered = [(ts, t) for ts, t in ordered if ts is not None]
    stamped = [(_parse_ts(e.get("ts")), e) for e in events]
    for i, (lo, t) in enumerate(ordered):
        hi = ordered[i + 1][0] if i + 1 < len(ordered) else _MAX_DT
        t["_events"] = [e for ts, e in stamped if ts is not None and lo <= ts < hi]


def is_skill_turn(turn: dict) -> bool:
    """기관 지침 스킬 턴인가. `user_question.skill` 이 정본(2026-09-17~), 그 전 턴은
    판정 이벤트·스킬 도구 호출 흔적으로 폴백."""
    # `resolve_turn_skill` 의 스티키 부착과 같은 규칙 — 앞선 턴에서 스킬을 로드했으면
    # 후속 턴도 스킬 턴이다(도구 호출·판정 없이 온프레미스 모델이 답한다).
    if turn.get("skill_sticky") or _SKILL_TOOLS & set(turn.get("tools_called") or ()):
        return True
    return any(
        e["type"] == "skill_verdict"
        or (e["type"] == "user_question" and (e.get("payload") or {}).get("skill"))
        for e in turn.get("_events") or [])


def score_turn(turn: dict, *, feedback: list[str], claim_audit: Optional[dict],
               citation_reported: bool, identifier_audit: Optional[dict] = None) -> list[str]:
    """턴의 위험 신호 목록. `feedback` = 그 답변의 rating 들(최신 우선, last-wins)."""
    signals: list[str] = []
    if citation_reported:
        signals.append("citation_report")
    effective = next((r for r in feedback if r), None)
    if effective == "thumbs_down" and not citation_reported:
        signals.append("thumbs_down")
    if identifier_audit and (identifier_audit.get("unsupported")
                             or identifier_audit.get("placeholders")):
        signals.append("identifier_mismatch")
    if claim_audit:
        if int(claim_audit.get("contradicted") or 0) > 0:
            signals.append("claim_contradicted")
        elif int(claim_audit.get("unverified") or 0) > 0:
            signals.append("claim_unverified")

    evs = turn.get("_events") or []
    # 기관 지침 스킬 턴은 설계상 [n] 인용을 달지 않는다(.md 자산 기반·원문 유출 금지).
    # 인용 부재를 결함으로 세면 큐가 스킬 턴으로 뒤덮인다(운영 실측 2026-09-17:
    # no_citation 49건 중 48건이 스킬 턴). 스킬 턴의 정답성은 판정(verdict) 축이다.
    skill = is_skill_turn(turn)
    forced = any(e["type"] == "user_question" and (e.get("payload") or {}).get("forced_search")
                 for e in evs)
    searches = [e for e in evs if e["type"] == "rag_search"]
    if searches and all(int((e.get("payload") or {}).get("hit_count") or 0) == 0
                        for e in searches):
        signals.append("search_empty")
    elif forced and not skill and turn.get("citations_used", 0) == 0:
        signals.append("no_citation")
    vr = turn.get("verified_rate")
    if vr is not None and vr < _LOW_VERIFIED_THRESHOLD:
        signals.append("low_verified")
    if turn.get("truncated"):
        signals.append("truncated")
    return signals


def priority(signals: list[str]) -> int:
    return sum(SIGNAL_WEIGHTS.get(s, 0) for s in signals)


def wilson_interval(success: int, n: int, z: float = 1.96) -> Optional[tuple[float, float]]:
    """이항 비율의 Wilson 신뢰구간 — 표본이 작을 때(주 20~30건) 정규근사보다 정직하다."""
    if n <= 0:
        return None
    p = success / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))
