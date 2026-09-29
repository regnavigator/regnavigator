"""retrieval — 검색 클라이언트.

RAG 검색은 `search_api_client`(openlaw-etl /search API, thin-client). `pg/mongo/
neo4j`_client 는 `/article`·`/law-graph`·pinned grounding 전용. `cache` = TTLCache.
로컬 임베딩/Qdrant/리랭커/sparse 스택은 2026-07 thin-client 전환으로 삭제됨.

spec: ../../docs/guide/architecture.md
"""
