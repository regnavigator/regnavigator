"""메시지 유틸 — state.messages 에서 텍스트 추출 (reports·grounding·chat_loop 공용)."""

from __future__ import annotations

from typing import Any


def content_text(content: Any) -> str:
    """메시지 content(str 또는 Anthropic block 리스트) → 평문 텍스트.

    구 `middleware/intent_search._text` 이관(ADR-0001 Phase 5).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def last_ai_text(state: dict) -> str:
    """마지막 AI 답변 텍스트. tool_call 만 있는 중간 메시지는 건너뜀.

    Anthropic-style block list content 는 text 블록만 이어붙인다.
    """
    for msg in reversed((state or {}).get("messages") or []):
        msg_type = getattr(msg, "type", None) or (
            msg.get("type") if isinstance(msg, dict) else None
        )
        if msg_type != "ai":
            continue
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls is None and isinstance(msg, dict):
            tool_calls = msg.get("tool_calls")
        if tool_calls or not content:
            continue
        if isinstance(content, list):
            parts = [b.get("text", "") for b in content if isinstance(b, dict)]
            return "\n".join(p for p in parts if p)
        return str(content)
    return ""


# ---------------------------------------------------------------------------
# 첨부 블록(2026-09-15, 프롬프트 인젝션 보강)
# ---------------------------------------------------------------------------
import re as _re

_ATTACH_BLOCK = _re.compile(r"\n*<attachment\b[^>]*>.*?</attachment>", _re.S | _re.I)
_ATTACH_TAG = _re.compile(r"<(/?)\s*attachment\b", _re.I)


def neutralize_attachment_tags(text: str) -> str:
    """첨부 본문 안의 `<attachment` / `</attachment>` 를 전각 `＜` 로 바꿔 프레임 탈출을 막는다.

    문서에 닫는 태그와 지시문을 넣으면 첨부 블록이 끝난 것처럼 보여 사용자 지시
    자리에 놓이던 구멍. 내용은 보존(전각 부등호), 파서(FE 접기·모델 구분)만 못 속인다.
    """
    return _ATTACH_TAG.sub(lambda m: "＜" + m.group(1) + "attachment", text or "")


def sanitize_attachment_name(name: str) -> str:
    """태그 속성값으로 안전한 파일명 — 부등호·따옴표·개행 제거, 120자."""
    n = _re.sub(r'[<>"\r\n]', " ", str(name or "")).strip()
    return (n or "attachment")[:120]


def strip_attachments(text: str) -> str:
    """`<attachment …>…</attachment>` 블록을 제거한 사용자 질문 텍스트.

    외부로 나가는 검색어(Tavily)는 이 텍스트만 쓴다 — 첨부 전문이 검색어로
    유출되던 경로 차단(2026-09-15).
    """
    return _ATTACH_BLOCK.sub("", text or "").strip()


def attachment_names(text: str) -> list[str]:
    return _re.findall(r'<attachment\s+name="([^"]*)"', text or "", flags=_re.I)
