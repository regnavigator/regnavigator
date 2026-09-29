"""보고서 RAG 인용의 본문(text) 확보 — 발췌 폴백 (2026-08-25).

사고: writer 는 citation 의 `text` 를 보고 [N] 을 단다(_WRITER_CITE_FIELDS).
그런데 openlaw PG 에 없는 코퍼스(admrul_attach = 심평원 hira_board)는
`/articles/bodies` 가 full_text 를 못 줘 `text` 가 통째로 비었고, writer 는
그 인용을 **한 건도 쓰지 않았다** — 급여기준 보고서가 고시·심사지침 대신
뉴스 기사만 인용(실측 2026-08-25, References 4건 전부 웹).

검색 API 가 준 매칭 발췌(snippet)는 실제 원문 조각이므로 근거로 유효하다.
"""
from __future__ import annotations

import pytest

from src import report_pipeline as rp


class _Core:
    def __init__(self, built):
        self.built = built


def _install(monkeypatch, built, bodies):
    monkeypatch.setattr(rp, "_lane_qdrant",
                        lambda q, tk, ctx=None, tts=None: _Core(built))
    import src.retrieval.search_api_client as sac
    monkeypatch.setattr(sac, "fetch_bodies", lambda keys: bodies)


@pytest.mark.asyncio
async def test_uses_full_text_when_available(monkeypatch):
    built = [("k1", {}, {"id": "c1", "snippet": "발췌", "title": "조문"})]
    _install(monkeypatch, built, {"k1": {"full_text": "원문" * 100}})
    kind, out = await rp._gather_one("rag", "q", 5.0)
    assert kind == "rag"
    assert out[0]["text"].startswith("원문")
    assert len(out[0]["text"]) > 10  # 발췌가 아니라 본문


@pytest.mark.asyncio
async def test_falls_back_to_snippet_when_no_body(monkeypatch):
    """admrul_attach 케이스 — 본문 0자여도 인용이 근거를 갖는다."""
    built = [("admrul:hira_board:고시:8#0", {},
              {"id": "c1", "snippet": "관절경 등의 수술에 사용된 치료재료 비용은…",
               "title": "관절경 치료재료 산정방법"})]
    _install(monkeypatch, built, {})          # bodies 미제공
    _kind, out = await rp._gather_one("rag", "q", 5.0)
    assert out[0]["text"].startswith("관절경 등의 수술")


@pytest.mark.asyncio
async def test_no_snippet_no_text(monkeypatch):
    """발췌조차 없으면 text 를 만들지 않는다 — 빈 근거 날조 금지."""
    built = [("k1", {}, {"id": "c1", "title": "제목만"})]
    _install(monkeypatch, built, {})
    _kind, out = await rp._gather_one("rag", "q", 5.0)
    assert "text" not in out[0]


@pytest.mark.asyncio
async def test_text_capped(monkeypatch):
    built = [("k1", {}, {"id": "c1", "snippet": "가" * 9000})]
    _install(monkeypatch, built, {})
    _kind, out = await rp._gather_one("rag", "q", 5.0)
    assert len(out[0]["text"]) <= rp._PER_SOURCE_TEXT_CAP


def test_writer_receives_text_field():
    """계약 고정 — writer 입력 필드에 text 가 있어야 인용이 성립."""
    assert "text" in rp._WRITER_CITE_FIELDS


# ── 메타 인용 = 본문에 실제 쓰인 것만 (2026-08-25) ──────────────────

def test_persist_uses_explicit_citations_over_step_scan(monkeypatch, tmp_path):
    """스레드에 채팅 step 인용이 있어도 메타에는 명시 전달분만 들어간다.

    (종전: state.steps 전수 스캔 → 보고서가 인용하지 않은 채팅 근거가
    사이드바 목록에 섞여 본문보다 근거가 많아 보였다.)
    """
    import os

    from src.persistence import get_blob_store, get_reports_repo
    import src.tools.reports as tr

    os.environ["BLOB_LOCAL_DIR"] = str(tmp_path / "blobs")
    get_blob_store.cache_clear()

    chat_cite = {"id": "cite_doc_chat_1", "number": 1, "title": "채팅이 찾은 근거"}
    used = [{"id": "cite_doc_used_1", "number": 1, "title": "보고서가 쓴 근거"}]
    state = {"steps": [
        {"id": "s_chat", "status": "done", "tool_name": "qdrant_search",
         "citations": [chat_cite]},
    ]}
    out = tr._persist_report(
        path="/final_report.md", body="# 제목\n\n본문", state=state,
        ctx={"thread_id": "t_persist_cites", "run_id": "r1"},
        citations=used)
    assert out
    meta = get_reports_repo().get(out[0])
    import json
    stored = json.loads(meta.citations_json or "[]")
    ids = {c.get("id") for c in stored}
    assert ids == {"cite_doc_used_1"}, ids
