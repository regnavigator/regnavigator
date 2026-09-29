"""관리자 보고서 화면 보강 (2026-08-26).

세 가지 — ① e2e·벤치 등 내부 트래픽이 실사용 결과에 섞이던 것 제외
② 어떤 모델이 썼는지 표시 ③ 본문 조회.
"""
from __future__ import annotations

import json

import pytest

from src.routes.admin import is_internal_thread


class TestInternalDetection:
    """`t_` 접두 때문에 e2e 스레드가 실사용으로 새던 버그(2026-08-26)."""

    @pytest.mark.parametrize("tid", [
        "t_e2e_doc_1787621276",      # 서류 e2e — 실제로 화면에 섞여 나옴
        "t_e2e_rptkinds_1787632877",
        "e2e_legacy",                # 구 형식(접두 없음)
        "t_qreg_20260825",           # 야간 회귀
        "qreg_20260825",
        "t_bench_x", "bench_x",
        "thread_e2e_x",
    ])
    def test_internal_ids_detected(self, tid):
        assert is_internal_thread(tid, user_id="u-1") is True

    @pytest.mark.parametrize("tid", [
        "t_1398cbb0",                # 실사용 스레드(베타 신고 건)
        "t_abc123", "abc123",
        "t_1398cbb0",                # hex 형 = 실사용(비-hex 이름은 이제 내부)
    ])
    def test_real_ids_not_flagged(self, tid):
        assert is_internal_thread(tid, user_id="u-1") is False

    def test_anonymous_is_internal(self):
        """/chat 은 JWT 필수 — user_id 없는 스레드는 스크립트 산물."""
        assert is_internal_thread("t_abc123", user_id=None) is True


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _seed_report(tmp_path, rid="rep-admin", tid="t_real_1", body="# 제목\n\n본문"):
    import os

    from src.persistence import get_blob_store, get_reports_repo
    from src.persistence.reports_repo import ReportMeta

    os.environ["BLOB_LOCAL_DIR"] = str(tmp_path / "blobs")
    get_blob_store.cache_clear()
    uri = get_blob_store().put(f"{tid}/{rid}.md", body)
    get_reports_repo().create(ReportMeta(
        id=rid, thread_id=tid, mode="deep", kind="final", status="done",
        blob_uri=uri, title="테스트 보고서",
        citations_json=json.dumps(
            [{"number": 1, "title": "의료기기법", "publisher": "법제처",
              "verified": True}], ensure_ascii=False)))
    return rid


def test_report_content_requires_admin(tmp_path):
    """비관리자는 본문을 못 본다 — require_admin 이 앞단에서 막는다."""
    rid = _seed_report(tmp_path, rid="rep-auth")
    r = _client().get(f"/admin/reports/{rid}/content")
    assert r.status_code in (401, 403), r.status_code


def test_report_content_shape(tmp_path, monkeypatch):
    """본문 + 인용 요약을 함께 준다(화면에서 품질 점검이 끝나게)."""
    from src.routes import admin as A

    rid = _seed_report(tmp_path, rid="rep-shape", body="# 제목\n\n본문 [1].")
    monkeypatch.setattr(A, "require_admin", lambda: True, raising=False)
    # 라우트 함수 직접 호출 — 의존성 주입 우회(인증은 위 테스트가 커버).
    out = A.admin_report_content(rid, _admin=True)
    assert out["report_id"] == rid
    assert out["markdown"].startswith("# 제목")
    assert out["chars"] == len("# 제목\n\n본문 [1].")
    assert out["citation_count"] == 1
    assert out["citations"][0]["title"] == "의료기기법"


def test_report_content_missing_blob(tmp_path, monkeypatch):
    """보관기간 경과·생성 전 — 500 이 아니라 409 로 안내."""
    from fastapi import HTTPException

    from src.persistence import get_reports_repo
    from src.persistence.reports_repo import ReportMeta
    from src.routes import admin as A

    get_reports_repo().create(ReportMeta(
        id="rep-noblob", thread_id="t_real_2", mode="deep", kind="final",
        status="done", blob_uri=None, title="만료본"))
    with pytest.raises(HTTPException) as ei:
        A.admin_report_content("rep-noblob", _admin=True)
    assert ei.value.status_code == 409
    with pytest.raises(HTTPException) as ei2:
        A.admin_report_content("no-such-report", _admin=True)
    assert ei2.value.status_code == 404


def test_sql_exclude_prefixes_cover_t_variants():
    """대화 원문 목록은 LIKE 기반이라 정규화를 못 한다 — 변형을 펼쳐 둬야 한다."""
    from src.routes.admin import (
        _INTERNAL_THREAD_PREFIXES,
        _INTERNAL_THREAD_PREFIXES_ALL as ALL,
    )
    for p in _INTERNAL_THREAD_PREFIXES:
        assert p in ALL
        assert f"t_{p}" in ALL          # `t_e2e_…` 형식이 실제로 새던 것
    assert "t_e2e_" in ALL
