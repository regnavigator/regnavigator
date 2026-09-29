"""보고서 동적 목차(2026-08-28) — 서론·결론 고정 + 본론 자유 + 목차 삽입.

불변식:
- 어떤 플랜이 와도 첫 섹션은 '개요'(채팅 발췌 계약), 마지막은 '결론 및 권고'.
- 총 분량 배수(4.75)는 고정 플랜과 동일 — 목차가 바뀌어도 분량 경제 불변.
- 플랜 파싱 실패는 전부 None → 기존 5섹션 폴백(개악 없음).
- 목차는 H1 아래 삽입, '목차' 자신은 목록에서 제외.
"""
from __future__ import annotations

import asyncio

from src.report_sections import build_dynamic_specs, insert_toc, section_specs


def test_dynamic_specs_head_tail_fixed():
    plan = [{"name": "등급 판정", "focus": "f1", "share": 2},
            {"name": "임상 요건", "focus": "f2", "share": 1}]
    specs = build_dynamic_specs(None, 30, plan)
    names = [s["name"] for s in specs]
    assert names[0] == "개요" and names[-1] == "결론 및 권고"
    assert names[1:-1] == ["등급 판정", "임상 요건"]


def test_dynamic_specs_total_budget_matches_fixed():
    """본론이 몇 개든 총 목표 분량은 고정 5섹션과 같다(±반올림)."""
    fixed_total = sum(x["target"] for x in section_specs(None, 30))
    for n in (2, 5):
        plan = [{"name": f"섹션{i}", "focus": "", "share": 1} for i in range(n)]
        dyn_total = sum(x["target"] for x in build_dynamic_specs(None, 30, plan))
        assert abs(dyn_total - fixed_total) <= n + 3


def test_dynamic_specs_share_allocation():
    plan = [{"name": "가", "focus": "", "share": 3},
            {"name": "나", "focus": "", "share": 1}]
    specs = build_dynamic_specs(None, 30, plan)
    body = {s["name"]: s["target"] for s in specs[1:-1]}
    assert body["가"] > body["나"] * 2  # 3:1 가중 반영


def test_plan_outline_falls_back_on_garbage():
    from src.report_pipeline import _plan_outline

    class Bad:
        async def ainvoke(self, *a, **k):
            class R: content = "목차를 설계할 수 없습니다"
            return R()

    assert asyncio.run(_plan_outline("q", None, [], model=Bad())) is None


def test_plan_outline_parses_and_filters():
    from src.report_pipeline import _plan_outline

    class Ok:
        async def ainvoke(self, *a, **k):
            class R:
                content = ('설계: [{"name":"등급 판정","focus":"x","share":2},'
                           '{"name":"개요","focus":"금지 이름","share":1},'
                           '{"name":"절차와 서류","focus":"y","share":1}]')
            return R()

    plan = asyncio.run(_plan_outline("q", None, [], model=Ok()))
    assert [p["name"] for p in plan] == ["등급 판정", "절차와 서류"]  # '개요' 제거


def test_insert_toc_after_h1_excluding_self():
    body = "# 제목\n\n## 개요\n\nA\n\n## 본론\n\nB\n\n## 결론 및 권고\n\nC"
    out = insert_toc(body)
    assert out.index("## 목차") < out.index("## 개요")
    assert "1. 개요" in out and "3. 결론 및 권고" in out
    assert out.count("목차") == 1  # 목차 항목에 자기 자신 없음


def test_insert_toc_skips_short_docs():
    assert insert_toc("# 제목\n\n## 개요\n\nA") == "# 제목\n\n## 개요\n\nA"
