"""식별자 대조 감사 — 답변의 서식·별표 번호가 이번 턴 근거에 실재하는지 결정적 대조.

배경(2026-09-17, 답변 품질 실측): "의료기기 품목허가 절차·서식" 질의 3턴에서 허가
신청서 서식번호가 턴마다 달랐다(별지 제2호 / 제○호 / 제1호). 인용 원문은 세 번 모두
**제3호서식**. 세 턴의 grounding 검증률은 0.57~0.63 으로 평범했다 — grounding 은 "인용한
문장이 출처에 있나"를 보므로, 출처 옆에 **틀린 번호를 새로 쓴 것**은 못 잡는다.

서식·별표 번호는 원문에 글자 그대로 있는 식별자다. LLM 없이 문자열 대조로 100%
판정된다 — 실무자가 그대로 옮겨 적는 정보라 틀리면 피해가 직접적이다.

범위: `별지 제N호(의M)서식` · `별표 N(의M)`. 조문 번호(제N조)는 일부러 뺀다 — 모델이
검색 없이 아는 조문을 (맞게) 쓰는 경우가 많아 "근거에 없음 = 오류"가 성립하지 않는다.

관측 전용: chat_loop 가 done 뒤 비차단 호출 → events(`identifier_audit`). 사용자
비노출(답변 뒤 자기 경고는 자기모순 — 2026-07-22 결정). 검수 큐 신호로 쓰인다.
"""

from __future__ import annotations

import re

# "별지 제3호서식" · "별지 제15호 서식" · "별지 제1호의2서식" · "[별지 제3호서식]"
_FORM = re.compile(r"별지\s*제\s*(\d{1,3})\s*호\s*(?:의\s*(\d{1,2}))?\s*서식")
# 번호를 못 채운 자리표시 — "별지 제○호서식", "별지 제OO호서식", "별지 제N호서식"
_FORM_PLACEHOLDER = re.compile(r"별지\s*제\s*[○◯OoNnXx_?]{1,3}\s*호\s*(?:의\s*\d{1,2})?\s*서식")
# "별표 7" · "별표7" · "별표 1의2" · "[별표 3]"
_ANNEX = re.compile(r"별표\s*(\d{1,3})(?:\s*의\s*(\d{1,2}))?(?!\d)")


def _forms(text: str) -> set[tuple[str, str]]:
    return {(m.group(1), m.group(2) or "") for m in _FORM.finditer(text or "")}


def _annexes(text: str) -> set[tuple[str, str]]:
    return {(m.group(1), m.group(2) or "") for m in _ANNEX.finditer(text or "")}


def _label(kind: str, key: tuple[str, str]) -> str:
    n, sub = key
    tail = f"의{sub}" if sub else ""
    return f"별지 제{n}호{tail}서식" if kind == "form" else f"별표 {n}{tail}"


def audit_identifiers(answer: str, haystack: str) -> dict | None:
    """답변의 서식·별표 번호 중 근거에 없는 것. 답변에 식별자가 없으면 None.

    번호 단위 대조 — 표기 변형("제15호 서식" vs "제15호서식")은 같은 것으로 본다.
    """
    a_forms, a_annex = _forms(answer), _annexes(answer)
    placeholders = sorted(set(m.group(0) for m in _FORM_PLACEHOLDER.finditer(answer or "")))
    if not a_forms and not a_annex and not placeholders:
        return None
    h_forms, h_annex = _forms(haystack), _annexes(haystack)
    unsupported = (
        [_label("form", k) for k in sorted(a_forms - h_forms, key=lambda k: (int(k[0]), k[1]))]
        + [_label("annex", k) for k in sorted(a_annex - h_annex, key=lambda k: (int(k[0]), k[1]))]
    )
    return {
        "forms": len(a_forms),
        "annexes": len(a_annex),
        "unsupported": unsupported[:12],
        "placeholders": placeholders[:5],
        # 근거에 있던 서식 — 검수자가 "무엇이 맞는 번호였나"를 바로 본다.
        "source_forms": [_label("form", k) for k in
                         sorted(h_forms, key=lambda k: (int(k[0]), k[1]))][:12],
    }
