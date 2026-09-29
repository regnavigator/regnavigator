"""리랭커 모델 A/B — 평가셋으로 실측(무중단 오프라인).

검색서버를 재시작하거나 ETL 코드를 고치지 않고 리랭커 후보를 비교한다:

1. 검색 API 에 `rerank=false` 로 **후보 풀**만 받는다(0.08s — 리랭커 미사용).
2. 후보 모델별로 그 풀을 **오프라인 재정렬**(CrossEncoder).
3. 같은 실버 라벨(`data/eval_queries.json`)로 hit@k·MRR 채점 + 쌍당 지연 측정.

현행 모델도 오프라인으로 함께 돌려 **동일 조건 비교**(법률종 부스팅은 서버 후단이라
빠짐 → 모델 간 상대 비교용. 절대 수치는 `eval_retrieval.py`(라이브 API) 기준).

⚠️ **DGX 에서 실행**(GPU 필요). 모델은 최초 1회 HF 다운로드.

usage (DGX):
  python ab_reranker.py                       # 기본 후보군
  AB_MODELS="a/b,c/d" POOL=25 python ab_reranker.py
env:
  SEARCH_URL(기본 http://localhost:8080) · SEARCH_KEY · POOL(25) · AB_DEVICE(cuda)
"""

from __future__ import annotations

import json
import os
import sys
import time

_DEFAULT_MODELS = [
    "BAAI/bge-reranker-v2-m3",                      # 현행(568M) — 오프라인 baseline
    "BAAI/bge-reranker-base",                       # 278M — 더 빠름
    "Alibaba-NLP/gte-multilingual-reranker-base",   # 306M — 다국어 강함
    "jinaai/jina-reranker-v2-base-multilingual",    # 278M — 빠르고 다국어
    "dragonkue/bge-reranker-v2-m3-ko",              # 한국어 파인튜닝(같은 크기)
]


def _pools(queries, url, key, pool):
    """rerank=false 로 후보 풀 수집 (article_key, text)."""
    import httpx

    out = []
    with httpx.Client(timeout=60) as c:
        for q in queries:
            r = c.post(f"{url}/search",
                       json={"query": q["query"], "top_k": pool, "rerank": False},
                       headers={"X-API-Key": key})
            r.raise_for_status()
            cands = [(h["article_key"],
                      f"{h.get('law_title','')} {h.get('article_title','')} {h.get('snippet','')}"[:1200])
                     for h in r.json() if h.get("article_key")]
            out.append((q["query"], q.get("relevant_keys") or [], cands))
    return out


def _score(model_id, pools, device):
    """모델로 재정렬 → (hit@1, hit@3, hit@5, MRR, 쌍당 ms)."""
    from sentence_transformers import CrossEncoder

    m = CrossEncoder(model_id, device=device, max_length=512, trust_remote_code=True)
    try:
        m.model.half()
    except Exception:  # noqa: BLE001 — fp16 미지원 모델은 그대로
        pass

    h1 = h3 = h5 = 0.0
    rr = 0.0
    pairs = t = 0
    for q, rel, cands in pools:
        if not cands:
            continue
        t0 = time.perf_counter()
        scores = m.predict([(q, c[1]) for c in cands])
        t += time.perf_counter() - t0
        pairs += len(cands)
        ranked = [k for k, _ in sorted(zip(cands, scores), key=lambda x: -x[1])]
        ranked = [c[0] for c in ranked]
        rs = set(rel)
        h1 += any(k in rs for k in ranked[:1])
        h3 += any(k in rs for k in ranked[:3])
        h5 += any(k in rs for k in ranked[:5])
        for i, k in enumerate(ranked, 1):
            if k in rs:
                rr += 1 / i
                break
    n = len(pools)
    return h1 / n, h3 / n, h5 / n, rr / n, (t / pairs) * 1000 if pairs else 0.0


def main() -> int:
    url = (os.getenv("SEARCH_URL") or "http://localhost:8080").rstrip("/")
    key = os.getenv("SEARCH_KEY") or ""
    pool = int(os.getenv("POOL") or "25")
    device = os.getenv("AB_DEVICE") or "cuda"
    models = [m.strip() for m in (os.getenv("AB_MODELS") or "").split(",") if m.strip()] \
        or _DEFAULT_MODELS

    with open("eval_queries.json", encoding="utf-8") as f:
        queries = json.load(f)
    print(f"[ab] 질의 {len(queries)} · pool={pool} · device={device}\n")

    pools = _pools(queries, url, key, pool)
    avg = sum(len(c) for _, _, c in pools) / len(pools)
    print(f"[ab] 후보 풀 수집 완료(평균 {avg:.1f}건/질의)\n")

    print(f"{'모델':<48} {'hit@1':>6} {'hit@3':>6} {'hit@5':>6} {'MRR':>6} {'ms/쌍':>7}")
    print("-" * 84)
    for mid in models:
        try:
            a, b, c, mrr, ms = _score(mid, pools, device)
            print(f"{mid:<48} {a:6.2f} {b:6.2f} {c:6.2f} {mrr:6.3f} {ms:7.1f}")
        except Exception as e:  # noqa: BLE001 — 다운로드/호환 실패는 건너뜀
            print(f"{mid:<48}  실패: {type(e).__name__}: {str(e)[:40]}")
    print("\n[ab] 상대 비교용(법률종 부스팅 제외). 채택 시 라이브 eval_retrieval.py 로 재확인.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
