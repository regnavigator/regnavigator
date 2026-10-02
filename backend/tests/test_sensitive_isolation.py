"""기밀 단계 격리 — 비기밀 턴은 기밀 메시지를 보지 못한다 (2026-10-02).

**이 파일이 지키는 것이 단계별 기밀의 전부다.**

조합(워크플로)에서 단계마다 기밀 여부를 다르게 줄 수 있게 하면서, 요청 컨텍스트는
여전히 스레드 전체 이력이면 보호가 아니라 **보호하는 척**이 된다 — 2단계에서 원내
모델로 처리한 사건 내용이 3단계(비기밀)에서 통째로 상용 모델로 나간다.

그래서 세 가지를 고정한다:
1. 기밀 턴에서 나온 메시지는 `sensitive=1` 로 저장된다.
2. 비기밀 턴의 **요청 메시지 목록에 그 본문이 없다**.
3. 기밀 턴은 전체 이력을 본다(원내 모델이므로 안전).

그리고 같은 표면의 누수 하나 더: 기밀 스레드의 자동 제목이 상용 모델을 쓰지 않는다.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.chat_loop import SENSITIVE_PLACEHOLDER, _drop_sensitive
from src.persistence.threads_repo import ThreadState

SECRET = "의뢰인 김모씨가 2026-03 무신고 영업을 했다는 사실관계"


# ── ① 저장: 기밀 턴 메시지에 표시가 붙는가 ────────────────────────────────

@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "s.db"))
    import src.persistence.threads_repo as TR

    monkeypatch.setattr(TR, "_repo", None)
    yield TR.get_threads_repo()
    monkeypatch.setattr(TR, "_repo", None)


def test_confidential_messages_are_marked(repo):
    repo.ensure_thread("t1", user_id="u1")
    repo.append_messages("t1", [HumanMessage(content="공개 질문")], sensitive=False)
    repo.append_messages("t1", [HumanMessage(content=SECRET)], sensitive=True)

    st = repo.get_state("t1")
    assert st.sensitive == [False, True]


def test_sensitive_defaults_false_for_old_rows(repo):
    """기밀 기능 도입 전 데이터는 전부 비기밀로 읽힌다."""
    repo.ensure_thread("t2", user_id="u1")
    repo.append_messages("t2", [HumanMessage(content="옛 메시지")])
    assert repo.get_state("t2").sensitive == [False]


# ── ② 필터: 비기밀 턴의 컨텍스트에서 빠지는가 ─────────────────────────────

def _state(msgs, flags) -> ThreadState:
    return ThreadState(
        thread_id="t", messages=msgs, steps=[], selected_law_keys=[],
        seqs=list(range(len(msgs))), sensitive=flags,
    )


def test_sensitive_body_never_reaches_non_confidential_turn():
    """핵심 불변식 — 기밀 본문이 비기밀 턴 컨텍스트에 남아 있으면 안 된다."""
    st = _state(
        [
            HumanMessage(content="1단계: 인허가 절차 알려줘"),
            AIMessage(content="1단계 답변"),
            HumanMessage(content=SECRET),              # 기밀 단계
            ToolMessage(content="기밀 검색 결과", tool_call_id="tc1"),
            AIMessage(content="기밀 단계 답변 — 쟁점 3건"),
            HumanMessage(content="3단계: 판례 찾아줘"),
        ],
        [False, False, True, True, True, False],
    )

    out = _drop_sensitive(st)
    blob = "\n".join(str(m.content) for m in out.messages)

    assert SECRET not in blob
    assert "기밀 검색 결과" not in blob
    assert "기밀 단계 답변" not in blob
    # 공개 내용은 그대로 남는다 — 필터가 대화를 통째로 날리면 안 된다.
    assert "1단계 답변" in blob
    assert "3단계: 판례 찾아줘" in blob


def test_dropped_span_leaves_one_placeholder():
    """연속된 기밀 구간은 표식 하나로 합친다 — 맥락 단절을 날조로 메우지 않도록."""
    st = _state(
        [HumanMessage(content="공개"), HumanMessage(content=SECRET),
         AIMessage(content="기밀 답"), HumanMessage(content="공개2")],
        [False, True, True, False],
    )
    out = _drop_sensitive(st)
    bodies = [str(m.content) for m in out.messages]
    assert bodies.count(SENSITIVE_PLACEHOLDER) == 1
    assert bodies == ["공개", SENSITIVE_PLACEHOLDER, "공개2"]


def test_seqs_stay_parallel_to_messages():
    """`seqs` 가 어긋나면 대화 압축이 엉뚱한 지점을 자른다(둘을 zip 한다)."""
    st = _state(
        [HumanMessage(content="a"), HumanMessage(content=SECRET),
         AIMessage(content="b")],
        [False, True, False],
    )
    out = _drop_sensitive(st)
    assert len(out.seqs) == len(out.messages)


def test_no_sensitive_returns_state_untouched():
    """기밀 메시지가 없으면 원본을 그대로 돌려준다(불필요한 복제 금지)."""
    st = _state([HumanMessage(content="a")], [False])
    assert _drop_sensitive(st) is st


def test_filtered_state_has_no_remaining_flags():
    """걸러낸 결과는 '기밀 없음' 상태여야 한다 — 두 번 걸러도 같은 결과."""
    st = _state(
        [HumanMessage(content="a"), HumanMessage(content=SECRET)],
        [False, True],
    )
    out = _drop_sensitive(st)
    assert not any(out.sensitive)
    assert _drop_sensitive(out) is out


# ── ③ 기밀 턴은 전체를 본다 ──────────────────────────────────────────────

def test_confidential_turn_sees_everything():
    """기밀 턴은 필터를 타지 않는다 — `_run_turn` 이 `if not confidential` 로 건다.

    여기서는 그 규약을 문서화하고, 필터 자체가 호출되지 않았을 때의 상태를 고정한다.
    """
    msgs = [HumanMessage(content=SECRET), AIMessage(content="기밀 답")]
    st = _state(msgs, [True, True])
    # 필터를 **안 거친** 상태가 기밀 턴이 보는 것
    assert st.messages is msgs
    blob = "\n".join(str(m.content) for m in st.messages)
    assert SECRET in blob


# ── ④ 같은 표면의 누수: 자동 제목 ────────────────────────────────────────

def test_auto_title_does_not_call_llm_for_confidential_thread(tmp_path, monkeypatch):
    """기밀 스레드는 제목도 밖으로 내보내지 않는다.

    종전엔 첫 질문 500자를 상용 `TITLE_MODEL` 로 보냈다 — 대화는 전부 원내로
    도는데 제목 생성만 조용히 빠져나가고 있었다. 사건 요지는 보통 첫 질문에 다
    들어 있어 유출 범위가 작지 않다.
    """
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("REPORTS_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)

    import src.persistence as P
    import src.persistence.threads_repo as TR

    monkeypatch.setattr(TR, "_repo", None)
    for f in (P.get_reports_repo, P.get_report_runs_repo, P.get_blob_store,
              P.get_users_repo, P.get_events_repo):
        f.cache_clear()

    from src.middleware import AUTH_DEV_BYPASS_USER_ID

    repo = TR.get_threads_repo()
    repo.ensure_thread("t_conf", user_id=AUTH_DEV_BYPASS_USER_ID)
    repo.append_messages("t_conf", [HumanMessage(content=SECRET)], sensitive=True)
    repo.mark_confidential("t_conf")

    called: list[str] = []

    import src.chat_loop as CL

    def _boom(spec):
        called.append(spec)
        raise AssertionError("기밀 스레드에서 상용 모델을 불렀다")

    monkeypatch.setattr(CL, "_base_model", _boom)

    from fastapi.testclient import TestClient

    from src.api import app

    with TestClient(app) as api:
        r = api.post("/chat/t_conf/auto-title")

    assert r.status_code == 200, r.text
    assert called == []
    # 폴백 제목은 질문 앞부분 — 모델을 안 거치고 로컬에서 만든다.
    assert r.json()["title"] == SECRET[:20]

    monkeypatch.setattr(TR, "_repo", None)


# ── ⑤ 보조 LLM 호출 정책 — 기밀 턴에서 상용 팩토리 호출 0회 (2026-10-03) ─────
#
# 감사 결과: 기밀 모드는 답변 모델 1개에만 걸려 있었고, 같은 턴의 보조 호출
# (압축 요약·커버리지 심판·적용가능성·grounding·무인용 감사)은 전부 상용 Haiku 로
# 나갔다. `aux_model` 이 그 정책의 단일 관문이다 — 여기서 고정한다.

def _set_policy(confidential, local_model=None):
    from src import chat_loop as cl
    cl.set_aux_policy(confidential=confidential, local_model=local_model)


def test_aux_model_non_confidential_uses_commercial(monkeypatch):
    from src import chat_loop as cl
    calls = []
    monkeypatch.setattr(cl, "build_chat_model", lambda spec, **k: calls.append(spec) or "M")
    _set_policy(False)
    assert cl.aux_model("anthropic:claude-haiku-4-5", max_tokens=100) == "M"
    assert calls == ["anthropic:claude-haiku-4-5"]


def test_aux_model_confidential_without_local_skips(monkeypatch):
    """핵심 불변식 — 기밀 턴 + 원내 없음이면 **None**(건너뜀). 상용 팩토리 호출 0."""
    from src import chat_loop as cl
    monkeypatch.setattr(cl, "build_chat_model",
                        lambda *a, **k: pytest.fail("기밀 턴에서 상용 모델을 만들었다"))
    _set_policy(True, local_model=None)
    assert cl.aux_model("anthropic:claude-haiku-4-5", max_tokens=100) is None


def test_aux_model_confidential_with_local_routes_onprem(monkeypatch):
    from src import chat_loop as cl, skill_local
    monkeypatch.setattr(cl, "build_chat_model",
                        lambda *a, **k: pytest.fail("기밀 턴에서 상용 모델을 만들었다"))
    seen = {}
    monkeypatch.setattr(skill_local, "build_model",
                        lambda mid, *, max_tokens: seen.update(mid=mid, mt=max_tokens) or "LOCAL")
    _set_policy(True, local_model="qwen-local")
    assert cl.aux_model("anthropic:claude-haiku-4-5", max_tokens=321) == "LOCAL"
    assert seen == {"mid": "qwen-local", "mt": 321}


@pytest.mark.parametrize("fn_path,kwargs,expect", [
    ("src.coverage.judge_coverage", dict(question="q", citations=[{"number": 1, "title": "t"}]), None),
    ("src.applicability.judge", dict(question="q", citations=[
        {"number": 1, "title": "식품위생법 제37조", "snippet": "영업신고"}]), {}),
])
def test_aux_callers_skip_in_confidential_turn(monkeypatch, fn_path, kwargs, expect):
    """보조 호출자들이 aux_model 의 None 을 '생략'으로 처리한다(예외·상용 폴백 없음)."""
    import asyncio
    import importlib
    from src import chat_loop as cl
    monkeypatch.setattr(cl, "build_chat_model",
                        lambda *a, **k: pytest.fail("기밀 턴에서 상용 모델을 만들었다"))
    _set_policy(True, local_model=None)
    mod_name, fn_name = fn_path.rsplit(".", 1)
    fn = getattr(importlib.import_module(mod_name), fn_name)
    out = asyncio.run(fn(**kwargs))
    assert out == expect


def test_grounding_skips_without_marking_verified(monkeypatch):
    """검증을 **안 한** 것을 검증됐다고 찍지 않는다 — 인용은 그대로, verified 미설정."""
    import asyncio
    from src import chat_loop as cl, grounding
    monkeypatch.setattr(cl, "build_chat_model",
                        lambda *a, **k: pytest.fail("기밀 턴에서 상용 모델을 만들었다"))
    _set_policy(True, local_model=None)
    cites = [{"number": 1, "title": "t", "text": "원문 본문", "snippet": "원문"}]
    out = asyncio.run(grounding.ground_citations("본문 [1]", cites))
    assert out == cites
    assert "verified" not in out[0]
    assert asyncio.run(grounding.audit_uncited_claims("본문 본문 본문 본문 본문 본문 본문 본문", "hay")) == []


def test_summary_skips_in_confidential_turn(monkeypatch):
    """압축 요약(L1) — 기밀 턴 + 원내 없음이면 빈 요약(무압축 진행)."""
    import asyncio
    from src import chat_loop as cl
    monkeypatch.setattr(cl, "build_chat_model",
                        lambda *a, **k: pytest.fail("기밀 턴에서 상용 모델을 만들었다"))
    _set_policy(True, local_model=None)
    assert asyncio.run(cl._summarize_text("오래된 턴 블록", None)) == ""


def test_policy_is_cleared_between_turns():
    """정책이 턴 사이에 새지 않는다 — 비기밀 턴이 앞 기밀 턴 정책을 물려받으면
    보조 호출이 조용히 생략된다(2026-10-03 실측: 전체 테스트 순서에서만 재현)."""
    from src import chat_loop as cl
    _set_policy(True, local_model=None)
    cl._AUX_POLICY.set(None)
    assert cl.is_confidential_turn() is False


# ── ⑥ 보고서 트리거 — 기밀 스레드는 422 ──────────────────────────────────

def test_report_trigger_rejects_confidential_thread(tmp_path, monkeypatch):
    """보고서 파이프라인은 기밀을 모른다(decompose·writer 가 상용/외부 GPU) —
    `confidential_seen` 스레드는 트리거 자체를 막는다."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("REPORTS_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)
    import src.persistence as P
    import src.persistence.threads_repo as TR
    monkeypatch.setattr(TR, "_repo", None)
    for f in (P.get_reports_repo, P.get_report_runs_repo, P.get_blob_store,
              P.get_users_repo, P.get_events_repo):
        f.cache_clear()
    from src.middleware import AUTH_DEV_BYPASS_USER_ID
    repo = TR.get_threads_repo()
    repo.ensure_thread("t_rc", user_id=AUTH_DEV_BYPASS_USER_ID)
    repo.append_messages("t_rc", [HumanMessage(content=SECRET)], sensitive=True)
    repo.mark_confidential("t_rc")

    from fastapi.testclient import TestClient
    from src.api import app
    with TestClient(app) as api:
        r = api.post("/reports", json={"thread_id": "t_rc",
                                       "idempotency_key": "rpt_abc123"})
    assert r.status_code == 422, r.text
    assert "기밀" in r.json()["detail"]
    monkeypatch.setattr(TR, "_repo", None)


# ── ⑦ 인가 거부 기본값 ────────────────────────────────────────────────────

def test_owner_check_rejects_when_owner_missing(tmp_path, monkeypatch):
    """소유자 없는 스레드는 **누구에게도** 열리지 않는다(종전: 전원에게 열림)."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "o.db"))
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    import src.persistence.threads_repo as TR
    monkeypatch.setattr(TR, "_repo", None)
    TR.get_threads_repo().ensure_thread("t_noowner")  # user_id 없음

    from fastapi.testclient import TestClient
    from src.api import app
    with TestClient(app) as api:
        assert api.get("/chat/t_noowner/state").status_code == 404
    monkeypatch.setattr(TR, "_repo", None)


# ── ⑧ sensitive 행 at-rest 암호화 ────────────────────────────────────────

def test_sensitive_rows_encrypted_at_rest(tmp_path, monkeypatch):
    """키가 있으면 기밀 행 본문이 DB 에 평문으로 남지 않고, 읽으면 투명 복호."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FILLED_VALUES_ENC_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "e.db"))
    from src.persistence import field_crypto
    field_crypto.reset_cache()
    import src.persistence.threads_repo as TR
    monkeypatch.setattr(TR, "_repo", None)
    repo = TR.get_threads_repo()
    repo.ensure_thread("t_enc", user_id="u1")
    repo.append_messages("t_enc", [HumanMessage(content="공개")], sensitive=False)
    repo.append_messages("t_enc", [HumanMessage(content=SECRET)], sensitive=True)

    import sqlite3
    con = sqlite3.connect(str(tmp_path / "e.db"))
    rows = con.execute("SELECT data_json, sensitive FROM chat_messages ORDER BY seq").fetchall()
    assert "공개" in rows[0][0] and rows[0][1] == 0
    assert SECRET not in rows[1][0] and rows[1][1] == 1   # 평문 없음
    assert '"enc"' in rows[1][0]

    msgs = repo.get_state("t_enc").messages
    assert [str(m.content) for m in msgs] == ["공개", SECRET]  # 투명 복호
    field_crypto.reset_cache()
    monkeypatch.setattr(TR, "_repo", None)
