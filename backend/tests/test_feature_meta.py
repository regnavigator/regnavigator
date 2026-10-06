"""기능 턴 렌더 메타(`feature`) — 저장·조회 왕복, 상한, 모델 입력 미포함 (2026-10-06)."""

from __future__ import annotations

import pytest


def test_feature_meta_as_stored_trims_and_drops_blank():
    from src.routes.chat import ChatFeatureMeta

    m = ChatFeatureMeta(id="prec_issues", title="판례", icon="balance",
                        values={"issue": " 구두 해지 ", "scope": "   ", "long": "x" * 5000},
                        run={"id": "run_1", "index": 2, "total": 6, "name": "상대 서면 대응"})
    s = m.as_stored()
    assert s["values"] == {"issue": " 구두 해지 ", "long": "x" * 4000}
    assert s["run"] == {"id": "run_1", "index": 2, "total": 6, "name": "상대 서면 대응"}
    assert s["icon"] == "balance"


def test_feature_meta_rejects_bad_shapes():
    from pydantic import ValidationError

    from src.routes.chat import ChatFeatureMeta

    with pytest.raises(ValidationError):
        ChatFeatureMeta(id="", title="x")
    with pytest.raises(ValidationError):
        ChatFeatureMeta(id="a", title="x", run={"id": "r", "index": 99, "total": 1})


def test_feature_not_in_anthropic_request():
    """`additional_kwargs.feature` 는 모델 요청 본문에 섞이지 않는다(6-1 실측 고정)."""
    from langchain_anthropic.chat_models import _format_messages
    from langchain_core.messages import HumanMessage

    m = HumanMessage(content="질문", additional_kwargs={"feature": {"id": "x", "values": {"a": "비밀사실"}}})
    _sys, fmt = _format_messages([m], model="claude-haiku-4-5-20251001")
    import json
    s = json.dumps(fmt, ensure_ascii=False)
    assert "feature" not in s and "비밀사실" not in s


def test_feature_roundtrip_through_repo_and_view(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "f.db"))
    import src.persistence.threads_repo as TR
    monkeypatch.setattr(TR, "_repo", None)
    from langchain_core.messages import HumanMessage

    from src.persistence.threads_repo import get_threads_repo
    from src.routes.chat import _message_view

    repo = get_threads_repo()
    repo.ensure_thread("t_f", user_id="u")
    meta = {"id": "legal_memo", "title": "쟁점별 법리 검토", "values": {},
            "run": {"id": "run_9", "index": 4, "total": 6}}
    repo.append_messages("t_f", [HumanMessage(content="…", id="m1", additional_kwargs={"feature": meta})])
    st = repo.get_state("t_f")
    view = _message_view(st.messages[0])
    assert view["feature"] == meta
    assert "feature" not in _message_view(HumanMessage(content="plain", id="m2"))
