"""검색 품질 metrics — 순수 함수(라이브 의존 없음, 테스트 가능).

입력: retrieved(랭크순 article_key 리스트), relevant(정답 article_key 집합).
recall@k = 정답 중 상위 k 에 든 비율 / precision@k = 상위 k 중 정답 비율 /
hit@k = 상위 k 에 정답 하나라도 / MRR = 첫 정답의 역순위.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional


_EF_SUFFIX = re.compile(r"_ef\d{8}$")


def normalize_key(article_key: str) -> str:
    """시행예정본 키(`…_ef20270527`) → 현행 키. 평가 비교 전에 적용(2026-10-03).

    종전엔 평가가 `SEARCH_INCLUDE_PENDING=0` 을 강제했다 — 운영 기본값(1)인 핵심
    기능이 평가 대상에서 빠져 있었다. 이유는 라벨이 현행 키만 수록해 예정본이 미스로
    잡혔기 때문이지 품질 저하가 아니었다(측정 아티팩트). 키를 정규화하면 운영과 같은
    설정으로 잴 수 있다.
    """
    return _EF_SUFFIX.sub("", article_key or "")


def normalize_keys(keys: Iterable[str]) -> list[str]:
    """정규화 + 순서 보존 dedupe(예정본·현행본이 같은 조문으로 합쳐질 때)."""
    out: list[str] = []
    seen: set[str] = set()
    for k in keys:
        n = normalize_key(k)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def recall_at_k(retrieved: list[str], relevant: Iterable[str], k: int) -> Optional[float]:
    """정답 중 상위 k 에 든 비율. 정답 라벨 없으면 None(정의 안 됨)."""
    rel = set(relevant)
    if not rel:
        return None
    topk = set(retrieved[:k])
    return len(topk & rel) / len(rel)


def precision_at_k(retrieved: list[str], relevant: Iterable[str], k: int) -> Optional[float]:
    """상위 k 중 정답 비율. 정답 라벨 없으면 None(정의 안 됨).

    **라벨이 없는 질의를 0 으로 세면 안 된다**(2026-10-02). 평가셋 183 중 69
    (37.7%)가 라벨 0건이라, 그걸 0점으로 분모에 넣으면 지표가 38% 과소보고되고
    검색을 아무리 개선해도 **절대 올라가지 않는 바닥**이 생긴다 — 보고된
    hit@3 0.54 는 라벨 있는 114 기준 ≈0.87 이었다. 그 바닥을 들고 튜닝하고
    있었다. `recall_at_k` 는 처음부터 None 이었는데 이 둘만 0.0 이었다.
    """
    rel = set(relevant)
    if not rel:
        return None
    topk = retrieved[:k]
    if not topk:
        return 0.0
    return sum(1 for r in topk if r in rel) / len(topk)


def hit_at_k(retrieved: list[str], relevant: Iterable[str], k: int) -> Optional[float]:
    """상위 k 에 정답이 하나라도 있으면 1.0. 정답 라벨 없으면 None."""
    rel = set(relevant)
    if not rel:
        return None
    return 1.0 if set(retrieved[:k]) & rel else 0.0


def reciprocal_rank(retrieved: list[str], relevant: Iterable[str]) -> Optional[float]:
    """첫 정답의 역순위(1/rank). 없으면 0. 정답 라벨 없으면 None."""
    rel = set(relevant)
    if not rel:
        return None
    for i, r in enumerate(retrieved, start=1):
        if r in rel:
            return 1.0 / i
    return 0.0


def evaluate_query(
    retrieved: list[str],
    relevant: Iterable[str],
    *,
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> dict:
    """단일 질의 metrics dict."""
    rel = list(relevant)
    out: dict = {"mrr": reciprocal_rank(retrieved, rel)}
    for k in ks:
        out[f"recall@{k}"] = recall_at_k(retrieved, rel, k)
        out[f"precision@{k}"] = precision_at_k(retrieved, rel, k)
        out[f"hit@{k}"] = hit_at_k(retrieved, rel, k)
    return out


def claim_groundedness(audited: list[dict]) -> dict:
    """무인용 사실 audit 결과 → 지지율 지표(factual-verification Phase 1).

    audited = [{"claim":.., "verdict": supported|contradicted|unverified}].
    반환: {total, supported, contradicted, unverified, supported_rate,
    unsupported_rate}. unsupported_rate = (contradicted+unverified)/total.
    total 0 이면 rate None(정의 안 됨).
    """
    total = len(audited or [])
    if total == 0:
        return {
            "total": 0, "supported": 0, "contradicted": 0, "unverified": 0,
            "supported_rate": None, "unsupported_rate": None,
        }
    from collections import Counter

    c = Counter((a.get("verdict") or "") for a in audited)
    s, con, unv = c.get("supported", 0), c.get("contradicted", 0), c.get("unverified", 0)
    return {
        "total": total, "supported": s, "contradicted": con, "unverified": unv,
        "supported_rate": round(s / total, 4),
        "unsupported_rate": round((con + unv) / total, 4),
    }


def aggregate(per_query: list[dict]) -> dict:
    """질의별 metrics → 평균(None 은 제외)."""
    if not per_query:
        return {}
    out: dict = {}
    for key in per_query[0].keys():
        vals = [q[key] for q in per_query if q.get(key) is not None]
        out[key] = round(sum(vals) / len(vals), 4) if vals else None
    return out
