"""본문 URL 강제(2026-08-19) — 링크 소유권을 모델에서 코드로.

배경: 종전 방어는 "URL 문자열이 검색 출처에 있으면 통과"였는데 그 전제가 틀렸다.
실측 `http://adv.kmdia.or.kr/ADV` 는 출처(웹 스니펫)에 있었으므로 통과했지만
스킴이 http 이고 그 경로는 403 이었다. 반대로 정상 주소는 백틱까지 매칭돼 오탐.
→ 케이스 추가가 아니라 **레지스트리 값만 남기는 강제**로 전환.
"""
from __future__ import annotations

from src.official_sources import (
    UNVERIFIED_URL_PLACEHOLDER,
    canonical_url,
    sanitize_body_urls,
)


# ── 정본 매핑 ─────────────────────────────────────────────────────────────

def test_registry_host_maps_to_canonical():
    assert canonical_url("https://emedi.mfds.go.kr") == "https://emedi.mfds.go.kr"


def test_http_scheme_is_upgraded_to_registry_value():
    """실측 사고의 핵심 — http 스킴이 정본(https)으로 교정된다."""
    assert canonical_url("http://adv.kmdia.or.kr") == "https://adv.kmdia.or.kr"


def test_invented_path_is_reduced_to_canonical():
    """모델이 붙인 하위 경로는 검증 불가 — 정본(루트)으로 되돌린다(403 방지)."""
    assert canonical_url("http://adv.kmdia.or.kr/ADV") == "https://adv.kmdia.or.kr"


def test_unknown_host_has_no_canonical():
    assert canonical_url("https://fake.example.go.kr/apply") is None


def test_www_prefix_matches_registry():
    assert canonical_url("https://www.emedi.mfds.go.kr/x") == "https://emedi.mfds.go.kr"


# ── 본문 강제 ─────────────────────────────────────────────────────────────

def test_bare_bad_url_replaced_with_phrase():
    body = "신청은 http://adv.kmdia.or.kr/ADV 에서 가능합니다."
    out, changed = sanitize_body_urls(body)
    assert "https://adv.kmdia.or.kr" in out
    assert "/ADV" not in out and "http://" not in out
    assert changed == ["http://adv.kmdia.or.kr/ADV"]


def test_unknown_host_removed_and_phrased():
    body = "자세한 내용은 https://fake.example.go.kr/apply 를 참고하세요."
    out, changed = sanitize_body_urls(body)
    assert UNVERIFIED_URL_PLACEHOLDER in out
    assert "fake.example.go.kr" not in out
    assert changed == ["https://fake.example.go.kr/apply"]


def test_markdown_link_to_unknown_host_keeps_label_only():
    body = "[민원 신청](https://fake.example.go.kr/apply) 에서 접수합니다."
    out, changed = sanitize_body_urls(body)
    assert out.startswith("민원 신청 ")
    assert "fake.example.go.kr" not in out and "](" not in out
    assert changed == ["https://fake.example.go.kr/apply"]


def test_markdown_link_to_registry_host_is_canonicalized():
    body = "[전자민원](http://emedi.mfds.go.kr/civil/apply) 참고"
    out, _ = sanitize_body_urls(body)
    assert "[전자민원](https://emedi.mfds.go.kr)" in out


def test_trailing_punctuation_preserved():
    """백틱·괄호가 붙어도 URL 만 정확히 잘라낸다(종전 오탐 원인)."""
    out, changed = sanitize_body_urls("확인: `https://emedi.mfds.go.kr`.")
    assert out == "확인: `https://emedi.mfds.go.kr`."
    assert changed == []


def test_clean_body_untouched():
    body = "제조업 허가는 의료기기법 제6조에 따릅니다[1]."
    out, changed = sanitize_body_urls(body)
    assert out == body and changed == []


def test_multiple_urls_mixed():
    body = ("신청 https://emedi.mfds.go.kr · 심의 http://adv.kmdia.or.kr/ADV · "
            "안내 https://unknown.example.com/x")
    out, changed = sanitize_body_urls(body)
    assert "https://emedi.mfds.go.kr" in out
    assert "https://adv.kmdia.or.kr" in out and "/ADV" not in out
    assert "unknown.example.com" not in out
    assert len(changed) == 2       # emedi 는 이미 정본이라 변경 없음


def test_empty_input():
    assert sanitize_body_urls("") == ("", [])
