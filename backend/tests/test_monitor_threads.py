"""모니터링 스레드 재구성 — 관찰·알람·주소록 (2026-10-02).

설계: `docs/spec/monitor-threads-design.md`.

여기서 지키는 불변식 두 가지:
1. **확인 못 함 ≠ 변경 없음.** 법령 DB 가 죽어 있으면 알람을 만들지 않는다.
   거짓 "변경 없음"은 모니터링 도구가 낼 수 있는 가장 나쁜 출력이다.
2. **같은 변경을 두 번 알리지 않는다.** 알람이 중복되면 사용자는 알람을 끈다.
"""

from __future__ import annotations


import pytest

from src.middleware import AUTH_DEV_BYPASS_USER_ID


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("REPORTS_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)

    import src.persistence as P
    import src.persistence.threads_repo as TR

    monkeypatch.setattr(TR, "_repo", None)
    caches = (P.get_reports_repo, P.get_report_runs_repo, P.get_blob_store,
              P.get_users_repo, P.get_events_repo, P.get_monitor_watch_repo,
              P.get_monitor_alert_repo, P.get_contacts_repo,
              P.get_monitor_targets_repo)
    for f in caches:
        f.cache_clear()

    from fastapi.testclient import TestClient

    from src.api import app

    yield TestClient(app)

    monkeypatch.setattr(TR, "_repo", None)
    for f in caches:
        f.cache_clear()


def _cite(ak: str, title: str) -> dict:
    return {"id": f"cite_doc_{ak}", "number": 1, "title": title,
            "source_kind": "doc", "doc_category": "법령"}


# ── ① 스레드 ───────────────────────────────────────────────────────────────

def test_create_monitor_thread_is_separate_kind(api):
    """모니터링 스레드는 채팅 스레드와 **같은 테이블, 다른 종류**다."""
    r = api.post("/monitor/threads", json={"title": "아크로제약"})
    assert r.status_code == 200, r.text
    tid = r.json()["thread_id"]

    from src.persistence.threads_repo import get_threads_repo

    assert get_threads_repo().get_meta(tid)["kind"] == "monitor"

    lst = api.get("/monitor/threads").json()["threads"]
    assert [t["id"] for t in lst] == [tid]
    assert lst[0]["watch_count"] == 0 and lst[0]["unread_alerts"] == 0


def test_chat_threads_are_not_listed_as_monitor(api):
    """일반 대화가 모니터링 목록에 섞이면 사이드바가 무의미해진다."""
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().ensure_thread("t_chat", user_id=AUTH_DEV_BYPASS_USER_ID)
    assert api.get("/monitor/threads").json()["threads"] == []


# ── ② 관찰 목록 ────────────────────────────────────────────────────────────

def test_watch_add_remove_and_restore(api):
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]

    r = api.post(f"/monitor/threads/{tid}/watch", json={
        "citations": [_cite("004097_0025001", "식품위생법 시행령 제25조")],
        "added_by": "user"})
    assert r.status_code == 200 and r.json()["count"] == 1

    api.delete(f"/monitor/threads/{tid}/watch/004097_0025001")
    assert api.get(f"/monitor/threads/{tid}/watch").json()["items"] == []

    # 다시 넣으면 되살아난다(soft delete 였으므로).
    api.post(f"/monitor/threads/{tid}/watch", json={
        "citations": [_cite("004097_0025001", "식품위생법 시행령 제25조")]})
    assert len(api.get(f"/monitor/threads/{tid}/watch").json()["items"]) == 1


def test_web_citations_cannot_be_watched_but_are_reported(api):
    """웹 인용은 조문 키가 없어 관찰할 수 없다 — 조용히 빼지 않고 알린다."""
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    r = api.post(f"/monitor/threads/{tid}/watch", json={
        "citations": [{"id": "cite_web_x", "title": "어떤 블로그",
                       "source_kind": "web"}]})
    assert r.json()["added"] == []
    assert r.json()["skipped"] == ["어떤 블로그"]


def test_suggest_marks_already_watched(api):
    """이미 관찰 중인 것은 '다시 추가' 가 아니라 '이미 있음' 으로 보여야 한다."""
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().merge_steps(tid, [{
        "id": "s1", "citations": [_cite("A_1", "법 제1조"), _cite("B_2", "법 제2조")]}])
    api.post(f"/monitor/threads/{tid}/watch",
             json={"citations": [_cite("A_1", "법 제1조")]})

    sug = api.post(f"/monitor/threads/{tid}/watch/suggest").json()["suggestions"]
    by_key = {s["article_key"]: s["already"] for s in sug}
    assert by_key == {"A_1": True, "B_2": False}


# ── ③ 알람 ─────────────────────────────────────────────────────────────────

def test_no_alerts_when_law_db_is_unavailable(api, monkeypatch):
    """**확인 못 함 ≠ 변경 없음.** DB 가 죽었으면 알람을 만들지 않는다."""
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    api.post(f"/monitor/threads/{tid}/watch",
             json={"citations": [_cite("A_1", "법 제1조")]})

    monkeypatch.setattr("src.retrieval.pg_client.is_available", lambda: False)
    r = api.post(f"/monitor/threads/{tid}/detect").json()
    assert r["complete"] is False and r["created"] == 0
    assert api.get("/monitor/alerts").json()["alerts"] == []


def test_same_change_is_not_alerted_twice(api, monkeypatch):
    """중복 알람이 오면 사용자는 알람을 끈다 — 그 순간 이 기능이 죽는다."""
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    api.post(f"/monitor/threads/{tid}/watch",
             json={"citations": [_cite("A_1", "법 제1조")]})

    monkeypatch.setattr(
        "src.amendments.detect_with_status",
        lambda items: ([{"article_key": "A_1", "title": "법 제1조",
                         "kind": "repealed"}],
                       {"checked": 1, "complete": True}))

    first = api.post(f"/monitor/threads/{tid}/detect").json()
    second = api.post(f"/monitor/threads/{tid}/detect").json()
    assert first["created"] == 1 and second["created"] == 0
    assert len(api.get("/monitor/alerts").json()["alerts"]) == 1


def test_alert_inbox_filters_and_read_state(api, monkeypatch):
    tid = api.post("/monitor/threads", json={"title": "대상 A"}).json()["thread_id"]
    api.post(f"/monitor/threads/{tid}/watch",
             json={"citations": [_cite("A_1", "법 제1조")]})
    monkeypatch.setattr(
        "src.amendments.detect_with_status",
        lambda items: ([{"article_key": "A_1", "title": "법 제1조",
                         "kind": "pending"}],
                       {"checked": 1, "complete": True}))
    api.post(f"/monitor/threads/{tid}/detect")

    box = api.get("/monitor/alerts?unread=1").json()
    assert box["unread_total"] == 1
    a = box["alerts"][0]
    assert a["thread_title"] == "대상 A" and a["unread"] is True

    assert api.post(f"/monitor/alerts/{a['id']}/read").json()["ok"] is True
    assert api.get("/monitor/alerts?unread=1").json()["alerts"] == []
    # 읽어도 목록엔 남는다 — 보관(dismiss)해야 사라진다.
    assert len(api.get("/monitor/alerts").json()["alerts"]) == 1
    api.post(f"/monitor/alerts/{a['id']}/dismiss")
    assert api.get("/monitor/alerts").json()["alerts"] == []


def test_thread_list_shows_unread_badge(api, monkeypatch):
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    api.post(f"/monitor/threads/{tid}/watch",
             json={"citations": [_cite("A_1", "법 제1조")]})
    monkeypatch.setattr(
        "src.amendments.detect_with_status",
        lambda items: ([{"article_key": "A_1", "title": "법 제1조",
                         "kind": "repealed"}], {"checked": 1, "complete": True}))
    api.post(f"/monitor/threads/{tid}/detect")

    t = api.get("/monitor/threads").json()["threads"][0]
    assert t["unread_alerts"] == 1 and t["watch_count"] == 1


# ── ④ 보고서 ───────────────────────────────────────────────────────────────

def test_thread_report_renders_alerts(api, monkeypatch):
    tid = api.post("/monitor/threads", json={"title": "대상 B"}).json()["thread_id"]
    api.post(f"/monitor/threads/{tid}/watch",
             json={"citations": [_cite("A_1", "법 제1조")]})
    monkeypatch.setattr(
        "src.amendments.detect_with_status",
        lambda items: ([{"article_key": "A_1", "title": "법 제1조",
                         "kind": "repealed"}], {"checked": 1, "complete": True}))
    api.post(f"/monitor/threads/{tid}/detect")

    r = api.post(f"/monitor/threads/{tid}/report", json={})
    assert r.status_code == 200, r.text
    assert r.json()["alerts"] == 1

    from src.persistence import get_blob_store, get_reports_repo

    md = get_blob_store().get(get_reports_repo().get(r.json()["report_id"]).blob_uri)
    assert "폐지" in md and "법 제1조" in md and "관찰 조문: 1건" in md


def test_empty_report_distinguishes_no_change_from_unchecked(api):
    """변경 0건 보고서도 "확인 못 한 구간이 있을 수 있다"를 말해야 한다."""
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    rid = api.post(f"/monitor/threads/{tid}/report", json={}).json()["report_id"]

    from src.persistence import get_blob_store, get_reports_repo

    md = get_blob_store().get(get_reports_repo().get(rid).blob_uri)
    assert "감지된 변경이 없습니다" in md
    assert "확인하지 못했다는 것은 다릅니다" in md


# ── ⑤ 주소록 ───────────────────────────────────────────────────────────────

def test_contacts_search_and_autoregister(api):
    api.post("/contacts", json={"email": "counsel@acro.co.kr", "name": "김변호사",
                                "org": "아크로제약"})
    api.post("/contacts", json={"email": "ra@other.co.kr", "name": "이담당"})

    assert len(api.get("/contacts").json()["contacts"]) == 2
    hit = api.get("/contacts?q=아크로").json()["contacts"]
    assert [c["email"] for c in hit] == ["counsel@acro.co.kr"]
    assert api.get("/contacts?q=김변").json()["contacts"][0]["name"] == "김변호사"


def test_invalid_email_rejected(api):
    assert api.post("/contacts", json={"email": "not-an-email"}).status_code == 422


def test_send_requires_recipients(api):
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    rid = api.post(f"/monitor/threads/{tid}/report", json={}).json()["report_id"]
    r = api.post(f"/monitor/threads/{tid}/send",
                 json={"report_id": rid, "recipients": []})
    assert r.status_code == 422


def test_send_registers_recipients_in_contacts(api, monkeypatch):
    """보낸 곳은 주소록에 남아야 다음에 고를 수 있다."""
    monkeypatch.setattr("src.observability.notifications.is_configured",
                        lambda: True)
    sent: list[str] = []
    monkeypatch.setattr("src.observability.notifications.send_email",
                        lambda to, subj, html: sent.append(to))

    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    rid = api.post(f"/monitor/threads/{tid}/report", json={}).json()["report_id"]
    r = api.post(f"/monitor/threads/{tid}/send",
                 json={"report_id": rid, "recipients": ["new@firm.co.kr"]})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert sent == ["new@firm.co.kr"]
    assert api.get("/contacts?q=new@firm").json()["contacts"]


def test_send_reports_failure_when_smtp_missing(api, monkeypatch):
    """SMTP 가 없으면 **조용히 성공하지 않는다** — 안 갔는데 갔다고 하면 안 된다."""
    monkeypatch.setattr("src.observability.notifications.is_configured",
                        lambda: False)
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    rid = api.post(f"/monitor/threads/{tid}/report", json={}).json()["report_id"]
    r = api.post(f"/monitor/threads/{tid}/send",
                 json={"report_id": rid, "recipients": ["a@b.co.kr"]})
    assert r.json()["ok"] is False


# ── ⑥ 권한 ─────────────────────────────────────────────────────────────────

def test_other_users_thread_is_forbidden(api):
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().ensure_thread("t_other", user_id="someone-else")
    assert api.get("/monitor/threads/t_other/watch").status_code == 403


# ── 종류 전환 (2026-10-02) ──────────────────────────────────────────────────

def test_convert_chat_thread_to_monitor(api):
    """상담하다 "이건 지켜봐야겠다" 싶을 때 그 자리에서 바꾼다.

    이미 모은 인용이 그대로 관찰 후보가 되므로 새로 시작할 이유가 없다.
    """
    from src.persistence.threads_repo import get_threads_repo

    repo = get_threads_repo()
    repo.ensure_thread("t_conv", user_id=AUTH_DEV_BYPASS_USER_ID)
    assert repo.get_meta("t_conv")["kind"] == "chat"
    assert api.get("/monitor/threads").json()["threads"] == []

    r = api.patch("/chat/t_conv/kind", json={"kind": "monitor"})
    assert r.status_code == 200, r.text
    assert repo.get_meta("t_conv")["kind"] == "monitor"
    assert [t["id"] for t in api.get("/monitor/threads").json()["threads"]] == ["t_conv"]


def test_convert_back_keeps_watch_list(api):
    """되돌려도 관찰 목록은 남는다 — 전환은 분류 변경이지 삭제가 아니다."""
    tid = api.post("/monitor/threads", json={"title": "테스트 대상"}).json()["thread_id"]
    api.post(f"/monitor/threads/{tid}/watch",
             json={"citations": [_cite("A_1", "법 제1조")]})

    api.patch(f"/chat/{tid}/kind", json={"kind": "chat"})
    assert api.get("/monitor/threads").json()["threads"] == []

    api.patch(f"/chat/{tid}/kind", json={"kind": "monitor"})
    items = api.get(f"/monitor/threads/{tid}/watch").json()["items"]
    assert [i["article_key"] for i in items] == ["A_1"]


def test_invalid_kind_rejected(api):
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().ensure_thread("t_bad", user_id=AUTH_DEV_BYPASS_USER_ID)
    assert api.patch("/chat/t_bad/kind", json={"kind": "보고서"}).status_code == 422


def test_cannot_convert_other_users_thread(api):
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().ensure_thread("t_mine_not", user_id="someone-else")
    assert api.patch("/chat/t_mine_not/kind",
                     json={"kind": "monitor"}).status_code in (403, 404)


def test_thread_list_exposes_kind(api):
    """목록이 `kind` 를 빠뜨리면 FE 필터가 **조용히 통과**한다(실측 버그)."""
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().ensure_thread("t_plain", user_id=AUTH_DEV_BYPASS_USER_ID)
    mon = api.post("/monitor/threads", json={"title": "대상"}).json()["thread_id"]

    rows = {t["thread_id"]: t.get("kind") for t in
            api.get("/chat/threads").json()["threads"]}
    assert rows["t_plain"] == "chat"
    assert rows[mon] == "monitor"


# ── 삭제 (2026-10-02) ───────────────────────────────────────────────────────

def test_delete_monitor_thread_cleans_up_watch_and_alerts(api, monkeypatch):
    """스레드를 지우면 관찰·알람도 같이 지운다.

    남겨 두면 ①감지 루프가 죽은 스레드를 계속 훑고 ②알람 모아보기에 주인 없는
    알람이 뜬다.
    """
    tid = api.post("/monitor/threads", json={"title": "지울 대상"}).json()["thread_id"]
    api.post(f"/monitor/threads/{tid}/watch",
             json={"citations": [_cite("A_1", "법 제1조")]})
    monkeypatch.setattr(
        "src.amendments.detect_with_status",
        lambda items: ([{"article_key": "A_1", "title": "법 제1조",
                         "kind": "repealed"}], {"checked": 1, "complete": True}))
    api.post(f"/monitor/threads/{tid}/detect")
    assert api.get("/monitor/alerts").json()["alerts"]

    r = api.delete(f"/chat/{tid}")
    assert r.status_code == 200, r.text
    assert r.json()["watch_deleted"] == 1
    assert r.json()["alerts_deleted"] == 1

    assert api.get("/monitor/threads").json()["threads"] == []
    assert api.get("/monitor/alerts").json()["alerts"] == []


def test_delete_plain_thread_still_works(api):
    """부속물이 없어도 삭제는 그대로 — 정리 실패가 삭제를 막으면 안 된다."""
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().ensure_thread("t_plain_del", user_id=AUTH_DEV_BYPASS_USER_ID)
    r = api.delete("/chat/t_plain_del")
    assert r.status_code == 200
    assert r.json()["watch_deleted"] == 0 and r.json()["alerts_deleted"] == 0


# ── 관찰 추천 (2026-10-02) ──────────────────────────────────────────────────

class _Rec:
    def __init__(self, text):
        self.text = text

    async def ainvoke(self, _msgs):
        class R:
            content = self.text
        return R()


def test_recommend_returns_reasons(monkeypatch):
    """추천은 **사유와 함께** 온다 — 왜 담아야 하는지 모르면 고를 수 없다."""
    import asyncio

    from src.monitor_recommend import recommend

    cands = [
        {"article_key": "A_1", "title": "식품위생법 제37조",
         "citation": {"snippet": "영업신고를 하여야 한다"}},
        {"article_key": "B_2", "title": "식품위생법 제1조(목적)",
         "citation": {"snippet": "이 법은 … 목적으로 한다"}},
    ]
    out = asyncio.run(recommend(
        "카페 개업", cands,
        model=_Rec('{"picks":[{"key":"A_1","why":"신고 요건이 바뀌면 서류를 다시 낸다"}]}'),
    ))
    assert out == {"A_1": "신고 요건이 바뀌면 서류를 다시 낸다"}


def test_recommend_drops_hallucinated_keys(monkeypatch):
    """후보에 없는 키를 지목하면 버린다."""
    import asyncio

    from src.monitor_recommend import recommend

    out = asyncio.run(recommend(
        "카페 개업",
        [{"article_key": "A_1", "title": "x", "citation": {}}],
        model=_Rec('{"picks":[{"key":"ZZZ","why":"지어낸 것"},'
                   '{"key":"A_1","why":"진짜"}]}'),
    ))
    assert out == {"A_1": "진짜"}


def test_recommend_empty_on_failure():
    """실패하면 아무것도 추천하지 않는다 — 없는 추천을 지어내는 것보다 낫다."""
    import asyncio

    from src.monitor_recommend import recommend

    class _Boom:
        async def ainvoke(self, _m):
            raise RuntimeError("down")

    assert asyncio.run(recommend("x y z", [{"article_key": "A", "title": "t",
                                            "citation": {}}],
                                 model=_Boom())) == {}


def test_recommend_requires_reason():
    """사유 없는 추천은 추천이 아니다 — 버린다."""
    import asyncio

    from src.monitor_recommend import recommend

    out = asyncio.run(recommend(
        "카페 개업", [{"article_key": "A_1", "title": "t", "citation": {}}],
        model=_Rec('{"picks":[{"key":"A_1","why":""}]}')))
    assert out == {}


def test_recommend_route_skips_for_confidential_without_onprem(api, monkeypatch):
    """기밀 대화의 주제를 상용 모델로 보내지 않는다."""
    tid = api.post("/monitor/threads", json={"title": "의뢰인 건"}).json()["thread_id"]
    from src.persistence.threads_repo import get_threads_repo

    get_threads_repo().mark_confidential(tid)
    monkeypatch.setattr("src.doc_fill.onprem_fill", lambda: False)

    r = api.post(f"/monitor/threads/{tid}/watch/recommend")
    assert r.status_code == 200
    assert r.json() == {"picks": {}, "skipped": "confidential"}


# ── 프리필 경로 (2026-10-02 실측 버그) ──────────────────────────────────────
#
# 위 더블 주입 테스트는 `model=` 을 넘기므로 **프리필을 타지 않는다** — 실제
# 버그를 하나도 잡지 못했다. 실제 경로(model=None)는 `build_chat_model` 을
# 가로채야 재현된다.

class _RecCapture:
    """주고받은 메시지를 보관하는 더블 — 프리필이 실제로 붙는지 본다."""

    def __init__(self, text):
        self.text = text
        self.msgs = None

    async def ainvoke(self, msgs):
        self.msgs = msgs

        class R:
            content = self.text

        return R()


def _patch_llm(monkeypatch, fake):
    import src.models

    monkeypatch.setattr(src.models, "build_chat_model", lambda *a, **k: fake)


def test_recommend_prefill_is_sent_and_response_restored(monkeypatch):
    """프리필을 붙여 보내고, `{` 없이 돌아온 응답을 되돌려 파싱한다.

    모델이 JSON 대신 "먼저 자료를 확인하겠습니다" 같은 서두를 뱉고 끝나는 일이
    있었다(후보 21건 실측, 추천 0건). 응답 첫 글자를 고정해 막는다.
    """
    import asyncio

    from src.monitor_recommend import _PREFILL, recommend

    fake = _RecCapture('[{"key":"A_1","why":"신고 요건이 바뀌면 서류가 바뀐다"}]}')
    _patch_llm(monkeypatch, fake)

    out = asyncio.run(recommend(
        "카페 개업", [{"article_key": "A_1", "title": "t", "citation": {}}]))

    assert out == {"A_1": "신고 요건이 바뀌면 서류가 바뀐다"}
    # 마지막 메시지가 프리필이어야 한다 — 이게 빠지면 버그가 그대로 돌아온다.
    assert fake.msgs is not None
    assert getattr(fake.msgs[-1], "content", None) == _PREFILL


def test_recommend_preamble_only_yields_nothing(monkeypatch):
    """대화체 서두만 오면 빈 결과 — 예외를 올리지 않는다(fail-open)."""
    import asyncio

    from src.monitor_recommend import recommend

    fake = _RecCapture("먼저 자료들을 확인하여 실무 변화를 추적하겠습니다.")
    _patch_llm(monkeypatch, fake)

    assert asyncio.run(recommend(
        "카페 개업", [{"article_key": "A_1", "title": "t", "citation": {}}])) == {}


def test_recommend_injected_model_has_no_prefill(monkeypatch):
    """`model=` 을 직접 넘기면 프리필을 붙이지 않는다 — 온전한 JSON 을 기대한다."""
    import asyncio

    from src.monitor_recommend import recommend

    fake = _RecCapture('{"picks":[{"key":"A_1","why":"사유"}]}')
    out = asyncio.run(recommend(
        "카페 개업", [{"article_key": "A_1", "title": "t", "citation": {}}],
        model=fake))

    assert out == {"A_1": "사유"}
    assert fake.msgs is not None and len(fake.msgs) == 1
