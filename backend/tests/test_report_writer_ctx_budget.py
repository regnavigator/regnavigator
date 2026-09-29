"""writer conversation_context 예산(2026-08-21) — t_1398cb 컨텍스트 초과 400 재발 방지.

실측 사고: accumulated_citations 342건·24만자가 무예산으로 writer 프롬프트에
직렬화 → 서빙 모델 컨텍스트 초과 → vLLM 400, 보고서 3연속 실패. 맥락 필드에도
gather 분과 같은 예산을 적용한다.
"""
import json

from src.report_pipeline import (
    _WRITER_CTX_CITATION_CHARS,
    _writer_conversation_context,
)


def _big_ctx(n_cites=342, text_chars=600):
    return {
        "user_query": "질문 " * 3000,                     # 1.2만자
        "provisional_answer": "답변 " * 10000,            # 4만자
        "accumulated_citations": [
            {"id": f"c{i}", "title": f"의료기기법 제{i}조", "article": f"제{i}조",
             "text": "본문 " * (text_chars // 3), "url": "https://law.go.kr/x"}
            for i in range(n_cites)
        ],
    }


def test_context_is_bounded():
    out = _writer_conversation_context(_big_ctx())
    assert len(out["user_query"]) <= 4000
    assert len(out["provisional_answer"]) <= 8000
    acc_json = json.dumps(out["accumulated_citations"], ensure_ascii=False)
    # 예산 + citation 1건 여유(첫 건은 항상 포함 규칙) 안에서 멈춘다
    assert len(acc_json) <= _WRITER_CTX_CITATION_CHARS + 2000
    # 앞(최근 부여 번호 순서) 인용이 보존된다
    assert out["accumulated_citations"][0]["title"] == "의료기기법 제0조"
    # url 등 불필요 필드는 슬림화로 제거
    assert "url" not in out["accumulated_citations"][0]


def test_small_context_untouched():
    ctx = {"user_query": "짧은 질문", "provisional_answer": "짧은 답",
           "accumulated_citations": [{"id": "c1", "title": "t", "text": "x"}]}
    out = _writer_conversation_context(ctx)
    assert out["user_query"] == "짧은 질문"
    assert len(out["accumulated_citations"]) == 1


def test_empty_and_missing_fields():
    assert _writer_conversation_context({}) == {}
    out = _writer_conversation_context({"user_query": None})
    assert out["user_query"] is None
