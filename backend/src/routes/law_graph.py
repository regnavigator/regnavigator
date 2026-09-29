"""법률 네트워크 서브그래프 — 요구사항 ④ (도메인 전문가용).

사용자가 채팅 응답의 인용(article_key)을 seed 로, 조문 인용 네트워크를 보며
grounding 에 쓸 법률을 직접 고를 수 있게 한다. 본 엔드포인트는 그 네트워크
데이터(노드+엣지)를 반환한다. 비차단 — 선택 결과는 다음 /chat 요청에 동봉.

데이터 토대(2026-06-18 라이브 측정): Neo4j Article 1.23M, CITES 커버리지 75.4%.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.retrieval.neo4j_client import ALLOWED_GRAPH_REL_TYPES, fetch_law_subgraph

router = APIRouter()

_MAX_SEEDS = 20


@router.get("/law-graph")
def get_law_graph(
    keys: str = Query(..., description="콤마구분 seed article_key (예: 006364_000100,001275_000700)"),
    depth: int = Query(1, ge=1, le=2, description="확장 홉 수(1~2)"),
    rels: str = Query("CITES", description="콤마구분 관계 타입 (CITES, DELEGATES_TO 등)"),
    per_node_cap: int = Query(25, ge=1, le=100, description="노드당 이웃 상한"),
    max_nodes: int = Query(80, ge=1, le=300, description="전체 노드 상한"),
):
    """seed article_key 들의 조문 인용 네트워크 서브그래프.

    응답:
      {
        "seeds": [str],
        "nodes": [{id, label, law_id, law_title, jo, gaji, target_type,
                   enforcement_date, is_seed}],
        "edges": [{source, target, type}],
        "node_count": int, "edge_count": int, "truncated": bool
      }

    422: seed 누락/과다 또는 허용되지 않은 rel 타입.
    503: Neo4j 연결 비활성.
    """
    seed_keys = [k.strip() for k in keys.split(",") if k.strip()]
    if not seed_keys:
        raise HTTPException(status_code=422, detail="keys 필수 (콤마구분 article_key)")
    if len(seed_keys) > _MAX_SEEDS:
        raise HTTPException(status_code=422, detail=f"seed 과다 (최대 {_MAX_SEEDS})")

    rel_types = tuple(r.strip() for r in rels.split(",") if r.strip())
    bad = [r for r in rel_types if r not in ALLOWED_GRAPH_REL_TYPES]
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"허용되지 않은 rel 타입: {bad}. 허용: {list(ALLOWED_GRAPH_REL_TYPES)}",
        )

    sub = fetch_law_subgraph(
        seed_keys,
        depth=depth,
        per_node_cap=per_node_cap,
        max_nodes=max_nodes,
        rel_types=rel_types or ("CITES",),
    )
    if sub is None:
        raise HTTPException(status_code=503, detail="Neo4j 연결 비활성")
    return sub
