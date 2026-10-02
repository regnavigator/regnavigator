"""기능 조합(워크플로) 진행 상태 — 저장·복원·상한 (2026-10-02).

전문가 모드에서 기능을 여러 개 골라 순서대로 돌리는 기능이다. 사용자 선택은
**단계마다 멈춤**이라, "지금 몇 단계인지"가 곧 조합 그 자체다. 그래서 이 상태는
클라이언트가 아니라 스레드가 든다 — 새로고침 한 번에 사라지면 조합을 잃는다.

여기서 지키는 것:
1. 저장한 커서가 `GET /state` 로 **그대로 돌아온다**(새로고침 생존).
2. 남의 스레드는 건드릴 수 없다.
3. feature id 는 검증하지 않는다 — 목록의 진실원은 프런트 레지스트리이고,
   여기서 화이트리스트를 복제하면 기능을 추가할 때마다 두 곳이 어긋난다.
   길이·개수만 막는다.
"""

from __future__ import annotations

import pytest

from src.middleware import AUTH_DEV_BYPASS_USER_ID


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "w.db"))
    monkeypatch.setenv("REPORTS_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)

    import src.persistence as P
    import src.persistence.threads_repo as TR

    monkeypatch.setattr(TR, "_repo", None)
    caches = (P.get_reports_repo, P.get_report_runs_repo, P.get_blob_store,
              P.get_users_repo, P.get_events_repo)
    for f in caches:
        f.cache_clear()

    from fastapi.testclient import TestClient

    from src.api import app

    yield TestClient(app)

    monkeypatch.setattr(TR, "_repo", None)
    for f in caches:
        f.cache_clear()


_SEQ = iter(range(1, 10_000))


def _thread(api) -> str:
    """빈 스레드 하나 — 소유자는 dev bypass 사용자."""
    from src.persistence.threads_repo import get_threads_repo

    tid = f"t_wf{next(_SEQ)}"
    get_threads_repo().ensure_thread(tid, user_id=AUTH_DEV_BYPASS_USER_ID)
    return tid


def test_workflow_survives_reload(api):
    """저장한 조합(입력·파일·기밀까지)이 `GET /state` 로 그대로 돌아온다."""
    tid = _thread(api)
    steps = [
        {"fn": "case_issues",
         "values": {"facts": "무신고 영업", "issue": "처분 수위"},
         "files": [{"id": "wff_abc", "name": "소장.pdf", "chars": 1200}],
         "confidential": True, "done": False},
        {"fn": "prec_issues", "values": {"issue": "처분 수위"},
         "files": [], "confidential": False, "done": False},
    ]

    r = api.patch(f"/chat/{tid}/workflow",
                  json={"steps": steps, "cursor": 1, "mode": "auto"})
    assert r.status_code == 200, r.text
    wf = r.json()["workflow"]
    assert wf["cursor"] == 1 and wf["mode"] == "auto" and wf["status"] == "draft"
    assert wf["steps"] == steps

    # 새로고침 = state 재조회. 여기서 비면 조합이 통째로 사라진다.
    got = api.get(f"/chat/{tid}/state").json()["workflow"]
    assert got == wf


def test_workflow_empty_steps_clears(api):
    """빈 배열은 조합 종료 — null 로 비운다(카드가 사라진다)."""
    tid = _thread(api)
    api.patch(f"/chat/{tid}/workflow",
              json={"steps": ["pathway", "brief"], "cursor": 0})

    r = api.patch(f"/chat/{tid}/workflow", json={"steps": [], "cursor": 0})
    assert r.status_code == 200
    assert r.json()["workflow"] is None
    assert api.get(f"/chat/{tid}/state").json()["workflow"] is None


def test_workflow_cursor_is_clamped(api):
    """커서는 0..len 으로 조인다 — 범위를 벗어나면 빈 단계를 가리킨다."""
    tid = _thread(api)
    r = api.patch(f"/chat/{tid}/workflow",
                  json={"steps": ["a", "b"], "cursor": 99})
    assert r.json()["workflow"]["cursor"] == 2

    r = api.patch(f"/chat/{tid}/workflow",
                  json={"steps": ["a", "b"], "cursor": -5})
    assert r.json()["workflow"]["cursor"] == 0


def test_legacy_string_steps_are_promoted(api):
    """1차 구현이 저장한 문자열 배열도 읽힌다 — 객체로 승격한다."""
    tid = _thread(api)
    r = api.patch(f"/chat/{tid}/workflow",
                  json={"steps": ["pathway", "brief"], "cursor": 0})
    steps = r.json()["workflow"]["steps"]
    assert [s["fn"] for s in steps] == ["pathway", "brief"]
    assert steps[0] == {"fn": "pathway", "values": {}, "files": [],
                        "confidential": False, "done": False}


def test_workflow_rejects_too_many_steps(api):
    """상한 초과는 422 — 길면 중간에 맥락이 흐려지고 끝까지 가지 않는다."""
    tid = _thread(api)
    r = api.patch(f"/chat/{tid}/workflow",
                  json={"steps": [f"f{i}" for i in range(9)], "cursor": 0})
    assert r.status_code == 422


def test_workflow_rejects_non_list(api):
    tid = _thread(api)
    r = api.patch(f"/chat/{tid}/workflow", json={"steps": "brief"})
    assert r.status_code == 422


def test_workflow_accepts_unknown_feature_id(api):
    """모르는 id 도 받는다 — 기능 목록의 진실원은 프런트 레지스트리다.

    여기서 화이트리스트를 들면 기능을 추가할 때마다 백·프런트가 어긋나고,
    어긋난 쪽은 조용히 422 로 떨어진다. 렌더 단계에서 못 찾은 id 를 빼는 쪽이
    맞다(FE `wfSteps` 가 그렇게 한다).
    """
    tid = _thread(api)
    r = api.patch(f"/chat/{tid}/workflow",
                  json={"steps": ["aaa_not_a_feature"], "cursor": 0})
    assert r.status_code == 200
    assert [x["fn"] for x in r.json()["workflow"]["steps"]] == ["aaa_not_a_feature"]


def test_workflow_rejects_other_users_thread(api):
    """남의 스레드는 404 — 존재 여부도 알려 주지 않는다."""
    from src.persistence.threads_repo import get_threads_repo

    other = "t_other"
    get_threads_repo().ensure_thread(other, user_id="someone-else")
    r = api.patch(f"/chat/{other}/workflow",
                  json={"steps": ["brief"], "cursor": 0})
    assert r.status_code == 404


def test_workflow_repo_roundtrip_and_bad_json(tmp_path, monkeypatch):
    """repo 단: 저장·복원 + 깨진 값은 조용히 None(기능만 꺼진다)."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "r.db"))
    import src.persistence.threads_repo as TR

    monkeypatch.setattr(TR, "_repo", None)
    repo = TR.get_threads_repo()
    tid = "t_repo1"
    repo.ensure_thread(tid, user_id="u1")

    assert repo.get_workflow(tid) is None
    repo.set_workflow(tid, {"steps": [{"fn": "a"}, {"fn": "b"}], "cursor": 1})
    got = repo.get_workflow(tid)
    assert [s["fn"] for s in got["steps"]] == ["a", "b"]
    assert got["cursor"] == 1

    repo.set_workflow(tid, None)
    assert repo.get_workflow(tid) is None

    # 손상된 값이 들어와도 예외를 올리지 않는다 — 조합만 안 보이면 된다.
    with repo._lock, repo._conn() as c:
        c.execute("UPDATE chat_threads SET workflow_json = ? WHERE id = ?",
                  ("{깨진", tid))
    assert repo.get_workflow(tid) is None

    with repo._lock, repo._conn() as c:
        c.execute("UPDATE chat_threads SET workflow_json = ? WHERE id = ?",
                  ('{"cursor": 1}', tid))
    assert repo.get_workflow(tid) is None

    monkeypatch.setattr(TR, "_repo", None)


# ── 조합 첨부 — 스레드 보관 + 암호화 (2026-10-02) ──────────────────────────
#
# 채팅 첨부는 무상태(프런트가 들고 있다 전송 때만 보냄)지만 조합은 그럴 수 없다.
# 짜 놓고 나중에 돌리거나, 새로고침 뒤 이어서 하기 때문이다. 사건 파일이므로
# 본문은 암호화해 두고, 대화를 지우면 같이 지워져야 한다.

def test_workflow_file_upload_and_delete(api):
    tid = _thread(api)
    r = api.post(f"/chat/{tid}/workflow/files",
                 files={"file": ("소장.txt", b"\xeb\xac\xb4\xec\x8b\xa0\xea\xb3\xa0 \xec\x98\x81\xec\x97\x85", "text/plain")})
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["id"].startswith("wff_") and meta["name"] == "소장.txt"
    assert meta["chars"] > 0
    # 본문은 응답에 싣지 않는다 — 메타만 조합 JSON 에 들어간다.
    assert "text" not in meta

    assert api.delete(f"/chat/{tid}/workflow/files/{meta['id']}").json()["ok"]
    assert api.delete(f"/chat/{tid}/workflow/files/{meta['id']}").json()["ok"] is False


def test_workflow_file_rejects_empty(api):
    tid = _thread(api)
    r = api.post(f"/chat/{tid}/workflow/files",
                 files={"file": ("빈.txt", b"", "text/plain")})
    assert r.status_code == 422


def test_workflow_file_rejects_other_users_thread(api):
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().ensure_thread("t_other_wf", user_id="someone-else")
    r = api.post("/chat/t_other_wf/workflow/files",
                 files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 404


def test_deleting_thread_removes_workflow_files(api):
    """대화를 지웠는데 사건 파일 내용이 DB 에 남아 있으면 안 된다."""
    tid = _thread(api)
    api.post(f"/chat/{tid}/workflow/files",
             files={"file": ("사건.txt", b"secret facts", "text/plain")})

    r = api.delete(f"/chat/{tid}")
    assert r.status_code == 200, r.text
    assert r.json()["workflow_files_deleted"] == 1


def test_workflow_file_text_roundtrip(tmp_path, monkeypatch):
    """저장·복원은 **요청한 순서**로 — 첨부 순서가 곧 맥락이다."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "wf.db"))
    import src.persistence as P

    P.get_workflow_files_repo.cache_clear()
    repo = P.get_workflow_files_repo()
    a = repo.put("t", "a.txt", "첫째")
    b = repo.put("t", "b.txt", "둘째")

    got = repo.get_many("t", [b.id, a.id])
    assert [f.name for f in got] == ["b.txt", "a.txt"]
    assert [f.text for f in got] == ["둘째", "첫째"]
    # 다른 스레드 것은 안 나온다.
    assert repo.get_many("other", [a.id]) == []
    P.get_workflow_files_repo.cache_clear()


# ── 숨은 턴 — 조합 중간 단계 (2026-10-02) ─────────────────────────────────
#
# 조합은 단계마다 답을 쏟지 않고 마지막에 한 번만 종합해 보여 준다. 그래서 단계는
# 숨은 턴으로 돈다 — 검색 강제·인용 번호·기밀 라우팅은 그대로 쓰면서 화면만
# 깨끗해진다. 지우는 게 아니라 접는 것이라, 컨텍스트에는 그대로 들어가야 한다.

def test_hidden_messages_are_marked_and_exposed(api):
    from langchain_core.messages import AIMessage, HumanMessage

    from src.persistence.threads_repo import get_threads_repo

    tid = _thread(api)
    repo = get_threads_repo()
    repo.append_messages(tid, [HumanMessage(content="보이는 질문")])
    repo.append_messages(tid, [HumanMessage(content="조합 2단계")], hidden=True)
    repo.append_messages(tid, [AIMessage(content="2단계 산출")], hidden=True)

    assert repo.get_state(tid).hidden == [False, True, True]

    msgs = api.get(f"/chat/{tid}/state").json()["messages"]
    assert [m.get("hidden", False) for m in msgs] == [False, True, True]


def test_hidden_stays_in_model_context(api):
    """숨김은 렌더 계층의 일이다 — 모델은 중간 단계를 봐야 종합할 수 있다.

    기밀(`sensitive`)과 **정반대**다: 기밀은 컨텍스트에서 빼고, 숨김은 넣는다.
    """
    from langchain_core.messages import HumanMessage

    from src.chat_loop import _drop_sensitive
    from src.persistence.threads_repo import get_threads_repo

    tid = _thread(api)
    repo = get_threads_repo()
    repo.append_messages(tid, [HumanMessage(content="숨은 단계 산출")], hidden=True)

    st = repo.get_state(tid)
    out = _drop_sensitive(st)  # 비기밀 턴 경로
    assert "숨은 단계 산출" in "\n".join(str(m.content) for m in out.messages)


# ── 입력 제안 — 단계별 모드의 핵심 (2026-10-02) ───────────────────────────

class _FakeLLM:
    def __init__(self, text):
        self.text = text
        self.msgs = None

    async def ainvoke(self, msgs):
        self.msgs = msgs

        class R:
            content = self.text

        return R()


def test_suggest_values_fills_requested_keys_only():
    """요청한 항목만 돌려준다 — 모르는 키를 지어내면 폼이 오염된다."""
    import asyncio

    from src.workflow import suggest_values

    fake = _FakeLLM('{"values": {"issue": "무신고 영업 처분", "zzz": "엉뚱"}}')
    out = asyncio.run(suggest_values(
        title="판례 검색", fields=[{"key": "issue", "label": "쟁점"}],
        context="1단계에서 영업신고 의무를 확인했다." * 5, model=fake))
    assert out == {"issue": "무신고 영업 처분"}


def test_suggest_values_empty_without_context():
    """앞 단계가 없으면 제안하지 않는다 — 빈 맥락으로 지어내면 안 된다."""
    import asyncio

    from src.workflow import suggest_values

    assert asyncio.run(suggest_values(
        title="t", fields=[{"key": "a"}], context="  ")) == {}


def test_suggest_values_survives_garbage():
    """파싱 실패해도 조합은 멈추지 않는다."""
    import asyncio

    from src.workflow import suggest_values

    fake = _FakeLLM("먼저 자료를 확인하겠습니다.")
    assert asyncio.run(suggest_values(
        title="t", fields=[{"key": "a"}], context="맥락" * 50, model=fake)) == {}


def test_suggest_route_excludes_confidential_output(api, monkeypatch):
    """기밀 단계 산출은 제안 맥락에 들어가지 않는다.

    여기서 새면 `_drop_sensitive` 로 막아 놓은 격리가 무의미해진다 — 제안은
    상용 모델을 쓴다.
    """
    from langchain_core.messages import AIMessage

    from src.persistence.threads_repo import get_threads_repo

    tid = _thread(api)
    repo = get_threads_repo()
    repo.append_messages(tid, [AIMessage(content="공개 산출 " * 30)])
    repo.append_messages(tid, [AIMessage(content="기밀사건내용 " * 30)], sensitive=True)

    seen: list[str] = []

    async def _spy(*, title, fields, context, **kw):
        seen.append(context)
        return {}

    import src.routes.chat as RC

    monkeypatch.setattr(RC, "_owned_meta_or_404", RC._owned_meta_or_404)
    monkeypatch.setattr("src.workflow.suggest_values", _spy)

    r = api.post(f"/chat/{tid}/workflow/suggest",
                 json={"title": "판례", "fields": [{"key": "issue"}]})
    assert r.status_code == 200, r.text
    assert seen and "공개 산출" in seen[0]
    assert "기밀사건내용" not in seen[0]


def test_workflow_file_ids_become_attachments(api):
    """조합 첨부는 서버가 본문으로 합친다 — 텍스트를 브라우저로 되돌리지 않는다."""
    from src.persistence import get_workflow_files_repo

    tid = _thread(api)
    f = get_workflow_files_repo().put(tid, "소장.txt", "사건 사실관계 본문")

    captured: dict = {}

    import src.routes.chat as RC

    orig = RC._compose_message

    def _spy(message, attachments):
        captured["atts"] = [(a.name, a.text) for a in (attachments or [])]
        return orig(message, attachments)

    RC._compose_message = _spy
    try:
        with api.stream("POST", "/chat",
                        json={"thread_id": tid, "message": "검토해줘",
                              "workflow_file_ids": [f.id]}) as resp:
            assert resp.status_code == 200
            for _ in resp.iter_lines():
                break
    finally:
        RC._compose_message = orig

    assert captured.get("atts") == [("소장.txt", "사건 사실관계 본문")]
