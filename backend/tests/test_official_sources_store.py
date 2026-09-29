"""공식 창구 동적 레지스트리(2026-08-19) — 자동 등재 안전조건·병합·비활성.

본문 URL 강제 이후 **레지스트리 커버리지 = 링크 커버리지**라, 등재를 자동화하되
잘못 등재되면 틀린 주소가 '검증됨'으로 답변에 나간다. 그래서 자동 등재 조건은
좁게 잡고(공공·협회 도메인, 루트, 반복, 실접속) 그 경계를 테스트로 고정한다.
"""
from __future__ import annotations

import pytest

from src.official_sources_store import (
    active_entries,
    host_of,
    invalidate_cache,
    is_auto_registrable,
    remove,
    set_active,
    upsert,
)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "s.db"))
    from src.persistence.settings_repo import reset_settings_repo_cache

    reset_settings_repo_cache()
    invalidate_cache()
    yield
    invalidate_cache()


# ── 자동 등재 안전조건 ─────────────────────────────────────────────────────

def test_public_domains_are_auto_registrable():
    for u in ("https://emedi.mfds.go.kr", "https://adv.kmdia.or.kr",
              "https://www.nhis.or.kr", "https://x.re.kr", "https://y.ac.kr"):
        assert is_auto_registrable(u) is True, u


def test_commercial_domains_are_not_auto_registrable():
    """광고·대행사 페이지가 '공식 창구'로 등재되면 서비스 신뢰가 무너진다."""
    for u in ("https://blog.naver.com/x", "https://someagency.co.kr",
              "https://example.com", "https://medical-ads.io"):
        assert is_auto_registrable(u) is False, u


def test_host_normalizes_www_and_case():
    assert host_of("https://WWW.Emedi.MFDS.go.kr/path") == "emedi.mfds.go.kr"


def test_non_url_has_no_host():
    assert host_of("그냥 문장") == ""
    assert is_auto_registrable("그냥 문장") is False


# ── 등재·병합 ─────────────────────────────────────────────────────────────

def test_upsert_normalizes_to_root_https():
    """경로·스킴은 보존하지 않는다 — 정본은 루트."""
    e = upsert(url="http://test.go.kr/some/path?q=1", name="테스트기관")
    assert e["url"] == "https://test.go.kr"
    assert e["host"] == "test.go.kr" and e["active"] is True


def test_dynamic_entry_merges_into_registry():
    upsert(url="https://newportal.go.kr", name="신규포털")
    from src.official_sources import all_sources, canonical_url

    assert any(s["url"] == "https://newportal.go.kr" for s in all_sources())
    # 강제 로직이 즉시 이 호스트를 정본으로 인정해야 한다(재기동 불요).
    assert canonical_url("http://newportal.go.kr/apply") == "https://newportal.go.kr"


def test_sanitize_keeps_dynamic_host_and_strips_others():
    upsert(url="https://newportal.go.kr", name="신규포털")
    from src.official_sources import sanitize_body_urls

    out, changed = sanitize_body_urls(
        "신청 http://newportal.go.kr/apply · 참고 https://ads.example.com/x")
    assert "https://newportal.go.kr" in out
    assert "ads.example.com" not in out
    assert len(changed) == 2


def test_deactivated_entry_leaves_registry():
    upsert(url="https://gone.go.kr", name="사라진기관")
    set_active("gone.go.kr", False, reason="HTTP 404")
    from src.official_sources import canonical_url

    assert canonical_url("https://gone.go.kr") is None
    assert all(e["host"] != "gone.go.kr" for e in active_entries())


def test_reactivation_resets_fail_count():
    upsert(url="https://flaky.go.kr", name="간헐")
    set_active("flaky.go.kr", False, reason="timeout")
    e = set_active("flaky.go.kr", True, reason="HTTP 200")
    assert e["active"] is True and e["fail_count"] == 0


def test_upsert_preserves_source_and_created_at():
    first = upsert(url="https://keep.go.kr", name="A", source="manual")
    again = upsert(url="https://keep.go.kr", name="B", source="auto")
    assert again["source"] == "manual"          # 최초 출처 보존
    assert again["created_at"] == first["created_at"]
    assert again["name"] == "B"


def test_remove_entry():
    upsert(url="https://tmp.go.kr", name="임시")
    assert remove("tmp.go.kr") is True
    assert remove("tmp.go.kr") is False


def test_seed_entries_always_present():
    """동적 저장소가 비어도 코드 시드는 살아 있어야 한다(폴백)."""
    from src.official_sources import canonical_url

    assert canonical_url("https://emedi.mfds.go.kr") == "https://emedi.mfds.go.kr"
