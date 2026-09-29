"""PII 마스킹 단어 수집·라벨링·허용어 — 오탐 피드백 루프의 저장소.

배경: NER 이 도메인 용어를 이름/주소로 오분류해 질문 핵심어가 `[이름]` 으로
사라지는 오탐이 계속 나온다(실측: 유권해석·통합운영·"영상분석 ○○ 프로토콜" 류).
코드 스토플리스트·접미 가드는 배포가 필요해 새 오탐마다 며칠씩 걸렸다.

구조(사용자 결정 2026-08-13, 2단계):
1. **전수 수집**: 채팅에서 NER 마스킹이 일어난 **모든 단어**를 자동 등재
   (`observe_many`, chat_loop 배선). 사용자 신고 여부와 무관하게 개선리스트에
   쌓인다 — "모든 필터 단어는 추가하고".
2. **신고는 플래그**: 사용자가 오탐 신고(`POST /feedback/pii`)하면 같은 항목에
   `reported` 표시 + **선보고 후조치** — 즉시 마스킹 제외(오탐은 시스템 잘못,
   사용자를 기다리게 하지 않는다).
3. **라벨링(후조치)**: 관리자가 각 단어를 `correct`(제대로 필터 — 진짜 개인정보)
   / `wrong`(틀리게 필터 — 오탐) 로 라벨. wrong=마스킹 영구 제외,
   correct=마스킹 유지(신고돼 있었으면 다시 마스킹 복귀). 라벨 셋은 NER
   임계값 튜닝·가드 개선의 실측 데이터가 된다.

마스킹 제외 규칙(`allowed_terms`): label=="wrong" **또는** (reported && 미라벨).
즉 신고는 즉시 풀리고, 관리자가 correct 로 라벨하면 다시 잠긴다.

안전 원칙("주민번호·이름 등 진짜 개인정보는 절대 필터"):
- **구조적 PII(주민번호·전화·카드…)는 어느 경로로도 등재·허용 불가** —
  `pii.has_pii` 매칭은 신고 422, 자동 수집은 조용히 스킵, wrong 라벨도 거부.
- correct 라벨 단어는 재신고해도 조용히 풀리지 않는다(재검토는 관리자 몫).
- 자동 수집분은 **진짜 이름·주소일 수 있다** — admin 전용 노출, 상한(500) 초과
  시 미신고·미라벨 최고(最古)부터 제거. 라벨 후 원문 보존이 부담스러우면
  관리자가 DELETE 로 지울 수 있다.

진실원은 app_settings DB(`pii_terms` 키, JSON) — 재기동 생존, 단일 워커라
프로세스 로컬 TTL 캐시로 충분(maintenance 와 같은 패턴).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

_log = logging.getLogger(__name__)

_KEY = "pii_terms"
_TTL_S = 10.0
_MAX_TERMS = 500          # KV JSON 비대 방지
_TERM_MIN, _TERM_MAX = 2, 30

_LABELS = ("correct", "wrong")

# {"approved": frozenset|None, "at": monotonic}
_CACHE: dict = {"approved": None, "at": 0.0}
_lock = threading.Lock()   # read-modify-write 직렬화(단일 프로세스 전제)


class TermRejected(ValueError):
    """등재/라벨 불가 — 사유는 str(예외)."""


def _load() -> dict:
    """DB 원본 로드. {"terms": {term: entry}} — 실패 시 빈 구조(채팅 비차단)."""
    try:
        from src.persistence.settings_repo import get_settings_repo

        raw = get_settings_repo().get(_KEY)
    except Exception as e:  # noqa: BLE001 — DB 장애가 게이트를 막으면 안 됨
        _log.warning("pii_terms 조회 실패(빈 목록으로 처리): %s", e)
        return {"terms": {}}
    if not raw:
        return {"terms": {}}
    try:
        data = json.loads(raw)
        terms = data.get("terms")
        if isinstance(terms, dict):
            return {"terms": terms}
    except Exception:  # noqa: BLE001
        pass
    return {"terms": {}}


def _save(data: dict, *, updated_by: Optional[str]) -> None:
    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(_KEY, json.dumps(data, ensure_ascii=False),
                            updated_by=updated_by)
    invalidate_cache()


def invalidate_cache() -> None:
    _CACHE["approved"] = None
    _CACHE["at"] = 0.0


def _unmasked(e: dict) -> bool:
    """이 항목은 마스킹 제외인가 — wrong 라벨 또는 (신고됨 && 미라벨)."""
    if e.get("label") == "wrong":
        return True
    return bool(e.get("reported")) and e.get("label") is None


def status_of(e: dict) -> str:
    """개선리스트 표시용 파생 상태 — correct|wrong|reported|unlabeled."""
    if e.get("label") in _LABELS:
        return e["label"]
    return "reported" if e.get("reported") else "unlabeled"


def allowed_terms() -> frozenset:
    """마스킹 제외 단어 집합 — `gate._stoplisted` 가 매 스팬마다 부르므로 TTL 캐시."""
    now = time.monotonic()
    if _CACHE["approved"] is not None and now - _CACHE["at"] < _TTL_S:
        return _CACHE["approved"]
    terms = _load()["terms"]
    approved = frozenset(
        t for t, e in terms.items() if isinstance(e, dict) and _unmasked(e))
    _CACHE["approved"] = approved
    _CACHE["at"] = now
    return approved


def _validate(term: str) -> str:
    """등재·라벨 공통 검증 — 통과 시 정규화된 단어 반환, 실패 시 TermRejected.

    구조적 PII 검사는 신고와 wrong 라벨 **양쪽**에서 한다(방어 이중화) — 여기서
    걸리면 그 문자열은 어떤 경로로도 허용어가 될 수 없다.
    """
    from src.guardrail.pii import has_pii

    s = (term or "").strip()
    if not (_TERM_MIN <= len(s) <= _TERM_MAX):
        raise TermRejected(f"단어는 {_TERM_MIN}~{_TERM_MAX}자여야 합니다.")
    if any(c in s for c in "\r\n\t"):
        raise TermRejected("단어에 줄바꿈·탭을 넣을 수 없습니다.")
    if has_pii(s):
        raise TermRejected(
            "주민등록번호·전화번호 등 개인정보 형식은 허용어로 등록할 수 없습니다.")
    return s


def _new_entry(now: str) -> dict:
    return {
        "placeholder": None,
        "count": 0,              # 마스킹 관측 수(자동 수집)
        "reported": False,       # 사용자 오탐 신고 여부 — "신고한 것만 따로 체크"
        "report_count": 0,
        "label": None,           # None | "correct"(정탐) | "wrong"(오탐)
        "reported_by": None,
        "thread_id": None,
        # 최근 관측 대화(최신이 앞, 최대 5) — 관리자 문맥 팝오버용(2026-09-21). thread_id 는 최초 관측(하위호환).
        "threads": [],
        # 정확한 가림 자리 문맥(최신 앞, 최대 3) — 마스킹 시점에 원문↔가린 글을 맞대어 이 단어가
        # 몇 번째 가림이었는지 찾고, **가린 글** 기준 앞뒤만 저장(원문 미보존 유지). 2026-09-21.
        "samples": [],
        "comment": None,
        "created_at": now,
        "last_seen_at": now,
        "labeled_at": None,
        "labeled_by": None,
    }


def _evict_if_full(terms: dict) -> bool:
    """상한 초과 시 미신고·미라벨 최고(最古) 1건 제거. 자리 확보 성공 여부."""
    if len(terms) < _MAX_TERMS:
        return True
    victims = sorted(
        (t for t, v in terms.items()
         if isinstance(v, dict) and not v.get("reported") and v.get("label") is None),
        key=lambda t: str(terms[t].get("last_seen_at") or ""))
    if not victims:
        return False
    terms.pop(victims[0], None)
    return True


_MAX_THREADS = 5


def _remember_thread(e: dict, thread_id: Optional[str]) -> None:
    if not thread_id:
        return
    lst = [t for t in (e.get("threads") or []) if t != thread_id]
    e["threads"] = ([thread_id] + lst)[:_MAX_THREADS]


def observe_many(spans: list[dict], *, thread_id: Optional[str] = None,
                 message_id: Optional[str] = None, original: Optional[str] = None,
                 masked: Optional[str] = None) -> int:
    """마스킹 발생 단어 전수 자동 등재(chat_loop 배선) — 등재/갱신 건수 반환.

    spans: [{"term", "placeholder", "score"?}, ...] (gate 가 수집한 NER 마스킹분).
    검증 실패(구조적 PII·길이 등)는 **조용히 스킵** — 자동 경로가 대화를 막거나
    로그를 오염시키면 안 된다. 상태는 절대 바꾸지 않는다(count·last_seen 만).
    """
    if not spans:
        return 0
    from src.persistence._common import utcnow_iso

    now = utcnow_iso()
    touched = 0
    # 원문·가린 글이 오면 단어별 정확한 가림 자리 문맥을 뽑는다(실패해도 수집은 계속).
    located: dict[str, list[dict]] = {}
    if original and masked:
        try:
            located = locate(original, masked, [str(sp.get("term") or "") for sp in spans])
        except Exception:  # noqa: BLE001 — 문맥 추출 실패가 수집·대화를 막으면 안 됨(로그는 남김)
            _log.warning("pii_terms locate 실패", exc_info=True)
    with _lock:
        data = _load()
        terms = data["terms"]
        for sp in spans:
            try:
                s = _validate(str(sp.get("term") or ""))
            except TermRejected:
                continue
            e = terms.get(s)
            if not isinstance(e, dict):
                if not _evict_if_full(terms):
                    continue
                e = _new_entry(now)
                terms[s] = e
            e["count"] = int(e.get("count") or 0) + 1
            e["last_seen_at"] = now
            if sp.get("placeholder") and not e.get("placeholder"):
                e["placeholder"] = str(sp["placeholder"])[:20]
            if thread_id and not e.get("thread_id"):
                e["thread_id"] = thread_id
            _remember_thread(e, thread_id)
            for ctx in located.pop(s, [])[:1]:     # 한 메시지에서 한 자리만(같은 단어 반복은 첫 자리)
                sample = {"thread_id": thread_id, "message_id": message_id, "at": now, **ctx}
                e["samples"] = ([sample] + [x for x in (e.get("samples") or [])
                                            if x.get("message_id") != message_id or not message_id])[:3]
            touched += 1
        if touched:
            _save(data, updated_by=None)
    return touched


def report(term: str, *, placeholder: Optional[str] = None,
           user_id: Optional[str] = None,
           thread_id: Optional[str] = None,
           comment: Optional[str] = None) -> dict:
    """사용자 오탐 신고 — reported 플래그 + **즉시 마스킹 제외**(선보고 후조치).

    이미 correct(정탐) 로 라벨된 단어는 신고해도 조용히 풀리지 않는다 —
    report_count 만 올라간다(재검토는 관리자 몫).
    """
    from src.persistence._common import utcnow_iso

    s = _validate(term)
    now = utcnow_iso()
    with _lock:
        data = _load()
        terms = data["terms"]
        e = terms.get(s)
        if not isinstance(e, dict):
            if not _evict_if_full(terms):
                raise TermRejected("허용어 목록이 가득 찼습니다(관리자 정리 필요).")
            e = _new_entry(now)
            terms[s] = e
        e["reported"] = True
        e["report_count"] = int(e.get("report_count") or 0) + 1
        e["last_seen_at"] = now
        if placeholder:
            e["placeholder"] = str(placeholder)[:20]
        if user_id and not e.get("reported_by"):
            e["reported_by"] = user_id
        if thread_id:
            e["thread_id"] = thread_id
            _remember_thread(e, thread_id)
        if comment:
            e["comment"] = str(comment)[:200]
        _save(data, updated_by=user_id)
    return {"term": s, "status": status_of(e), "unmasked": _unmasked(e), **e}


def label(term: str, verdict: str, *, labeled_by: Optional[str] = None) -> dict:
    """관리자 라벨링 — correct(제대로 필터 = 진짜 개인정보, 마스킹 유지·복귀) |
    wrong(틀리게 필터 = 오탐, 마스킹 영구 제외).

    wrong 은 `_validate` 를 다시 통과해야 한다 — DB 를 직접 만졌어도 구조적
    PII 는 절대 허용어가 되지 않는다.
    """
    from src.persistence._common import utcnow_iso

    if verdict not in _LABELS:
        raise TermRejected("label 은 correct|wrong 이어야 합니다.")
    s = (term or "").strip()
    if verdict == "wrong":
        s = _validate(s)
    with _lock:
        data = _load()
        e = data["terms"].get(s)
        if not isinstance(e, dict):
            raise KeyError(s)
        e["label"] = verdict
        e["labeled_at"] = utcnow_iso()
        e["labeled_by"] = labeled_by
        _save(data, updated_by=labeled_by)
    return {"term": s, "status": status_of(e), "unmasked": _unmasked(e), **e}


def remove(term: str, *, removed_by: Optional[str] = None) -> bool:
    """목록에서 제거 — wrong 라벨이었다면 즉시 다시 마스킹 대상이 된다."""
    s = (term or "").strip()
    with _lock:
        data = _load()
        if s not in data["terms"]:
            return False
        data["terms"].pop(s)
        _save(data, updated_by=removed_by)
    return True


def list_terms(status: Optional[str] = None,
               reported_only: bool = False) -> list[dict]:
    """개선리스트 — 최신 관측순. status 필터(unlabeled|reported|correct|wrong),
    reported_only=True 면 사용자 신고분만("신고한 것만 따로 체크")."""
    terms = _load()["terms"]
    items = []
    for t, e in terms.items():
        if not isinstance(e, dict):
            continue
        if reported_only and not e.get("reported"):
            continue
        st = status_of(e)
        if status is not None and st != status:
            continue
        items.append({"term": t, "status": st, "unmasked": _unmasked(e), **e})
    items.sort(key=lambda x: str(x.get("last_seen_at") or ""), reverse=True)
    return items



# ── 문맥 조회(관리자 라벨링 보조, 2026-09-21) ────────────────────────────────
# 운영자: "필터된 단어만 보고는 알 수 없는 경우가 있다 — 주변 원문을 팝오버로".
# 대화는 **가린 상태로만** 저장되므로(원문 미보존이 설계) 보여 줄 수 있는 건 가린 질문의 앞뒤다.
# 가림 자리(placeholder)를 표시하고, 같은 종류 가림이 여러 곳이면 어느 것인지 특정하지 않는다.

_CTX_CHARS = 70


def _text_of(message) -> str:
    c = getattr(message, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in c)
    return str(c or "")


def contexts(term: str, *, limit: int = 5) -> dict:
    """단어가 관측된 대화에서 가림 표시가 들어간 사용자 질문의 앞뒤 문맥.

    반환 {term, placeholder, contexts:[{thread_id, message_id, created_at, before, mark, after,
    same_kind}], missing_threads}. 대화가 지워졌으면(90일 정리 등) missing_threads 에 센다.
    """
    from src.persistence.threads_repo import get_threads_repo

    data = _load()
    e = data["terms"].get(str(term).strip())
    if not isinstance(e, dict):
        raise KeyError(term)
    ph = e.get("placeholder") or ""
    # 1순위 — 마스킹 시점에 찾아 둔 정확한 자리(2026-09-21 이후 관측분).
    exact = [{"thread_id": s.get("thread_id"), "message_id": s.get("message_id"),
              "created_at": s.get("at"), "before": s.get("before", ""), "mark": s.get("mark", ph),
              "after": s.get("after", ""), "same_kind": 1, "exact": True}
             for s in (e.get("samples") or [])]
    if exact:
        return {"term": str(term).strip(), "placeholder": ph or None, "contexts": exact[:limit],
                "missing_threads": 0, "threads_known": len(e.get("threads") or []), "siblings": []}
    tids = list(e.get("threads") or [])
    if e.get("thread_id") and e["thread_id"] not in tids:
        tids.append(e["thread_id"])
    repo = get_threads_repo()
    out: list[dict] = []
    missing = 0
    for tid in tids:
        if len(out) >= limit:
            break
        if not repo.get_meta(tid):
            missing += 1
            continue
        try:
            msgs = repo.get_state(tid).messages
            times = repo.message_created_at(tid)
        except Exception:  # noqa: BLE001 — 한 대화 조회 실패가 목록 전체를 막지 않게(로그는 남김)
            _log.warning("pii context 조회 실패 thread=%s", tid, exc_info=True)
            continue
        for m in reversed(msgs):          # 최근 질문부터
            if getattr(m, "type", "") != "human":
                continue
            text = _text_of(m)
            if not ph or ph not in text:
                continue
            same = text.count(ph)
            i = text.rfind(ph)
            out.append({
                "thread_id": tid,
                "message_id": getattr(m, "id", None),
                "created_at": times.get(getattr(m, "id", "") or ""),
                "before": ("…" if i > _CTX_CHARS else "") + text[max(0, i - _CTX_CHARS):i],
                "mark": ph,
                "after": text[i + len(ph):i + len(ph) + _CTX_CHARS]
                + ("…" if len(text) > i + len(ph) + _CTX_CHARS else ""),
                "same_kind": same,
            })
            if len(out) >= limit:
                break
    # 옛 항목(자리 미기록) — 같은 대화에서 같은 종류로 가려진 다른 단어를 함께 보여 준다.
    # 참고문헌 저자 목록처럼 수십 개가 한꺼번에 가려진 경우 "무엇들이 함께 가려졌나"가 판단 근거가 된다.
    siblings: list[str] = []
    if out and any(c["same_kind"] > 1 for c in out):
        tset = set(tids)
        for t2, e2 in data["terms"].items():
            if t2 == str(term).strip() or not isinstance(e2, dict) or (e2.get("placeholder") or "") != ph:
                continue
            if tset & set((e2.get("threads") or []) + ([e2["thread_id"]] if e2.get("thread_id") else [])):
                siblings.append(t2)
    for c in out:
        c["exact"] = False
    return {"term": str(term).strip(), "placeholder": ph or None, "contexts": out,
            "missing_threads": missing, "threads_known": len(tids), "siblings": siblings[:40]}



# ── 정확한 가림 자리 찾기(2026-09-21) ────────────────────────────────────────
# 운영자: "다 똑같은 문맥이 나오면 구분을 어떻게 하냐" — 참고문헌처럼 한 질문에 [이름] 이 수십 개면
# 가린 글만으로는 어느 자리가 어느 단어였는지 알 수 없다. 원문이 살아 있는 마스킹 순간에 원문과 가린 글을
# 앞에서부터 맞대어, 가림 표시마다 원문의 어떤 단어가 들어 있었는지 찾는다(수집된 단어 목록과 대조).

_PH_RE = __import__("re").compile(r"\[[^\[\]\s]{1,10}\]")


def locate(original: str, masked: str, terms: list[str], *, ctx: int = 60) -> dict[str, list[dict]]:
    """→ {단어: [{before, mark, after}]} — before/after 는 **가린 글** 기준(다른 개인정보도 가려진 상태).

    수집 목록에 없는 치환(구조적 PII 등)은 다음 고정 텍스트로 재동기화해 건너뛴다. 정렬이 어긋나면
    거기까지만(부분 결과) — 틀린 자리를 내놓느니 비워 둔다.
    """
    cand = sorted({t for t in terms if t}, key=len, reverse=True)
    out: dict[str, list[dict]] = {}
    i = j = 0
    n, m = len(original), len(masked)
    while i < n and j < m:
        if masked[j] == "[":
            mm = _PH_RE.match(masked, j)
            if mm and not original.startswith(mm.group(0), i):
                ph = mm.group(0)
                term = next((t for t in cand if original.startswith(t, i)), None)
                if term is None:
                    nxt = masked[mm.end():mm.end() + 12]
                    cut = nxt.find("[")
                    nxt = nxt[:cut] if cut >= 0 else nxt
                    if not nxt:
                        break
                    k = original.find(nxt, i + 1)
                    if k < 0:
                        break
                    i = k
                else:
                    out.setdefault(term, []).append({
                        "before": ("…" if mm.start() > ctx else "") + masked[max(0, mm.start() - ctx):mm.start()],
                        "mark": ph,
                        "after": masked[mm.end():mm.end() + ctx] + ("…" if m > mm.end() + ctx else ""),
                    })
                    i += len(term)
                j = mm.end()
                continue
        if original[i] == masked[j]:
            i += 1
            j += 1
            continue
        break
    return out
