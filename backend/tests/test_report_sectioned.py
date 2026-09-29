"""보고서 섹션 분할 작성 — 분량 확대 (2026-08-25).

단발 writer 는 응답 하나의 자연 길이 한계에 갇힌다(운영 40건 실측: 중앙값
5,995자, 상위는 max_tokens=8000 에 압착). 지시문이 "8,000자 이상"을 요구해도
물리적으로 불가능했다. 길이는 **호출 수**로 늘린다 — 섹션마다 독립 호출.
"""
from __future__ import annotations

import asyncio

import pytest

from src import report_pipeline as rp
from src import report_sections as rs


class _FakeLLM:
    """섹션 프롬프트를 받아 그 섹션만 목표치만큼 써 주는 가짜 writer."""

    def __init__(self, chars_per_section=5000, short_first=False):
        self.astream_n = 0
        self.ainvoke_n = 0
        self.prompts: list[str] = []
        self.chars = chars_per_section
        self.short_first = short_first

    async def ainvoke(self, prompt, config=None):
        self.ainvoke_n += 1
        return type("R", (), {"content": "의료기기 허가 절차 심층 보고서"})()

    async def astream(self, prompt, config=None):
        self.astream_n += 1
        self.prompts.append(prompt)
        name = "섹션"
        for line in prompt.splitlines():
            if line.startswith("[이번 섹션]"):
                name = line.split(".", 1)[-1].strip()
                break
        n = self.chars
        if self.short_first and self.astream_n == 1:
            n = 100  # 목표 미달 → 확장 재호출 유도
        yield type("C", (), {"content": f"## {name}\n" + ("본문 [1]. " * (n // 8))})()


def _payload():
    return {
        "queries": ["q1"],
        "web_results": [{"id": "w1", "title": "동향"}],
        "rag_results": [{"id": "r1", "title": "의료기기법", "text": "원문"}],
        "conversation_context": {"user_query": "허가 절차"},
    }


def _run(llm, monkeypatch, captured):
    def _fake_persist(*, path, body, state, ctx=None, citations=None):
        captured["body"] = body
        return ("rpt_sec", "blob://x")

    monkeypatch.setattr(rp, "_persist_report", _fake_persist, raising=False)
    import src.tools.reports as TR
    monkeypatch.setattr(TR, "_persist_report", _fake_persist)
    monkeypatch.setattr(rp, "_revise_enabled", lambda: False)
    return asyncio.run(rp.synthesize_and_persist(
        _payload(), {"steps": []}, {"configurable": {}}, model=llm))


def test_section_plan_targets_sum(monkeypatch):
    """섹션 목표의 합 = 보고서 목표 분량. 기본값이 현행(6,000자)을 크게 넘어야."""
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "4000")
    specs = rs.section_specs()
    total = sum(s["target"] for s in specs)
    assert len(specs) == 5
    assert total >= 18000, total
    # 개요는 채팅 발췌용이라 짧게, 근거가 가장 두껍게
    assert specs[0]["name"] == "개요" and specs[0]["target"] < 1000
    assert max(specs, key=lambda s: s["target"])["name"] == "근거"


def test_sectioned_writes_each_section(monkeypatch):
    """섹션 수만큼 writer 호출 + 제목 1콜, 본문에 5섹션 헤더가 한 번씩."""
    monkeypatch.setenv("REPORT_SECTIONED", "1")
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "1000")
    captured: dict = {}
    llm = _FakeLLM(chars_per_section=2000)
    _run(llm, monkeypatch, captured)
    assert llm.astream_n == 5, llm.astream_n
    assert llm.ainvoke_n == 1                      # 제목 생성
    body = captured["body"]
    for name in ("개요", "핵심 결론", "근거", "실무 액션", "리스크/후속"):
        assert body.count(f"## {name}") == 1, (name, body.count(f"## {name}"))
    assert body.startswith("# ")                   # H1 조립됨


def test_sectioned_body_is_much_longer(monkeypatch):
    """분량 목적 자체 검증 — 단발(≈1콜 분량)보다 배수로 길다."""
    monkeypatch.setenv("REPORT_SECTIONED", "1")
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "1000")
    captured: dict = {}
    _run(_FakeLLM(chars_per_section=3000), monkeypatch, captured)
    assert len(captured["body"]) > 3000 * 3


def test_short_section_triggers_expand(monkeypatch):
    """목표 80% 미달 섹션은 1회 확장 재호출(레포 설계에 없던 길이 검증)."""
    monkeypatch.setenv("REPORT_SECTIONED", "1")
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "2000")
    captured: dict = {}
    llm = _FakeLLM(chars_per_section=3000, short_first=True)
    _run(llm, monkeypatch, captured)
    assert llm.astream_n == 6                       # 5섹션 + 확장 1
    assert any("[확장 지시]" in p for p in llm.prompts)


def test_section_prompt_carries_context(monkeypatch):
    """응집성 재료 — 전체 구성·목표 분량·직전 섹션 꼬리가 프롬프트에 있어야."""
    monkeypatch.setenv("REPORT_SECTIONED", "1")
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "1000")
    captured: dict = {}
    llm = _FakeLLM(chars_per_section=2000)
    _run(llm, monkeypatch, captured)
    first, second = llm.prompts[0], llm.prompts[1]
    assert "[보고서 전체 구성]" in first
    assert "목표 분량" in first
    assert "[직전 섹션 마지막 부분" not in first     # 첫 섹션엔 없음
    assert "[직전 섹션 마지막 부분" in second        # 이후엔 이어붙음
    assert "한 섹션만" in first                      # 범위 고정


def test_disabled_falls_back_to_single(monkeypatch):
    """노브로 구 경로 복귀 — 회귀 시 즉시 되돌릴 수 있어야."""
    monkeypatch.setenv("REPORT_SECTIONED", "0")
    captured: dict = {}
    llm = _FakeLLM(chars_per_section=2000)
    _run(llm, monkeypatch, captured)
    assert llm.astream_n == 1


def test_document_draft_keeps_single(monkeypatch):
    """서식 초안은 5섹션 계약이 아니므로 섹션 모드를 타면 안 된다."""
    monkeypatch.setenv("REPORT_SECTIONED", "1")
    captured: dict = {}
    llm = _FakeLLM(chars_per_section=2000)

    def _fake_persist(*, path, body, state, ctx=None, citations=None):
        captured["body"] = body
        return ("rpt_doc", "blob://x")

    import src.tools.reports as TR
    monkeypatch.setattr(TR, "_persist_report", _fake_persist)
    monkeypatch.setattr(rp, "_revise_enabled", lambda: False)
    p = _payload()
    p["purpose"] = "document_draft"
    asyncio.run(rp.synthesize_and_persist(
        p, {"steps": []}, {"configurable": {}}, model=llm))
    assert llm.astream_n == 1


def test_strip_stray_headers():
    """모델이 다음 섹션까지 앞서 쓰면 `## ` 중복 — 소제목으로 강등."""
    out = rs.strip_stray_headers(
        "# 제목\n## 근거\n본문\n## 실무 액션\n남의 섹션", "근거")
    # `### ` 도 `## ` 를 포함하므로 H2 만 정확히 센다.
    h2 = [ln for ln in out.splitlines()
          if ln.startswith("## ") and not ln.startswith("### ")]
    assert len(h2) == 1, h2
    assert out.startswith("## 근거")
    assert "### 실무 액션" in out
    assert "# 제목" not in out
    # 헤더가 아예 없으면 붙여준다
    assert rs.strip_stray_headers("본문만", "개요").startswith("## 개요")


# ── 분리 경계 가드 (2026-08-25) ──────────────────────────────────────

def test_engine_has_no_app_coupling():
    """작성 엔진이 앱(파이프라인·저장소·인용 스키마)을 다시 끌어오면 실패.

    엔진을 그대로 떼어 다른 파이프라인에 붙일 수 있는 상태를 유지하기 위한
    회귀 방지 — 결합이 생기면 여기서 즉시 드러난다.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(rs))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]          # 설명 docstring 제외
    code = ast.unparse(tree)
    for banned in ("src.persistence", "src.report_pipeline", "get_reports_repo",
                   "citations_json", "_persist_report", "fastapi"):
        assert banned not in code, f"report_sections 에 {banned} 결합 재유입"
    # 실행 코드에 남은 src import 자체가 없어야(순수 엔진)
    assert "from src" not in code and "import src" not in code


def test_engine_api_is_injection_based():
    """공개 API 계약 — llm·규율·입력을 주입받고 문자열을 돌려준다."""
    import inspect

    params = list(inspect.signature(rs.write_sections).parameters)
    assert params[0] == "llm"
    for kw in ("base_rules", "writer_input", "cfg", "emit", "sem", "load"):
        assert kw in params, kw
    assert list(inspect.signature(rs.write_single).parameters)[0] == "llm"


# ── 보고서 종류별 분량 (2026-08-25) ─────────────────────────────────

def test_purpose_scales_length(monkeypatch):
    """목적에 맞는 분량 — '요약'에 2만 자를 요구하면 채우기용 서술이 나온다."""
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "4000")

    def total(purpose):
        return sum(x["target"] for x in rs.section_specs(purpose))

    full = total("license_strategy")      # 전략 — 최대 깊이
    change = total("change_response")     # 변화 대응 — 중간
    summary = total("reg_summary")        # 요약 — 간결
    assert full > change > summary, (full, change, summary)
    assert total(None) == full            # 목적 미지정 = 최대(종전 동작)
    assert summary < full * 0.7


def test_thin_evidence_lowers_target(monkeypatch):
    """근거가 얇으면 목표도 낮춘다 — 확장 재호출이 헛돌지 않게."""
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "4000")
    rich = sum(x["target"] for x in rs.section_specs(None, 30))
    mid = sum(x["target"] for x in rs.section_specs(None, 10))
    thin = sum(x["target"] for x in rs.section_specs(None, 3))
    assert rich > mid > thin
    assert rs.section_specs(None, None)[0]["target"] == \
        rs.section_specs(None, 30)[0]["target"]      # 미지정 = 감산 없음


def test_targets_never_degenerate(monkeypatch):
    """최악 조합(요약 + 근거 3건)에서도 섹션이 사라지지 않는다."""
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "1000")
    specs = rs.section_specs("reg_summary", 1)
    assert len(specs) == 5
    assert all(x["target"] >= 400 for x in specs)


def test_pipeline_passes_purpose_and_evidence(monkeypatch):
    """파이프라인이 목적·근거량을 엔진에 실제로 넘기는지(배선 검증)."""
    seen: dict = {}
    real = rs.section_specs

    def _spy(purpose=None, evidence_count=None):
        seen["purpose"] = purpose
        seen["evidence_count"] = evidence_count
        return real(purpose, evidence_count)

    monkeypatch.setattr(rs, "section_specs", _spy)
    monkeypatch.setenv("REPORT_SECTIONED", "1")
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "800")
    captured: dict = {}
    p = _payload()
    p["purpose"] = "reg_summary"
    llm = _FakeLLM(chars_per_section=2000)

    def _fake_persist(*, path, body, state, ctx=None, citations=None):
        captured["body"] = body
        return ("rpt_p", "blob://x")

    import src.tools.reports as TR
    monkeypatch.setattr(TR, "_persist_report", _fake_persist)
    monkeypatch.setattr(rp, "_revise_enabled", lambda: False)
    asyncio.run(rp.synthesize_and_persist(
        p, {"steps": []}, {"configurable": {}}, model=llm))
    assert seen["purpose"] == "reg_summary"
    assert seen["evidence_count"] == 2          # web 1 + rag 1


# ── 보고서 성격 판정 (2026-08-25) ───────────────────────────────────

def test_parse_decompose_object_and_array():
    """신계약(객체)·구계약(배열) 모두 수용 — 모델이 옛 형식을 뱉어도 안전."""
    qs, pu = rp._parse_decompose(
        '{"queries": ["a", "b"], "purpose": "license_strategy"}')
    assert qs == ["a", "b"] and pu == "license_strategy"
    qs, pu = rp._parse_decompose('["a", "b"]')          # 구 계약
    assert qs == ["a", "b"] and pu is None
    # 목록에 없는 purpose 는 버린다(모델 창작 차단)
    _qs, pu = rp._parse_decompose('{"queries": ["a"], "purpose": "창작"}')
    assert pu is None
    assert rp._parse_decompose("JSON 아님") == ([], None)


@pytest.mark.asyncio
async def test_decompose_infers_purpose():
    class _M:
        async def ainvoke(self, prompt, cfg=None):
            return type("R", (), {"content":
                '{"queries": ["q1", "q2"], "purpose": "reg_summary"}'})()

    qs, pu = await rp.decompose_and_classify("질문", "잠정", model=_M())
    assert qs == ["q1", "q2"] and pu == "reg_summary"
    # 얇은 래퍼는 쿼리만 — 구 호출자 호환
    assert await rp.decompose_queries("질문", "잠정", model=_M()) == ["q1", "q2"]


@pytest.mark.asyncio
async def test_decompose_failure_returns_pair():
    """실패해도 (쿼리, None) 짝을 지킨다 — 호출자 언패킹이 깨지면 보고서 전멸."""
    class _Boom:
        async def ainvoke(self, prompt, cfg=None):
            raise RuntimeError("down")

    qs, pu = await rp.decompose_and_classify("원 질문", "", model=_Boom())
    assert qs == ["원 질문"] and pu is None
    assert await rp.decompose_and_classify("", "", model=_Boom()) == ([], None)


def test_plan_rebalanced_to_observed_capacity(monkeypatch):
    """배수는 실측 달성률에 맞춘다 — 못 채울 목표는 헛된 재호출·억지 서술."""
    monkeypatch.setenv("REPORT_SECTION_TARGET_CHARS", "4000")
    by = {x["name"]: x["target"] for x in rs.section_specs()}
    # 소재가 풍부해 넘치던 섹션 > 소재가 적어 미달하던 섹션
    assert by["근거"] > by["실무 액션"] > by["핵심 결론"] > by["리스크/후속"]
    assert sum(by.values()) == 19000          # 총합은 유지(재배분일 뿐)


def test_numeric_citation_rule_in_section_prompt():
    """표 셀 안 수치 인용 누락(실측 1건) 재발 방지 — 규칙이 프롬프트에 있어야."""
    h = rs._SECTION_MODE_HEADER
    assert "표 셀 안도" in h and "수치가 든 문장" in h
