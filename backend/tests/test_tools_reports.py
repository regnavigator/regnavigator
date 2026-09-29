"""보고서 저장 보조 유틸 테스트 — _last_ai_text / _file_entry.

(구 `_save`/@tool 래퍼 테스트는 ADR-0001 Phase 5 에서 도구 은퇴와 함께 삭제 —
영속 코어 `_persist_report` 는 report_runner e2e·test_report_pipeline 이 커버.)
"""

from __future__ import annotations

from types import SimpleNamespace

from src.tools.reports import _file_entry, _last_ai_text


def _ai_msg(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="ai", content=text, tool_calls=None)


def test_last_ai_text_string():
    state = {"messages": [_ai_msg("# 보고서 본문\n내용")]}
    assert _last_ai_text(state) == "# 보고서 본문\n내용"


def test_last_ai_text_anthropic_blocks():
    state = {
        "messages": [
            SimpleNamespace(
                type="ai",
                content=[{"type": "text", "text": "첫 줄"},
                         {"type": "text", "text": "둘 줄"}],
                tool_calls=[],
            )
        ]
    }
    assert _last_ai_text(state) == "첫 줄\n둘 줄"


def test_last_ai_text_skips_messages_with_tool_calls():
    """tool_calls 있는 ai 메시지는 *최종* 응답이 아니므로 건너뜀."""
    state = {
        "messages": [
            _ai_msg("최종"),
            SimpleNamespace(type="ai", content="중간",
                            tool_calls=[{"name": "x"}]),
        ]
    }
    assert _last_ai_text(state) == "최종"


def test_last_ai_text_empty_when_no_ai():
    state = {"messages": [SimpleNamespace(type="human", content="질문",
                                          tool_calls=None)]}
    assert _last_ai_text(state) == ""


def test_file_entry_lines_split():
    entry = _file_entry("줄1\n줄2\n줄3")
    assert entry["content"] == ["줄1", "줄2", "줄3"]
    assert entry["is_streaming"] is False
    assert isinstance(entry["created_at"], int)
    assert entry["created_at"] == entry["modified_at"]


def test_file_entry_empty_string():
    entry = _file_entry("")
    assert entry["content"] == []
