"""자체 chat 루프(src/chat_loop.py) 단위 테스트 — ADR-0001 Phase 1.

가짜 모델 주입(`models=` 파라미터)으로 LLM 없이 루프 의미론을 검증한다:
- 도구 없는 단답 → token/done 이벤트 + 메시지 영속
- PII at-rest 스크럽 (저장 원문에 주민번호 없음)
- 도구 호출 → steps 이벤트 + ToolMessage 영속 + 인용 번호
- ask_clarify → clarify 이벤트 + 턴 종료 (interrupt 아님)
- intent 강제 → forced 바인딩 선택
- threads_repo merge/selected_law_keys 의미론
"""

from __future__ import annotations

import asyncio
import json

import pytest

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage


def _clear_persistence_caches():
    """lru_cache 된 repo 들이 테스트 tmp 경로로 오염돼 다른 테스트(예:
    test_quota_admin)에 새는 것 방지 — test_token_logger 와 동일 패턴."""
    from src import persistence as P

    for f in (P.get_users_repo, P.get_events_repo, P.get_reports_repo,
              P.get_feedback_repo, P.get_report_runs_repo, P.get_blob_store):
        f.cache_clear()


@pytest.fixture()
def threads_repo(tmp_path, monkeypatch):
    """테스트 스코프 SQLite ThreadsRepo — 전역 캐시 리셋."""
    import src.persistence.threads_repo as tr

    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "chat.db"))
    monkeypatch.setattr(tr, "_repo", None)
    _clear_persistence_caches()
    yield tr.get_threads_repo()
    monkeypatch.setattr(tr, "_repo", None)
    _clear_persistence_caches()


@pytest.fixture(autouse=True)
def _quiet_env(monkeypatch):
    monkeypatch.setenv("CHAT_GROUNDING_GATE_DISABLE", "1")  # LLM 콜 차단
    monkeypatch.delenv("PII_NER_API_URL", raising=False)    # regex-only 스크럽
    monkeypatch.setenv("INTENT_SEARCH_DISABLE", "1")        # 기본 비강제(개별 테스트에서 켬)


class FakeModel:
    """astream 만 흉내 — responses 순서대로 chunk 방출, 호출 기록."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[list] = []

    async def astream(self, messages, config=None):
        self.calls.append(list(messages))
        r = self.responses.pop(0)
        if r.get("tool"):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[{
                    "name": r["tool"],
                    "args": json.dumps(r.get("args") or {}),
                    "id": r.get("tc_id", "tc_1"),
                    "index": 0,
                    "type": "tool_call_chunk",
                }],
            )
        else:
            for part in r.get("chunks") or [r.get("text", "")]:
                yield AIMessageChunk(content=part)


def _collect(thread_id: str, text: str, models, **kw) -> list[dict]:
    from src.chat_loop import run_chat_turn

    async def _run():
        return [ev async for ev in run_chat_turn(thread_id, text, models=models, **kw)]

    return asyncio.run(_run())


def test_plain_answer_streams_and_persists(threads_repo):
    normal = FakeModel([{"chunks": ["안녕", "하세요"]}])
    events = _collect("t1", "안녕", (normal, normal))

    types = [e["type"] for e in events]
    assert types[0] == "meta"
    assert "token" in types
    done = events[-1]
    assert done["type"] == "done" and done["text"] == "안녕하세요"

    state = threads_repo.get_state("t1")
    assert [m.type for m in state.messages] == ["human", "ai"]


def test_pii_scrubbed_at_rest(threads_repo):
    normal = FakeModel([{"text": "답변"}])
    _collect("t2", "제 주민번호는 900101-1234567 입니다", (normal, normal))

    state = threads_repo.get_state("t2")
    stored = state.messages[0].content
    assert "900101-1234567" not in stored
    # egress — 모델이 받은 request 에도 원문 없음
    sent = "".join(
        str(getattr(m, "content", "")) for m in normal.calls[0]
    )
    assert "900101-1234567" not in sent


def test_tool_call_flow_steps_and_citations(threads_repo, monkeypatch):
    import src.chat_loop as cl
    from src.tools.search import QdrantCore

    def fake_run_qdrant(query, *, top_k=None, target_types=None):
        hit = {"article_key": "ak1", "law_title": "의료기기법", "article_num": "제6조",
               "snippet": "허가 조문"}
        from src.tools.citations import build_citation_from_api_hit
        return QdrantCore(
            built=[("ak1", hit, build_citation_from_api_hit(hit, 0))],
            final_keys=["ak1"], qdrant_keys=["ak1"],
            pg_meta_by_key={}, qdrant_by_key={"ak1": hit},
        )

    monkeypatch.setattr(cl, "run_qdrant", fake_run_qdrant)

    normal = FakeModel([
        {"tool": "qdrant_search", "args": {"query": "의료기기 허가"}},
        {"text": "허가는 식약처 소관입니다 [1]"},
    ])
    events = _collect("t3", "의료기기 허가 절차는?", (normal, normal))

    steps_events = [e for e in events if e["type"] == "steps"]
    assert steps_events, "steps 이벤트 누락"
    final_steps = steps_events[-1]["steps"]
    done_steps = [s for s in final_steps if s.get("status") == "done"]
    assert done_steps and done_steps[0]["tool_name"] == "qdrant_search"
    cites = done_steps[0].get("citations") or []
    assert cites and cites[0]["number"] == 1

    state = threads_repo.get_state("t3")
    assert [m.type for m in state.messages] == ["human", "ai", "tool", "ai"]
    assert len(normal.calls) == 2  # tool 후 재호출


def test_clarify_ends_turn(threads_repo):
    normal = FakeModel([
        {"tool": "ask_clarify",
         "args": {"question": "어떤 제품군인가요?", "options": ["의료기기", "의약품"]}},
        {"text": "이 응답은 나오면 안 됨"},
    ])
    events = _collect("t4", "규제", (normal, normal))

    clarify = [e for e in events if e["type"] == "clarify"]
    assert clarify and clarify[0]["question"] == "어떤 제품군인가요?"
    assert clarify[0]["options"] == ["의료기기", "의약품"]
    done = events[-1]
    assert done["type"] == "done" and done.get("clarify_pending") is True
    assert len(normal.calls) == 1  # 턴 종료 — 모델 재호출 없음

    # 히스토리 유효성 — tool_use 에 tool_result 짝이 남아야 다음 턴이 유효
    state = threads_repo.get_state("t4")
    assert [m.type for m in state.messages] == ["human", "ai", "tool"]


def test_intent_forces_qdrant_binding(threads_repo, monkeypatch):
    monkeypatch.setenv("INTENT_SEARCH_DISABLE", "0")
    import src.guardrail.intent as intent_mod
    monkeypatch.setattr(intent_mod, "should_search", lambda text, ctx=None: True)

    normal = FakeModel([{"text": "일반 답"}])
    forced = FakeModel([{"text": "강제 후 답"}])
    events = _collect("t5", "의료기기 임상 규제 알려줘", (normal, forced))

    # 첫 호출은 forced 바인딩 (규제 의도 + 이번 턴 미검색)
    assert len(forced.calls) == 1
    assert len(normal.calls) == 0
    assert events[-1]["text"] == "강제 후 답"


def test_web_prefetch_injects_without_llm_roundtrip(threads_repo, monkeypatch):
    """웹 프리페치(지연 개선 2026-07-25) — 규제 턴에서 tavily 가 LLM 왕복 없이
    tool_use/tool_result 쌍으로 주입되는지. 구 forced_web 바인딩(웹 쿼리 생성용
    LLM 호출)은 프리페치 실패 시 폴백으로만 발화해야 한다."""
    import src.chat_loop as cl
    from src.tools.search import QdrantCore

    monkeypatch.setenv("INTENT_SEARCH_DISABLE", "0")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    import src.guardrail.intent as intent_mod
    monkeypatch.setattr(intent_mod, "should_search", lambda text, ctx=None: True)

    def fake_run_qdrant(query, *, top_k=None, target_types=None):
        hit = {"article_key": "ak1", "law_title": "의료기기법", "article_num": "제6조",
               "snippet": "허가 조문"}
        from src.tools.citations import build_citation_from_api_hit
        return QdrantCore(
            built=[("ak1", hit, build_citation_from_api_hit(hit, 0))],
            final_keys=["ak1"], qdrant_keys=["ak1"],
            pg_meta_by_key={}, qdrant_by_key={"ak1": hit},
        )

    def fake_run_tavily(query, *, max_results=None):
        r = {"title": "식약처 보도자료", "url": "https://mfds.go.kr/a", "content": "웹 본문"}
        from src.tools.citations import extract_web_citation
        return [(r, extract_web_citation(r, 0))]

    monkeypatch.setattr(cl, "run_qdrant", fake_run_qdrant)
    monkeypatch.setattr(cl, "run_tavily", fake_run_tavily)

    forced = FakeModel([{"tool": "qdrant_search", "args": {"query": "허가"}}])
    forced_web = FakeModel([{"text": "이게 나오면 폴백이 잘못 발화한 것"}])
    normal = FakeModel([{"text": "허가는 식약처 소관 [1], 최근 동향 [2]"}])
    events = _collect("t_wp", "의료기기 허가 절차는?", (normal, forced, forced_web))

    # forced_web(웹 쿼리 생성용 LLM 왕복)은 호출되지 않아야 — 프리페치가 대체.
    assert len(forced_web.calls) == 0
    assert len(forced.calls) == 1 and len(normal.calls) == 1

    # 히스토리: human → ai(qdrant tc) → tool → ai(주입 tavily tc) → tool → ai(답)
    state = threads_repo.get_state("t_wp")
    assert [m.type for m in state.messages] == [
        "human", "ai", "tool", "ai", "tool", "ai"]

    # 웹 step + 인용 번호 연속(qdrant [1] 다음 웹 [2]).
    steps_events = [e for e in events if e["type"] == "steps"]
    done_steps = [s for s in steps_events[-1]["steps"] if s.get("status") == "done"]
    tools = [s["tool_name"] for s in done_steps]
    assert "tavily_search" in tools
    web_cites = [c for s in done_steps if s["tool_name"] == "tavily_search"
                 for c in (s.get("citations") or [])]
    assert web_cites and web_cites[0]["number"] == 2


def test_web_prefetch_failure_skips_web_this_turn(threads_repo, monkeypatch):
    """프리페치 실패(쿼터 초과·tavily 다운) → 이번 턴 웹 스킵.

    구 forced_web 바인딩 폴백은 두지 않는다 — 방금 실패한 웹 검색을 LLM 왕복
    (쿼리 생성)까지 태워 재시도해봐야 또 실패한다(실측 2026-07-25 Tavily 쿼터
    초과: 폴백 회차가 LLM 1회 + abort 만 낭비). qdrant 근거만으로 답변 진행."""
    import src.chat_loop as cl
    from src.tools.search import QdrantCore, SearchError

    monkeypatch.setenv("INTENT_SEARCH_DISABLE", "0")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    import src.guardrail.intent as intent_mod
    monkeypatch.setattr(intent_mod, "should_search", lambda text, ctx=None: True)

    def fake_run_qdrant(query, *, top_k=None, target_types=None):
        hit = {"article_key": "ak1", "law_title": "의료기기법", "article_num": "제6조",
               "snippet": "허가 조문"}
        from src.tools.citations import build_citation_from_api_hit
        return QdrantCore(
            built=[("ak1", hit, build_citation_from_api_hit(hit, 0))],
            final_keys=["ak1"], qdrant_keys=["ak1"],
            pg_meta_by_key={}, qdrant_by_key={"ak1": hit},
        )

    def failing_run_tavily(query, *, max_results=None):
        raise SearchError("웹 검색 일시 실패. 잠시 후 다시 시도해주세요.")

    monkeypatch.setattr(cl, "run_qdrant", fake_run_qdrant)
    monkeypatch.setattr(cl, "run_tavily", failing_run_tavily)

    forced = FakeModel([{"tool": "qdrant_search", "args": {"query": "허가"}}])
    forced_web = FakeModel([{"text": "이게 나오면 웹 스킵이 잘못된 것"}])
    normal = FakeModel([{"text": "허가는 식약처 소관 [1]"}])
    events = _collect("t_wpf", "의료기기 허가 절차는?", (normal, forced, forced_web))

    assert len(forced_web.calls) == 0  # 웹 회차 없음 — LLM 낭비 제거
    assert events[-1]["type"] == "done"
    assert events[-1]["text"].startswith("허가는 식약처")
    # 히스토리에 tavily 흔적 없음(주입·바인딩 둘 다 스킵)
    state = threads_repo.get_state("t_wpf")
    assert [m.type for m in state.messages] == ["human", "ai", "tool", "ai"]


def test_compaction_summarizes_old_turns(threads_repo, monkeypatch):
    """임계 초과 시 오래된 턴이 요약으로 대체되고(human 경계 컷), 요약이 영속된다."""
    import src.chat_loop as cl
    from langchain_core.messages import AIMessage

    monkeypatch.setenv("CHAT_SUMMARY_TRIGGER_TOKENS", "10")  # 즉시 트리거
    monkeypatch.setenv("CHAT_SUMMARY_KEEP_TURNS", "1")

    summarize_calls: list[tuple] = []

    async def fake_summarize(block, prev):
        summarize_calls.append((block, prev))
        return "요약: 사용자는 SaMD 제조사, 2등급 허가 문의함"

    monkeypatch.setattr(cl, "_summarize_text", fake_summarize)

    # 과거 2턴 시드 (각 human+ai)
    threads_repo.ensure_thread("t7")
    threads_repo.append_messages("t7", [
        HumanMessage(content="우리는 SaMD 제조사입니다. 허가 절차는?", id="m1"),
        AIMessage(content="허가 절차는 다음과 같습니다..." * 20, id="m2"),
        HumanMessage(content="2등급이면 어떻게 되나요?", id="m3"),
        AIMessage(content="2등급은 인증 대상으로..." * 20, id="m4"),
    ])

    normal = FakeModel([{"text": "세 번째 답"}])
    _collect("t7", "그럼 임상은요?", (normal, normal))

    # 요약 1회 호출 + 영속
    assert len(summarize_calls) == 1
    st = threads_repo.get_state("t7")
    assert st.summary_text and "SaMD" in st.summary_text
    assert st.summary_upto_seq is not None

    # 모델 request: system 에 요약 포함, 오래된 턴(m1·m2)은 미포함
    sent = normal.calls[0]
    sys_content = sent[0].content                # SystemMessage (블록 리스트 or 문자열)
    sys_text = (
        sys_content if isinstance(sys_content, str)
        else " ".join(b.get("text", "") for b in sys_content)
    )
    assert "요약:" in sys_text
    sent_ids = [getattr(m, "id", None) for m in sent]
    assert "m1" not in sent_ids and "m2" not in sent_ids
    assert "m3" in sent_ids                       # keep_turns=1 → 직전 턴 유지

    # DB 원본은 보존 (요약은 working set 만)
    assert [m.id for m in st.messages[:4]] == ["m1", "m2", "m3", "m4"]


def test_same_thread_turns_serialize(threads_repo):
    """같은 thread 동시 요청은 직렬화 — 히스토리 interleave 방지 (20인 안정성)."""
    import src.chat_loop as cl

    class SlowModel(FakeModel):
        async def astream(self, messages, config=None):
            await asyncio.sleep(0.05)
            async for ch in super().astream(messages, config):
                yield ch

    async def _run_both():
        m1 = SlowModel([{"text": "답1"}])
        m2 = SlowModel([{"text": "답2"}])

        async def consume(msg, models):
            return [e async for e in cl.run_chat_turn("t8", msg, models=models)]

        await asyncio.gather(consume("질문1", (m1, m1)), consume("질문2", (m2, m2)))

    asyncio.run(_run_both())

    state = threads_repo.get_state("t8")
    types = [m.type for m in state.messages]
    # 직렬화되면 human,ai,human,ai — interleave(human,human,ai,ai)면 실패
    assert types == ["human", "ai", "human", "ai"]
    # 락 dict 누수 없음
    assert "t8" not in cl._turn_locks and "t8" not in cl._turn_lock_refs


def test_fe_read_endpoints(threads_repo, monkeypatch):
    """FE 조회 3종 — 목록/state 리로드/소유자 격리 (Phase 4 계약)."""
    from fastapi.testclient import TestClient
    from langchain_core.messages import AIMessage
    from src.api import app

    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "fe@test.dev")

    threads_repo.ensure_thread("t9", user_id="dev-bypass-user")
    threads_repo.append_messages("t9", [
        HumanMessage(content="질문입니다", id="m1"),
        AIMessage(content="답변입니다 [1]", id="m2"),
    ])
    threads_repo.merge_steps("t9", [{
        "id": "s1", "status": "done", "ts": 1, "tool_name": "qdrant_search",
        "citations": [{"id": "c1", "number": 1, "title": "의료기기법"}],
    }])
    threads_repo.set_title("t9", "테스트 제목")
    # 남의 thread — 목록·조회에서 보이면 안 됨
    threads_repo.ensure_thread("t_other", user_id="someone-else")

    client = TestClient(app)

    r = client.get("/chat/threads")
    assert r.status_code == 200
    tids = [t["thread_id"] for t in r.json()["threads"]]
    assert "t9" in tids and "t_other" not in tids

    r = client.get("/chat/t9/state")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "테스트 제목"
    assert [m["type"] for m in body["messages"]] == ["human", "ai"]
    assert body["steps"][0]["citations"][0]["number"] == 1

    assert client.get("/chat/t_other/state").status_code == 404  # 소유자 격리
    assert client.get("/chat/no_such/state").status_code == 404

    # rename + delete (Phase 4 FE 계약)
    r = client.patch("/chat/t9", json={"title": "새 제목"})
    assert r.status_code == 200 and r.json()["title"] == "새 제목"
    assert client.patch("/chat/t_other", json={"title": "탈취"}).status_code == 404
    assert client.delete("/chat/t_other").status_code == 404
    assert client.delete("/chat/t9").status_code == 200
    assert client.get("/chat/t9/state").status_code == 404  # 삭제 확인


def test_thread_ownership_on_write_paths(threads_repo, monkeypatch):
    """POST /chat·/reports 소유권 — 남의 thread 이어쓰기/보고서 생성 차단."""
    from fastapi.testclient import TestClient
    from src.api import app

    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "owner@test.dev")  # → dev-bypass-user

    threads_repo.ensure_thread("t_mine", user_id="dev-bypass-user")
    # 진입 허들 통과용 실질 상담 맥락(실질 주제 + 누적 citation) — 이 테스트는
    # 소유권 라우팅(404/202) 검증이 목적이므로 게이트는 넘겨야 함.
    threads_repo.append_messages("t_mine", [
        HumanMessage(content="의료기기 제조 허가 절차를 알려줘", id="m1"),
        AIMessage(content="허가 절차는 다음과 같습니다 [1]", id="m1a"),
    ])
    threads_repo.merge_steps("t_mine", [{
        "id": "s1", "tool_name": "qdrant_search", "status": "done",
        "citations": [{"id": "c1", "number": 1, "title": "의료기기법 제6조"}],
    }])
    threads_repo.ensure_thread("t_theirs", user_id="someone-else")
    threads_repo.append_messages("t_theirs", [HumanMessage(content="남의 질문", id="m2")])

    spawned = []
    import src.report_runner as rr
    monkeypatch.setattr(rr, "spawn_report_job", lambda **kw: spawned.append(kw))

    client = TestClient(app)

    # 남의 thread 에 채팅 이어쓰기 → 404 (스트림 시작 전 차단)
    r = client.post("/chat", json={"thread_id": "t_theirs", "message": "hi"})
    assert r.status_code == 404

    # 남의 thread 로 보고서 → 404, 잡 미생성
    r = client.post("/reports", json={
        "thread_id": "t_theirs", "idempotency_key": "rpt_steal_1"})
    assert r.status_code == 404 and not spawned

    # 미존재 thread 보고서 → 404 (빈 thread 보고서 불가)
    r = client.post("/reports", json={
        "thread_id": "t_none", "idempotency_key": "rpt_none_1"})
    assert r.status_code == 404

    # 내 thread 보고서 → 202 + 잡 spawn
    r = client.post("/reports", json={
        "thread_id": "t_mine", "idempotency_key": "rpt_mine_1"})
    assert r.status_code == 202
    assert spawned and spawned[0]["thread_id"] == "t_mine"


def test_report_duplicate_trigger_blocked_per_thread(threads_repo, monkeypatch):
    """스레드당 동시 보고서 1개 — 진행 중 다른 키 트리거는 409(report_in_progress),
    같은 키 재시도는 멱등 200(running). (2026-07-24 챗×보고서 간섭 정리)"""
    from fastapi.testclient import TestClient
    from src.api import app

    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "owner@test.dev")

    threads_repo.ensure_thread("t_dup", user_id="dev-bypass-user")
    threads_repo.append_messages("t_dup", [
        HumanMessage(content="의료기기 제조 허가 절차를 알려줘", id="m1"),
        AIMessage(content="허가 절차는 다음과 같습니다 [1]", id="m1a"),
    ])
    threads_repo.merge_steps("t_dup", [{
        "id": "s1", "tool_name": "qdrant_search", "status": "done",
        "citations": [{"id": "c1", "number": 1, "title": "의료기기법 제6조"}],
    }])

    spawned = []
    import src.report_runner as rr
    monkeypatch.setattr(rr, "spawn_report_job", lambda **kw: spawned.append(kw))

    client = TestClient(app)
    r1 = client.post("/reports", json={
        "thread_id": "t_dup", "idempotency_key": "rpt_dup_1"})
    assert r1.status_code == 202 and len(spawned) == 1

    # 진행 중 + 다른 키 → 409 report_in_progress, 잡 미생성
    r2 = client.post("/reports", json={
        "thread_id": "t_dup", "idempotency_key": "rpt_dup_2"})
    assert r2.status_code == 409
    assert "report_in_progress" in r2.text
    assert len(spawned) == 1

    # 같은 키 재시도(더블클릭) → 멱등 200 running
    r3 = client.post("/reports", json={
        "thread_id": "t_dup", "idempotency_key": "rpt_dup_1"})
    assert r3.status_code == 200 and r3.json()["status"] == "running"


def test_quota_path_chat_reads_exempt():
    from src.middleware.quota import _is_quota_path

    assert _is_quota_path("/chat", "POST") is True
    assert _is_quota_path("/chat/threads", "GET") is False
    assert _is_quota_path("/chat/t1/state", "GET") is False
    assert _is_quota_path("/chat/t1/auto-title", "POST") is True


def test_threads_repo_merge_semantics(threads_repo):
    threads_repo.ensure_thread("t6")
    threads_repo.merge_steps("t6", [{"id": "s1", "status": "running", "ts": 10,
                                     "label": "검색", "tool_name": "qdrant_search"}])
    threads_repo.merge_steps("t6", [{"id": "s1", "status": "done", "ended_at": 20}])
    state = threads_repo.get_state("t6")
    assert len(state.steps) == 1
    assert state.steps[0]["status"] == "done"
    assert state.steps[0]["label"] == "검색"  # 필드 단위 merge — start 필드 보존

    # selected_law_keys — None=미변경, []=해제
    threads_repo.set_selected_law_keys("t6", ["a", "b"])
    assert threads_repo.get_state("t6").selected_law_keys == ["a", "b"]
    threads_repo.set_selected_law_keys("t6", None)
    assert threads_repo.get_state("t6").selected_law_keys == ["a", "b"]
    threads_repo.set_selected_law_keys("t6", [])
    assert threads_repo.get_state("t6").selected_law_keys == []
