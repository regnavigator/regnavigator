"""평가 라벨 생성 — 질의를 검색해 LLM-judge 로 관련성 판정 → 실버 라벨.

정답 article_key 라벨링은 도메인 지식이 필요해 수작업이 이상적이나, 회귀 감시용
**실버 라벨**(LLM 판정)로 부트스트랩한다. 각 질의를 넓게 검색(top_k=LABEL_POOL)한 뒤
LLM(기본 Sonnet)이 각 후보의 관련성을 판정 → 관련 키만 relevant_keys 로 저장.

한계(정직히): ① LLM 판정이라 gold 아님(도메인 전문가 검수 필요). ② 검색이 놓친
관련 조문은 라벨 풀에 없어 recall 상한이 존재. → **회귀 감시·상대 비교엔 유효**,
절대 정확도 주장엔 부적합.

usage:
  python scripts/build_eval_labels.py            # seed → data/eval_queries.json
  LABEL_POOL=15 JUDGE_MODEL=anthropic:claude-sonnet-4-6 python scripts/build_eval_labels.py
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

_SEED = os.getenv("EVAL_SEED") or "data/eval_queries_seed.json"
_OUT = os.getenv("EVAL_OUT") or "data/eval_queries.json"
_POOL = int(os.getenv("LABEL_POOL") or "15")

_JUDGE_SYS = (
    "너는 의료 규제 검색 평가자다. 사용자 질의와 후보 법령 조문 목록이 주어진다. "
    "각 후보가 질의에 **직접 답하는 데 실제로 관련 있는지** 판정하라. 제목·조문번호·"
    "발췌를 근거로 관련 있는 것만 고른다. 애매하면 제외(정밀도 우선). "
    "출력은 관련 있는 후보의 key 만 JSON 배열로. 예: [\"009514_0006001\", \"...\"]. "
    "관련 없으면 []. 오직 JSON 배열만 출력."
)


def _judge(llm, query: str, hits: list[dict]) -> list[str]:
    cand = [
        {"key": h.get("article_key"),
         "law": h.get("law_title"), "article": h.get("article_num"),
         "snippet": (h.get("snippet") or "")[:200]}
        for h in hits if h.get("article_key")
    ]
    if not cand:
        return []
    prompt = (
        f"[질의]\n{query}\n\n[후보 조문]\n"
        + json.dumps(cand, ensure_ascii=False, indent=1)
    )
    from langchain_core.messages import HumanMessage, SystemMessage
    resp = llm.invoke([SystemMessage(content=_JUDGE_SYS),
                       HumanMessage(content=prompt)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    text = text.strip()
    # JSON 배열만 추출(코드펜스 등 제거).
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        keys = json.loads(text[start:end + 1])
    except ValueError:
        return []
    valid = {c["key"] for c in cand}
    return [k for k in keys if k in valid]


def main() -> int:
    if not os.path.exists(_SEED):
        print(f"seed 없음: {_SEED}")
        return 1
    with open(_SEED, encoding="utf-8") as f:
        seed = json.load(f)

    from src.models import primary_model
    from src.retrieval.search_api_client import is_available, search_articles

    if not is_available():
        print("검색 API 미설정(RAG_SEARCH_API_URL/KEY) — 라벨 생성 불가")
        return 1
    llm = primary_model(os.getenv("JUDGE_MODEL"))

    out: list[dict] = []
    print(f"[label] {len(seed)} 질의 · pool={_POOL} · judge={os.getenv('JUDGE_MODEL') or 'primary'}\n")
    for i, item in enumerate(seed, start=1):
        q = item["query"]
        # seed 별 종별 지정(guide 질의 등, 2026-07-24) — 미지정은 기본 종 세트.
        tts = item.get("target_types")
        hits = search_articles(q, top_k=_POOL, target_types=tts)
        rel = _judge(llm, q, hits)
        entry: dict = {"query": q, "relevant_keys": rel}
        if tts:
            entry["target_types"] = tts
        out.append(entry)
        tag = f"[{','.join(tts)}] " if tts else ""
        print(f"  {i:2}. rel={len(rel):2}/{len(hits):2}  {tag}{q[:36]}")

    labeled = sum(1 for o in out if o["relevant_keys"])
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[label] 저장 {_OUT} — {labeled}/{len(out)} 질의에 라벨 있음(실버).")
    print("주의: LLM 판정 실버 라벨 — gold 는 도메인 전문가 검수 필요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
