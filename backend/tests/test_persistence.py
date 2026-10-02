"""persistence + API 통합 테스트.

- BlobStore (Local) put/get/key 안전성
- ReportsRepo (SQLite) create/update/get/list
- API 라우트 (FastAPI TestClient) — 목록·메타·다운로드
"""
from __future__ import annotations

import json

import pytest

from src.middleware import AUTH_DEV_BYPASS_USER_ID


@pytest.fixture(autouse=True)
def _isolated_persistence(tmp_path, monkeypatch):
    """각 테스트마다 별도 SQLite + 별도 blob 디렉터리. 캐시도 초기화."""
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "reports.db"))
    monkeypatch.delenv("API_TOKEN", raising=False)

    # lru_cache 리셋
    from src import persistence as P
    P.get_blob_store.cache_clear()
    P.get_reports_repo.cache_clear()
    yield
    P.get_blob_store.cache_clear()
    P.get_reports_repo.cache_clear()


def test_blob_local_put_get(tmp_path, monkeypatch):
    from src.persistence import get_blob_store

    b = get_blob_store()
    uri = b.put("t1/r1.md", "# hello\n안녕")
    assert uri.startswith("file://")
    assert b.get(uri) == "# hello\n안녕"
    assert b.presigned_url(uri) is None  # local 백엔드


def test_blob_rejects_path_escape():
    from src.persistence import get_blob_store

    b = get_blob_store()
    with pytest.raises(ValueError):
        b.put("../escape.md", "x")
    with pytest.raises(ValueError):
        b.put("/abs/path.md", "x")


def test_reports_create_update_get_list():
    from src.persistence import get_reports_repo
    from src.persistence.reports_repo import ReportMeta

    r = get_reports_repo()
    m = ReportMeta(id="rid-001", thread_id="t-A", mode="deep", kind="final", status="running")
    r.create(m)

    r.update_status("rid-001", status="done", blob_uri="file:///blob/x.md",
                    citations=[{"n": 1, "title": "법1"}], title="최종")
    got = r.get("rid-001")
    assert got is not None
    assert got.status == "done"
    assert got.blob_uri == "file:///blob/x.md"
    assert got.title == "최종"
    assert json.loads(got.citations_json) == [{"n": 1, "title": "법1"}]
    assert got.completed_at is not None

    # 두 번째 보고서 (다른 thread)
    r.create(ReportMeta(id="rid-002", thread_id="t-B", mode="deep", kind="rag", status="running"))
    rows_a = r.list_for_thread("t-A")
    rows_b = r.list_for_thread("t-B")
    assert len(rows_a) == 1 and rows_a[0].id == "rid-001"
    assert len(rows_b) == 1 and rows_b[0].id == "rid-002"


def test_api_list_get_download():
    from fastapi.testclient import TestClient
    from src.api import app
    from src.persistence import get_blob_store, get_reports_repo
    from src.persistence.reports_repo import ReportMeta

    repo = get_reports_repo()
    blob = get_blob_store()
    uri = blob.put("t-A/r-X.md", "# 보고서\n본문")
    repo.create(ReportMeta(
        id="r-X", thread_id="t-A", mode="deep", kind="final", status="done",
        blob_uri=uri, title="최종 보고서",
        citations_json=json.dumps([{"n": 1, "title": "원전"}], ensure_ascii=False),
    ))

    client = TestClient(app)

    res = client.get("/threads/t-A/reports")
    assert res.status_code == 200
    payload = res.json()
    assert payload["count"] == 1
    assert payload["reports"][0]["citations"] == [{"n": 1, "title": "원전"}]

    res = client.get("/reports/r-X")
    assert res.status_code == 200
    assert res.json()["title"] == "최종 보고서"

    res = client.get("/reports/r-X/download")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    assert "본문" in res.text


def test_api_404_when_missing():
    from fastapi.testclient import TestClient
    from src.api import app

    client = TestClient(app)
    assert client.get("/reports/no-such").status_code == 404
    assert client.get("/reports/no-such/download").status_code == 404


def test_api_suggestions():
    from fastapi.testclient import TestClient
    from src.api import app

    client = TestClient(app)
    res = client.get("/suggestions")
    assert res.status_code == 200
    body = res.json()
    assert "welcome_message" in body

    # examples — Claude/Gemini-style 카드 (3~4개)
    assert "examples" in body
    assert 3 <= len(body["examples"]) <= 5
    for ex in body["examples"]:
        assert ex.get("id")
        assert ex.get("label")
        assert ex.get("prompt")  # 클릭 시 input에 prefill

    # categories — drill-down용 (3~4개)
    assert "categories" in body
    assert 3 <= len(body["categories"]) <= 5
    for cat in body["categories"]:
        assert "id" in cat
        assert "label" in cat
        assert isinstance(cat["questions"], list)
        assert len(cat["questions"]) >= 1
        assert all(isinstance(q, str) and q for q in cat["questions"])


def _persist_capture(monkeypatch, configurable: dict) -> dict:
    """주어진 configurable로 _persist_report 1회 실행 후 captured 반환."""
    import src.tools.reports as reports_mod

    captured: dict = {}

    class FakeRepo:
        def create(self, meta):
            captured["meta"] = meta
            return meta.id
        def update_status(self, *a, **kw):
            captured["update"] = kw

    class FakeBlob:
        def put(self, key, body):
            captured["key"] = key
            return f"file:///{key}"

    monkeypatch.setattr(reports_mod, "get_reports_repo", lambda: FakeRepo())
    monkeypatch.setattr(reports_mod, "get_blob_store", lambda: FakeBlob())
    monkeypatch.setattr(
        reports_mod, "ensure_config", lambda: {"configurable": configurable}
    )
    result = reports_mod._persist_report(
        path="/final_report.md", body="# 보고서",
        state={"steps": [], "messages": []},
    )
    assert result is not None
    return captured


def test_persist_report_uses_parent_thread_id(monkeypatch):
    """deep 는 별도 langgraph thread(관리 run)에서 돌고 chat thread 는
    config.configurable.parent_thread_id 로 들어온다 → reports 는 chat thread
    기준으로 묶여야 하므로 parent_thread_id 우선.
    """
    captured = _persist_capture(
        monkeypatch,
        {
            "thread_id": "deep-thread-Y",          # deep 가 도는 별도 thread
            "parent_thread_id": "chat-thread-X",   # 사용자 chat thread
            "run_id": "run-1",
        },
    )
    meta = captured["meta"]
    assert meta.thread_id == "chat-thread-X"          # parent 우선
    assert captured["key"].startswith("chat-thread-X/")


def test_persist_report_falls_back_to_thread_id_when_no_parent(monkeypatch):
    """parent_thread_id 없으면 — fast 그래프 케이스 — 그냥 thread_id 그대로 사용."""
    import src.tools.reports as reports_mod

    captured = {}

    class FakeRepo:
        def create(self, meta):
            captured["meta"] = meta
            return meta.id
        def update_status(self, *a, **kw): pass

    class FakeBlob:
        def put(self, key, body):
            captured["key"] = key
            return f"file:///{key}"

    monkeypatch.setattr(reports_mod, "get_reports_repo", lambda: FakeRepo())
    monkeypatch.setattr(reports_mod, "get_blob_store", lambda: FakeBlob())
    monkeypatch.setattr(
        reports_mod,
        "ensure_config",
        lambda: {"configurable": {"thread_id": "thread-Z", "run_id": "run-2"}},
    )

    state = {"steps": [], "messages": []}
    reports_mod._persist_report(path="/rag_report.md", body="# rag", state=state)
    assert captured["meta"].thread_id == "thread-Z"


# ── auto-title — 신 라우트 POST /chat/{tid}/auto-title ─────────────────
# (구 POST /threads/{tid}/auto-title(langgraph loopback)은 ADR-0001 Phase 5
#  삭제 — threads_repo 직접 조회로 이관. 응답 shape {thread_id, title}.)
@pytest.fixture()
def threads_repo(monkeypatch):
    """테스트 스코프 SQLite ThreadsRepo — 전역 캐시 리셋.

    (SQLite 경로는 autouse `_isolated_persistence` 가 tmp 로 세팅.
     패턴: tests/test_chat_loop.py 의 threads_repo 픽스처.)
    """
    import src.persistence.threads_repo as tr

    monkeypatch.setattr(tr, "_repo", None)
    yield tr.get_threads_repo()
    monkeypatch.setattr(tr, "_repo", None)


def test_api_auto_title_idempotent_when_already_set(threads_repo, monkeypatch):
    # 거부 기본값(2026-10-03): 소유자 검사는 요청 user_id 가 있어야 통과 — bypass 사용자로.
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    """R7 — 이미 thread.title 있으면 LLM 호출 없이 그대로 반환."""
    from fastapi.testclient import TestClient
    from langchain_core.messages import HumanMessage
    from src.api import app

    # title 이 이미 있으면 LLM 은 절대 호출되면 안 됨
    import src.chat_loop as cl
    monkeypatch.setattr(
        cl, "_base_model",
        lambda spec: pytest.fail("LLM must not be called when title already set"))

    # owner 없는 스레드는 이제 거부된다(2026-10-03 거부 기본값) — bypass 사용자 소유로.
    threads_repo.ensure_thread("tA", user_id=AUTH_DEV_BYPASS_USER_ID)
    threads_repo.append_messages("tA", [HumanMessage(content="광고 심의 질문", id="m1")])
    threads_repo.set_title("tA", "기존 제목")

    client = TestClient(app)
    res = client.post("/chat/tA/auto-title")
    assert res.status_code == 200
    assert res.json() == {"thread_id": "tA", "title": "기존 제목"}


def test_api_auto_title_404_when_thread_missing(threads_repo):
    from fastapi.testclient import TestClient
    from src.api import app

    client = TestClient(app)
    res = client.post("/chat/none/auto-title")
    assert res.status_code == 404


def test_api_auto_title_409_when_no_human_message(threads_repo, monkeypatch):
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    from fastapi.testclient import TestClient
    from src.api import app

    threads_repo.ensure_thread("tB", user_id=AUTH_DEV_BYPASS_USER_ID)  # human 메시지 없는 thread

    client = TestClient(app)
    res = client.post("/chat/tB/auto-title")
    assert res.status_code == 409


def test_api_token_enforced(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "secret-xyz")
    from fastapi.testclient import TestClient
    from src.api import app

    client = TestClient(app)
    # 토큰 없음 → 401
    assert client.get("/threads/t/reports").status_code == 401
    # 잘못된 토큰 → 403
    assert client.get(
        "/threads/t/reports", headers={"Authorization": "Bearer wrong"}
    ).status_code == 403
    # 올바른 토큰 → 200 (빈 목록)
    assert client.get(
        "/threads/t/reports", headers={"Authorization": "Bearer secret-xyz"}
    ).status_code == 200


# ── search_messages — human/ai content 만 매치 (tool 원문 오탐 방지, 2026-07-24) ──
def test_search_messages_matches_human_ai_only(threads_repo):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    threads_repo.ensure_thread("ts_a", user_id="u1")
    threads_repo.append_messages("ts_a", [
        HumanMessage(content="의료기기 허가 절차 알려줘", id="sa1"),
        AIMessage(content="허가는 다음과 같습니다", id="sa2"),
    ])
    # ts_b: 사용자 대화엔 '허가' 없음 — tool 메시지(검색 결과 원문)에만 존재.
    threads_repo.ensure_thread("ts_b", user_id="u1")
    threads_repo.append_messages("ts_b", [
        HumanMessage(content="오늘 날씨 어때", id="sb1"),
        ToolMessage(content="의료기기법 제6조 허가 원문 덩어리...", tool_call_id="tc1", id="sb2"),
    ])

    rows = threads_repo.search_messages("u1", "허가")
    ids = [r["id"] for r in rows]
    assert "ts_a" in ids
    assert "ts_b" not in ids  # tool 원문만 매치되는 thread 는 제외


def test_search_messages_scopes_to_user(threads_repo):
    from langchain_core.messages import HumanMessage

    threads_repo.ensure_thread("ts_mine", user_id="u1")
    threads_repo.append_messages("ts_mine", [HumanMessage(content="임상시험 승인", id="sm1")])
    threads_repo.ensure_thread("ts_other", user_id="u2")
    threads_repo.append_messages("ts_other", [HumanMessage(content="임상시험 승인", id="so1")])

    ids = [r["id"] for r in threads_repo.search_messages("u1", "임상시험")]
    assert ids == ["ts_mine"]
