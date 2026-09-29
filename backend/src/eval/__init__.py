"""RAG 검색 품질 평가 — 라벨 기반 metrics (recall@k·precision@k·MRR).

품질을 숫자로 측정해야 개선이 추측이 아니다. `metrics.py` 는 순수 함수(테스트 가능),
`scripts/eval_retrieval.py` 가 실제 run_qdrant 로 돌려 집계한다.
"""
