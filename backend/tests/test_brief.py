"""서면·의견서 초안 — 문단 수정의 안전장치 (2026-10-01).

핵심은 "잘 고치는가" 가 아니라 **엉뚱한 곳을 고치지 않는가** 와
**없는 근거를 만들지 않는가** 다. 둘 다 조용히 틀리면 서면 전체를 버려야 한다.
"""

from __future__ import annotations

import asyncio

import pytest

from src.brief import (
    ReviseConflict,
    allowed_citations,
    revise_paragraph,
    sanitize_citations,
    skeleton,
    split_paragraphs,
)

BODY = """# 의견서

## 사실관계

의뢰인은 2026-03-11 영업을 개시했다 [1].

신고는 하지 않았다 [2].

## 검토

제3조 제1항의 신고 의무가 적용된다 [1].
"""


def test_headings_are_not_editable_paragraphs():
    """섹션 제목을 문단으로 세면 '문단 2를 고쳐라'가 구조를 깬다."""
    paras = split_paragraphs(BODY)
    kinds = [p["kind"] for p in paras]
    assert kinds[0] == "heading"                      # # 의견서
    assert "paragraph" in kinds
    # 인덱스는 연속 — FE 가 같은 번호로 가리킨다.
    assert [p["index"] for p in paras] == list(range(len(paras)))


def test_revise_replaces_only_the_named_paragraph():
    paras = split_paragraphs(BODY)
    target = next(p for p in paras if "신고는 하지 않았다" in p["text"])

    new_body, dropped = revise_paragraph(
        BODY, index=target["index"], original_text=target["text"],
        replacement="신고 의무를 이행하지 않았다 [2].",
    )
    assert dropped == []
    assert "신고 의무를 이행하지 않았다" in new_body
    assert "신고는 하지 않았다" not in new_body
    # 다른 문단은 그대로.
    assert "의뢰인은 2026-03-11 영업을 개시했다 [1]." in new_body
    assert "제3조 제1항의 신고 의무가 적용된다 [1]." in new_body


def test_revise_refuses_when_paragraph_drifted():
    """원문이 바뀌었으면 거부한다 — 조용히 다른 문단을 고치는 것이 최악이다."""
    with pytest.raises(ReviseConflict) as e:
        revise_paragraph(BODY, index=2, original_text="내가 기억하던 옛 문장",
                         replacement="새 문장")
    assert e.value.current  # 현재 내용을 돌려줘 FE 가 다시 읽게 한다


def test_revise_refuses_out_of_range_index():
    with pytest.raises(ReviseConflict):
        revise_paragraph(BODY, index=99, original_text="x", replacement="y")


def test_invented_citation_numbers_are_stripped():
    """문서에 없는 [7] 을 모델이 붙이면 떼어낸다 — 가짜 근거가 제일 위험하다."""
    paras = split_paragraphs(BODY)
    target = next(p for p in paras if "신고는 하지 않았다" in p["text"])

    new_body, dropped = revise_paragraph(
        BODY, index=target["index"], original_text=target["text"],
        replacement="신고를 하지 않았다 [2]. 과태료가 부과된다 [7].",
    )
    assert dropped == [7]
    assert "[7]" not in new_body
    assert "[2]" in new_body          # 원래 있던 번호는 살린다


def test_allowed_citations_reads_whole_document():
    assert allowed_citations(BODY) == {1, 2}


def test_sanitize_cleans_leftover_spacing():
    out, dropped = sanitize_citations("과태료가 부과된다 [9].", {1})
    assert dropped == [9]
    assert out == "과태료가 부과된다."


def test_revise_refuses_empty_result():
    """인용만 있던 문단이 통째로 비면 교체하지 않는다."""
    paras = split_paragraphs(BODY)
    target = next(p for p in paras if "신고는 하지 않았다" in p["text"])
    with pytest.raises(ReviseConflict):
        revise_paragraph(BODY, index=target["index"],
                         original_text=target["text"], replacement="[9]")


def test_skeleton_has_all_sections():
    s = skeleton("김철수 사건 의견서")
    for t in ("사실관계", "쟁점", "관련 법령·조문", "검토", "결론"):
        assert f"## {t}" in s
    assert s.startswith("# 김철수 사건 의견서")


# ── 라우트 계약 (2026-10-01) ────────────────────────────────────────────────

def test_revise_route_is_registered_and_async():
    """수정은 LLM 호출·blob 쓰기를 하므로 async 여야 한다(이벤트 루프 블로킹 방지)."""
    import inspect

    from src.routes import reports as R

    fn = R.revise_document_paragraph
    assert inspect.iscoroutinefunction(fn)
    # 조회 전용 라우트는 동기 — 스레드풀로 간다(async 규약).
    assert not inspect.iscoroutinefunction(R.list_document_paragraphs)


def test_brief_route_does_not_require_article_bodies():
    """초안 생성은 조문 본문 소스(PG·/articles/bodies)에 의존하면 안 된다.

    그 경로가 막혀 서식 작성이 안 열리는 상황에서도 서면은 돼야 한다 —
    근거는 이미 대화의 인용에 들어 있다.
    """
    import inspect

    from src.routes import reports as R

    import ast
    import textwrap

    src = inspect.getsource(R.create_document_from_brief)
    # docstring 은 그 사실을 **설명**하므로 제외하고 코드만 본다.
    tree = ast.parse(textwrap.dedent(src))
    fn_node = tree.body[0]
    if (fn_node.body and isinstance(fn_node.body[0], ast.Expr)
            and isinstance(fn_node.body[0].value, ast.Constant)):
        fn_node.body = fn_node.body[1:]
    code = ast.unparse(fn_node)
    assert "fetch_bodies" not in code
    assert "articles/bodies" not in code


def test_revise_refuses_when_onprem_unavailable():
    """원내 모델이 없으면 503 으로 분명히 거부한다 — 상용 모델로 새지 않는다.

    서면에는 사건 사실관계가 들어간다. 조용히 외부로 보내면 기밀 모드의 의미가 없다.
    """
    import inspect

    from src.routes import reports as R

    src = inspect.getsource(R.revise_document_paragraph)
    assert "onprem_fill()" in src
    assert "status_code=503" in src
    # 단, 사용자가 직접 친 문장(replacement)은 모델 없이도 통과해야 한다.
    i_manual = src.index("if manual is not None:")
    i_gate = src.index("onprem_fill()")
    assert i_manual < i_gate, "직접 수정이 원내 모델 게이트에 막히면 안 된다"


# ── 왕복 (2026-10-01) ───────────────────────────────────────────────────────

@pytest.fixture()
def _api(tmp_path, monkeypatch):
    """dev 인증 우회 + tmp 저장소로 격리된 TestClient."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("REPORTS_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)

    import src.persistence as P
    import src.persistence.threads_repo as TR

    monkeypatch.setattr(TR, "_repo", None)
    for f in (P.get_reports_repo, P.get_report_runs_repo, P.get_blob_store,
              P.get_users_repo, P.get_events_repo):
        f.cache_clear()

    from fastapi.testclient import TestClient

    from src.api import app

    yield TestClient(app)

    monkeypatch.setattr(TR, "_repo", None)
    for f in (P.get_reports_repo, P.get_report_runs_repo, P.get_blob_store,
              P.get_users_repo, P.get_events_repo):
        f.cache_clear()


def test_brief_roundtrip_create_then_revise_manually(_api):
    """초안 생성 → 문단 직접 수정 → 본문 반영. 원내 모델 없이 동작해야 한다."""
    from src.middleware import AUTH_DEV_BYPASS_USER_ID
    from src.persistence.threads_repo import get_threads_repo

    tr = get_threads_repo()
    tr.ensure_thread("t_brief", user_id=AUTH_DEV_BYPASS_USER_ID)

    r = _api.post("/documents/from-brief",
                  json={"thread_id": "t_brief", "title": "테스트 의견서"})
    assert r.status_code == 200, r.text
    doc = r.json()
    rid = doc["report_id"]
    assert doc["title"] == "테스트 의견서"

    paras = doc["paragraphs"]
    target = next(p for p in paras if p["kind"] == "paragraph")

    r2 = _api.post(f"/documents/{rid}/revise", json={
        "index": target["index"],
        "original_text": target["text"],
        "replacement": "의뢰인은 2026-03-11 영업을 개시했다.",
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["dropped_citations"] == []

    r3 = _api.get(f"/documents/{rid}/paragraphs")
    assert r3.status_code == 200
    texts = [p["text"] for p in r3.json()["paragraphs"]]
    assert "의뢰인은 2026-03-11 영업을 개시했다." in texts
    assert target["text"] not in texts


def test_brief_revise_conflict_returns_409(_api):
    """다른 사람이(또는 다른 탭이) 먼저 고쳤으면 409 로 막고 현재 내용을 돌려준다."""
    from src.middleware import AUTH_DEV_BYPASS_USER_ID
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().ensure_thread("t_brief2", user_id=AUTH_DEV_BYPASS_USER_ID)
    rid = _api.post("/documents/from-brief",
                    json={"thread_id": "t_brief2"}).json()["report_id"]

    r = _api.post(f"/documents/{rid}/revise", json={
        "index": 1, "original_text": "내가 보던 옛 문장", "replacement": "새 문장",
    })
    assert r.status_code == 409
    assert "current" in r.json()["detail"]


def test_skeleton_sections_have_editable_paragraphs():
    """각 섹션 안내문은 **고칠 수 있는 문단**이어야 한다.

    제목과 붙여 쓰면 한 덩어리가 heading 으로 분류돼 수정 대상이 0개가 된다
    (구현 중 실제로 그랬다).
    """
    paras = split_paragraphs(skeleton("의견서"))
    assert any(p["kind"] == "paragraph" for p in paras)
    headings = [p["text"] for p in paras if p["kind"] == "heading"]
    assert any(h.startswith("## 사실관계") for h in headings)


# ── 초안 조립 (2026-10-02) ──────────────────────────────────────────────────

class _M:
    def __init__(self, type_, content):
        self.type = type_
        self.content = content


def test_compose_fills_sections_from_conversation():
    """"그냥 서식만 나온다"(실사용 지적) — 재료가 있으면 채워야 한다."""
    from src.brief import compose_from_thread

    msgs = [
        _M("human", "의뢰인이 영업신고 없이 카페를 3개월 운영했습니다. 처분 수위가 궁금합니다."),
        _M("ai", "식품위생법 제37조 제4항에 따라 영업신고 의무가 있습니다 [1]. "
                 "미신고 영업은 같은 법 제97조의 벌칙 대상입니다 [2]. " + "상세 " * 40
                 + "<next_steps>[]</next_steps>"),
    ]
    cites = [{"number": 1, "title": "식품위생법 제37조", "publisher": "식품의약품안전처"},
             {"number": 2, "title": "식품위생법 제97조"}]
    body = compose_from_thread(msgs, cites, title="처분 검토 의견서")

    assert "영업신고 없이 카페를 3개월" in body     # 사실관계 = 사용자가 쓴 그대로
    assert "1. 의뢰인이 영업신고 없이" in body       # 쟁점 = 질문을 번호로
    assert "`[1]` 식품위생법 제37조" in body         # 관련 법령 = 인용 목록
    assert "제97조의 벌칙" in body                   # 검토 = 답변 본문
    assert "<next_steps>" not in body               # 마커는 서면에 들어갈 글이 아니다


def test_compose_marks_missing_sections_instead_of_leaving_blank():
    """빈 칸은 '빠뜨린 것'인지 '없는 것'인지 구분이 안 된다(원칙 5와 같은 규율)."""
    from src.brief import compose_from_thread

    body = compose_from_thread([], [], title="빈 의견서")
    assert body.count("대화에서 확인되지 않았습니다") >= 3
    for h in ("## 사실관계", "## 쟁점", "## 관련 법령·조문", "## 검토", "## 결론"):
        assert h in body


def test_compose_output_is_paragraph_editable():
    """조립 결과도 문단 단위로 고칠 수 있어야 한다 — 그게 이 패널의 전부다."""
    from src.brief import compose_from_thread, split_paragraphs

    msgs = [_M("human", "카페 개업 절차를 알려주세요."),
            _M("ai", "영업신고가 필요합니다 [1]. " + "본문 " * 40)]
    paras = split_paragraphs(
        compose_from_thread(msgs, [{"number": 1, "title": "식품위생법"}],
                            title="t"))
    assert sum(1 for p in paras if p["kind"] == "paragraph") >= 4


def test_compose_keeps_citation_numbers_consistent():
    """본문이 쓰는 [n] 이 관련 법령 절의 번호와 같아야 수정 시 보호가 작동한다."""
    from src.brief import allowed_citations, compose_from_thread

    msgs = [_M("human", "질문입니다."),
            _M("ai", "근거는 다음과 같습니다 [3]. " + "본문 " * 40)]
    body = compose_from_thread(msgs, [{"number": 3, "title": "식품위생법 제37조"}],
                               title="t")
    assert 3 in allowed_citations(body)


def test_compose_strips_chat_preamble_from_answers():
    """v32 이전에 쌓인 답변의 서두가 서면에 따라 들어오면 안 된다."""
    from src.brief import compose_from_thread

    msgs = [_M("human", "카페 개업 절차를 알려주세요."),
            _M("ai", "지금까지 확보한 근거를 바탕으로 정리합니다.\n\n"
                     "영업신고가 필요합니다 [1]. " + "본문 " * 40)]
    body = compose_from_thread(msgs, [{"number": 1, "title": "식품위생법"}], title="t")
    assert "확보한 근거를 바탕으로" not in body
    assert "영업신고가 필요합니다" in body


def test_compose_drops_ai_instructions_from_facts():
    """"…분해해줘" 는 사실관계가 아니라 AI 에게 시킨 말이다."""
    from src.brief import compose_from_thread

    msgs = [_M("human",
               "의뢰인은 서울 마포구에서 주류를 파는 베이커리 카페를 준비 중입니다. "
               "밟아야 하는 인허가 의무를 단계별 절차로 분해해줘.")]
    body = compose_from_thread(msgs, [], title="t")
    facts = body.split("## 쟁점")[0]
    assert "베이커리 카페를 준비 중입니다" in facts
    assert "분해해줘" not in facts
    # 쟁점 절에는 원문이 그대로 남아야 한다 — 무엇을 물었는지가 쟁점이다.
    assert "분해해줘" in body.split("## 쟁점")[1].split("## 관련")[0]


def test_compose_is_honest_when_no_facts_were_given():
    """질의만 오간 대화를 사실관계인 척 올리면 의견서에 "찾아줘"가 적힌다.

    그 상태를 숨기지 말고 드러내고, 입력된 질의는 인용으로 남겨 참고하게 한다.
    """
    from src.brief import compose_from_thread

    body = compose_from_thread([_M("human", "서식을 찾아줘.")], [], title="t")
    facts = body.split("## 쟁점")[0]
    assert "사실관계가 입력되지 않았습니다" in facts
    assert "> 서식을 찾아줘" in facts          # 참고용 인용으로는 남는다


# ── 자동 다듬기 (2026-10-02) ────────────────────────────────────────────────

class _Polisher:
    def __init__(self, text):
        self.text = text

    async def ainvoke(self, _p):
        class R:
            content = self.text
        return R()


def test_polish_rewrites_but_keeps_only_existing_citations():
    """다듬기는 쓰기가 아니다 — 새 인용 번호는 기계적으로 제거한다."""
    from src.brief import polish_section

    out = asyncio.run(polish_section(
        "검토",
        "영업신고가 필요해요 [1]. 그리고 위생교육도 받아야 해요. " + "내용 " * 30,
        allowed={1},
        model=_Polisher("영업신고 의무가 있다 [1]. 위생교육 이수가 선행된다 [9]. "
                        + "서술 " * 30),
    ))
    assert out is not None
    text, dropped = out
    assert dropped == [9]
    assert "[9]" not in text and "[1]" in text


def test_polish_keeps_original_when_result_is_a_summary():
    """1/4 밑으로 줄면 다듬기가 아니라 요약이다 — 내용이 날아간다."""
    from src.brief import polish_section

    long_body = "영업신고가 필요합니다 [1]. " + "상세 내용 " * 60
    assert asyncio.run(polish_section("검토", long_body, allowed={1},
                                      model=_Polisher("요약하면 신고가 필요하다."))) is None


def test_polish_skips_placeholder_sections():
    """안내문뿐인 절은 다듬을 것이 없다."""
    from src.brief import polish_section

    assert asyncio.run(polish_section(
        "결론", "_（결론을 작성하십시오.）_", allowed=set(),
        model=_Polisher("아무 말"))) is None


def test_polish_failure_returns_none(monkeypatch):
    from src.brief import polish_section

    class _Boom:
        async def ainvoke(self, _p):
            raise RuntimeError("down")

    assert asyncio.run(polish_section("검토", "본문 " * 40, allowed=set(),
                                      model=_Boom())) is None


def test_section_split_join_roundtrip():
    """절 단위로 갈랐다가 합쳐도 구조가 보존돼야 한다."""
    from src.brief import join_sections, split_sections

    body = "# 제목\n\n## 사실관계\n\n내용 A\n\n## 검토\n\n내용 B\n"
    secs = split_sections(body)
    assert [t for t, _ in secs] == ["", "사실관계", "검토"]
    back = join_sections(secs)
    assert "## 사실관계" in back and "내용 A" in back and "내용 B" in back


def test_polish_route_requires_onprem():
    """서면에는 사건 사실관계가 들어간다 — 상용 모델로 새면 안 된다."""
    import inspect

    from src.routes import reports as R

    src = inspect.getsource(R.polish_document)
    assert "onprem_fill()" in src and "status_code=503" in src


def test_polish_route_allows_partial_success():
    """한 절이 실패해도 나머지는 얻는다 — 전부 아니면 전무는 긴 문서에 가혹하다."""
    import inspect

    from src.routes import reports as R

    src = inspect.getsource(R.polish_document)
    assert "skipped" in src and "out.append((title, content))" in src


# ── 서면 종류(2026-10-06) ─────────────────────────────────────────────────────

def test_brief_kinds_sections_and_fallback():
    from src.brief import BRIEF_KINDS, sections_for, skeleton

    assert set(BRIEF_KINDS) == {"opinion", "review", "demand", "answer", "inquiry"}
    assert sections_for("answer")[0]["title"] == "상대방 주장 요지"
    assert sections_for("nope") is sections_for("opinion")
    s = skeleton("답변서", sections=sections_for("answer"))
    for h in ("## 상대방 주장 요지", "## 반박", "## 근거 법령·판례", "## 결론"):
        assert h in s


def test_compose_from_thread_by_kind_uses_same_material():
    from langchain_core.messages import AIMessage, HumanMessage

    from src.brief import compose_from_thread

    msgs = [HumanMessage(content="상대방은 2026-03 계약이 해지됐다고 주장한다."),
            AIMessage(content="검토 결과 " + "해지 통보가 유효하려면 서면이어야 한다. " * 6)]
    cites = [{"number": 1, "title": "민법 제543조", "source_kind": "doc"}]
    ans = compose_from_thread(msgs, cites, title="답변서", kind="answer")
    assert ans.startswith("# 답변서") and "## 상대방 주장 요지" in ans and "1. 상대방은" in ans
    assert "`[1]` 민법 제543조" in ans and "## 반박" in ans and "서면이어야" in ans
    dem = compose_from_thread(msgs, cites, title="", kind="demand")
    assert dem.startswith("# 내용증명") and "## 요구 사항" in dem
    # 의견서는 종전 경로 그대로
    op = compose_from_thread(msgs, cites, title="의견서", kind="opinion")
    assert "## 관련 법령·조문" in op and "## 결론" in op


def test_compose_from_thread_skips_hidden_step_turns():
    """연계 중간 단계(hidden)는 서면 재료가 아니다 — 종합·사용자 발화만."""
    from langchain_core.messages import AIMessage, HumanMessage

    from src.brief import compose_from_thread

    msgs = [HumanMessage(content="상대방의 주장을 분석해줘. [상대 주장] 구두 해지"),
            AIMessage(content="단계 산출 " * 20),
            HumanMessage(content="다음 단계를 거쳤어. 종합해줘"),
            AIMessage(content="종합: 구두 해지 통보는 " + "서면 요건을 못 갖춘다. " * 6)]
    hidden = [True, True, False, False]
    out = compose_from_thread(msgs, [], title="답변서", kind="answer", hidden=hidden)
    assert "구두 해지" in out and "종합: 구두 해지" in out
    assert "상대방의 주장을 분석해줘" not in out and "단계 산출" not in out
