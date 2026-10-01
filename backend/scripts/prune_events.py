"""이벤트 보존정리 — 개인정보처리방침 §3 이행 (2026-08-03).

`events` 는 성격이 섞인 테이블이라 한 가지 기간으로 자를 수 없다. 세 부류로 나눈다.

1. **내용 이벤트** (`user_question`·`rag_search`·`claim_audit` …)
   payload 에 사용자 질문·검색어·주장 문장이 들어간다(PII 마스킹본이지만 대화
   내용 그 자체). 대화 기록과 같은 기간(기본 90일)에 **삭제**한다.

2. **지표 이벤트** (`llm_call`·`report_quality`·`quota_blocked` …)
   payload 는 토큰·비용·소요시간 뿐이고 내용이 없다. 기간이 지나면 식별자
   (user_id·thread_id·message_id)만 **비식별화**하고 행은 남긴다 — 지우면
   비용 추이·품질 이력이 통째로 사라지는데, 그 이력은 개인을 식별하지 않고도
   성립한다. 방침의 "통계 목적" 취지와도 맞다.

3. **증빙 이벤트** (`legal_consent`·`erasure_request`)
   동의·삭제요구 이행 증명 — 「개인정보 보호법」 제28조의8·제36조 관련.
   **건드리지 않는다**(방침 표: "이행 증명에 필요한 기간").

env:
  EVENT_CONTENT_RETENTION_DAYS=90   내용 이벤트 보존(기본 CHAT_RETENTION_DAYS 와 동일)
  EVENT_METRIC_RETENTION_DAYS=90    지표 이벤트 비식별화 시점
  PRUNE_APPLY=1                     실제 적용(미설정 = DRY_RUN 미리보기)

사용:
  python scripts/prune_events.py                 # 미리보기
  PRUNE_APPLY=1 python scripts/prune_events.py   # 실제 적용

medi-cron 컨테이너가 일 1회 실행(docker-compose).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

# 내용이 담긴 이벤트 — 기간 경과 시 삭제.
CONTENT_TYPES = (
    "user_question",      # 질문 원문(마스킹본)
    "rag_search",         # 검색 질의어 + 히트 법령
    "claim_audit",        # 답변에서 뽑은 주장 문장
    "user_feedback",      # 자유 코멘트(사용자 작성 텍스트)
    "citation_report",    # 인용 신고 사유(사용자 작성)
    "unverified_contact",  # 연락처 추정 입력 기록
    "url_enforced",       # 강제로 교정·제거된 URL 원본(답변 파생 내용)
    # IRB/DRB 판정 로그 — 입력 스니펫(마스킹본) 포함이라 내용 분류(삭제권 정합).
    # 골든셋으로 쓰려면 보존기간 내 주기 export (rulepack_version 포함).
    "skill_verdict",
    # 탈퇴 사유(사용자 자유 입력) — 분류 누락으로 user_id 채 영구 잔존하던 것
    # (2026-08-11 발견 — emit 이 변수형(WITHDRAW_EVENT)이라 게이트 테스트가 놓침).
    # 탈퇴 상태 자체는 users.deleted_at 이 정본이라 이벤트는 90d 후 삭제 무해.
    "account_withdraw",
    # PII 오탐 신고(사용자가 직접 타이핑한 단어 포함) — 개선리스트의 정본은
    # app_settings 'pii_terms' 라 이벤트는 이력용. 기간 경과 시 삭제 무해.
    "pii_report",
    # 열거 커버리지 감사(2026-08-21) — missing 에 질문 유래 항목 제목(마스킹본)
    # 이 실리므로 내용 분류. 빈도 관측 후 개입 여부 결정용 — 기간 경과 삭제 무해.
    "enum_coverage",
    # 서류 화면 문제 신고(2026-08-27) — 사유·코멘트가 내용이라 CONTENT.
    "doc_report",
)

# 지표만 있는 이벤트 — 기간 경과 시 식별자만 제거하고 집계는 보존.
METRIC_TYPES = (
    "llm_call",
    "report_quality",
    "quality_regression",  # 골든셋 야간 회귀 요약(질문은 내장 고정셋 — 사용자 내용 아님)
    "report_download",
    # 보고서 완료 메일 발송 결과(2026-08-21) — payload 는 ok/error 유형명만
    # (수신 주소 비적재). /admin/reports 발송 상태 조인용.
    "report_email",
    "quota_blocked",
    # 서류 초안 기입 관측(2026-08-24) — 항목명(서식 유래)·건수만, 기입 값 비적재.
    "doc_fill",
    # 식별자 대조 감사(2026-09-17) — payload 는 서식·별표 번호 라벨과 건수뿐
    # (법령 식별자 — 사용자 작성 내용 아님). 빈도 추이를 보존한다.
    "identifier_audit",
    "feedback",           # 👍/👎 등급(코멘트는 user_feedback 쪽)
    "model_ab",
    # 사용자 요청 보고서 삭제(2026-08-27) — payload 는 kind 만. 삭제 빈도 관측용.
    "report_deleted",
    # 진행 중 보고서 사용자 중단(2026-09-02) — payload 없음, 빈도 관측용.
    "report_cancelled",
    "monitor_report",   # 고객사 리포트 발송 결과(건수·성패). 고객사명은 싣지 않는다
    "pathway",          # 규제 경로 분해 산출 요약(단계 수·서식/기한 보유율). 본문 미포함
)

# 증빙 — 절대 건드리지 않는다(감사추적).
AUDIT_TYPES = ("legal_consent", "erasure_request")


def _days(key: str, default: int) -> int:
    try:
        return max(1, int((os.getenv(key) or "").strip() or str(default)))
    except ValueError:
        return default


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def main() -> int:
    from src.persistence import get_events_repo

    apply = (os.getenv("PRUNE_APPLY") or "").strip() == "1"
    content_days = _days("EVENT_CONTENT_RETENTION_DAYS",
                         _days("CHAT_RETENTION_DAYS", 90))
    metric_days = _days("EVENT_METRIC_RETENTION_DAYS", 90)
    c_cut, m_cut = _cutoff(content_days), _cutoff(metric_days)
    repo = get_events_repo()

    for name in ("count_older_than", "delete_older_than", "anonymize_older_than"):
        if not hasattr(repo, name):
            print(f"[prune-events] repo 에 {name} 미구현 — 건너뜀")
            return 0

    n_content = repo.count_older_than(cutoff_iso=c_cut, types=CONTENT_TYPES)
    n_metric = repo.count_older_than(cutoff_iso=m_cut, types=METRIC_TYPES)
    print(f"[prune-events] 내용 {content_days}d(cutoff={c_cut[:10]}) 대상 {n_content}건 "
          f"· 지표 {metric_days}d 대상 {n_metric}건 · apply={apply}")
    print(f"[prune-events] 증빙 보존(삭제 안 함): {', '.join(AUDIT_TYPES)}")

    if not apply:
        print("[prune-events] DRY_RUN — 적용 안 함. 실제 적용: PRUNE_APPLY=1")
        return 0

    deleted = repo.delete_older_than(cutoff_iso=c_cut, types=CONTENT_TYPES)
    anon = repo.anonymize_older_than(cutoff_iso=m_cut, types=METRIC_TYPES)
    print(f"[prune-events] 삭제 {deleted}건 · 비식별화 {anon}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
