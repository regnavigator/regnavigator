"""골든셋 야간 품질 회귀 — 대표 질문을 실제 /chat 루프로 돌려 자동 채점.

왜: 프롬프트·검색·모델을 계속 바꾸는데, 트래픽이 적어 사용자 신호로는 품질
회귀를 못 잡는다(피드백 2건/10일). 같은 질문을 매일 같은 조건으로 돌리면
오늘-어제의 차이 = 우리가 바꾼 것의 효과다. 수동 벤치(bench_chatloop.py)의
자동화 — 세션에 사람이 없어도 회귀가 다음 날 아침 알림으로 잡힌다.

사용:
    PYTHONUTF8=1 python scripts/quality_regression.py --now          # 즉시 1회
    python scripts/quality_regression.py --at 03:00                  # KST 03:00 까지 대기 후 1회
    python scripts/quality_regression.py --now --limit 3             # 부분 실행(스모크)

운영: medi-cron 컨테이너의 전용 루프가 `--at 03:00` 으로 상시 실행
(docker-compose.yml). 03시 선택: 새벽 4시대 DGX 데이터 갱신 재구동(writer
재기동)과 낮 시간 GPU 경합을 모두 피한다.

채점(질문당):
    total_s / ttft_s        응답 시간(구간)
    citations / verified    인용 수·grounding 검증 통과 수(trailing steps 반영)
    next_steps              <next_steps> 마커 계약 준수
    claim_flagged           무인용 사실 audit 의 contradicted+unverified(events 조회)
    error                   턴 실패

결과는 events(quality_regression, user_id 없음=익명 — 관리자 통계 scope=real
에서 자동 제외)로 적재하고, 직전 실행과 비교해 임계 하락 시 ops 알림
(send_ops_alert — OPS_ALERT_WEBHOOK_URL 미설정이면 WARNING 로그).

⚠️ 골든 질문은 이 파일에 내장한다 — data/ 는 .dockerignore 라 이미지에 없다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

_log = logging.getLogger("quality_regression")

_KST = timezone(timedelta(hours=9))

# ── 골든 질문 — 사용목적 8종(규제검색·인허가·AI의료기기·임상·R&D·보고서·
#    정부과제·사업화) 커버 + 실사용 질문 패턴. 바꾸면 이력 비교가 끊기므로
#    추가는 뒤에 append, 삭제는 지양(질문 텍스트가 사실상 지표 키다).
#    expect_search=False 는 검색 없이 처리돼야 하는 발화(라우팅 회귀 감시용)
#    — 인용 지표 분모에서 제외한다.
GOLDEN_QUESTIONS: list[dict] = [
    {"q": "의료기기 임상시험을 하려면 식약처 승인 절차가 어떻게 되나요?"},
    {"q": "2등급 의료기기 인증 절차와 필요한 서류를 알려주세요."},
    {"q": "AI 기반 영상판독 소프트웨어는 의료기기 몇 등급으로 분류되나요?"},
    {"q": "소프트웨어 의료기기(SaMD)의 변경허가 대상이 되는 변경은 무엇인가요?"},
    {"q": "신의료기술평가 절차와 평가 유예 제도에 대해 설명해주세요."},
    {"q": "의료기기 광고 사전심의 대상과 절차가 궁금합니다."},
    {"q": "의료기기 GMP 심사의 종류와 준비해야 할 서류는요?"},
    {"q": "체외진단의료기기의 성능평가 요건을 알려주세요."},
    {"q": "임상시험 대상자 동의서에 반드시 포함해야 할 사항은 무엇인가요?"},
    {"q": "의료기기 부작용이 발생하면 언제까지 누구에게 보고해야 하나요?"},
    {"q": "연구자주도 임상시험과 의뢰자주도 임상시험의 규제상 차이는요?"},
    {"q": "혁신의료기기로 지정받으려면 어떤 요건이 필요하고 혜택은 무엇인가요?"},
    {"q": "의료기기 수입업 허가는 어떻게 받나요?"},
    {"q": "디지털치료기기(DTx) 허가를 받으려면 어떤 임상 자료가 필요한가요?"},
    {"q": "의료기기 판매업 신고 없이 온라인으로 판매하면 어떤 처벌을 받나요?"},
    # 평가셋(data/eval_queries.json, 라벨 보유 114 중)에서 보강(2026-10-03) — 16문항은
    # LLM 비결정성 노이즈 대비 표본이 너무 작아 verified_rate 한 문항이 ±6%p 흔들렸다.
    {"q": "1단계 허가 및 2단계 평가에 필요한 **'다기관 독립 검증 데이터'**를 확보할 때, 병원 간 데이터 공유 과정에서 개인정보보호법(가명정보 처리) 및 의료법상 발생할 수 있는 법적 리스크와 해결 방안은 무엇인가요?"},
    {"q": "AI 기반 영상 진단 보조 소프트웨어를 병원(B2B)에 판매하려 할 때, 식약처 인허가(의료기기 등급) 취득 후 신의료기술평가를 거쳐 수가(급여/비급여)를 적용받기까지의 단계별 규제 허들과 대응 전략은 무엇인가요?"},
    {"q": "AI 진단 소프트웨어를 병원(EHR/PACS)에 무료로 설치해주고 진단 건당 수수료를 받는 **'Pay-per-use BM'**이나 대여/구독형 모델을 적용할 때, 의료법상 환자 유인·알선이나 리베이트 규제에 저촉될 가능성이 있나요?"},
    {"q": "[이름] 대표님 존함이 [이름] [생년월일]생이신데, 대표자 명의로 의료기기 제조업 허가를 신청할 때 결격사유 조회는 어떻게 이뤄지나요?"},
    {"q": "구급차 개조 후 보건소에 제출할 신고서 양식과 작성 방법을 알려줘"},
    {"q": "그중 생물학적 안전성 자료는 어떤 경우에 면제되나요?"},
    {"q": "내시경을 이용한 의료기기 제품을 만들어서 품목허가를 받고 싶은데. 어떤 프로세스로 진행하는 것이 좋을까?"},
    {"q": "디지털치료기기 안전성 성능 평가 방법"},
    {"q": "마약류 취급자 허가 절차 안내"},
    {"q": "비대면진료 규정 위반 시 행정처분과 벌칙"},
    {"q": "비대면진료 중개매체 신고 요건과 절차"},
    {"q": "소프트웨어 의료기기(SaMD) 허가는 어떻게 받나요"},
    {"q": "식약처에 다기관 가명정보 결합 승인을 신청할 때 필요한 서류와 절차는?"},
    {"q": "신의료기술평가에서 임상적 근거가 부족해 유예될 리스크를 줄이기 위해, **'혁신의료기술 평가 트랙'**이나 **'혁신의료기기 통합심사 제도'**를 활용해 선진입(선사용)하는 전략의 실익과 조건은 무엇인가요?"},
    {"q": "안녕하세요 저는 [이름] [전화번호] 입니다. 체외진단의료기기 허가 절차 알려주세요."},
    {"q": "원격/비대면 진료에 관한 우리나라와 주요국의 주요 규제를 비교해서 표로 작성해줘."},
    {"q": "의료 데이터 가명처리의 기술적 기준은 뭔가요?"},
    {"q": "의료기기 2등급 제조허가 신청 시 필요한 기술문서 항목이 뭔가요?"},
    {"q": "의료기기 공급자가 리베이트로 적발된 구체적 사건이 있나요?"},
    {"q": "의료기기 광고 사전심의 위반 시 처벌은?"},
    {"q": "의료기기 광고에서 [주소] 금지되는 표현 예시가 뭐야?"},
    {"q": "의료기기 멸균 밸리데이션 기준"},
    {"q": "의료기기 부작용 보고 의무와 기한 알려줘"},
    {"q": "의료기기 생물학적 안전성 시험 항목"},
    {"q": "의료기기 수수료의 '시장 상당가격'을 어떻게 입증하나요?"},
    {"q": "의료기기 임상시험 승인절차 알려줘"},
    {"q": "의료기기 재심사 대상과 기간은 어떻게 되나요"},
    {"q": "의료기기 제조업 허가 신청 절차를 알려주세요"},
    {"q": "의료기기 제조허가 절차와 필요 [이름] 뭔가요?"},
    {"q": "의료기기 품목허가란?"},
    {"q": "의료기기 허가 절차와 필요한 서류가 뭔가요?"},
    {"q": "의료법상 리베이트 판단 기준과 적발 사례는?"},
    {"q": "의약품 품목허가 신청에 필요한 자료"},
    {"q": "임상시험 IRB 심사 시 개인정보 보호 항목에서 확인해야 할 사항은?"},
    # 라우팅 감시 — 규제 질의가 아니면 검색·인용 없이 정중히 처리돼야 한다.
    {"q": "안녕하세요, 뭘 도와줄 수 있나요?", "expect_search": False},
]


# ── 순수 함수(테스트 대상) ─────────────────────────────────────────────────

def aggregate(rows: list[dict]) -> dict:
    """질문별 채점 rows → 실행 1회 요약 지표."""
    ok = [r for r in rows if not r.get("error")]
    reg = [r for r in ok if r.get("expect_search", True)]
    cites = sum(r.get("citations", 0) for r in reg)
    verified = sum(r.get("verified", 0) for r in reg)
    totals = [r["total_s"] for r in ok if r.get("total_s") is not None]
    dones = [r["done_s"] for r in ok if r.get("done_s") is not None]
    ttfts = [r["ttft_s"] for r in ok if r.get("ttft_s") is not None]
    return {
        "n": len(rows),
        "n_regulatory": len(reg),
        "errors": len(rows) - len(ok),
        "error_questions": [r["q"][:40] for r in rows if r.get("error")],
        # 체감 지표 — 회귀 판정은 이 값으로 한다(후처리 시간 미포함).
        "avg_done_s": round(sum(dones) / len(dones), 2) if dones else None,
        "max_done_s": round(max(dones), 2) if dones else None,
        "avg_total_s": round(sum(totals) / len(totals), 2) if totals else None,
        "max_total_s": round(max(totals), 2) if totals else None,
        "avg_ttft_s": round(sum(ttfts) / len(ttfts), 2) if ttfts else None,
        "citations": cites,
        "verified": verified,
        "verified_rate": round(verified / cites, 3) if cites else None,
        "no_citation_questions": [
            r["q"][:40] for r in reg if r.get("citations", 0) == 0],
        "next_steps_rate": round(
            sum(1 for r in ok if r.get("next_steps")) / len(ok), 3) if ok else None,
        "claim_total": sum(r.get("claim_total", 0) for r in ok),
        "claim_flagged": sum(r.get("claim_flagged", 0) for r in ok),
    }


def detect_regression(cur: dict, prev: Optional[dict]) -> list[str]:
    """전일 대비 임계 하락 목록(비면 정상). 임계는 노이즈(모델 비결정성·GPU
    경합)에 안 울리게 보수적으로 — 절대 악화 + 상대 악화를 함께 요구한다."""
    issues: list[str] = []
    if cur.get("errors"):
        issues.append(
            f"턴 실패 {cur['errors']}건: {', '.join(cur.get('error_questions', []))}")
    vr, pvr = cur.get("verified_rate"), (prev or {}).get("verified_rate")
    if vr is not None and pvr is not None and vr < pvr - 0.10 and vr < 0.85:
        issues.append(f"인용 검증률 하락 {pvr:.0%} → {vr:.0%}")
    if cur.get("no_citation_questions") and cur.get("citations", 0) == 0:
        issues.append("규제 질문 전체가 무인용 — 검색 경로 이상 의심")
    # 지연은 **체감 완료(done)** 로만 판정한다. total(후처리 포함)이 늘어난 건
    # 사용자 체감 악화가 아니므로 알리지 않는다 — 섞으면 오알림이 난다.
    # done 이 양쪽에 없을 때만(구 실행분 비교) total 로 폴백.
    key, label = (("avg_done_s", "응답시간")
                  if cur.get("avg_done_s") is not None
                  and (prev or {}).get("avg_done_s") is not None
                  else ("avg_total_s", "응답시간(후처리 포함)"))
    at, pat = cur.get(key), (prev or {}).get(key)
    if at is not None and pat is not None and at > pat * 1.5 and at > 25:
        issues.append(f"평균 {label} 악화 {pat:.1f}s → {at:.1f}s")
    ns, pns = cur.get("next_steps_rate"), (prev or {}).get("next_steps_rate")
    if ns is not None and ns < 0.8 and (pns is None or ns < pns):
        issues.append(f"next_steps 계약 준수율 {ns:.0%}")
    # 환각 신호(2026-10-03) — 종전엔 claim_flagged 를 **집계만** 하고 임계가 없었다.
    # 환각이 2배가 돼도 알림 0. 절대 임계(flag 비율 15%)는 전일과 무관하게 울린다 —
    # 매일 9%p 씩 나빠지면 상대 임계만으로는 영원히 안 울리는 drift 를 막는다.
    ct, cf = cur.get("claim_total") or 0, cur.get("claim_flagged") or 0
    if ct >= 10:
        rate = cf / ct
        if rate > 0.15:
            issues.append(f"무인용 사실 미지지율 {rate:.0%} ({cf}/{ct}) — 환각 의심")
    # 무인용 규제 질문 — 종전엔 **전체 합이 0** 일 때만. 16문항 중 15개가 무인용이
    # 돼도 1개만 인용 있으면 조용했다. 비율로 본다.
    nq = cur.get("no_citation_questions") or []
    n_reg = cur.get("n_regulatory") or 0
    if n_reg and len(nq) / n_reg > 0.2:
        issues.append(f"무인용 규제 질문 {len(nq)}/{n_reg} — 검색 경로 이상 의심")
    return issues


def next_run_delay_s(now_kst: datetime, at: str) -> float:
    """다음 `at`(HH:MM, KST)까지 초 — 항상 미래(지났으면 내일)."""
    hh, mm = (int(x) for x in at.split(":"))
    target = now_kst.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now_kst:
        target += timedelta(days=1)
    return (target - now_kst).total_seconds()


# ── 실행 여부 판정 — "바뀐 날만 돈다" (2026-09-18) ─────────────────────────
#
# 실측(9/5~9/18): 골든셋 1회 = LLM 호출 ~110회·입력 ~110만 토큰 ≈ 1 USD. 매일 돌아서
# 내부 트래픽이 전체 LLM 비용의 80%(14일 13.2 / 16.5 USD)였다. 이 회귀의 목적은
# "오늘-어제의 차이 = 우리가 바꾼 것의 효과"이므로, 아무것도 안 바꾼 날은 돌 이유가 없다.
# 배포 지문(커밋·프롬프트 버전·모델)이 직전 전체 실행과 같으면 건너뛰고, 검색 데이터
# 변동(일일 ETL) 감시용으로 QREG_MAX_AGE_DAYS(기본 7)일에 한 번은 강제로 돈다.

def build_fingerprint() -> dict:
    """무엇이 바뀌면 다시 재야 하는가 — 백엔드 커밋·프롬프트 버전·채팅 모델."""
    import os

    from src.prompts.supervisor import PROMPT_VERSION
    return {
        "git_sha": (os.getenv("APP_GIT_SHA") or "unknown").strip() or "unknown",
        "prompt_version": PROMPT_VERSION,
        "chat_model": (os.getenv("CHAT_MODEL") or os.getenv("SUPERVISOR_MODEL") or "").strip(),
    }


def should_run(fp: dict, prev: Optional[dict], prev_ts: Optional[datetime],
               now: datetime, *, max_age_days: int = 7) -> tuple[bool, str]:
    """(실행 여부, 사유). `prev` = 직전 **전체** 실행의 payload, `prev_ts` = 그 시각(UTC).

    모르면 돈다 — 지문을 알 수 없거나(git_sha=unknown) 직전 기록이 없으면 건너뛰지 않는다.
    건너뛰어서 회귀를 놓치는 쪽이 1 USD 보다 비싸다.
    """
    if not prev or not prev_ts:
        return True, "직전 전체 실행 기록 없음"
    prev_fp = prev.get("fingerprint") or {}
    if not prev_fp:
        return True, "직전 실행에 지문 없음(도입 전 기록)"
    if fp.get("git_sha") in (None, "", "unknown"):
        return True, "배포 커밋을 알 수 없음"
    changed = [k for k in ("git_sha", "prompt_version", "chat_model")
               if (fp.get(k) or "") != (prev_fp.get(k) or "")]
    if changed:
        return True, "변경: " + ", ".join(
            f"{k} {prev_fp.get(k) or '-'}→{fp.get(k) or '-'}" for k in changed)
    age_days = (now - prev_ts).total_seconds() / 86400
    if age_days >= max_age_days:
        return True, f"변경 없음이지만 마지막 실행 후 {age_days:.1f}일(≥{max_age_days}일) — 주기 점검"
    return False, f"변경 없음 · 마지막 실행 {age_days:.1f}일 전(<{max_age_days}일)"


def _last_full_run() -> tuple[Optional[dict], Optional[datetime]]:
    """직전 **전체** 실행(--limit 부분 실행 제외)의 (payload, 시각)."""
    from src.persistence import get_events_repo
    try:
        for ev in get_events_repo().list_by_type("quality_regression", limit=10):
            if not ev.payload_json:
                continue
            payload = json.loads(ev.payload_json)
            if payload.get("partial"):
                continue
            ts = ev.ts
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return payload, ts
    except Exception:
        _log.debug("직전 전체 실행 조회 실패", exc_info=True)
    return None, None


# ── 실행 ───────────────────────────────────────────────────────────────────

async def _run_question(spec: dict, thread_id: str) -> dict:
    from src.chat_loop import run_chat_turn

    row: dict = {"q": spec["q"], "expect_search": spec.get("expect_search", True)}
    t0 = time.monotonic()
    ttft = None
    done_s = None
    body = ""
    steps: list[dict] = []
    error = None
    try:
        async for ev in run_chat_turn(thread_id, spec["q"]):
            et = ev.get("type")
            if et == "token" and ttft is None:
                ttft = time.monotonic() - t0
            elif et == "done":
                # ⚠️ 사용자 체감 완료 시점은 `done` 이다(답변·인용 렌더 확정).
                # 그 뒤 grounding 검증·claim audit 이 비차단으로 더 도는데,
                # 종전엔 스트림 종료까지를 total 로 재서 **체감보다 ~9s 부풀려**
                # 기록됐다(2026-08-19 실측: done 22.7s / 스트림 종료 32.1s).
                done_s = time.monotonic() - t0
                body = ev.get("text") or ""
                steps = ev.get("steps") or []
            elif et == "steps":
                # grounding 검증 배지는 done *뒤* trailing steps 로 온다 —
                # 마지막 스냅샷이 verified 포함 최종본.
                steps = ev.get("steps") or steps
            elif et == "error":
                error = ev.get("message") or "unknown"
    except Exception as e:  # noqa: BLE001 — 한 질문 실패가 실행 전체를 못 죽이게
        error = f"{type(e).__name__}: {e}"

    cites = [c for s in steps for c in (s.get("citations") or [])]
    row.update({
        # done_s = 사용자 체감 완료(주 지표). total_s = 후처리 포함 스트림 종료.
        "done_s": round(done_s, 2) if done_s is not None else None,
        "total_s": round(time.monotonic() - t0, 2),
        "ttft_s": round(ttft, 2) if ttft is not None else None,
        "citations": len(cites),
        "verified": sum(1 for c in cites if c.get("verified")),
        "next_steps": "<next_steps>" in body,
        "error": error,
    })
    return row


def _attach_claim_audit(rows: list[dict], thread_ids: list[str]) -> None:
    """턴이 남긴 claim_audit 이벤트(스레드별)를 rows 에 합류 — audit 은
    run_chat_turn 내부에서 done 뒤 인라인 실행되므로 스트림 종료 시 이미 적재됨."""
    from src.persistence import get_events_repo

    repo = get_events_repo()
    for row, tid in zip(rows, thread_ids):
        try:
            evs = [e for e in repo.list_for_thread(tid)
                   if e.event_type == "claim_audit"]
            if evs and evs[-1].payload_json:
                p = json.loads(evs[-1].payload_json)
                row["claim_total"] = int(p.get("total") or 0)
                row["claim_flagged"] = (
                    int(p.get("contradicted") or 0) + int(p.get("unverified") or 0))
        except Exception:
            _log.debug("claim_audit 조회 실패 thread=%s", tid, exc_info=True)


async def run_once(limit: Optional[int] = None) -> dict:
    from src.persistence import get_events_repo
    from src.persistence.events_repo import Event

    date_key = datetime.now(_KST).strftime("%Y%m%d_%H%M")
    specs = GOLDEN_QUESTIONS[:limit] if limit else GOLDEN_QUESTIONS
    rows: list[dict] = []
    thread_ids: list[str] = []

    # 순차 실행 — 동시 실행은 프로세스 로컬 LLM RPS 캡·검색 백프레셔에 눌려
    # 지연 지표를 왜곡한다. 순차라야 "질문 1개의 체감 시간"이 나온다.
    for i, spec in enumerate(specs):
        tid = f"qreg_{date_key}_{i:02d}"
        thread_ids.append(tid)
        print(f"[{i + 1}/{len(specs)}] {spec['q'][:50]}", flush=True)
        rows.append(await _run_question(spec, tid))

    _attach_claim_audit(rows, thread_ids)
    summary = aggregate(rows)

    repo = get_events_repo()
    # 비교 기준은 직전 **전체** 실행 — 부분 실행(--limit)과 비교하면 지표가 어긋난다.
    prev_payload, _ = _last_full_run()
    prev = (prev_payload or {}).get("summary")

    issues = detect_regression(summary, prev)
    repo.emit(Event(
        id="", ts="", event_type="quality_regression",
        payload_json=json.dumps(
            {"summary": summary, "issues": issues, "rows": rows,
             "fingerprint": build_fingerprint(), "partial": bool(limit)},
            ensure_ascii=False),
    ))

    print("\n=== 요약 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if issues:
        print("\n⚠️ 회귀 의심:")
        for it in issues:
            print(f"  - {it}")
        from src.observability.alerts import send_ops_alert
        send_ops_alert(
            "품질 회귀 감지 (골든셋 야간 실행)",
            "\n".join(issues),
            dedup_key=f"quality_regression_{date_key[:8]}")
    else:
        print("\n회귀 없음.")
    return summary


def main() -> int:
    # ⚠️ 모듈 최상단 load_dotenv 금지 — 테스트가 이 모듈(순수 함수)을 import
    # 하는 순간 .env 가 pytest 전체에 주입돼 무관한 테스트가 403 으로 무너진다
    # (2026-08-16 실측 32건). 실행 시점에만 로드한다.
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--now", action="store_true", help="즉시 1회 실행")
    g.add_argument("--at", metavar="HH:MM",
                   help="다음 KST HH:MM 까지 대기 후 1회 실행(운영 루프용)")
    ap.add_argument("--limit", type=int, default=None,
                    help="앞에서 N개 질문만(스모크)")
    ap.add_argument("--force", action="store_true",
                    help="--at 에서도 변경 여부와 무관하게 실행")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.at:
        delay = next_run_delay_s(datetime.now(_KST), args.at)
        print(f"[qreg] 다음 실행 KST {args.at} — {delay / 3600:.1f}h 대기", flush=True)
        time.sleep(delay)
        # 예약 실행만 건너뛰기 대상 — `--now` 는 사람이 지금 보려는 것이라 항상 돈다.
        import os
        always = (os.getenv("QREG_ALWAYS") or "").strip() == "1"
        if not (args.force or always):
            try:
                max_age = int((os.getenv("QREG_MAX_AGE_DAYS") or "7").strip() or "7")
            except ValueError:
                max_age = 7
            fp = build_fingerprint()
            prev_payload, prev_ts = _last_full_run()
            run, why = should_run(fp, prev_payload, prev_ts,
                                  datetime.now(timezone.utc), max_age_days=max_age)
            print(f"[qreg] {'실행' if run else '건너뜀'} — {why}", flush=True)
            if not run:
                try:
                    from src.persistence import get_events_repo
                    from src.persistence.events_repo import Event
                    get_events_repo().emit(Event(
                        id="", ts="", event_type="quality_regression_skipped",
                        payload_json=json.dumps({"reason": why, "fingerprint": fp},
                                                ensure_ascii=False)))
                except Exception:
                    _log.debug("skip 이벤트 적재 실패", exc_info=True)
                return 0
    asyncio.run(run_once(limit=args.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
