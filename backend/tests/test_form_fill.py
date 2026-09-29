"""원본 서식 기입(form_fill, 2026-08-25) — 인용 선별·라벨 매핑·XML 폴백.

kordoc 실행이 필요한 통합 경로는 KORDOC_CLI 설정 시에만(skipif) — CI 에는
node/kordoc 이 없어도 순수 파이썬 부분은 전부 검증된다.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from src.form_fill import (
    heuristic_map,
    map_values_to_labels,
    xml_append_fallback,
)
# 서식 인용 선별은 인용 스키마 소유 모듈에 있다(2026-08-25 분리) —
# form_fill 은 URL + 값만 아는 순수 엔진.
from src.tools.citations import pick_form_citation


def test_pick_form_citation_prefers_form_over_annex():
    cites = [
        {"id": "cite_web_x", "url": "https://ex.com"},  # 웹 — 제외
        {"article_key": "009740_000100E_attachment", "doc_category": "법령별표서식",
         "download_url": "https://www.law.go.kr/LSW/flDownload.do?flSeq=1"},
        {"article_key": "009740_000100F_attachment", "doc_category": "법령별표서식",
         "download_url": "https://www.law.go.kr/LSW/flDownload.do?flSeq=2"},
    ]
    picked = pick_form_citation(cites)
    assert picked["article_key"].endswith("F_attachment")  # 서식(F) 우선


def test_pick_form_citation_requires_download_url():
    # 링크 없는 별표 인용만 있으면 None — 기관 서식(스킬 자산) 케이스.
    assert pick_form_citation(
        [{"article_key": "x_000100E_attachment", "doc_category": "법령별표서식"}]
    ) is None
    assert pick_form_citation([]) is None


def test_heuristic_map_norm_and_containment():
    labels = ["명칭(상호)", "소재지", "담당자 성명", "처리기간"]
    filled = {"명칭 상호": "메디레그", "제조소 소재지 주소": "광주 동구",
              "담당자 성명": "김담당", "무관항목": "x"}
    m = heuristic_map(labels, filled)
    assert m["명칭(상호)"] == "메디레그"       # 정규화 동등
    assert m["소재지"] == "광주 동구"           # 포함 관계
    assert m["담당자 성명"] == "김담당"
    assert "처리기간" not in m                  # 대응 없는 라벨은 비움


class _FakeModel:
    def __init__(self, reply):
        self.reply = reply

    async def ainvoke(self, prompt):
        class _R:
            content = self.reply
        return _R()


@pytest.mark.asyncio
async def test_map_values_llm_rejects_invented():
    labels = ["연구책임자 성명"]
    filled = {"책임자": "홍길동"}
    # 모델이 없는 라벨·없는 값을 창작해도 걸러진다.
    m = await map_values_to_labels(
        labels, filled,
        model=_FakeModel(json.dumps(
            {"연구책임자 성명": "홍길동", "창작라벨": "홍길동",
             "연구책임자 성명2": "창작값"}, ensure_ascii=False)))
    assert m == {"연구책임자 성명": "홍길동"}


def _mini_hwpx(path: str, body_xml: str):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", body_xml)
        z.writestr("version.xml", "<v/>")


def test_xml_append_fallback(tmp_path):
    p = str(tmp_path / "f.hwpx")
    _mini_hwpx(p, "<hp:p><hp:run><hp:t>소재지</hp:t></hp:run></hp:p>"
                  "<hp:p><hp:run><hp:t>기타</hp:t></hp:run></hp:p>")
    n = xml_append_fallback(p, {"소재지": "광주 동구", "없는라벨": "x"})
    assert n == 1
    xml = zipfile.ZipFile(p).read("Contents/section0.xml").decode()
    assert "소재지      광주 동구" in xml
    assert "없는라벨" not in xml
    # 값 없으면 no-op
    assert xml_append_fallback(p, {}) == 0


def test_form_fill_does_not_know_citation_schema():
    """분리 경계 가드 — 기입 엔진이 인용·보고서 스키마를 다시 끌어오면 실패.

    (엔진을 별도 서비스로 떼어낼 수 있는 상태를 유지하기 위한 회귀 방지.)
    """
    import ast
    import inspect

    import src.form_fill as ff

    # 주석·독스트링(경계를 *설명*하는 문장)은 제외하고 **실행 코드**만 본다.
    tree = ast.parse(inspect.getsource(ff))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]  # 독스트링 노드 제거
    code_text = ast.unparse(tree)
    for banned in ("citations", "doc_category", "article_key",
                   "get_reports_repo", "ReportMeta"):
        assert banned not in code_text, f"form_fill 에 {banned} 결합 재유입"
    # 공개 진입점은 URL + 값만 받는다.
    params = list(inspect.signature(ff.build_filled_form).parameters)
    assert params[:2] == ["form_url", "filled"]


def test_download_url_prefers_hit_attachment_link(monkeypatch):
    """검색 히트가 링크를 실어 주면 Neo4j 왕복 없이 그대로 쓴다(2026-08-26).

    ETL f247e53 이후 law.go.kr 수확분(44,907청크)은 100% 이 필드를 갖는다.
    """
    from src.tools import citations as C

    def _boom(*a, **k):  # Neo4j 를 건드리면 실패
        raise AssertionError("attachment_link 있는데 Neo4j 조회함")

    monkeypatch.setattr("src.retrieval.neo4j_client.fetch_attachment_by_key",
                        _boom, raising=False)
    url = C._download_url_for_attachment(
        {"article_key": "2100000230864_000300_attachment",
         "attachment_link": "/LSW/flDownload.do?flSeq=123"}, {})
    assert url == "https://www.law.go.kr/LSW/flDownload.do?flSeq=123"


def test_download_url_falls_back_when_no_hit_link(monkeypatch):
    """HIRA 게시판 등 링크 없는 코퍼스 — 기존 Neo4j 경로가 계속 동작."""
    from src.tools import citations as C

    monkeypatch.setattr(
        "src.retrieval.neo4j_client.fetch_attachment_by_key",
        lambda key: {"link": "/LSW/flDownload.do?flSeq=999"}, raising=False)
    url = C._download_url_for_attachment(
        {"article_key": "009740_000100E_attachment", "attachment_link": None}, {})
    assert url.endswith("flSeq=999")


# ── patch 파이프라인 (2026-08-27 전환) ──────────────────────────────────


def test_apply_values_to_md_next_empty_cell():
    """라벨 옆 빈 셀이 있으면 거기에 — 담당자 전화번호 케이스."""
    from src.form_fill import apply_values_to_md

    md = '<tr><td colspan="5">담당자 전화번호</td><td colspan="6"></td></tr>'
    out, applied, unmatched = apply_values_to_md(md, {"담당자 전화번호": "02-555-0100"})
    assert '<td colspan="6">02-555-0100</td>' in out
    assert applied == ["담당자 전화번호"] and unmatched == []


def test_apply_values_to_md_inline_when_no_empty_neighbor():
    """옆이 빈 셀이 아니면 라벨 셀에 병기 — 성명(한글)|( 한자) 케이스."""
    from src.form_fill import apply_values_to_md

    md = '<tr><td colspan="7">성명(한글)</td><td colspan="6">(한자)</td></tr>'
    out, applied, _ = apply_values_to_md(md, {"성명(한글)": "홍길동"})
    assert "성명(한글)<br>홍길동" in out
    assert applied == ["성명(한글)"]


def test_apply_values_to_md_exact_match_only():
    """정규화 동등만 — 비슷한 라벨에 슬쩍 넣지 않는다(오기입 > 미기입 위해).
    미매칭은 unmatched 로 정직 보고."""
    from src.form_fill import apply_values_to_md

    md = '<tr><td>자격 구분<br>[ ] 면허 [ ] 학위</td></tr>'
    out, applied, unmatched = apply_values_to_md(md, {"자격 구분": "면허"})
    assert applied == [] and unmatched == ["자격 구분"]
    assert out == md  # 원문 무변경


def test_apply_values_to_md_skips_nested_table_cells():
    """중첩 표가 든 셀은 건드리지 않는다 — 처리절차 흐름도 파손 방지."""
    from src.form_fill import apply_values_to_md

    md = '<td colspan="14"><table><tr><td>성명</td></tr></table></td>'
    out, applied, unmatched = apply_values_to_md(md, {"성명": "홍길동"})
    # 바깥 셀은 _TD_RE 가 배제, 안쪽 셀은 매칭됨 — 안쪽만 채워지는 건 허용.
    # 핵심: 바깥 셀 통째 교체로 흐름도가 깨지지 않는 것.
    assert "<table>" in out
