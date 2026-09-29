"""대화 검색 결과의 매칭 발췌(2026-08-16).

배경: `/chat/search` 는 thread 제목만 돌려줬다 — "의료기기 GMP …" 처럼 비슷한
제목이 여러 개면 어느 대화인지 고를 수 없어 검색이 사실상 무용했다. 어디가
걸렸는지 보여줘야 결과가 쓸모 있다.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.persistence.threads_repo import SqliteThreadsRepo, match_excerpt


# ── 발췌 헬퍼(순수) ────────────────────────────────────────────────────────

def test_excerpt_centers_on_match_with_ellipsis():
    text = "가" * 100 + "GMP 부적합" + "나" * 100
    out = match_excerpt(text, "GMP")
    assert "GMP 부적합" in out
    assert out.startswith("…") and out.endswith("…")
    assert len(out) < 120  # 원문 전체가 아니라 주변만


def test_excerpt_head_when_no_match():
    out = match_excerpt("의료기기 허가 절차 안내", "존재하지않는말")
    assert out.startswith("의료기기 허가")


def test_excerpt_no_leading_ellipsis_at_start():
    out = match_excerpt("GMP 심사 기준은 다음과 같습니다", "GMP")
    assert not out.startswith("…")


def test_excerpt_case_insensitive_and_whitespace_collapsed():
    out = match_excerpt("절차는\n\n  gmp   심사를 포함", "GMP")
    assert "gmp 심사를" in out


def test_excerpt_empty_content():
    assert match_excerpt("", "GMP") == ""


# ── 리포지토리 통합 ────────────────────────────────────────────────────────

@pytest.fixture()
def repo(tmp_path):
    return SqliteThreadsRepo(str(tmp_path / "t.db"))


def _seed(repo, thread_id: str, user_id: str, title: str, msgs: list):
    repo.ensure_thread(thread_id, user_id=user_id)
    repo.append_messages(thread_id, msgs)
    repo.set_title(thread_id, title)


def test_search_returns_match_snippet(repo):
    _seed(repo, "t1", "u1", "의료기기 GMP 문의", [
        HumanMessage(content="GMP 부적합 판정을 받으면 어떻게 하나요"),
        AIMessage(content="재신청 절차는 다음과 같습니다"),
    ])
    rows = repo.search_messages("u1", "부적합")
    assert len(rows) == 1
    assert "부적합" in rows[0]["match_snippet"]


def test_snippet_distinguishes_similar_titles(repo):
    """같은 제목 두 대화 — 발췌가 달라야 사용자가 고를 수 있다."""
    _seed(repo, "t1", "u1", "의료기기 허가", [
        HumanMessage(content="2등급 인증 서류가 궁금합니다")])
    _seed(repo, "t2", "u1", "의료기기 허가", [
        HumanMessage(content="3등급 허가 서류는 무엇인가요")])
    rows = repo.search_messages("u1", "서류")
    snippets = {r["id"]: r["match_snippet"] for r in rows}
    assert len(rows) == 2
    assert snippets["t1"] != snippets["t2"]
    assert "2등급" in snippets["t1"] and "3등급" in snippets["t2"]


def test_search_scoped_to_owner(repo):
    _seed(repo, "t1", "u1", "내 대화", [HumanMessage(content="GMP 심사")])
    _seed(repo, "t2", "u2", "남의 대화", [HumanMessage(content="GMP 심사")])
    rows = repo.search_messages("u1", "GMP")
    assert [r["id"] for r in rows] == ["t1"]


def test_tool_message_content_not_searched(repo):
    """도구 메시지(검색된 법령 원문)는 대상 아님 — 2자 질의에 전부 매치되던 회귀."""
    from langchain_core.messages import ToolMessage

    _seed(repo, "t1", "u1", "대화", [
        HumanMessage(content="등급이 궁금해요"),
        ToolMessage(content="제6조 제조업의 허가 …", tool_call_id="x"),
    ])
    assert repo.search_messages("u1", "제조업의") == []


def test_no_results_has_no_snippet_key_error(repo):
    assert repo.search_messages("u1", "없는말") == []
