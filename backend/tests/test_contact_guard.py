"""_unverified_contacts / _contact_guard_step — 검증 불가 링크·연락처 backstop(B).

프롬프트 가드(A)를 뚫고 나온 지어낸 URL·전화번호를 코드로 잡는다. 파괴적 스트립이
아니라 경고 step(비파괴) — false positive 로 정상 링크를 지우지 않는다(무결).
"""

from types import SimpleNamespace

from src.chat_loop import (
    _detect_unverified_contacts,
    _turn_source_haystack,
    _unverified_contacts,
)


def test_fabricated_url_flagged():
    assert _unverified_contacts("확인: emed.mfds.go.kr 에서", "") == ["emed.mfds.go.kr"]


def test_url_in_source_passes():
    body = "https://www.law.go.kr/a 참고"
    assert _unverified_contacts(body, "x https://www.law.go.kr/a y") == []


def test_fabricated_phone_flagged():
    assert _unverified_contacts("전화 043-719-4000 로", "") == ["043-719-4000"]


def test_phone_in_source_passes():
    assert _unverified_contacts("043-719-4000", "대표전화 043-719-4000 입니다") == []


def test_date_not_phone():
    """2026-07-22 같은 날짜는 전화번호 형식 아님 → 무시."""
    assert _unverified_contacts("2026-07-22 시행", "") == []


def test_article_and_citation_ignored():
    assert _unverified_contacts("제25조 [3] 참조", "") == []


def test_trailing_punctuation_trimmed():
    assert _unverified_contacts("(emed.mfds.go.kr).", "") == ["emed.mfds.go.kr"]


def test_dedupe_and_mixed():
    r = _unverified_contacts("emed.mfds.go.kr 와 043-719-4000, 다시 emed.mfds.go.kr", "")
    assert r == ["emed.mfds.go.kr", "043-719-4000"]


def test_case_and_space_insensitive():
    assert _unverified_contacts("EMED.MFDS.GO.KR", "emed.mfds.go.kr") == []


def test_haystack_from_citations_and_tool_msgs():
    """haystack = citation url/snippet + 이번 턴 tool 메시지 원문."""
    state = SimpleNamespace(
        messages=[
            {"type": "human", "id": "h1"},
            SimpleNamespace(type="tool", content="검색결과: https://www.mfds.go.kr/portal"),
        ]
    )
    turn_steps = [
        {"citations": [{"url": "https://www.law.go.kr/x", "title": "법"}]}
    ]
    hay = _turn_source_haystack(state, turn_steps)
    assert "law.go.kr/x" in hay and "mfds.go.kr/portal" in hay
    # 두 URL 다 source 에 있으니 통과
    assert _unverified_contacts(
        "https://www.law.go.kr/x 와 https://www.mfds.go.kr/portal", hay
    ) == []


def test_registry_leads_haystack():
    """공식 창구 레지스트리는 haystack **맨 앞** — audit 이 앞부분만 잘라 써서
    (_AUDIT_SRC_CAP) 맨 뒤에 붙이면 검색 원문에 밀려 잘려나간다(2026-08-13
    실측: 시스템이 준 emedi 주소·콜센터 번호가 unverified 로 판정됐다)."""
    from src.official_sources import registry_haystack

    state = SimpleNamespace(messages=[
        {"type": "human", "id": "h1"},
        SimpleNamespace(type="tool", content="검색결과 " + "x" * 30000),
    ])
    hay = _turn_source_haystack(state, [])
    reg = registry_haystack()
    assert reg and hay.startswith(reg.splitlines()[0])


def test_detect_toggle(monkeypatch):
    """감지는 목록 반환(사용자 비노출 — step 아님). 토글로 off."""
    state = SimpleNamespace(messages=[{"type": "human", "id": "h2"}], steps=[])
    assert _detect_unverified_contacts(state, [], "가짜 emed.mfds.go.kr 안내") == [
        "emed.mfds.go.kr"
    ]
    monkeypatch.setenv("CHAT_CONTACT_GUARD_DISABLE", "1")
    assert _detect_unverified_contacts(state, [], "가짜 emed.mfds.go.kr 안내") == []


def test_detect_empty_when_clean():
    state = SimpleNamespace(messages=[{"type": "human", "id": "h1"}], steps=[])
    assert _detect_unverified_contacts(state, [], "일반 규제 안내입니다. [1]") == []


def test_registry_official_url_passes():
    """검증된 공식 창구(레지스트리)는 검색 없이도 통과 — allowlist."""
    state = SimpleNamespace(messages=[{"type": "human", "id": "h1"}], steps=[])
    assert _detect_unverified_contacts(
        state, [], "의료기기 전자민원시스템 https://emedi.mfds.go.kr, 상담 1577-1255"
    ) == []


def test_registry_typo_still_flagged():
    """레지스트리에 없는 오타 포털(emed)·미검증 번호는 여전히 플래그."""
    state = SimpleNamespace(messages=[{"type": "human", "id": "h1"}], steps=[])
    out = _detect_unverified_contacts(state, [], "잘못된 emed.mfds.go.kr 와 043-719-4000")
    assert "emed.mfds.go.kr" in out and "043-719-4000" in out
