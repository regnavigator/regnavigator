"""출처 적합성 필터 — 의미 유사도 ≠ 적용가능성 (2026-10-02).

**문제.** 벡터 검색은 "조문 텍스트가 질의와 얼마나 닮았나"로 뽑는다. 그런데
사용자가 필요한 건 "**이 법령이 내 상황에 적용되는가**"다. 둘은 다르다.

실측(2026-10-02, 카페 개업 질의):
  - 「어린이 식생활안전관리 특별법」 별표: 어린이 기호식품 우수판매업소 시설기준
    → '식품접객업' 용어가 겹쳐 뽑혔지만 **적용 대상이 어린이 기호식품 판매업소**다.
  - 「서울특별시 서대문구 카페 폭포 운영 조례」 → '카페'가 폭포 이름이다.
  - 상위 17건 중 13건이 전국 각지의 **음식판매자동차(푸드트럭) 조례** — 사용자
    관할과 무관하다.
  - 「공유재산 및 물품 관리법 시행령」 → 「식품위생법 시행령」을 **인용하는 문장**에
    '휴게음식점영업'이 등장해 뽑혔다.

종전 파이프라인에는 적용가능성을 보는 층이 **아예 없었다**(검색→중복제거→인용).
그래서 이 네 유형이 전부 모델에게 그대로 전달되고, 모델이 쓰면 인용이 됐다.

**설계.** 인용 번호를 매기기 **전에** 거른다(`_assign_turn_citation_numbers` 앞).
번호가 붙은 뒤에 빼면 본문 `[n]` 과 참고문헌이 어긋나고, 모델에게 준 뒤에 빼면
이미 답변에 쓰인 뒤다.

거르는 규칙은 전부 **법령명·조문제목·발췌 문자열**만 본다 — 외부 호출이 없어
TTFT 에 영향이 없다. 규칙이 놓치는 것은 `applicability.py` 의 LLM 판정이 받는다.

**안전장치.** 규칙이 과하면 근거가 0건이 되고 답을 못 한다. 그래서
`MIN_KEEP` 건은 점수 순으로 무조건 남긴다 — 필터는 노이즈를 깎는 장치지
근거를 없애는 장치가 아니다.
"""

from __future__ import annotations

import os
import re
from typing import Optional

#: 규칙이 전부 걸러도 이만큼은 남긴다(점수 상위). 근거 0건 방지.
MIN_KEEP = 4

# ── ① 적용대상 한정어 ───────────────────────────────────────────────────────
# 법령명·조문제목에 이 말이 있으면 그 법은 **그 대상 전용**이다. 질의에 같은
# 대상이 없으면 적용되지 않는다. (어린이 식생활안전관리 특별법 사례)
_SCOPE_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("어린이", ("어린이", "아동", "유아", "영유아", "키즈", "소아")),
    ("청소년", ("청소년", "미성년", "학생")),
    ("노인", ("노인", "고령", "실버")),
    ("장애인", ("장애인", "장애")),
    ("임산부", ("임산부", "임신", "산모")),
    ("학교", ("학교", "교육", "학생", "급식")),
    ("군인", ("군인", "군", "병영")),
    ("농어업인", ("농어업", "농업", "어업", "농어촌", "농가")),
    ("외국인", ("외국인", "이주", "다문화")),
    ("개식용", ("개식용", "개 사육", "식용견")),
    ("전통시장", ("전통시장", "시장")),
)

# ── ② 임의 제도 ─────────────────────────────────────────────────────────────
# '우수·인증·등급·모범' 류는 **받아도 되고 안 받아도 되는** 제도다. 의무 절차를
# 물었는데 이게 섞이면 사용자는 필수 요건으로 오해한다.
_VOLUNTARY = ("우수", "인증", "지정평가", "위생등급", "등급 지정", "모범업소",
              "안심업소", "표창", "선정", "포상")
_DUTY_CUES = ("신고", "허가", "등록", "의무", "절차", "요건", "해야", "필요")

# ── ③ 관할 ─────────────────────────────────────────────────────────────────
#: 질의에 지자체가 특정됐는가. "서울시", "마포구", "성남시", "제주특별자치도"…
_REGION_RE = re.compile(
    r"(특별시|광역시|특별자치시|특별자치도|[가-힣]{1,6}(?:시|군|구|도)\b)")
#: 자치법규를 몇 건 이상 거르면 사용자에게 관할을 되묻게 하는가.
ASK_REGION_AT = 3

# ── ④ 타법 인용 유발 ───────────────────────────────────────────────────────
#: 「○○법」 … 바로 뒤에 질의어가 오는 꼴. 그 조문의 주제가 아니라 **인용**이다.
_CROSSREF_RE = re.compile(r"「[^」]{2,40}」\s*(?:제\d+조[^\s]*\s*)?[^。.\n]{0,20}$")


def _text_of(hit: dict) -> str:
    return " ".join(str(hit.get(k) or "") for k in
                    ("law_title", "article_title", "article_num"))


def has_region(query: str) -> bool:
    """질의가 관할 지자체를 특정했는가."""
    return bool(_REGION_RE.search(query or ""))


def _scope_mismatch(query: str, title: str) -> Optional[str]:
    q = query or ""
    for label, syns in _SCOPE_TERMS:
        if label not in title:
            continue
        if any(s in q for s in syns):
            return None          # 질의도 그 대상을 말하고 있다 — 적용된다
        return f"적용대상 불일치({label})"
    return None


def _voluntary_scheme(query: str, title: str) -> Optional[str]:
    if not any(v in title for v in _VOLUNTARY):
        return None
    if not any(d in (query or "") for d in _DUTY_CUES):
        return None
    return "임의 제도(의무 절차 질의)"


def _crossref_only(query: str, hit: dict) -> Optional[str]:
    """질의 핵심어가 **타법 인용 구문 안에서만** 등장하는가.

    「공유재산 및 물품 관리법 시행령」이 "「식품위생법 시행령」 제21조제8호가목의
    휴게음식점영업" 이라고 쓰면 '휴게음식점영업' 이 그 조문의 주제처럼 보인다.
    실제 주제는 공유재산 사용허가다.
    """
    snippet = str(hit.get("snippet") or "")
    law_title = str(hit.get("law_title") or "")
    if not snippet or "「" not in snippet:
        return None
    # 질의어 중 제목에 없고 발췌에만 있는 2글자 이상 토큰
    for tok in {t for t in re.split(r"[\s,·]+", query or "") if len(t) >= 3}:
        if tok in law_title or tok not in snippet:
            continue
        # 그 토큰이 등장하는 자리마다 앞이 「…법」 인용인지 본다
        spots = [m.start() for m in re.finditer(re.escape(tok), snippet)]
        if spots and all(_CROSSREF_RE.search(snippet[:s]) for s in spots):
            return "타법 인용 문장에서만 일치"
    return None


def classify(query: str, hit: dict, *, max_score: float | None = None) -> Optional[str]:
    """제외 사유. 통과면 None.

    `max_score` 를 주면 점수 꼬리도 본다 — 리랭커 점수는 **음수가 될 수 있어서**
    비율만 쓰면 부호가 뒤집힌다. 음수는 그 자체로 탈락.
    """
    title = _text_of(hit)

    if hit.get("target_type") == "ordin" and not has_region(query):
        return "관할 미지정(자치법규)"

    for check in (_scope_mismatch(query, title),
                  _voluntary_scheme(query, title)):
        if check:
            return check

    r = _crossref_only(query, hit)
    if r:
        return r

    score = hit.get("score")
    if isinstance(score, (int, float)):
        if score < 0:
            return "점수 음수"
        if max_score and max_score > 0 and score < max_score * _tail_ratio():
            return f"점수 꼬리({score / max_score * 100:.0f}%)"
    return None


def _tail_ratio() -> float:
    try:
        return float((os.getenv("SOURCE_FILTER_TAIL_RATIO") or "").strip() or "0.12")
    except ValueError:
        return 0.12


def disabled() -> bool:
    return (os.getenv("SOURCE_FILTER_DISABLE") or "").strip() == "1"


def apply(query: str, hits: list[dict]) -> tuple[list[dict], list[dict]]:
    """(통과 hits, 제외 기록) — 제외 기록은 `{article_key, title, reason}`.

    `MIN_KEEP` 보장: 통과가 그보다 적으면 제외분에서 점수 순으로 채운다.
    """
    if disabled() or not hits:
        return hits, []

    scores = [h.get("score") for h in hits if isinstance(h.get("score"), (int, float))]
    mx = max(scores) if scores else None

    kept: list[dict] = []
    dropped: list[tuple[dict, str]] = []
    for h in hits:
        reason = classify(query, h, max_score=mx)
        if reason:
            dropped.append((h, reason))
        else:
            kept.append(h)

    if len(kept) < MIN_KEEP and dropped:
        # 근거가 모자라면 되살린다 — 답을 못 하는 것보다 낫다. 단 **되살려도 되는
        # 사유만**이다(2026-10-02 실측 교훈): 관할 미지정·점수 꼬리는 "이 질의에
        # 안 맞다"가 아니라 "확신이 약하다"지만, 적용대상 불일치·임의 제도·타법
        # 인용은 **그 법이 이 상황에 적용되지 않는다**는 판정이다. 그걸 되살리면
        # 애초에 막으려던 바로 그 인용(어린이 식생활안전관리 특별법)이 돌아온다.
        revivable = [d for d in dropped if d[1].startswith(("관할 미지정", "점수"))]
        revivable.sort(key=lambda d: d[0].get("score") or 0, reverse=True)
        revive_n = MIN_KEEP - len(kept)
        revived = {id(h) for h, _ in revivable[:revive_n]}
        for h, _r in revivable[:revive_n]:
            kept.append(h)
        dropped = [d for d in dropped if id(d[0]) not in revived]

    log = [{"article_key": h.get("article_key"),
            "title": _text_of(h)[:80],
            "target_type": h.get("target_type"),
            "reason": r} for h, r in dropped]
    return kept, log


def region_hint(dropped: list[dict]) -> Optional[str]:
    """자치법규를 다수 걸렀으면 모델에게 **지역을 되묻게** 하는 지시를 만든다.

    버리고 입을 닫으면 "지자체마다 다르다"는 중요한 사실까지 사라진다. 사용자
    결정(2026-10-02): 지역을 되묻는다.
    """
    n = sum(1 for d in dropped if d.get("reason", "").startswith("관할 미지정"))
    if n < ASK_REGION_AT:
        return None
    return (f"⚠️ 자치법규 {n}건이 검색됐으나 질문에 관할 지자체가 없어 제외했다. "
            "이 사안은 지자체 조례로 요건이 달라질 수 있다 — 답변 말미에 "
            "**어느 지역인지 한 줄로 되물어라**. 추측해서 특정 지자체 조례를 "
            "인용하지 마라.")
