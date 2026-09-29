"""regex 1차 PII 스크럽 — 구조적 민감정보를 결정적으로 마스킹.

파이프라인 입구(입력)에서 개인·민감정보를 placeholder 로 치환해 외부(LLM·Tavily·
LangSmith)로 원문이 나가지 않게 한다. **구조적 포맷**(주민번호·전화·카드·이메일·
IP·차량번호·여권·사업자번호·암호화폐 지갑)만 대상 — 이름·주소 같은 문맥 의존
PII 는 별도 NER 모델(OpenMed) 2차의 몫(향후).

설계 원칙:
- **고정밀 우선**: 오탐이 법령명·조문·금액·날짜를 훼손하면 검색 품질이 깎이므로,
  경계(lookbehind/lookahead)와 구조가 뚜렷한 패턴만 쓴다. 계좌번호처럼 포맷이
  들쭉날쭉해 오탐 위험이 큰 항목은 제외(NER 2차로).
- **로그에 원문 금지**: 탐지 결과는 카테고리 라벨만 반환(원문 값 미기록).
- **멱등**: placeholder(대괄호+한글)는 재매칭되지 않아 반복 적용해도 안전.
"""

from __future__ import annotations

import re

# (category, placeholder, pattern) — 적용 순서 = 리스트 순서(더 구체적/긴 것 먼저).
# 경계는 ASCII 영숫자(`0-9A-Za-z`)로 조여, 숫자열이 hex 지갑주소·base58 같은
# 더 긴 영숫자 토큰 안에 박혀 있을 때 오탐(부분 매칭)하지 않게 한다. 한국어·공백·
# 문장부호 인접은 그대로 매칭(예: "연락처010-…").
_B = r"(?<![0-9A-Za-z])"   # 왼쪽 경계
_E = r"(?![0-9A-Za-z])"    # 오른쪽 경계
_SPECS: list[tuple[str, str, str]] = [
    ("email", "[이메일]", r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    # 암호화폐 지갑 — 숫자 패턴보다 먼저(hex 안 숫자열 선점 방지).
    ("crypto", "[지갑주소]", r"\b0x[a-fA-F0-9]{40}\b"),
    ("crypto", "[지갑주소]",
     r"\b(?:bc1[a-z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"),
    # 주민등록번호 YYMMDD-Gxxxxxx (G=1~8: 내국/외국인).
    ("rrn", "[주민등록번호]", _B + r"\d{6}[-\s]?[1-8]\d{6}" + _E),
    # 생년월일 — '생년월일' 키워드가 동반될 때만(문맥 한정). 날짜 일반을 잡으면
    # 법령의 시행일·공포일이 파괴된다. NER 교체(2026-08-14, 한국어 특화 모델은
    # DT 라벨을 안 쓰기로 결정)로 잃는 DOB 리콜의 보완.
    ("dob", "[생년월일]",
     r"생년월일\s*[:은는]?\s*\d{4}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*일?"),
    # 사업자등록번호 NNN-NN-NNNNN.
    ("biz_reg", "[사업자번호]", _B + r"\d{3}-\d{2}-\d{5}" + _E),
    # 신용카드 — 4-4-4-4(구분자 필수) 또는 16연속.
    ("card", "[카드번호]",
     _B + r"(?:\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}|\d{16})" + _E),
    # 휴대폰 01N-XXXX-XXXX.
    ("phone", "[전화번호]", _B + r"01[0-9][-\s]?\d{3,4}[-\s]?\d{4}" + _E),
    # 유선 지역번호(02 또는 0NN)-XXX(X)-XXXX.
    ("phone", "[전화번호]", _B + r"0(?:2|[3-6][1-5])[-\s]?\d{3,4}[-\s]?\d{4}" + _E),
    # 여권번호 — 한국 여권 접두(M/S/R/O/D 등) + 8자리.
    ("passport", "[여권번호]", r"(?<![A-Za-z0-9])[MSRODmsrod]\d{8}" + _E),
    # IPv4.
    ("ip", "[IP주소]",
     _B + r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)" + _E),
    # 차량번호판 12가3456 / 123가4567.
    ("license_plate", "[차량번호]", r"\d{2,3}[가-힣]\s?\d{4}"),
]

_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    (cat, ph, re.compile(pat)) for cat, ph, pat in _SPECS
]


def scrub(text: str) -> tuple[str, list[str]]:
    """구조적 PII 를 placeholder 로 치환.

    반환: (치환된 텍스트, 발견 카테고리 라벨 리스트). 라벨 리스트로 건수·종류
    집계(원문 값은 반환/로그하지 않음). 발견 없으면 (원문, []).
    """
    if not text:
        return text, []
    found: list[str] = []
    out = text
    for category, placeholder, pattern in _PATTERNS:
        def _repl(_m, _c=category):
            found.append(_c)
            return placeholder
        out = pattern.sub(_repl, out)
    return out, found


def has_pii(text: str) -> bool:
    """스크럽 없이 PII 존재 여부만 빠르게 판정."""
    if not text:
        return False
    return any(p.search(text) for _, _, p in _PATTERNS)
