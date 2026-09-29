"""Neo4j 클라이언트 — 별표(Attachment) 본문·인용 그래프 fetch.

운영 Attachment 노드 실제 schema (verify 결과):
  Attachment {
    id,                  # 006364_000100E_attachment
    title,               # 별표·서식 제목
    attachment_subtype,  # 별표 / 서식 / 별지
    annex_type,          # 별표 / 서식
    full_text,           # 본문 (markdown)
    link,                # 원본 다운로드 path (예: /LSW/flDownload.do?flSeq=...)
    mst_id, jurisdiction
  }

  (Law)-[:CONTAINS_ATTACHMENT]->(Attachment)
  (Article)-[:REFERS_TO_ATTACHMENT]->(Attachment)
  (Article)-[:CITES]->(Article)

env: NEO4J_URI, NEO4J_USER, NEO4J_PASS
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

_log = logging.getLogger(__name__)

_driver = None
_lock = threading.Lock()


def close_driver() -> None:
    """Neo4j 드라이버 종료(종료 경로 전용, 재호출 안전)."""
    global _driver
    drv, _driver = _driver, None
    if drv is None:
        return
    try:
        drv.close()
    except Exception:  # noqa: BLE001
        pass


def _get_driver():
    """neo4j Driver lazy init. None 반환 시 비활성."""
    global _driver
    if _driver is not None:
        return _driver

    uri = (os.getenv("NEO4J_URI") or "").strip()
    user = (os.getenv("NEO4J_USER") or "").strip()
    password = (os.getenv("NEO4J_PASS") or "").strip()
    if not (uri and user and password):
        return None

    with _lock:
        if _driver is not None:
            return _driver
        try:
            from neo4j import GraphDatabase
        except ImportError:
            _log.warning("neo4j 미설치 — `pip install neo4j`. 별표·그래프 기능 비활성.")
            return None

        try:
            _driver = GraphDatabase.driver(uri, auth=(user, password))
            _driver.verify_connectivity()
            _log.info("Neo4j connected: %s", uri)
        except Exception as e:
            _log.warning("Neo4j 연결 실패: %s", e)
            return None

    return _driver


def fetch_attachment(law_id: str, annex_num: str | int) -> Optional[dict]:
    """법령 ID + 별표 번호 → Attachment 본문.

    annex_num은 "19", "19의2" 같은 표시형 또는 "byl_001" 형태도 허용.
    Neo4j에서 Law의 CONTAINS_ATTACHMENT 관계로 Attachment 노드 fetch.

    반환:
        {
            "attachment_key": str,
            "title": str,
            "type": str,        # 별표 / 서식 / ...
            "content": str,     # 본문 markdown/text
            "law_id": str,
        }
        또는 None (미발견).
    """
    driver = _get_driver()
    if driver is None:
        return None

    # annex_num → 후보 id 정확 매칭(2026-08-25). 종전 CONTAINS 퍼지 매칭은
    # Attachment 0건 시절엔 무해했지만, ETL 40만 건 적재 후 번호 "1"이 제목·id
    # 부분문자열에 걸려 엉뚱한 첨부를 반환했다(실측: 별표 1 요청에 서식 반환).
    # id 규격은 PG 와 동일: {law_id}_{NNNN}{BB}{E|F}_attachment
    # (NNNN=번호 zero-pad 4, BB=가지 2, E=별표/F=서식 — pg_client 참조).
    from src.retrieval.pg_client import parse_annex_num

    num_str = str(annex_num).strip()
    candidates: list[str] = []
    parsed = parse_annex_num(num_str)
    if parsed:
        n, branch = parsed
        # 별표(E) 우선, 서식(F) 차선 — 종류 구분이 필요하면 /annex 처럼 PG(kind)로.
        candidates = [f"{law_id}_{n:04d}{branch:02d}E_attachment",
                      f"{law_id}_{n:04d}{branch:02d}F_attachment"]
    elif num_str.startswith("byl"):
        candidates = [f"{law_id}_{num_str}_attachment"]
    if not candidates:
        return None
    try:
        with driver.session() as s:
            res = s.run(
                """
                UNWIND $keys AS k
                MATCH (a:Attachment {id: k})
                RETURN a.id AS attachment_key,
                       a.title AS title,
                       a.annex_type AS annex_type,
                       a.attachment_subtype AS attachment_subtype,
                       a.full_text AS full_text,
                       a.link AS link
                LIMIT 1
                """,
                keys=candidates,
            ).single()
        if not res:
            return None
        return {
            "attachment_key": res["attachment_key"],
            "title": res["title"],
            "type": res["attachment_subtype"] or res["annex_type"],
            "content": res["full_text"],
            "link": res["link"],
            "law_id": law_id,
        }
    except Exception as e:
        _log.warning("Neo4j fetch_attachment 실패: %s", e)
        return None


def fetch_attachment_by_key(article_key: str) -> Optional[dict]:
    """Attachment.id 정확 매칭 — article_key(= Neo4j Attachment.id)로 직접 조회.

    `fetch_attachment(law_id, num)` 의 `CONTAINS` fuzzy 검색과 달리 id 정확 매칭이라
    더 빠르고(id 인덱스) 정확(부분문자열 충돌·번호 환산 불필요). citation payload에
    article_key 가 있으면 다운로드 링크 조회는 이 경로가 1순위.

    반환: fetch_attachment 와 동일 dict 또는 None.
    """
    driver = _get_driver()
    if driver is None:
        return None
    try:
        with driver.session() as s:
            res = s.run(
                """
                MATCH (a:Attachment {id: $key})
                RETURN a.id AS attachment_key,
                       a.title AS title,
                       a.annex_type AS annex_type,
                       a.attachment_subtype AS attachment_subtype,
                       a.full_text AS full_text,
                       a.link AS link
                LIMIT 1
                """,
                key=article_key,
            ).single()
        if not res:
            return None
        return {
            "attachment_key": res["attachment_key"],
            "title": res["title"],
            "type": res["attachment_subtype"] or res["annex_type"],
            "content": res["full_text"],
            "link": res["link"],
        }
    except Exception as e:
        _log.warning("Neo4j fetch_attachment_by_key 실패: %s", e)
        return None


# 법률 네트워크(요구사항 ④)에서 허용하는 조문-조문 관계 타입.
# Cypher relationship type 은 파라미터화 불가 → 화이트리스트로만 주입(인젝션 차단).
# 2026-06-18 라이브 측정: CITES 커버리지 75.4%, 그 외 위임·대응 등 풍부.
ALLOWED_GRAPH_REL_TYPES = (
    "CITES",
    "CITES_HISTORICAL",
    "DELEGATES_TO",
    "CORRESPONDS_TO",
    "REGULATES_VIA",
)


def _article_label(p: dict) -> str:
    """Article 노드 props → 사용자향 표시 라벨 ("{법령명} 제N조[의M]")."""
    law = (p.get("title") or "").strip()          # Article.title = 법령명
    jo = (str(p.get("jo") or "")).strip()
    gaji = (str(p.get("gaji") or "")).strip()
    art = f"제{jo}조" if jo else ""
    if gaji and gaji not in ("0", "00", "000"):
        art += f"의{gaji}"
    return (f"{law} {art}".strip()) or str(p.get("id") or "")


def _article_node(p: dict, *, is_seed: bool) -> dict:
    return {
        "id": p.get("id"),
        "label": _article_label(p),
        "law_id": p.get("lawId"),
        "law_title": p.get("title"),
        "jo": p.get("jo"),
        "gaji": p.get("gaji"),
        "target_type": p.get("targetType"),
        "enforcement_date": p.get("enforcementDate"),
        "is_seed": is_seed,
    }


def fetch_law_subgraph(
    seed_keys: list[str],
    *,
    depth: int = 1,
    per_node_cap: int = 25,
    max_nodes: int = 80,
    rel_types: tuple[str, ...] = ("CITES",),
) -> Optional[dict]:
    """seed article_key 들에서 조문 인용 네트워크 서브그래프를 만든다 (요구사항 ④).

    Qdrant 검색 결과의 `article_key`(= Neo4j `Article.id`)를 seed 로 받아, 방향무관
    인용 관계를 `depth` 홉까지 bounded BFS 로 확장한다. 허브 조문(out-degree 최대
    588)으로 폭발하지 않도록 per-node/total 캡을 둔다. 읽기전용.

    Args:
        seed_keys: 시작 article_key 목록.
        depth: 확장 홉 수(1~2 로 클램프).
        per_node_cap: 노드당 가져올 이웃 상한.
        max_nodes: 전체 노드 상한(초과 시 truncated=True).
        rel_types: 허용 관계 타입(ALLOWED_GRAPH_REL_TYPES 로 필터링).

    Returns:
        {seeds, nodes:[{id,label,law_id,law_title,jo,gaji,target_type,is_seed}],
         edges:[{source,target,type}], node_count, edge_count, truncated}
        Neo4j 비활성이면 None.
    """
    driver = _get_driver()
    if driver is None:
        return None

    seeds_in = list(dict.fromkeys(k for k in (seed_keys or []) if k))
    rels = [t for t in rel_types if t in ALLOWED_GRAPH_REL_TYPES] or ["CITES"]
    rel_pattern = "|".join(rels)
    depth = max(1, min(int(depth), 2))
    if not seeds_in:
        return {"seeds": [], "nodes": [], "edges": [], "node_count": 0,
                "edge_count": 0, "truncated": False}

    # seed 역해소: 채팅 citation 의 article_key 는 PG/Qdrant 7자리지만 Neo4j
    # Article.id 는 6자리(그 prefix). 후보 = 원본(이미 6자리면 매칭) + 끝1자 제거
    # (7→6). Neo4j id 인덱스 정확매칭으로 스캔 회피. (정방향=resolve_article_keys)
    candidates = list(dict.fromkeys(
        c for sd in seeds_in for c in (sd, sd[:-1]) if c
    ))

    visited: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}
    truncated = False

    try:
        with driver.session() as s:
            # seed 노드 적재(매칭된 Neo4j id 만 frontier).
            for r in s.run(
                "MATCH (a:Article) WHERE a.id IN $ids RETURN a", ids=candidates
            ).data():
                p = r["a"]
                visited[p["id"]] = p
            frontier = list(visited.keys())
            seed_set = set(frontier)

            for _hop in range(depth):
                if not frontier or len(visited) >= max_nodes:
                    break
                rows = s.run(
                    f"""
                    UNWIND $ids AS sid
                    MATCH (a:Article {{id: sid}})
                    CALL (a) {{
                        MATCH (a)-[c:{rel_pattern}]-(b:Article)
                        RETURN b AS b, type(c) AS rt,
                               startNode(c).id AS src, endNode(c).id AS dst
                        LIMIT $cap
                    }}
                    RETURN b, rt, src, dst
                    """,
                    ids=frontier, cap=per_node_cap,
                ).data()
                nxt: list[str] = []
                for row in rows:
                    edges[(row["src"], row["dst"], row["rt"])] = {
                        "source": row["src"], "target": row["dst"], "type": row["rt"],
                    }
                    b = row["b"]
                    bid = b.get("id")
                    if bid and bid not in visited:
                        if len(visited) >= max_nodes:
                            truncated = True
                            continue
                        visited[bid] = b
                        nxt.append(bid)
                frontier = nxt
    except Exception as e:
        _log.warning("Neo4j fetch_law_subgraph 실패: %s", e)
        return None

    nodes = [_article_node(p, is_seed=(nid in seed_set)) for nid, p in visited.items()]
    return {
        "seeds": list(seed_set),
        "nodes": nodes,
        "edges": list(edges.values()),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "truncated": truncated,
    }


def list_attachments(law_id: str) -> list[dict]:
    """법령 ID에 속한 모든 Attachment 메타 — 사이드 패널 선택용 등."""
    driver = _get_driver()
    if driver is None:
        return []
    try:
        with driver.session() as s:
            rows = s.run(
                """
                MATCH (l:Law {lawId: $law_id})-[:CONTAINS_ATTACHMENT]->(a:Attachment)
                RETURN a.id AS attachment_key,
                       a.title AS title,
                       a.annex_type AS annex_type,
                       a.attachment_subtype AS attachment_subtype
                ORDER BY a.id
                """,
                law_id=law_id,
            ).data()
        return [
            {
                "attachment_key": r["attachment_key"],
                "title": r["title"],
                "type": r["attachment_subtype"] or r["annex_type"],
            }
            for r in rows
        ]
    except Exception as e:
        _log.warning("Neo4j list_attachments 실패: %s", e)
        return []
