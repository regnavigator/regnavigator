"""RAG 검색 품질 평가 — 라벨 질문셋으로 recall@k·precision@k·MRR 집계.

품질을 숫자로 본다. 질문셋(JSON)에 정답 article_key 를 라벨링하면, 실제 run_qdrant
로 검색해 상위 결과가 정답을 얼마나 잡는지 측정.

질문셋 형식 (data/eval_queries.json):
  [
    {"query": "의료기기 제조허가 절차", "relevant_keys": ["009514_0006001", ...]},
    ...
  ]
  (정답 article_key = /article·citation 의 그 키. 7자리 PG/Qdrant 포맷.)

usage:
  python scripts/eval_retrieval.py [질문셋경로]      # 기본 data/eval_queries.json
  EVAL_TOP_K=10 python scripts/eval_retrieval.py

※ 임베딩·Qdrant 가 떠 있어야 실행됨(없으면 검색 빈 결과 → 0점).
"""

from __future__ import annotations

import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

# 운영과 같은 설정(`SEARCH_INCLUDE_PENDING=1`)으로 잰다(2026-10-03). 종전엔 0 을
# 강제했다 — 예정본 키(`_ef…`)가 라벨에 없어 미스로 잡히는 **측정 아티팩트**를 피하려
# 핵심 기능을 평가에서 뺀 것. 지금은 `normalize_keys` 가 키를 현행으로 접어 비교한다.
# 명시 설정이 있으면 존중.
os.environ.setdefault("SEARCH_INCLUDE_PENDING", "1")


def main() -> int:
    path = (sys.argv[1] if len(sys.argv) > 1
            else os.getenv("EVAL_QUERY_SET") or "data/eval_queries.json")
    if not os.path.exists(path):
        print(f"질문셋 없음: {path}\n"
              f"형식: [{{\"query\": ..., \"relevant_keys\": [article_key...]}}]")
        return 1

    with open(path, encoding="utf-8") as f:
        queries = json.load(f)
    top_k = int(os.getenv("EVAL_TOP_K") or "10")

    from src.eval.metrics import aggregate, evaluate_query, normalize_keys
    from src.tools.search import run_qdrant

    per_query: list[dict] = []
    print(f"[eval] {len(queries)} 질의 · top_k={top_k}\n")
    for i, item in enumerate(queries, start=1):
        q = item["query"]
        relevant = item.get("relevant_keys") or []
        t0 = time.perf_counter()
        try:
            # 라벨과 동일 종별로 검색(guide 질의 등) — 미지정은 기본(종전 동작).
            core = run_qdrant(q, top_k=top_k,
                              target_types=item.get("target_types"))
            retrieved = normalize_keys(core.final_keys)
        except Exception as e:  # noqa: BLE001
            print(f"  {i}. ERROR {type(e).__name__}: {e}")
            retrieved = []
        m = evaluate_query(retrieved, normalize_keys(relevant), ks=(1, 3, 5, top_k))
        per_query.append(m)
        print(f"  {i}. recall@{top_k}={m[f'recall@{top_k}']} "
              f"mrr={m['mrr']:.3f} ({time.perf_counter() - t0:.1f}s) | {q[:40]}")

    agg = aggregate(per_query)
    print("\n=== 집계 ===")
    for k, v in agg.items():
        print(f"  {k}: {v}")

    out_path = os.getenv("EVAL_REPORT_OUT") or "eval_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"aggregate": agg, "per_query": per_query}, f,
                  ensure_ascii=False, indent=2)
    print(f"\n(리포트: {out_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
