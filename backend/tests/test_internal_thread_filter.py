"""내부 트래픽 대화 제외(2026-08-19) + http:// URL 가드.

① 야간 회귀(`qreg_*`)·벤치·e2e 가 만든 대화가 관리자 '대화 원문' 목록에서
   `(제목 없음)` 익명 대화로 섞여 **실사용처럼 보였다**(운영자 지적).
② 답변이 `http://adv.kmdia.or.kr/ADV` 를 제시 — 스킴이 http 이고 그 경로는 403.
   공공기관 사이트는 사실상 전부 https 라, http 는 낡은 출처·날조 신호로 본다.
"""
from __future__ import annotations

from src.chat_loop import _unverified_contacts
from src.routes.admin import is_internal_thread


# ── ① 내부 대화 판별 ───────────────────────────────────────────────────────

def test_script_prefixes_are_internal():
    for tid in ("qreg_20260819_0300_01", "bench_ab12cd", "e2e_purpose_x",
                "hrep_0819_007", "hrep2_0819_01", "lat_1755_0"):
        assert is_internal_thread(tid, "u-1") is True, tid


def test_anonymous_thread_is_internal():
    """/chat 은 JWT 필수 — user_id 없는 대화는 스크립트 산물뿐."""
    assert is_internal_thread("t_9f3a", None) is True


def test_real_user_thread_is_not_internal():
    assert is_internal_thread("t_9f3a2b1c", "u-42") is False


def test_internal_reserved_email_domain():
    """`…@internal` 계정은 내부(2026-08-28 재발 대응: e2e@internal 이 user_id
    를 달고 돌자 사용자 규칙(관리자·익명)을 전부 통과해 이용 지표에 샜다)."""
    assert is_internal_thread("t_9f3a2b1c", "e2e@internal") is True
    assert is_internal_thread("anything", "E2E@Internal") is True


def test_prefix_check_is_not_substring_match():
    """접두 판정이 부분 문자열 매치로 흐르지 않는다.

    정책 갱신(2026-08-27): 실사용 id 는 `t_` + hex 뿐 — `t_workbench_1` 같은
    사람이 지은 이름은 이제 **스크립트 산물로 분류**된다(로컬 e2e 가 임의
    이름으로 운영 집계에 섞인 재발 대응). hex 형이면 'bench' 유사 여부와
    무관하게 실사용.
    """
    assert is_internal_thread("t_workbench_1", "u-42") is True   # 비-hex 이름
    assert is_internal_thread("t_beac4e5f12", "u-42") is False   # hex 는 실사용


# ── ② URL 가드 ────────────────────────────────────────────────────────────

def test_http_url_flagged_even_when_in_source():
    """source 에 있어도 http:// 면 신호 — 실측 오안내 재현."""
    body = "신청은 http://adv.kmdia.or.kr/ADV 에서 가능합니다."
    hay = "광고사전심의 http://adv.kmdia.or.kr/ADV 안내"
    assert _unverified_contacts(body, hay) == ["http://adv.kmdia.or.kr/ADV"]


def test_https_url_in_source_passes():
    body = "신청은 https://adv.kmdia.or.kr 에서 가능합니다."
    hay = "의료기기 광고사전심의: https://adv.kmdia.or.kr"
    assert _unverified_contacts(body, hay) == []


def test_https_url_absent_from_source_flagged():
    body = "https://fake.example.go.kr 에서 신청하세요."
    assert _unverified_contacts(body, "다른 내용") == ["https://fake.example.go.kr"]


def test_registry_url_is_https():
    """레지스트리에 http:// 값이 섞이면 가드가 자기 자신을 신고하게 된다."""
    from src.official_sources import OFFICIAL_SOURCES

    for s in OFFICIAL_SOURCES:
        url = s.get("url") or ""
        assert not url.startswith("http://"), s["name"]


def test_ad_review_portal_registered():
    """광고심의 창구 — 반복 오안내가 나던 항목이라 검증값으로 등재."""
    from src.official_sources import registry_haystack

    assert "https://adv.kmdia.or.kr" in registry_haystack()
