"""서류 초안 모드(document_draft, 2026-08-24) — Phase ① 백엔드.

베타 피드백("IRB 서류가 채팅에서 끊기고 복붙 불편") 대응: 서류는 보고서
파이프라인이 파일로 만든다. 핵심 규율 — **서식 구조도 근거에서만**(4케이스),
기입값은 `[확인 필요: 항목명]` 마커(기존 irb-form-filler 스킬 규격 재사용).
"""
from __future__ import annotations


import pytest

from src.report_pipeline import (
    _DOCUMENT_DRAFT_INSTRUCTIONS,
    _RECONCILE_INSTRUCTIONS,
    draft_form_assets,
)


def test_draft_instructions_carry_core_rules():
    t = _DOCUMENT_DRAFT_INSTRUCTIONS
    assert "[확인 필요" in t                      # 스킬과 동일 마커 규격
    assert "구조도 근거에서만" in t                # 4케이스 원칙
    assert "지어내" in t                          # 날조 금지
    assert "## 개요" in t                         # summary 추출 호환
    assert "# " in t                              # H1 제목 계약(사이드바)
    # 일반 보고서의 분량 강제(8,000자)는 서류에 없음
    assert "8,000자" in _RECONCILE_INSTRUCTIONS
    assert "8,000자" not in t


def test_purpose_selects_draft_instructions(monkeypatch):
    """synthesize 의 지시문 선택 분기 — 소스 검사로 고정(LLM 호출 없이)."""
    import inspect

    from src import report_pipeline
    src = inspect.getsource(report_pipeline.synthesize_and_persist)
    assert "_DOCUMENT_DRAFT_INSTRUCTIONS" in src
    assert 'document_draft' in src


def test_reports_route_accepts_document_draft():
    import inspect

    from src.routes import reports
    src = inspect.getsource(reports)
    assert '"document_draft"' in src


class TestDraftFormAssets:
    def test_disabled_without_bundle(self, monkeypatch):
        monkeypatch.delenv("SKILL_BUNDLE_DIR", raising=False)
        assert draft_form_assets("IRB 심의 서류") == []

    def test_irb_assets_injected(self, monkeypatch, tmp_path):
        ref = tmp_path / "irb-form-filler" / "references"
        ref.mkdir(parents=True)
        (ref / "form-registry.md").write_text("# IRB 서식 레지스트리\n서식 11 …",
                                              encoding="utf-8")
        (ref / "field-mapping.md").write_text("# 매핑", encoding="utf-8")
        monkeypatch.setenv("SKILL_BUNDLE_DIR", str(tmp_path))
        out = draft_form_assets("연구계획심의 의뢰서 초안 작성해줘")  # 'irb' 없어도 '심의'로 매칭
        assert len(out) == 2
        assert out[0]["id"].startswith("skill:irb-form-filler")
        assert "화순전남대" in out[0]["publisher"]
        assert "서식 11" in out[0]["text"]

    def test_drb_requires_explicit_keyword(self, monkeypatch, tmp_path):
        ref = tmp_path / "drb-form-filler" / "references"
        ref.mkdir(parents=True)
        (ref / "form-registry.md").write_text("DRB", encoding="utf-8")
        monkeypatch.setenv("SKILL_BUNDLE_DIR", str(tmp_path))
        assert draft_form_assets("심의 서류") == []      # '심의'만으론 DRB 미주입
        assert len(draft_form_assets("DRB 심의 의뢰서")) == 1

    def test_non_irb_request_no_injection(self, monkeypatch, tmp_path):
        (tmp_path / "irb-form-filler" / "references").mkdir(parents=True)
        monkeypatch.setenv("SKILL_BUNDLE_DIR", str(tmp_path))
        assert draft_form_assets("의료기기 제조허가 신청서") == []


@pytest.mark.asyncio
async def test_decompose_draft_hint(monkeypatch):
    """서류 모드 decompose 프롬프트에 서식·기재요령 힌트가 붙는다."""
    captured = {}

    class _M:
        async def ainvoke(self, prompt, cfg=None):
            captured["prompt"] = prompt

            class _R:
                content = '["a", "b", "c"]'
            return _R()

    from src.report_pipeline import decompose_queries
    qs = await decompose_queries("IRB 서류 초안", "답변", model=_M(),
                                 purpose="document_draft")
    assert qs == ["a", "b", "c"]
    assert "서식" in captured["prompt"] and "기재요령" in captured["prompt"]

    await decompose_queries("일반 질문", "답변", model=_M(), purpose=None)
    assert "기재요령" not in captured["prompt"]
