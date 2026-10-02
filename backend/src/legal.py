"""법적 고지 정본(single source of truth) — 면책·이용조건.

**왜 코드에 두나**: 면책 문구를 LLM 이 매번 작성하면 표현이 흔들리고 누락될 수 있다.
법적 고지는 **결정적으로 부착**해야 한다(References 와 같은 원칙 — 본문 텍스트가 아닌
시스템이 붙인다). 프롬프트는 "면책을 쓰라"가 아니라 "면책은 시스템이 붙이니 쓰지 말라".

노출 경로:
- 보고서: `report_pipeline` 이 본문 끝에 `DISCLAIMER_REPORT` 부착(강제).
- 채팅: 세션 첫 법령 응답에 `DISCLAIMER_CHAT`(프롬프트에 정확 문구 제공).
- 프런트: `GET /legal` 로 받아 **상시 노출**(푸터/배너) — 한 번만 보여주고 마는 것보다
  법적으로 안전하다.

문구는 서비스 실제 구조(AI 생성·법령 개정·국외이전)에 근거한다. 약관·개인정보처리방침
전문은 `docs/legal/` — 시행 전 사업자 정보를 채울 것.

version 을 올리면 프런트가 재동의를 받을 수 있다.
"""

from __future__ import annotations

# 고지 개정 시 올린다(프런트 재동의 트리거).
# 2026-07-16: 약관·개인정보처리방침 전면 개정(법령 정식 명칭·보수적 표현·주석 제거).
LEGAL_VERSION = "2026-10-03"  # 서비스명 정정·보호책임자·국외이전 연락처·기밀 경로·사업자 정보 — 재동의

# ── 채팅 — 세션 첫 법령 응답에 1회(프롬프트가 이 문구를 그대로 사용) ──────
DISCLAIMER_CHAT = (
    "본 답변은 AI가 법령 원문을 검색·요약한 **참고 정보**이며 법률자문이 아닙니다. "
    "법령은 개정될 수 있으므로 시행일·경과규정을 확인하시고, 최종 판단은 "
    "관할기관 또는 전문가에게 확인하시기 바랍니다."
)

# ── 보고서 — 본문 끝에 시스템이 강제 부착 ────────────────────────────────
#: 본문 끝에 면책을 붙일 때의 구분자 — 프런트가 이 뒤를 작은 글씨로 렌더한다.
CHAT_DISCLAIMER_SEP = "\n\n---\n"


def append_chat_disclaimer(body: str) -> str:
    """채팅 답변 본문 끝에 `DISCLAIMER_CHAT` 을 결정적으로 붙인다(멱등)."""
    if not body:
        return body
    if DISCLAIMER_CHAT.strip()[:20] in body:
        return body  # 이미 있음(LLM 이 붙였거나 재부착)
    return body.rstrip() + CHAT_DISCLAIMER_SEP + DISCLAIMER_CHAT


def append_report_disclaimer(body: str) -> str:
    """보고서·의견서 본문 끝에 `DISCLAIMER_REPORT` 를 결정적으로 붙인다(멱등)."""
    if not body:
        return body
    if "법률자문 또는 관할기관의 유권해석이 아닙니다" in body:
        return body
    return body.rstrip() + "\n\n" + DISCLAIMER_REPORT.strip() + "\n"


DISCLAIMER_REPORT = """
---

## 법적 고지

본 보고서는 AI가 법령 원문과 공개 자료를 검색·분석해 생성한 **참고 자료**이며,
**법률자문 또는 관할기관의 유권해석이 아닙니다.**

- **개정 가능성**: 법령·고시는 수시로 개정됩니다. 인용된 조문의 **시행일·경과규정**을
  반드시 확인하십시오. 본 보고서는 작성 시점의 자료에 근거합니다.
- **인용 검증**: 각 인용 `[n]`은 원문 대조로 자동 검증되나, 해석의 정확성까지
  보장하지 않습니다.
- **최종 확인 의무**: 허가·심의·신고 등 규제 절차의 최종 판단은 **관할기관** 또는
  **변호사·인허가 전문가**의 확인을 받으십시오.
- **책임 제한**: 본 보고서에 근거한 의사결정으로 발생한 손해에 대해 서비스 제공자는
  법령이 허용하는 범위에서 책임을 지지 않습니다.
"""

# ── /legal 응답 — 프런트 상시 노출용 ────────────────────────────────────
LEGAL_NOTICE = {
    "version": LEGAL_VERSION,
    "disclaimer_short": DISCLAIMER_CHAT,
    "disclaimer_report": DISCLAIMER_REPORT.strip(),
    "key_points": [
        "AI가 생성한 참고 정보이며 법률자문이 아닙니다.",
        "법령 개정·시행일·경과규정을 반드시 직접 확인하십시오.",
        "최종 판단은 관할기관 또는 전문가 확인이 필요합니다.",
        "입력한 개인정보(이름·주민번호 등)는 자동 마스킹되나, 민감정보 입력을 삼가십시오.",
        "질의 내용은 답변 생성을 위해 국외 AI 서비스로 전송됩니다(개인정보처리방침 참조).",
    ],
    "docs": {
        "terms": "/docs/legal/terms.md",
        "privacy": "/docs/legal/privacy.md",
    },
}
