"""report_pipeline (#26) — 결정적 조각 단위 테스트.

extract_report_context(순수) / decompose_queries(LLM 1회·stub) /
gather_for_report(run_* stub — 병렬·dedup·부분실패·타임아웃).
asyncio.run 으로 호출(플러그인 무의존).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from src import report_pipeline as RP
from src.tools.search import SearchError


# ── extract_report_context (순수) ──
def test_extract_context_last_qa_and_citations():
    state = {
        "messages": [
            {"type": "human", "content": "의료기기 허가 절차?"},
            {"type": "ai", "content": "허가는 …[1]"},
            {"type": "human", "content": "보고서 만들어줘"},
            {"type": "ai", "content": "아래 버튼을 눌러주세요"},
        ],
        "steps": [
            {"id": "s1", "citations": [{"id": "c1", "title": "의료기기법"}]},
            {"id": "s2", "citations": [{"id": "c1", "title": "의료기기법"},
                                       {"id": "c2", "title": "시행규칙"}]},
        ],
    }
    ctx = RP.extract_report_context(state)
    assert ctx["user_query"] == "보고서 만들어줘"
    assert ctx["provisional_answer"] == "아래 버튼을 눌러주세요"
    assert [c["id"] for c in ctx["accumulated_citations"]] == ["c1", "c2"]  # dedup


def test_extract_context_empty():
    ctx = RP.extract_report_context({})
    assert ctx["user_query"] == "" and ctx["accumulated_citations"] == []


# ── decompose_queries (LLM 1회 stub) ──
class _StubLLM:
    def __init__(self, content):
        self._c = content

    async def ainvoke(self, prompt, config=None):
        return type("R", (), {"content": self._c})()

    async def astream(self, prompt, config=None):
        # writer 는 astream(prompt, {"tags": [...]}). 단일 chunk 로 시뮬레이션
        # — synthesize_and_persist 가 섹션 제목만 emit, 누적 본문은 동일.
        yield type("C", (), {"content": self._c})()


def test_decompose_parses_json_array():
    out = asyncio.run(RP.decompose_queries(
        "의료기기 허가", "잠정답",
        model=_StubLLM('["허가 절차 법령", "GMP 요건", "최근 개정"]')))
    assert out == ["허가 절차 법령", "GMP 요건", "최근 개정"]


def test_decompose_bad_json_fallback_single():
    out = asyncio.run(RP.decompose_queries(
        "의료기기 허가", "", model=_StubLLM("쓸데없는 텍스트")))
    assert out == ["의료기기 허가"]


def test_decompose_empty_query():
    assert asyncio.run(RP.decompose_queries("", "", model=_StubLLM("[]"))) == []


def test_decompose_caps_max(monkeypatch):
    monkeypatch.setattr(RP, "MAX_QUERIES", 2)
    out = asyncio.run(RP.decompose_queries(
        "q", "", model=_StubLLM('["a","b","c","d"]')))
    assert out == ["a", "b"]


# ── gather_for_report (run_* stub — 병렬·dedup·부분실패·타임아웃) ──
def _web_built(ids):
    return [({"url": f"u{i}"}, {"id": i, "source_kind": "web"}) for i in ids]


class _Core:
    def __init__(self, ids):
        self.built = [(i, object(), {"id": i, "source_kind": "rag"})
                      for i in ids]


def test_gather_parallel_dedup_ok(monkeypatch):
    monkeypatch.setattr(RP, "_REPORT_GUIDE_TOP_K", 0)
    monkeypatch.setattr(RP, "run_tavily",
                        lambda q: _web_built(["w1", "w1", "w2"]))
    monkeypatch.setattr(RP, "run_qdrant", lambda q, top_k=None, target_types=None: _Core(["r1", "r2"]))
    g = asyncio.run(RP.gather_for_report(["q1", "q2"]))
    # 쿼리 2개 × 각 web/rag, 같은 id 는 dedup.
    assert {c["id"] for c in g["web"]} == {"w1", "w2"}
    assert {c["id"] for c in g["rag"]} == {"r1", "r2"}
    assert g["web_ok"] and g["rag_ok"]


def test_gather_partial_web_fails_rag_ok(monkeypatch):
    monkeypatch.setattr(RP, "_REPORT_GUIDE_TOP_K", 0)
    def _boom(q):
        raise SearchError("no tavily key")
    monkeypatch.setattr(RP, "run_tavily", _boom)
    monkeypatch.setattr(RP, "run_qdrant", lambda q, top_k=None, target_types=None: _Core(["r1"]))
    g = asyncio.run(RP.gather_for_report(["q"]))
    assert g["web"] == [] and g["web_ok"] is False
    assert {c["id"] for c in g["rag"]} == {"r1"} and g["rag_ok"] is True


def test_gather_per_source_timeout(monkeypatch):
    monkeypatch.setattr(RP, "_REPORT_GUIDE_TOP_K", 0)
    def _slow(q):
        time.sleep(0.5)
        return _web_built(["w"])
    monkeypatch.setattr(RP, "run_tavily", _slow)
    monkeypatch.setattr(RP, "run_qdrant", lambda q, top_k=None, target_types=None: _Core(["r1"]))
    g = asyncio.run(RP.gather_for_report(
        ["q"], per_source_timeout_s=0.05, deadline_s=5))
    assert g["web"] == [] and g["web_ok"] is False   # 타임아웃 → 빈 결과
    assert g["rag_ok"] is True                        # rag 는 정상


def test_gather_budget_cap(monkeypatch):
    monkeypatch.setattr(RP, "_REPORT_GUIDE_TOP_K", 0)
    monkeypatch.setattr(RP, "MAX_CITATIONS_PER_KIND", 3)
    monkeypatch.setattr(
        RP, "run_qdrant",
        lambda q, top_k=None, target_types=None: _Core([f"r{i}" for i in range(10)]))
    monkeypatch.setattr(RP, "run_tavily", lambda q: [])
    g = asyncio.run(RP.gather_for_report(["q"]))
    assert len(g["rag"]) == 3  # 예산컷


# ── #27 synthesize_and_persist + numbering ──
def test_number_citations_rag_first_dedup():
    web = [{"id": "w1"}, {"id": "w2"}]
    rag = [{"id": "r1"}, {"id": "r1"}, {"id": "r2"}]
    out = RP._number_citations(web, rag)
    assert [(c["id"], c["number"]) for c in out] == [
        ("r1", 1), ("r2", 2), ("w1", 3), ("w2", 4)]  # rag 먼저·dedup·연번


def test_synthesize_and_persist_success(monkeypatch):
    captured = {}

    def _fake_persist(*, path, body, state, ctx=None, citations=None):
        captured["path"] = path
        captured["body"] = body
        captured["cite_steps"] = [s for s in state["steps"]
                                  if s.get("id") == "report_synth"]
        return ("rep_99", "blob://x")
    import src.tools.reports as RPT
    monkeypatch.setattr(RPT, "_persist_report", _fake_persist)

    payload = {
        "queries": ["q1"],
        "web_results": [{"id": "w1", "title": "동향"}],
        "rag_results": [{"id": "r1", "title": "의료기기법"}],
        "conversation_context": {"user_query": "허가 절차"},
    }
    # writer 출력에 '## 개요' 섹션 포함 → overview 로 발췌돼야.
    body_md = ("# 종합 보고서\n\n## 개요\n사전심의 의무 [1]. 위반 시 처벌 [2].\n\n"
               "## 핵심 결론\n...본문...\n\n## References\n[1] ...")
    rid, overview, used = asyncio.run(RP.synthesize_and_persist(
        payload, {"steps": []}, {"configurable": {}},
        model=_StubLLM(body_md)))
    assert rid == "rep_99"
    assert captured["path"] == "/final_report.md"
    assert "## 개요" in captured["body"]
    # overview = '## 개요' 섹션 본문, 다음 '##' 직전까지.
    assert "사전심의 의무 [1]" in overview
    assert "위반 시 처벌 [2]" in overview
    assert "핵심 결론" not in overview        # 다음 섹션은 안 들어감
    assert "## 개요" not in overview          # 헤더는 빠짐
    # used_citations 반환 — 노드가 완료 step 에 붙여 개요 [N] 클릭 가능하게.
    assert [(c["id"], c["number"]) for c in used] == [("r1", 1), ("w1", 2)]
    # 결정적 번호 citation 이 합성 done step 으로 주입됨(persist 코어가 메타 기록).
    cs = captured["cite_steps"][0]["citations"]
    assert [(c["id"], c["number"]) for c in cs] == [("r1", 1), ("w1", 2)]


def test_synthesize_revise_pass_replaces_draft(monkeypatch):
    # 이 테스트는 **비평·개정 패스**의 호출 수를 검증한다 — 섹션 분할
    # 작성(기본 ON)은 writer 호출을 N배로 만들므로 단발 모드로 고정.
    monkeypatch.setenv("REPORT_SECTIONED", "0")
    """REPORT_REVISE_ENABLE=1 → 초안 astream + 비평 ainvoke + 개정 astream,
    최종 저장 본문은 개정본. 어느 단계 실패해도 초안 유지(별도 검증)."""
    import src.tools.reports as RPT
    captured = {}

    def _fake_persist(*, path, body, state, ctx=None, citations=None):
        captured["body"] = body
        return ("rpt_rev", "blob://x")
    monkeypatch.setattr(RPT, "_persist_report", _fake_persist)
    monkeypatch.setenv("REPORT_REVISE_ENABLE", "1")

    class SeqLLM:
        def __init__(self):
            self.astream_n = 0
            self.ainvoke_n = 0

        async def ainvoke(self, prompt, config=None):
            self.ainvoke_n += 1
            # 비평 — 근거 없는 주장 지적(→ 개정 트리거)
            return type("R", (), {"content": "- [2] 근거 없이 단정. 보강 필요."})()

        async def astream(self, prompt, config=None):
            self.astream_n += 1
            text = (
                "## 개요\n초안 결론 [1].\n\n## 근거\n간략 [1].\n"
                if self.astream_n == 1 else
                "## 개요\n개정된 결론입니다 [1].\n\n## 근거\n구체 보강 [1] [2].\n"
            )
            yield type("C", (), {"content": text})()

    llm = SeqLLM()
    payload = {
        "queries": ["q1"],
        "web_results": [{"id": "w1", "title": "동향"}],
        "rag_results": [{"id": "r1", "title": "의료기기법"}],
        "conversation_context": {"user_query": "허가 절차"},
    }
    rid, overview, _used = asyncio.run(RP.synthesize_and_persist(
        payload, {"steps": []}, {"configurable": {}}, model=llm))

    assert llm.astream_n == 2 and llm.ainvoke_n == 1   # 초안+개정 스트림, 비평 1
    assert "개정된 결론" in captured["body"]            # 개정본이 저장됨
    assert "개정된 결론" in overview                     # 개요도 개정본에서 발췌
    assert rid == "rpt_rev"


def test_synthesize_revise_disabled_keeps_draft(monkeypatch):
    # 이 테스트는 **비평·개정 패스**의 호출 수를 검증한다 — 섹션 분할
    # 작성(기본 ON)은 writer 호출을 N배로 만들므로 단발 모드로 고정.
    monkeypatch.setenv("REPORT_SECTIONED", "0")
    """REPORT_REVISE_ENABLE=0 → 개정 패스 미실행(초안 1회 스트림만)."""
    import src.tools.reports as RPT
    captured = {}
    monkeypatch.setattr(RPT, "_persist_report",
                        lambda **k: (captured.update(body=k["body"]), ("r", "u"))[1])
    monkeypatch.setenv("REPORT_REVISE_ENABLE", "0")

    class CountLLM(_StubLLM):
        def __init__(self, c):
            super().__init__(c)
            self.astream_n = 0

        async def astream(self, prompt, config=None):
            self.astream_n += 1
            async for x in super().astream(prompt, config):
                yield x

    llm = CountLLM("## 개요\n초안만 [1].\n")
    payload = {"web_results": [], "rag_results": [{"id": "r1", "title": "법"}],
               "conversation_context": {}}
    asyncio.run(RP.synthesize_and_persist(
        payload, {"steps": []}, {"configurable": {}}, model=llm))
    assert llm.astream_n == 1                           # 개정 패스 없음
    assert "초안만" in captured["body"]


def test_synthesize_empty_body_returns_none(monkeypatch):
    import src.tools.reports as RPT
    monkeypatch.setattr(RPT, "_persist_report",
                        lambda **k: (_ for _ in ()).throw(AssertionError("호출 X")))
    rid, overview, used = asyncio.run(RP.synthesize_and_persist(
        {"web_results": [], "rag_results": [], "conversation_context": {}},
        {"steps": []}, {"configurable": {}}, model=_StubLLM("   ")))
    assert rid is None and overview == "" and used == []


def test_extract_overview_picks_section():
    md = ("# 보고서\n\n## 개요\n첫 문장. 둘째 [1].\n\n## 결론\n다른 섹션\n")
    out = RP._extract_overview(md)
    assert "첫 문장" in out and "둘째 [1]" in out
    assert "다른 섹션" not in out


def test_extract_overview_fallback_first_paragraph():
    """'## 개요' 가 없으면 H1 이후 첫 단락 폴백."""
    md = "# 보고서\n\n핵심 한 줄 [1].\n\n## 다른 섹션\n본문"
    out = RP._extract_overview(md)
    assert "핵심 한 줄 [1]" in out
    assert "다른 섹션" not in out


def test_extract_overview_empty_input():
    assert RP._extract_overview("") == ""
    assert RP._extract_overview("# 비어있는 보고서") == ""


def test_finalize_splits_combined_markers():
    """gemma 실측 quirk: '[1, 4]' 결합 마커 → 개별 [N] 분해 후 정상 재번호."""
    body = "형사처벌과 행정처분 병과 [1, 4]. 단독 인용 [4]."
    cites = [
        {"id": "c1", "number": 1, "title": "T1"},
        {"id": "c4", "number": 4, "title": "T4"},
    ]
    final, used = RP._finalize_citations(body, cites)
    assert "[1] [2]." in final              # 1→1, 4→2 (등장 순)
    assert "단독 인용 [2]." in final
    assert "[1, 4]" not in final
    assert [(c["id"], c["number"]) for c in used] == [("c1", 1), ("c4", 2)]


# ── _finalize_citations: 사용분만 순서대로 재번호 + References 부착 ──
def test_finalize_renumbers_in_appearance_order():
    """등장 순서로 [1],[2],[3].. 재할당. 사용 안 한 citation 은 References 미등재."""
    body = "본문 A [3]. 본문 B [1]. 다시 A [3]."  # 등장 순: 3 → 1
    cites = [
        {"id": "c1", "number": 1, "title": "T1", "url": "U1"},
        {"id": "c2", "number": 2, "title": "T2", "url": "U2"},
        {"id": "c3", "number": 3, "title": "T3", "url": "U3"},
    ]
    final, used = RP._finalize_citations(body, cites)
    # 본문: 3→1, 1→2 (등장 순)
    assert "본문 A [1]." in final
    assert "본문 B [2]." in final
    assert "다시 A [1]." in final
    # used = c3, c1 (등장 순), 새 번호 1, 2. c2 미등재.
    assert [(c["id"], c["number"]) for c in used] == [("c3", 1), ("c1", 2)]
    # References 자동 부착, 사용분만.
    assert "## References" in final
    assert "[1] T3" in final
    assert "[2] T1" in final
    assert "T2" not in final  # c2 미사용


def test_finalize_strips_orphan_and_writer_refs():
    body = ("핵심 [1]. 환각 [99].\n\n## References\n[1] writer가 만든 거 (X)")
    cites = [{"id": "c1", "number": 1, "title": "T1", "url": "U1"}]
    final, used = RP._finalize_citations(body, cites)
    # [99] orphan 제거, writer 의 References 섹션 절단 → 시스템 References 새로 부착.
    assert "[99]" not in final
    assert "환각 ." in final  # [99] 만 사라지고 자리 자체 남음
    assert "writer가 만든 거" not in final
    assert "## References" in final and "[1] T1" in final
    assert [(c["id"], c["number"]) for c in used] == [("c1", 1)]


def test_finalize_replaces_latex_math_markers():
    """gemma writer 가 섞는 LaTeX 수식 마커($\\rightarrow$ 등) → 유니코드 치환.

    프런트(react-markdown)는 수식 렌더러가 없어 글자 그대로 노출됨
    (e2e 실측 2026-07-25, 보고서당 ~4회)."""
    body = ("승인 $\\rightarrow$ 동의 $\\to$ 수행 [1]. "
            "배율 $\\times$ 및 기준 $ \\geq $ 준수.")
    cites = [{"id": "c1", "number": 1, "title": "T1", "url": "U1"}]
    final, _ = RP._finalize_citations(body, cites)
    assert "승인 → 동의 → 수행" in final
    assert "배율 × 및 기준 ≥ 준수" in final
    assert "$" not in final.split("## References")[0]


def test_finalize_no_citations_no_refs_section():
    body = "본문에 인용 없음."
    final, used = RP._finalize_citations(body, [{"id": "c1", "number": 1, "title": "T"}])
    assert "## References" not in final
    assert used == []


def test_writer_citations_keeps_whole_and_contiguous():
    """회귀: writer 입력 JSON tail 절단으로 citations 배열이 통째 잘려
    번호 매핑이 깨지던 버그. 예산 초과 시 *통째*로만 드롭(mid-array 금지),
    [1..k] 연속 보장. writer 불필요 필드(id/url)는 슬림화로 제거."""
    cites = [
        {"id": "a", "number": 1, "title": "T1", "url": "U1",
         "text": "x" * 1000, "doc_id": "law"},
        {"id": "b", "number": 2, "title": "T2", "text": "y" * 1000},
        {"id": "c", "number": 3, "title": "T3", "text": "z" * 1000},
    ]
    # 예산을 ~2개치로 제한 → 3번째는 통째 드롭.
    out = RP._writer_citations(cites, char_budget=2200)
    assert [c["number"] for c in out] == [1, 2]   # 연속, mid-array 절단 없음
    assert "id" not in out[0] and "url" not in out[0] and "doc_id" not in out[0]
    assert out[0]["text"] == "x" * 1000           # text 보존(근거 대조용)


def test_writer_citations_always_includes_at_least_one():
    """단일 citation 이 예산보다 커도 최소 1개는 포함(빈 입력 방지)."""
    cites = [{"id": "a", "number": 1, "title": "T", "text": "q" * 5000}]
    out = RP._writer_citations(cites, char_budget=100)
    assert len(out) == 1 and out[0]["number"] == 1


def test_finalize_references_are_line_separated_bullets():
    """회귀: References 가 single \\n 으로 붙어 마크다운에서 한 줄로 뭉치던 버그.
    각 항목이 불릿(`- `)으로 줄 분리돼야 함."""
    body = "A [1]. B [2]."
    cites = [
        {"id": "c1", "number": 1, "title": "의료기기법 제24조", "url": "https://x/24"},
        {"id": "c2", "number": 2, "title": "의료법 제57조", "url": "https://x/57"},
    ]
    final, _ = RP._finalize_citations(body, cites)
    assert "- [1] 의료기기법 제24조 (https://x/24)" in final
    assert "- [2] 의료법 제57조 (https://x/57)" in final
    # 두 출처가 같은 줄에 붙지 않음(불릿 줄 분리).
    assert "(https://x/24) - [2]" not in final
    # 헤더와 첫 항목 사이 빈 줄(헤더→리스트 분리).
    assert "## References\n\n- [1]" in final


# ── grounding 검증: 근거 문장 추출 + substring 검증 ──
def test_claim_for_extracts_sentence():
    body = "첫 문장입니다. 사전심의 의무가 있다 [2]. 다음 문장."
    claim = RP._claim_for(body, 2)
    assert "사전심의 의무가 있다 [2]" in claim
    assert "첫 문장입니다" not in claim


def test_ground_citations_verifies_substring():
    body = "광고는 사전심의 의무가 있다 [1]. 위반 시 처벌 [2]."
    cites = [
        # [1]: 원문에 그대로 있는 근거 → verified
        {"id": "c1", "number": 1, "title": "T1",
         "text": "제24조 의료기기 광고는 사전심의 의무가 있다. 기타 ..."},
        # [2]: source 에 없는 환각 quote → verified=False
        {"id": "c2", "number": 2, "title": "T2",
         "text": "전혀 무관한 본문 내용만 있음."},
    ]

    class _Stub:
        async def ainvoke(self, prompt, config=None):
            return type("R", (), {"content": (
                '[{"n":1,"quote":"의료기기 광고는 사전심의 의무가 있다"},'
                '{"n":2,"quote":"위반 시 3년 이하 징역"}]')})()

    out = asyncio.run(RP._ground_citations(body, cites, model=_Stub()))
    by = {c["number"]: c for c in out}
    assert by[1]["verified"] is True
    assert "사전심의 의무가 있다" in by[1]["supporting_quote"]
    # [2] quote 가 source 에 없음 → 환각 → 미검증, quote 미부착
    assert by[2]["verified"] is False
    assert "supporting_quote" not in by[2]


def test_ground_citations_none_means_unverified():
    body = "추론성 문장 [1]."
    cites = [{"id": "c1", "number": 1, "title": "T",
              "text": "관련 원문."}]

    class _Stub:
        async def ainvoke(self, prompt, config=None):
            return type("R", (), {"content": '[{"n":1,"quote":"NONE"}]'})()

    out = asyncio.run(RP._ground_citations(body, cites, model=_Stub()))
    assert out[0]["verified"] is False
    assert "supporting_quote" not in out[0]


def test_ground_citations_no_text_passthrough():
    """text 필드 없는 citation 은 grounding 대상 아님(원본 반환)."""
    cites = [{"id": "c1", "number": 1, "title": "T"}]
    out = asyncio.run(RP._ground_citations("본문 [1].", cites))
    assert out == cites


# ── 재설계보고서 반영(①·④·⑤) — 결정적 검증 조각 ──
def test_unbacked_articles_flags_missing():
    """본문 산문의 조문번호가 수집 근거 어디에도 없으면 flag(F1·F7)."""
    body = "제28조의8 위반 시 제71조에 따라 처벌됩니다. 제24조는 근거 있음."
    cites = [
        {"title": "개인정보 보호법 제28조의8", "text": "국외이전 요건 ..."},
        {"title": "의료기기법", "article": "제24조", "text": "광고 제한 ..."},
    ]
    assert RP._unbacked_articles(body, cites) == ["제71조"]


def test_unbacked_articles_all_backed_empty():
    body = "제24조에 따릅니다."
    cites = [{"title": "T", "text": "제24조 원문"}]
    assert RP._unbacked_articles(body, cites) == []


def test_law_article_pairs_extract_and_skip_generic():
    text = "「의료기기법」 제25조와 개인정보 보호법 제28조의8, 동법 제71조."
    pairs = RP._law_article_pairs(text)
    assert ("의료기기법", "제25조") in pairs
    # 공백 포함 법령명은 마지막 단어로 절단됨("보호법") — 양쪽(본문·근거)이 같은
    # 규칙으로 절단되므로 페어 대조는 일관 동작(한계는 docstring 참조).
    assert ("보호법", "제28조의8") in pairs
    assert not any(l == "동법" for l, _a in pairs)  # 지시대명사 제외


def test_unbacked_articles_law_pair_mismatch():
    """조번호는 수집됐지만 다른 법령 소속 — 법령 귀속 오류 flag(F7)."""
    body = "의료법 제92조에 따라 과태료가 부과됩니다."
    cites = [{"title": "의료기기법 제92조", "text": "의료기기법 제92조 원문 ..."}]
    flags = RP._unbacked_articles(body, cites)
    assert len(flags) == 1 and flags[0].startswith("의료법 제92조")
    assert "다른 법령 소속" in flags[0]


def test_unbacked_articles_pair_backed_ok():
    body = "의료기기법 제92조에 따라 부과됩니다."
    cites = [{"title": "의료기기법 제92조", "text": "..."}]
    assert RP._unbacked_articles(body, cites) == []


def test_unbacked_articles_number_backed_no_pair_info_passes():
    """근거에 페어 정보가 없으면(제목에 법령명 無) 오탐 방지 위해 통과."""
    body = "의료법 제92조에 따라 부과됩니다."
    cites = [{"title": "조문", "text": "제92조 내용 ..."}]
    assert RP._unbacked_articles(body, cites) == []


def test_gather_tier_tagging_and_upgrade(monkeypatch):
    monkeypatch.setattr(RP, "_REPORT_GUIDE_TOP_K", 0)
    """⑥ web(T3) 언급 조문이 rag 에 없으면 표적 재검색으로 T1 승격."""
    rag_queries = []

    def _tav(q):
        return [({"url": "u", "content": "의료기기법 제25조에 따라 사전심의 의무"},
                 {"id": "w1", "source_kind": "web", "title": "블로그"})]

    def _qd(q, top_k=None, target_types=None):
        rag_queries.append((q, tuple(target_types or [])))
        return _Core(["r1"] if len(rag_queries) == 1 else ["r_up"])

    monkeypatch.setattr(RP, "run_tavily", _tav)
    monkeypatch.setattr(RP, "run_qdrant", _qd)
    g = asyncio.run(RP.gather_for_report(["q"]))
    assert any("의료기기법 제25조" in q for q, _tt in rag_queries)   # 승격 표적 검색
    assert {c["id"] for c in g["rag"]} == {"r1", "r_up"}        # 승격분 합류
    assert all(c.get("tier") == "T1" for c in g["rag"])
    assert all(c.get("tier") == "T3" for c in g["web"])


def test_gather_tier_upgrade_skips_when_backed(monkeypatch):
    monkeypatch.setattr(RP, "_REPORT_GUIDE_TOP_K", 0)
    """rag 가 이미 그 (법령, 조문)을 가지면 승격 재검색 안 함."""
    rag_queries = []

    def _tav(q):
        return [({"url": "u", "content": "의료기기법 제25조 관련 동향"},
                 {"id": "w1", "source_kind": "web"})]

    class _CoreTitled:
        def __init__(self):
            self.built = [("r1", object(),
                           {"id": "r1", "source_kind": "rag",
                            "title": "의료기기법 제25조"})]

    def _qd(q, top_k=None, target_types=None):
        rag_queries.append(q)
        return _CoreTitled()

    monkeypatch.setattr(RP, "run_tavily", _tav)
    monkeypatch.setattr(RP, "run_qdrant", _qd)
    asyncio.run(RP.gather_for_report(["q"]))
    assert rag_queries == ["q"]  # 표적 재검색 없음


def test_verify_rendered_cleans_broken_markers():
    """Gate D 축소판 — 빈 마커 `[]`·orphan 잔여 `" ."` 정리(F6)."""
    body = "환각 주장 [] 남음 .\n정상 문장 [1]."
    fixed, _n = RP._verify_rendered(body)
    assert "[]" not in fixed
    assert "남음." in fixed          # " ." → "."
    assert "정상 문장 [1]." in fixed  # 정상 인용은 불변


def test_verify_rendered_normalizes_duplicate_headers():
    """gemma e2e 실측 quirk: '## ## 개요' → '## 개요' 정규화(개요 추출 의존)."""
    body = "# 제목\n\n## ## 개요\n결론 [1].\n\n### ## 근거\n상세."
    fixed, _n = RP._verify_rendered(body)
    assert "\n## 개요\n" in fixed
    assert "### 근거" in fixed
    assert "## ##" not in fixed
    # 정규화 후 개요 추출이 동작해야 한다.
    assert "결론 [1]" in RP._extract_overview(fixed)


def test_preverify_only_checks_cited_numbers():
    """본문에 인용 안 된 citation 은 선행 grounding 대상에서 제외(허위 지적 방지)."""
    seen = {}

    async def _fake_ground(body, cites, **kw):
        seen["numbers"] = [c["number"] for c in cites]
        return [dict(c, verified=False) for c in cites]

    import unittest.mock as mock
    with mock.patch.object(RP, "_ground_citations", _fake_ground):
        findings, stats = asyncio.run(RP._preverify_findings(
            "본문 주장 [2].",
            [{"number": 1, "text": "원문A"}, {"number": 2, "text": "원문B"}]))
    assert seen["numbers"] == [2]           # [1] 은 미인용 — 검사 제외
    assert stats["draft_unverified"] == 1   # [2] 만 카운트
    assert any("[2]" in f for f in findings)


def test_verify_rendered_counts_uncited_numeric():
    """무인용 수치·제재 주장 건수 반환(품질 메트릭·report_quality 이벤트용)."""
    body = "위반 시 5천만원 이하의 벌금이 부과됩니다.\n근거 있는 벌칙 3년 [1].\n"
    _fixed, n = RP._verify_rendered(body)
    assert n == 1  # [1] 달린 문장은 제외, 무인용 벌금 문장만


def test_stamp_as_of_after_h1():
    body = "# 보고서 제목\n\n## 개요\n본문."
    out = RP._stamp_as_of(body)
    lines = out.splitlines()
    assert lines[0] == "# 보고서 제목"
    assert lines[2].startswith("> 작성 기준일: ")
    assert "## 개요" in out


def test_stamp_as_of_no_h1_prepends():
    out = RP._stamp_as_of("## 개요\n본문.")
    assert out.startswith("> 작성 기준일: ")
    assert "## 개요" in out


def test_critique_extra_findings_force_revise():
    """LLM 비평이 '중대한 문제 없음'이어도 결정적 지적(extra_findings)이 있으면
    개정 패스가 실행되고 지적이 프롬프트에 포함된다(반영 ① 배선)."""
    seen = {}

    class _LLM:
        async def ainvoke(self, prompt, config=None):
            return type("R", (), {"content": "중대한 문제 없음"})()

        async def astream(self, prompt, config=None):
            seen["revise_prompt"] = prompt
            yield type("C", (), {"content": "개정된 본문 [1]."})()

    out, _extra = asyncio.run(RP._critique_and_revise(
        _LLM(), "초안 [1].", [{"number": 1, "title": "T"}], lambda *a: None,
        extra_findings=["근거 불일치 인용 [1]: 수정 필요"]))
    assert out == "개정된 본문 [1]."
    assert "근거 불일치 인용 [1]" in seen["revise_prompt"]


def test_critique_no_findings_no_issue_keeps_draft():
    """비평 무지적 + 결정적 지적 없음 → 개정 미실행, 초안 유지."""
    class _LLM:
        async def ainvoke(self, prompt, config=None):
            return type("R", (), {"content": "중대한 문제 없음"})()

        async def astream(self, prompt, config=None):
            raise AssertionError("개정 호출되면 안 됨")
            yield  # pragma: no cover

    out, _extra = asyncio.run(RP._critique_and_revise(
        _LLM(), "초안 [1].", [], lambda *a: None, extra_findings=[]))
    assert out == "초안 [1]."


def test_synthesize_stamps_as_of_date(monkeypatch):
    """합성 경로에서 작성 기준일이 시스템 결정적으로 부착된다(F9)."""
    import src.tools.reports as RPT
    captured = {}

    def _fake_persist(*, path, body, state, ctx=None, citations=None):
        captured["body"] = body
        return ("r1", "u")
    monkeypatch.setattr(RPT, "_persist_report", _fake_persist)
    monkeypatch.setenv("REPORT_REVISE_ENABLE", "0")
    payload = {"web_results": [], "rag_results": [{"id": "r1", "title": "법"}],
               "conversation_context": {}}
    asyncio.run(RP.synthesize_and_persist(
        payload, {"steps": []}, {"configurable": {}},
        model=_StubLLM("# 제목\n\n## 개요\n결론 [1].\n")))
    assert "> 작성 기준일: " in captured["body"]


def test_gather_guide_lane_and_t3(monkeypatch):
    """가이드라인 보충 레인(2026-07-24) — 쿼리별 guide 단독 검색 + T3 태깅."""
    monkeypatch.setattr(RP, "_REPORT_GUIDE_TOP_K", 6)
    monkeypatch.setattr(RP, "_REPORT_TIER_UPGRADE_MAX", 0)
    calls = []

    class _CoreG:
        def __init__(self, ids, cat=None):
            self.built = [(i, object(),
                           ({"id": i, "source_kind": "rag", "doc_category": cat}
                            if cat else {"id": i, "source_kind": "rag"}))
                          for i in ids]

    def _qd(q, top_k=None, target_types=None):
        calls.append(tuple(target_types or []))
        if target_types == ["guide"]:
            return _CoreG(["g1"], cat="가이드라인")
        return _CoreG(["r1"])

    monkeypatch.setattr(RP, "run_tavily", lambda q: [])
    monkeypatch.setattr(RP, "run_qdrant", _qd)
    g = asyncio.run(RP.gather_for_report(["q"]))
    assert ("guide",) in calls and () in calls        # 법령 + guide 별도 콜
    by = {c["id"]: c for c in g["rag"]}
    assert by["r1"]["tier"] == "T1"
    assert by["g1"]["tier"] == "T3"                    # 가이드라인 T1 오태깅 방지


# ── 검수 지적 표적 재수집 1회 루프 (2026-08-27) ──────────────────────


def test_gap_queries_parses_and_caps(monkeypatch):
    """지적 → 검색 질의: JSON 배열만 신뢰, 최대 3개, 길이 검증."""
    class _M:
        async def ainvoke(self, prompt, cfg=None):
            class _R:
                content = '["의료기기법 제6조 결격사유", "품질책임자 자격 기준", "x", "네번째 질의", "다섯번째"]'
            return _R()

    qs = asyncio.run(RP._gap_queries("- [3] 근거 없음", model=_M()))
    assert qs == ["의료기기법 제6조 결격사유", "품질책임자 자격 기준", "네번째 질의"][:3]
    assert len(qs) <= 3
    # 깨진 출력 = 빈 목록(루프 생략, 개악 없음)
    class _Bad:
        async def ainvoke(self, prompt, cfg=None):
            class _R:
                content = "JSON 아님"
            return _R()
    assert asyncio.run(RP._gap_queries("지적", model=_Bad())) == []


def test_regather_dedups_and_numbers_continue(monkeypatch):
    """재수집 근거는 기존과 dedup 되고 번호가 이어진다(마스터 합류 전제)."""
    existing = [{"id": "c1", "number": 1, "article_key": "AK1"},
                {"id": "c2", "number": 2}]

    async def _fake_gather(kind, q, timeout, *a, **k):
        return "rag", [
            {"id": "c1", "article_key": "AK1", "title": "중복"},      # dedup
            {"id": "c9", "article_key": "AK9", "title": "신규", "text": "본문"},
        ]

    monkeypatch.setattr(RP, "_gather_one", _fake_gather)
    out = asyncio.run(RP._regather_for_findings(["질의"], existing))
    assert [c["id"] for c in out] == ["c9"]
    assert out[0]["number"] == 3  # 기존 최대 번호(2) 다음


def test_regather_disabled_paths(monkeypatch):
    """allow_regather=False(테스트 주입 경로)·env=0 이면 외부 콜 없이 종전 동작."""
    monkeypatch.setenv("REPORT_REGATHER_ENABLE", "0")
    assert RP._regather_enabled() is False
    monkeypatch.delenv("REPORT_REGATHER_ENABLE", raising=False)
    assert RP._regather_enabled() is True


def test_critique_regather_feeds_revise(monkeypatch):
    """ISSUES → 재수집 → 개정 입력에 새 번호가 실리고 반환 튜플로 나온다."""
    calls = {"n": 0}

    class _LLM:  # 1콜=비평(ISSUES), 2콜=개정
        async def ainvoke(self, prompt, cfg=None):
            calls["n"] += 1

            class _R:
                content = ("VERDICT: ISSUES\n- [1] 근거 없음"
                           if calls["n"] == 1 else "")
            return _R()

    async def _fake_stream(llm, prompt, cfg=None):
        # 개정 프롬프트에 보강 근거 안내·새 citation 이 실렸는지 검증
        assert "[보강 근거 추가]" in prompt and '"number": 7' in prompt
        return "개정본 [7]"

    async def _fake_gap(critique, model=None):
        return ["보강 질의"]

    async def _fake_regather(queries, all_citations):
        return [{"id": "new1", "number": 7, "title": "보강", "text": "t"}]

    monkeypatch.setattr(RP, "_accumulate_stream", _fake_stream)
    monkeypatch.setattr(RP, "_gap_queries", _fake_gap)
    monkeypatch.setattr(RP, "_regather_for_findings", _fake_regather)
    body, extra = asyncio.run(RP._critique_and_revise(
        _LLM(), "초안 [1]", [{"number": 1, "title": "기존", "text": "t"}],
        lambda *a: None, critique_llm=_LLM.__call__ and _LLM(),
        all_citations=[{"id": "c1", "number": 1}],
        allow_regather=True,
    ))
    assert body == "개정본 [7]"
    assert extra and extra[0]["number"] == 7
