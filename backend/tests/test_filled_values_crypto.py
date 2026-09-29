"""서류 기입값 저장 암호화 + 내 서식 목록·삭제 (2026-09-18).

뉴스레터(9/18)가 "작성된 서식은 암호화되어 저장되며, 본인 계정으로만 열고
내려받을 수 있습니다"를 명기했다. 여기서 잠그는 것:
  ① 컬럼 원문은 `enc1:` 암호문 — 사용자 값이 DB 파일에 평문으로 없다
  ② repo 를 통한 읽기는 평문 그대로(호출자 무변경) · 레거시 평문 행도 읽힌다
  ③ 키 회전: 새 키를 앞에 두고 옛 키를 뒤에 남기면 옛 암호문도 복호
  ④ GET /documents 는 본인 서류만 · DELETE 뒤 run 이 지운 서류를 가리키지 않는다
"""
from __future__ import annotations

import json
import sqlite3
import time

import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet

from src.persistence import field_crypto

SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "medi.db"))
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    monkeypatch.delenv("FILLED_VALUES_ENC_KEY", raising=False)
    field_crypto.reset_cache()
    from src import persistence as P
    from src.persistence.threads_repo import reset_threads_repo_cache
    caches = (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo, P.get_report_runs_repo)
    for f in caches:
        f.cache_clear()
    reset_threads_repo_cache()
    yield
    for f in caches:
        f.cache_clear()
    reset_threads_repo_cache()
    field_crypto.reset_cache()


# ── ① ② ③ field_crypto 단위 ──────────────────────────────────────────

def test_roundtrip_and_prefix():
    ct = field_crypto.encrypt_text('{"성명": "김철수"}')
    assert ct.startswith(field_crypto.PREFIX)
    assert "김철수" not in ct
    assert field_crypto.decrypt_text(ct) == '{"성명": "김철수"}'
    # 이미 암호문이면 이중 암호화하지 않는다
    assert field_crypto.encrypt_text(ct) == ct


def test_legacy_plaintext_passes_through():
    assert field_crypto.decrypt_text('{"a": "1"}') == '{"a": "1"}'
    assert field_crypto.decrypt_text(None) is None
    assert field_crypto.decrypt_text("") == ""


def test_no_key_means_plaintext_with_flag(monkeypatch):
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    field_crypto.reset_cache()
    assert not field_crypto.is_enabled()
    assert field_crypto.encrypt_text('{"a": "1"}') == '{"a": "1"}'


def test_key_rotation_keeps_old_ciphertext_readable(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("FILLED_VALUES_ENC_KEY", old)
    field_crypto.reset_cache()
    ct_old = field_crypto.encrypt_text('{"x": "y"}')
    # 새 키를 앞에, 옛 키를 뒤에
    monkeypatch.setenv("FILLED_VALUES_ENC_KEY", f"{new},{old}")
    field_crypto.reset_cache()
    assert field_crypto.decrypt_text(ct_old) == '{"x": "y"}'
    ct_new = field_crypto.encrypt_text('{"x": "z"}')
    # 옛 키만 남기면 새 암호문은 못 연다 — 조용히 빈 값이 아니라 예외
    monkeypatch.setenv("FILLED_VALUES_ENC_KEY", old)
    field_crypto.reset_cache()
    with pytest.raises(RuntimeError):
        field_crypto.decrypt_text(ct_new)


def test_bad_key_format_fails_loudly(monkeypatch):
    monkeypatch.setenv("FILLED_VALUES_ENC_KEY", "not-a-fernet-key")
    field_crypto.reset_cache()
    with pytest.raises(RuntimeError):
        field_crypto.encrypt_text("{}")


# ── 부팅 검증(2026-09-21: 운영 키 끝 '=' 누락 → 3일간 서식 작성 전건 500) ──

def test_validate_key_rejects_key_missing_padding(monkeypatch):
    """실제 사고 형태 — 44자 키에서 끝 '=' 하나가 빠진 43자."""
    truncated = Fernet.generate_key().decode()[:-1]
    monkeypatch.setenv("FILLED_VALUES_ENC_KEY", truncated)
    with pytest.raises(RuntimeError) as ei:
        field_crypto.validate_key()
    assert "43자" in str(ei.value)
    assert truncated not in str(ei.value)  # 키 값은 메시지에 남기지 않는다


def test_validate_key_modes(monkeypatch):
    monkeypatch.setenv("FILLED_VALUES_ENC_KEY", Fernet.generate_key().decode())
    assert field_crypto.validate_key() == "explicit"
    monkeypatch.delenv("FILLED_VALUES_ENC_KEY")
    assert field_crypto.validate_key() == "derived"  # NEXTAUTH_SECRET 파생
    monkeypatch.delenv("NEXTAUTH_SECRET")
    assert field_crypto.validate_key() == "off"


def test_boot_refuses_bad_key(monkeypatch):
    """lifespan 이 막아야 배포 healthz 에서 실패로 드러난다 — 서식 작성 시점까지 미루지 않는다."""
    from fastapi.testclient import TestClient

    from src.api import app

    monkeypatch.setenv("FILLED_VALUES_ENC_KEY", Fernet.generate_key().decode()[:-1])
    with pytest.raises(RuntimeError, match="FILLED_VALUES_ENC_KEY"):
        with TestClient(app):
            pass


# ── ① ② repo 계층 ───────────────────────────────────────────────────

def _raw_column(tmp_path, report_id: str) -> str | None:
    with sqlite3.connect(tmp_path / "medi.db") as c:
        row = c.execute("SELECT filled_values FROM reports WHERE id=?",
                        (report_id,)).fetchone()
    return row[0] if row else None


def test_repo_stores_ciphertext_and_reads_plain(tmp_path):
    from src.persistence import ReportMeta, get_reports_repo
    repo = get_reports_repo()
    repo.create(ReportMeta(id="doc-1", thread_id="t1", mode="deep", kind="doc",
                           status="done", blob_uri=None, filled_values="{}"))
    merged = repo.merge_filled_values("doc-1", {"성명": "김철수", "연락처": "062-000-0000"})
    assert merged == {"성명": "김철수", "연락처": "062-000-0000"}

    raw = _raw_column(tmp_path, "doc-1")
    assert raw.startswith("enc1:")
    assert "김철수" not in raw and "062-000" not in raw
    # DB 파일 바이트 전체에도 평문이 없다
    assert "김철수".encode("utf-8") not in (tmp_path / "medi.db").read_bytes()

    meta = repo.get("doc-1")
    assert json.loads(meta.filled_values) == merged
    # 두 번째 병합도 복호→병합→재암호화
    assert repo.merge_filled_values("doc-1", {"주소": "광주"})["성명"] == "김철수"


def test_legacy_plaintext_row_is_readable_and_promoted(tmp_path):
    from src.persistence import ReportMeta, get_reports_repo
    repo = get_reports_repo()
    repo.create(ReportMeta(id="doc-legacy", thread_id="t1", mode="deep",
                           kind="doc", status="done", blob_uri=None))
    with sqlite3.connect(tmp_path / "medi.db") as c:
        c.execute("UPDATE reports SET filled_values=? WHERE id=?",
                  ('{"성명": "이영희"}', "doc-legacy"))
    assert json.loads(repo.get("doc-legacy").filled_values) == {"성명": "이영희"}
    repo.merge_filled_values("doc-legacy", {"연락처": "010"})
    assert _raw_column(tmp_path, "doc-legacy").startswith("enc1:")
    assert json.loads(repo.get("doc-legacy").filled_values) == {"성명": "이영희", "연락처": "010"}


# ── ④ 라우트: 내 서류 목록 · 삭제 ──────────────────────────────────

def _token(sub: str) -> str:
    now = int(time.time())
    return pyjwt.encode({"sub": sub, "email": f"{sub}@example.com",
                         "email_verified": True, "iat": now, "exp": now + 3600},
                        SECRET, algorithm="HS256")


def _h(sub: str) -> dict:
    return {"Authorization": f"Bearer {_token(sub)}"}


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _seed_doc(*, report_id: str, thread_id: str, owner: str, title: str) -> None:
    from src.persistence import (ReportMeta, get_blob_store, get_report_runs_repo,
                                 get_reports_repo)
    from src.persistence.threads_repo import get_threads_repo
    uri = get_blob_store().put(f"{report_id}.md", "# 서식\n- [확인 필요: 성명]\n")
    get_reports_repo().create(ReportMeta(
        id=report_id, thread_id=thread_id, mode="deep", kind="doc",
        status="done", blob_uri=uri, title=title, filled_values="{}"))
    get_threads_repo().ensure_thread(thread_id, user_id=owner)
    runs = get_report_runs_repo()
    idem = f"rpt_form_{report_id}"
    ok, _ = runs.acquire(idempotency_key=idem, thread_id=thread_id, user_id=owner,
                         prompt=f"[서식] {title}", purpose="document_draft")
    assert ok
    runs.finish(idem, status="completed", report_id=report_id)


def test_list_documents_is_owner_scoped_and_newest_first():
    _seed_doc(report_id="d-a1", thread_id="ta", owner="alice", title="허가신청서")
    time.sleep(0.01)
    _seed_doc(report_id="d-a2", thread_id="tb", owner="alice", title="변경신청서")
    _seed_doc(report_id="d-b1", thread_id="tc", owner="bob", title="봅의 서식")
    from src.persistence import get_reports_repo
    get_reports_repo().merge_filled_values("d-a2", {"성명": "김철수"})

    c = _client()
    r = c.get("/documents", headers=_h("alice"))
    assert r.status_code == 200, r.text
    docs = r.json()["documents"]
    assert [d["id"] for d in docs] == ["d-a2", "d-a1"]
    assert docs[0]["filled_count"] == 1 and docs[0]["title"] == "변경신청서"
    assert all("filled_values" not in d for d in docs)  # 목록엔 값 자체가 안 실린다

    assert [d["id"] for d in c.get("/documents", headers=_h("bob")).json()["documents"]] == ["d-b1"]
    assert c.get("/documents", headers=_h("carol")).json()["documents"] == []


def test_delete_document_detaches_run_and_hides_it():
    _seed_doc(report_id="d-old", thread_id="t1", owner="alice", title="첫 서식")
    time.sleep(0.01)
    _seed_doc(report_id="d-new", thread_id="t1", owner="alice", title="둘째 서식")
    from src.persistence import get_report_runs_repo, get_reports_repo
    runs = get_report_runs_repo()
    assert runs.latest_draft_report_for_thread("t1") == "d-new"

    c = _client()
    # 남의 서류는 404 — 존재도 안 알려준다
    assert c.delete("/reports/d-new", headers=_h("bob")).status_code == 404
    assert get_reports_repo().get("d-new") is not None

    r = c.delete("/reports/d-new", headers=_h("alice"))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert get_reports_repo().get("d-new") is None
    # run 은 남지만 지운 서류를 가리키지 않는다 → 이전 초안으로 자연 복귀
    assert runs.latest_draft_report_for_thread("t1") == "d-old"
    assert [d["id"] for d in c.get("/documents", headers=_h("alice")).json()["documents"]] == ["d-old"]
    assert c.get("/reports/d-new", headers=_h("alice")).status_code == 404


# ── 서식 수명 규칙(2026-09-18): 대화 삭제 → 서식 cascade, 보관한 것만 남는다 ──

def test_thread_delete_cascades_documents_except_kept():
    _seed_doc(report_id="d-tmp", thread_id="t1", owner="alice", title="임시 서식")
    _seed_doc(report_id="d-keep", thread_id="t1", owner="alice", title="보관 서식")
    from src.persistence import get_reports_repo
    get_reports_repo().merge_filled_values("d-keep", {"성명": "김철수"})

    c = _client()
    # 남의 서식은 보관 토글도 404
    assert c.post("/documents/d-keep/keep", json={"kept": True}, headers=_h("bob")).status_code == 404
    r = c.post("/documents/d-keep/keep", json={"kept": True}, headers=_h("alice"))
    assert r.status_code == 200 and r.json()["kept"] is True

    r = c.delete("/chat/t1", headers=_h("alice"))
    assert r.status_code == 200, r.text
    assert r.json()["documents_deleted"] == 1 and r.json()["documents_kept"] == 1

    repo = get_reports_repo()
    assert repo.get("d-tmp") is None
    assert repo.get("d-keep") is not None
    docs = c.get("/documents", headers=_h("alice")).json()["documents"]
    assert [d["id"] for d in docs] == ["d-keep"]
    assert docs[0]["kept"] is True and docs[0]["thread_alive"] is False
    # 대화가 없어도 보관한 서식은 소유자가 계속 연다(run 기록이 소유 근거)
    assert c.get("/reports/d-keep", headers=_h("alice")).status_code == 200
    assert c.get("/reports/d-keep", headers=_h("bob")).status_code == 404


def test_list_reports_status_and_field_counts():
    _seed_doc(report_id="d-s", thread_id="ts", owner="alice", title="상태 확인")
    from src.persistence import get_reports_repo
    c = _client()
    d = c.get("/documents", headers=_h("alice")).json()["documents"][0]
    assert (d["field_count"], d["filled_count"], d["status"]) == (1, 0, "empty")
    assert d["thread_alive"] is True and d["kept"] is False
    get_reports_repo().merge_filled_values("d-s", {"성명": "김철수"})
    d = c.get("/documents", headers=_h("alice")).json()["documents"][0]
    assert (d["filled_count"], d["status"]) == (1, "done")


def test_document_status_rule():
    from src.form_docs import document_status
    assert document_status(5, 0) == "empty"
    assert document_status(5, 2) == "partial"
    assert document_status(5, 5) == "done"
    assert document_status(0, 3) == "partial"   # 본문을 못 읽어 전체 수를 모를 때


def test_document_alias_and_source_thread_title():
    _seed_doc(report_id="d-al", thread_id="t-al", owner="alice", title="허가신청서")
    from src.persistence.threads_repo import get_threads_repo
    get_threads_repo().set_title("t-al", "체외진단기기 허가 상담") if hasattr(get_threads_repo(), "set_title") else None
    c = _client()
    assert c.patch("/documents/d-al", json={"alias": "A사 건"}, headers=_h("bob")).status_code == 404
    assert c.patch("/documents/d-al", json={"alias": "x" * 61}, headers=_h("alice")).status_code == 422
    r = c.patch("/documents/d-al", json={"alias": "  A사   1차 제출  "}, headers=_h("alice"))
    assert r.status_code == 200 and r.json()["alias"] == "A사 1차 제출"
    d = c.get("/documents", headers=_h("alice")).json()["documents"][0]
    assert d["alias"] == "A사 1차 제출" and d["title"] == "허가신청서"   # 원 제목은 보존
    assert "thread_title" in d
    # 빈 값 = 해제
    assert c.patch("/documents/d-al", json={"alias": ""}, headers=_h("alice")).json()["alias"] is None
    assert c.get("/documents", headers=_h("alice")).json()["documents"][0]["alias"] is None
