"""법적 고지 — 정본 + 결정적 부착 + /legal 노출.

핵심: 면책 문구를 **LLM 이 쓰지 않는다**(표현 흔들림·누락 방지). References 와 같이
시스템이 결정적으로 부착한다.
"""
from __future__ import annotations

import pytest


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "test-secret-32-bytes-min-padding-xx")
    yield


def test_public_endpoints_bypass_auth():
    """회귀: `/legal`·`/load` 는 인증 켜진 prod 에서도 공개여야 한다.

    (dev 는 NEXTAUTH_SECRET 미설정이라 인증이 꺼져 있어 이 버그가 안 드러났다 —
    실제로 `/load` 가 prod 에서 401 이었다.)
    """
    c = _client()
    for path in ("/legal", "/load", "/healthz", "/readyz"):
        assert c.get(path).status_code != 401, f"{path} 가 인증에 막힘"


def test_legal_endpoint_public_and_complete():
    """프런트가 상시 노출용으로 가져간다(인증 X)."""
    res = _client().get("/legal")
    assert res.status_code == 200
    d = res.json()
    assert d["version"]
    assert "법률자문이 아닙니다" in d["disclaimer_short"]
    assert "## 법적 고지" in d["disclaimer_report"]
    # 국외이전 고지는 개인정보보호법상 필수 — key_points 에 반드시 있어야.
    assert any("국외" in k for k in d["key_points"])


def test_report_disclaimer_has_required_clauses():
    """규제 상담 면책의 필수 요소 4가지."""
    from src.legal import DISCLAIMER_REPORT
    assert "법률자문 또는 관할기관의 유권해석이 아닙니다" in DISCLAIMER_REPORT  # 성격
    assert "시행일·경과규정" in DISCLAIMER_REPORT                                # 개정
    assert "관할기관" in DISCLAIMER_REPORT and "전문가" in DISCLAIMER_REPORT     # 최종확인
    assert "책임을 지지 않습니다" in DISCLAIMER_REPORT                            # 책임제한


def test_report_body_gets_disclaimer_even_if_llm_omits_it():
    """writer 가 면책을 안 써도 시스템이 붙인다(누락 불가)."""
    from src.legal import DISCLAIMER_REPORT
    from src.report_pipeline import _finalize_citations

    body = "# 제목\n\n## 개요\n본문 [1]\n\n## References\n[1] LLM이 임의로 쓴 refs"
    b, _ = _finalize_citations(body, [{"id": "c1", "number": 1, "title": "의료기기법"}])
    final = b.rstrip() + "\n" + DISCLAIMER_REPORT
    assert "LLM이 임의로 쓴" not in final       # LLM refs 제거
    assert "## References" in final             # 시스템 refs
    assert "## 법적 고지" in final              # 시스템 면책


def test_writer_prompt_forbids_writing_disclaimer():
    """writer 지시가 '면책·References 를 쓰라'가 아니라 시스템 부착이어야 한다.

    (구 langgraph writer 프롬프트는 legacy/ 이전 후 2026-09-29 삭제(git history) — 현행 writer
    지시는 report_pipeline._RECONCILE_INSTRUCTIONS.)
    """
    from src.report_pipeline import _RECONCILE_INSTRUCTIONS as p
    assert "시스템이 자동 부착" in p   # References 는 시스템 몫
    assert "법적 고지" not in p        # 면책을 쓰라는 지시가 없어야 함


def test_chat_disclaimer_verbatim_in_supervisor_prompt():
    """채팅 면책은 정본 문구를 그대로 쓰도록 지시(임의 변경 금지)."""
    import io
    p = io.open("src/prompts/supervisor.py", encoding="utf-8").read()
    assert "법령은 개정될 수 있으므로 시행일·경과규정을 확인하시고" in p
    assert "임의로 바꾸거나 요약하지 말 것" in p
