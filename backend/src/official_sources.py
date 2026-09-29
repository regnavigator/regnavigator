"""검증된 공식 규제 창구 레지스트리 — 운영정보(URL·전화) 환각 방지.

목적: 모델이 "심사 진행 확인 방법" 류 질문에 **정확한** 공식 URL·전화를 안내하도록
신뢰 참고를 주입하고(프롬프트), contact guard(B)가 이 값들을 검증됨으로 통과시킨다.
검색 코퍼스(법령 조문)엔 이런 운영정보가 없어 모델이 지어내던 문제(`emed.mfds.go.kr`
오타 환각)의 근본 대응.

⚠️ **값 변경 시 반드시 공식 출처로 재확인** — 모델·개발자 추측 금지. 틀린 값을
'공식'으로 굳히면 환각보다 나쁘다. 아래 값은 2026-07-22 웹 검증(mfds.go.kr 계열
도메인 확인). 운영자는 주기적으로 재확인할 것.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

_log = logging.getLogger(__name__)

# (name, url, phones, note) — 검증됨. 값 추가/수정은 공식 출처 확인 후에만.
OFFICIAL_SOURCES: list[dict] = [
    {
        "name": "의료기기 전자민원시스템",
        "url": "https://emedi.mfds.go.kr",
        "phones": [],
        "note": "의료기기 허가·인증·신고 신청 및 진행상황(민원처리) 조회",
    },
    {
        "name": "의료기기통합정보시스템(UDI 포털)",
        "url": "https://udiportal.mfds.go.kr",
        "phones": [],
        "note": "UDI 코드·의료기기 통합정보",
    },
    {
        "name": "의약품안전나라(의약품 전자민원)",
        "url": "https://nedrug.mfds.go.kr",
        "phones": [],
        "note": "의약품 허가·전자민원",
    },
    {
        "name": "식약처 대표 누리집",
        "url": "https://www.mfds.go.kr",
        "phones": [],
        "note": "공지·법령·부서 안내",
    },
    {
        "name": "의료기기 광고사전심의(한국의료기기산업협회)",
        "url": "https://adv.kmdia.or.kr",
        "phones": [],
        "note": "의료기기 광고 사전심의 신청·조회. 2026-08-19 접속 확인(200). "
                "⚠️ 하위 경로를 임의로 붙이지 말 것 — `/ADV` 는 403, 진입은 루트",
    },
    {
        "name": "식약처 종합상담실",
        "url": "",
        "phones": ["1577-1255"],
        "note": "대표 상담(유료, 평일 09~18시)",
    },
    {
        "name": "정부민원안내콜센터",
        "url": "",
        "phones": ["110"],
        "note": "무료 정부 통합 상담",
    },
    {
        "name": "의료기기안전평가과",
        "url": "",
        "phones": ["043-719-5007", "043-719-5015"],
        "note": "의료기기 심사 문의",
    },
]


def render_reference_block() -> str:
    """프롬프트 주입용 컴팩트 참고 블록(검증된 값만). stable(캐시) 블록에 실린다."""
    lines = [
        "## 공식 창구 참고 (검증됨 — 운영정보는 아래 값만 사용, 그 외 URL·전화는 지어내지 말 것)"
    ]
    for s in all_sources():
        bits = []
        if s["url"]:
            bits.append(s["url"])
        if s["phones"]:
            bits.append(" · ".join(s["phones"]))
        joined = " / ".join(bits) if bits else "(연락처 없음)"
        lines.append(f"- {s['name']}: {joined} — {s['note']}")
    return "\n".join(lines)


def registry_haystack() -> str:
    """contact guard(B) allowlist — 레지스트리 URL·전화 총합(검증됨 처리용)."""
    parts: list[str] = []
    for s in all_sources():
        if s["url"]:
            parts.append(s["url"])
        parts.extend(s["phones"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 본문 URL 강제 (2026-08-19) — 링크 소유권을 모델에서 **코드**로 이전
# ---------------------------------------------------------------------------
# 왜 규칙·스토플리스트가 아니라 강제인가:
#   종전 방어는 "URL 문자열이 검색 출처에 있으면 통과"였다. 그 전제가 틀렸다 —
#   웹 스니펫·수년 전 가이드라인 PDF 에 적힌 주소도 죽거나 경로가 바뀐다.
#   실측(2026-08-19): 답변이 `http://adv.kmdia.or.kr/ADV` 를 제시했는데 스킴은
#   http, 그 경로는 403(진입점은 루트)였다. 출처에 있었으므로 가드는 통과시켰다.
#   반대로 정상 주소(`emedi.mfds.go.kr`)는 마크다운 백틱까지 매칭돼 오탐됐다.
#   → 진짜 오류는 놓치고 정상은 신고하는 구조. 케이스를 더 넣어도 안 바뀐다.
#
# 그래서 **본문 링크는 레지스트리 값만** 남긴다. 인용 출처 링크는 우측 패널
# citation 이 이미 정본으로 렌더하므로 본문에 중복될 이유가 없다(References 를
# 본문에서 금지한 것과 같은 채널 분리 원칙).
_URL_TOKEN_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", re.IGNORECASE)

# 레지스트리 밖 링크 자리에 남길 문구 — 문장 중간에 들어가도 읽히는 형태.
UNVERIFIED_URL_PLACEHOLDER = "해당 기관 공식 누리집"


def _host_of(url: str) -> str:
    m = re.match(r"https?://([^/\s]+)", (url or "").strip(), re.IGNORECASE)
    return (m.group(1) if m else "").lower().lstrip("www.")


def all_sources() -> list[dict]:
    """코드 시드 + **동적 등재분**(app_settings, 자동 유지보수).

    ⚠️ 캐싱 금지 — 동적 등재분은 런타임에 늘어난다(store 가 자체 TTL 캐시를
    갖는다). 여기서 `lru_cache` 를 쓰면 자동 등재가 재기동 전까지 반영되지 않는다.
    """
    out = list(OFFICIAL_SOURCES)
    try:
        from src.official_sources_store import active_entries

        for e in active_entries():
            out.append({"name": e.get("name") or e.get("host", ""),
                        "url": e.get("url") or "", "phones": [],
                        "note": e.get("note") or ""})
    except Exception as e:  # noqa: BLE001 — 동적 조회 실패가 답변을 막으면 안 됨
        _log.debug("동적 레지스트리 조회 실패(시드만 사용): %s", e)
    return out


def _canonical_by_host() -> dict[str, str]:
    """host → 레지스트리 정본 URL(시드 + 동적)."""
    out: dict[str, str] = {}
    for s in all_sources():
        u = (s.get("url") or "").strip()
        if u:
            out[_host_of(u)] = u
    return out


def canonical_url(url: str) -> Optional[str]:
    """레지스트리에 있는 호스트면 **정본 URL**, 없으면 None.

    같은 호스트라도 하위 경로는 정본으로 되돌린다 — 모델이 붙인 경로는 검증할
    수 없고, 실측에서 그 경로가 403 이었다. 루트는 최소한 살아 있는 값이다.
    """
    host = _host_of(url)
    return _canonical_by_host().get(host) if host else None


def sanitize_body_urls(text: str) -> tuple[str, list[str]]:
    """본문의 URL을 레지스트리 값으로 강제. (정리된 본문, 제거·교정된 원본 목록).

    - 레지스트리 호스트 → 정본 URL 로 치환(http→https·임의 경로 제거가 여기서 해결)
    - 그 외 → 링크 제거. 마크다운 링크는 라벨만 남기고, 맨 URL 은 문구로 대체
    """
    if not text:
        return text, []
    changed: list[str] = []

    def _md(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        canon = canonical_url(url)
        if canon:
            if canon.rstrip("/") != url.rstrip("/"):
                changed.append(url)
            return f"[{label}]({canon})"
        changed.append(url)
        return label  # 링크만 벗기고 문구는 보존

    out = _MD_LINK_RE.sub(_md, text)

    def _bare(m: re.Match) -> str:
        url = m.group(0)
        # 문장부호가 붙어 온 경우 분리(백틱·괄호로 인한 오탐 방지).
        trail = ""
        while url and url[-1] in "`.,);]}":
            trail = url[-1] + trail
            url = url[:-1]
        canon = canonical_url(url)
        if canon:
            if canon.rstrip("/") != url.rstrip("/"):
                changed.append(url)
            return canon + trail
        changed.append(url)
        return UNVERIFIED_URL_PLACEHOLDER + trail

    out = _URL_TOKEN_RE.sub(_bare, out)
    return out, changed
