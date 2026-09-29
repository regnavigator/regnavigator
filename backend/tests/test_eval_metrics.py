"""검색 품질 metrics 순수 함수 테스트."""
from __future__ import annotations

from src.eval.metrics import (
    aggregate,
    evaluate_query,
    hit_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

R = ["a", "b", "c", "d", "e"]   # 랭크순 retrieved


def test_recall_at_k():
    assert recall_at_k(R, ["a", "c"], 3) == 1.0        # 둘 다 top3
    assert recall_at_k(R, ["a", "z"], 5) == 0.5        # a만 잡음
    assert recall_at_k(R, ["d"], 3) == 0.0             # d는 top3 밖
    assert recall_at_k(R, [], 3) is None               # 라벨 없음 → 정의 안 됨


def test_precision_at_k():
    assert precision_at_k(R, ["a", "b"], 2) == 1.0     # top2 다 정답
    assert precision_at_k(R, ["a"], 4) == 0.25         # top4 중 1개
    assert precision_at_k([], ["a"], 3) == 0.0


def test_hit_at_k():
    assert hit_at_k(R, ["c"], 3) == 1.0
    assert hit_at_k(R, ["d"], 3) == 0.0
    assert hit_at_k(R, ["z"], 5) == 0.0


def test_reciprocal_rank():
    assert reciprocal_rank(R, ["a"]) == 1.0            # 1위
    assert reciprocal_rank(R, ["c"]) == 1 / 3          # 3위
    assert reciprocal_rank(R, ["z"]) == 0.0            # 없음


def test_evaluate_query_shape():
    m = evaluate_query(R, ["a", "c"], ks=(1, 3, 5))
    assert m["recall@3"] == 1.0 and m["hit@1"] == 1.0 and m["mrr"] == 1.0
    assert set(m) >= {"recall@1", "precision@5", "hit@3", "mrr"}


def test_aggregate_means_and_skips_none():
    per = [
        {"recall@3": 1.0, "mrr": 1.0},
        {"recall@3": 0.0, "mrr": 0.5},
        {"recall@3": None, "mrr": 0.0},   # 라벨 없는 질의 → recall 평균서 제외
    ]
    agg = aggregate(per)
    assert agg["recall@3"] == 0.5         # (1.0+0.0)/2, None 제외
    assert agg["mrr"] == 0.5              # (1.0+0.5+0.0)/3


def test_aggregate_empty():
    assert aggregate([]) == {}
