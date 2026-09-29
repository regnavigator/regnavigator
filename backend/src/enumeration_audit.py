"""열거 커버리지 감사 — 입력에 열거된 항목을 답변이 다뤘는지 결정적 대조.

배경(2026-08-21, 베타 스레드 t_1398cb): 첨부 보도자료의 10대 과제 중 1건
(EMR 연동 배설케어시스템)이 답변에서 **조용히 누락**됐다. 모델이 항목을 규제
유형 4종으로 클러스터링하며 탈락시켰고, "근거 확인된 것만 제시" 규율(v20)이
근거 없는 항목의 침묵 누락으로 전이했다. claim audit(grounding)는 "쓴 문장"의
근거만 검사하므로 "안 쓴 항목"은 잡지 못한다 — 그 사각을 이 감사가 메운다.

관측 전용: chat_loop 가 done 뒤 비차단으로 호출해 events(enum_coverage)로만
적재한다. 개입(보완 검색·재생성) 없음 — 먼저 재고, 빈도를 보고 개입을 결정
(claim audit → 프롬프트 각론과 같은 2단계 패턴). 프롬프트 측 대응은
supervisor v24(열거 완전성 규율)가 담당.
"""
from __future__ import annotations

import re

# 열거 마커: 행머리 불릿/번호 + 인라인 ▲(보도자료 관행 — "…개발▲ …개발▲ …").
_LINE_ITEM = re.compile(
    r"^[ \t]*(?:[▲△■□●•◦*]|[-–][ \t]|\d{1,2}[.)][ \t]|[①-⑳])[ \t]*(.+)$",
    re.MULTILINE,
)
_INLINE_MARKS = ("▲", "△", "①")

# 항목 제목에서 변별력 없는 범용어 — 커버 판정 토큰에서 제외.
_STOPWORDS = frozenset({
    "개발", "위한", "기반", "통한", "및", "등", "관련", "대한", "이용한", "활용한",
    "사업", "사업화", "구축", "제작", "연구", "과제", "지원", "제품", "기술",
    "시스템", "플랫폼", "서비스", "모델", "장치", "국내", "국산", "세계최초",
    "국내최초", "맞춤형", "차세대", "스마트", "지능형",
})

_MIN_ITEMS = 3          # 미만이면 열거로 안 봄(일반 문장 오탐 방지)
_MAX_ITEMS = 40         # 초과분 무시(폭주 방지)
_ITEM_LEN = (6, 120)    # 항목 제목 길이 범위(자)


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" .,;:·-—|")
    return s.strip()


def extract_enumerated_items(text: str) -> list[str]:
    """입력에서 열거 항목 제목을 뽑는다. 열거가 아니면 빈 리스트."""
    if not text:
        return []
    items: list[str] = []
    for m in _LINE_ITEM.finditer(text):
        items.append(_clean(m.group(1)))
    # 인라인 열거(개행 없이 ▲…▲…) — 행머리 매칭이 첫 항목만 잡는 케이스 보강.
    for mark in _INLINE_MARKS:
        if text.count(mark) >= _MIN_ITEMS:
            parts = text.split(mark)[1:]
            for p in parts:
                # 항목은 다음 마커·개행 전까지 — 문단 꼬리가 붙지 않게 첫 줄만.
                items.append(_clean(p.split("\n", 1)[0]))
            break
    lo, hi = _ITEM_LEN
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if not (lo <= len(it) <= hi):
            continue
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
        if len(out) >= _MAX_ITEMS:
            break
    return out if len(out) >= _MIN_ITEMS else []


def _tokens(item: str) -> list[str]:
    toks = re.findall(r"[A-Za-z0-9가-힣]{2,}", item)
    sig = [t for t in toks if t not in _STOPWORDS]
    # 길고 특수한 토큰이 변별력 높다 — 길이순 상위 6개만.
    sig.sort(key=len, reverse=True)
    return sig[:6]


def _tok_hit(t: str, answer: str) -> bool:
    # 복합명사 어미 변형 허용("디지털병리기기" ↔ 답변의 "디지털병리") —
    # 5자 이상 토큰은 끝 2자를 뗀 접두로도 매칭.
    return t in answer or (len(t) >= 5 and t[: len(t) - 2] in answer)


def _covered(item: str, answer: str) -> bool:
    toks = _tokens(item)
    if not toks:
        return True  # 변별 토큰이 없으면 판정 불가 — 누락으로 안 세운다
    # 5자 이상 토큰은 단독으로도 변별력 충분("연속혈당측정기") — 1개 매칭이면
    # 커버. 짧은 토큰뿐이면 2개 이상 겹쳐야 커버(우연 일치 방지).
    if any(_tok_hit(t, answer) for t in toks if len(t) >= 5):
        return True
    hits = sum(1 for t in toks if t in answer)
    return hits >= min(2, len(toks))


def audit_enumeration(question: str, answer: str) -> dict | None:
    """질문의 열거 항목 vs 답변 커버리지. 열거가 없으면 None.

    반환: {"items": n, "covered": k, "missing": [항목 제목…]} — events 적재용.
    """
    items = extract_enumerated_items(question or "")
    if not items:
        return None
    missing = [it for it in items if not _covered(it, answer or "")]
    return {
        "items": len(items),
        "covered": len(items) - len(missing),
        "missing": missing[:10],
    }
