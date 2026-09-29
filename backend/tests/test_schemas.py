"""Citation/Step 타입드 스키마 — 런타임은 dict(동작 보존) + producers shape 정합."""
from __future__ import annotations


def test_typeddict_is_dict_at_runtime():
    from src.schemas import Citation, Step
    c: Citation = {
        "id": "cite_web_x", "number": 1, "source_kind": "web",
        "title": "t", "snippet": "s", "status": "active", "verified": True,
    }
    s: Step = {"id": "s_1", "status": "running"}
    assert isinstance(c, dict) and isinstance(s, dict)
    assert c["number"] == 1            # 접근부 무변경(dict)


def test_web_citation_conforms(monkeypatch):
    from src.tools.citations import extract_web_citation
    c = extract_web_citation(
        {"url": "https://www.mfds.go.kr/x", "title": "광고", "content": "본문"}, 3)
    for key in ("id", "number", "source_kind", "title", "snippet", "status", "verified"):
        assert key in c
    assert c["number"] == 3 and c["source_kind"] == "web"


def test_step_producers_conform():
    from src.steps import step_done, step_error, step_start
    sid, start = step_start("법령 검색", tool_name="qdrant_search")
    assert start["status"] == "running" and start["tool_name"] == "qdrant_search"
    assert start["id"] == sid

    done = step_done(sid, output_preview="3건")
    assert done["status"] == "done" and done["id"] == sid

    err = step_error(sid, message="일시 실패")
    assert err["status"] == "error" and err["error_message"] == "일시 실패"
