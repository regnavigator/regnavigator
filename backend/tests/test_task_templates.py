"""직무(task) 템플릿 — 저장·목록·이름변경·삭제 · 값/파일 미저장 · 사용자 격리 (2026-10-06)."""

from __future__ import annotations

import pytest


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "tt.db"))
    monkeypatch.setenv("REPORTS_BLOB_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("AUTH_DEV_BYPASS_USER", "dev@example.com")
    monkeypatch.delenv("BETA_WHITELIST_EMAILS", raising=False)

    import src.persistence as P

    P.get_task_templates_repo.cache_clear()
    from fastapi.testclient import TestClient

    from src.api import app

    yield TestClient(app)
    P.get_task_templates_repo.cache_clear()


_STEPS = [
    {"fn": "case_issues", "values": {"facts": "비밀 사실관계"}, "files": [{"id": "wff_1", "name": "소장.pdf", "chars": 9}],
     "confidential": True, "done": True},
    {"fn": "prec_issues", "values": {"issue": "쟁점"}, "files": [], "confidential": False, "done": True},
]


def test_create_strips_values_and_files(api):
    r = api.post("/task-templates", json={"name": "  사건 검토 → 판례  ", "steps": _STEPS})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["id"].startswith("tt_") and t["name"] == "사건 검토 → 판례"
    assert t["steps"] == [{"fn": "case_issues", "confidential": True},
                          {"fn": "prec_issues", "confidential": False}]
    assert "values" not in t["steps"][0] and "files" not in t["steps"][0]
    assert "비밀" not in r.text


def test_list_rename_delete(api):
    tid = api.post("/task-templates", json={"name": "A", "steps": _STEPS}).json()["id"]
    assert [x["id"] for x in api.get("/task-templates").json()["items"]] == [tid]

    r = api.patch(f"/task-templates/{tid}", json={"name": "B"})
    assert r.status_code == 200 and r.json()["name"] == "B"
    assert api.get("/task-templates").json()["items"][0]["name"] == "B"

    assert api.delete(f"/task-templates/{tid}").status_code == 204
    assert api.get("/task-templates").json()["items"] == []
    assert api.delete(f"/task-templates/{tid}").status_code == 404
    assert api.patch(f"/task-templates/{tid}", json={"name": "C"}).status_code == 404


@pytest.mark.parametrize("body", [
    {"name": "x", "steps": []},
    {"name": "x", "steps": [{"fn": ""}]},
    {"name": "", "steps": _STEPS},
    {"name": "x" * 81, "steps": _STEPS},
    {"name": "x", "steps": [{"fn": f"f{i}"} for i in range(9)]},
])
def test_rejects_bad_input(api, body):
    assert api.post("/task-templates", json=body).status_code == 422


def test_per_user_cap(api):
    """상한은 repo 로 채운다 — 50회 POST 는 rate limit(429)에 먼저 걸린다."""
    from src.middleware import AUTH_DEV_BYPASS_USER_ID
    from src.persistence import get_task_templates_repo
    from src.persistence.task_templates_repo import MAX_PER_USER

    repo = get_task_templates_repo()
    for i in range(MAX_PER_USER):
        repo.create(AUTH_DEV_BYPASS_USER_ID, f"t{i}", _STEPS)
    r = api.post("/task-templates", json={"name": "overflow", "steps": _STEPS})
    assert r.status_code == 422 and str(MAX_PER_USER) in r.json()["detail"]
    assert len(api.get("/task-templates").json()["items"]) == MAX_PER_USER


def test_other_user_cannot_see_or_touch(api):
    tid = api.post("/task-templates", json={"name": "mine", "steps": _STEPS}).json()["id"]

    from src.persistence import get_task_templates_repo

    repo = get_task_templates_repo()
    assert repo.list_for_user("someone-else") == []
    assert repo.rename("someone-else", tid, "stolen") is False
    assert repo.delete("someone-else", tid) is False
    assert api.get("/task-templates").json()["items"][0]["name"] == "mine"
