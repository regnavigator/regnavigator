"""system prompt 모음 — supervisor(채팅).

(rag_analyst/web_analyst 는 서브에이전트 은퇴와 함께 삭제 — ADR-0001 Phase 5.
 writer 는 구 langgraph 서브에이전트 프롬프트로 legacy/ 이전 후 2026-09-29 삭제(git history) —
 현행 보고서 writer 는 src/report_pipeline._RECONCILE_INSTRUCTIONS 사용.)
본문은 각 모듈에. 버전 라벨은 모듈 상단 PROMPT_VERSION.
"""

from .supervisor import SUPERVISOR_PROMPT

__all__ = [
    "SUPERVISOR_PROMPT",
]
