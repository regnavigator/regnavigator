"""Tier-0 — 자연어 "법령명 제N조" → (법령명, article_num) 파싱.

"의료기기법 제25조 인용해줘" 같은 *명시적 조문 지정* 질의를 LLM 없이 결정적으로
해석한다. 매칭 실패(법령명/조문 패턴 불명확)면 None → 호출자가 일반 채팅으로 폴백.
"""

from __future__ import annotations

import re

# 제25조 / 제 25 조 / 제3조의2 / 제3조의 2
_ARTICLE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")

# 법령명 꼬리 — 조문 앞에 오는 법령명스러운 구의 끝.
_LAW_SUFFIX = "(?:법률|법|시행령|시행규칙|규칙|규정|고시|훈령|예규|조례|준칙|령)"
_LAW_NAME = re.compile(
    r"([가-힣A-Za-z0-9·]+(?:\s+[가-힣A-Za-z0-9·]+)*?" + _LAW_SUFFIX + r")\s*$"
)


def parse_article_query(q: str) -> tuple[str, str] | None:
    """질의 → (법령명 후보, article_num) 또는 None.

    article_num 은 PG `article_num` 컬럼 포맷("제25조", "제3조의2")으로 정규화.
    법령명은 후보일 뿐 — 정확 매칭은 호출자(PG 조회)가 token-drop 으로 보정.
    """
    if not q or not q.strip():
        return None
    m = _ARTICLE.search(q)
    if not m:
        return None
    jo = int(m.group(1))
    gaji = m.group(2)
    article_num = f"제{jo}조" + (f"의{int(gaji)}" if gaji else "")

    before = q[: m.start()].strip()
    if not before:
        return None
    lm = _LAW_NAME.search(before)
    if not lm:
        return None
    law = re.sub(r"\s+", " ", lm.group(1)).strip()
    if not law:
        return None
    return law, article_num
