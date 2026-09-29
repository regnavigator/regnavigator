"""프로세스 종료 시 외부 커넥션 정리 — 2026-08-04 감사 H-19.

지금까지 lifespan 의 finally 는 백그라운드 태스크만 취소하고 **커넥션은 하나도
닫지 않았다**. SIGTERM(=재배포)마다 psycopg 풀 2개·Neo4j 드라이버·pymongo·
httpx 클라이언트 3개가 정리되지 않은 채 프로세스가 사라져, 서버 쪽에 좀비 세션이
남는다. 배포가 잦을수록 PG `max_connections` 를 압박한다.

전부 **best-effort** 다 — 종료 경로에서 예외가 나도 다른 정리를 막지 않는다.
다만 삼키지 않고 debug 로 남긴다(어느 것이 안 닫혔는지 추적 가능해야 한다).
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def _safe(label: str, fn) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 — 종료 경로, 하나 실패가 나머지를 막으면 안 됨
        _log.debug("[shutdown] %s 정리 실패(%s)", label, type(e).__name__)


def close_all() -> None:
    """열려 있는 외부 커넥션·클라이언트를 모두 닫는다. 재호출 안전."""
    # 앱 DB(운영 Postgres — users·events·reports·chat thread 상태)
    def _app_pg():
        from src.persistence import _pg
        _pg.close_pool()

    # openlaw PG/Neo4j/Mongo — 읽기 전용이지만 커넥션은 똑같이 남는다
    def _openlaw_pg():
        from src.retrieval import pg_client
        pg_client.close_pool()

    def _neo4j():
        from src.retrieval import neo4j_client
        neo4j_client.close_driver()

    def _mongo():
        from src.retrieval import mongo_client
        mongo_client.close_client()

    # httpx 클라이언트 — 전부 @lru_cache(maxsize=1) 싱글턴이라 캐시에서 꺼내 닫고
    # 캐시를 비운다(테스트에서 재사용해도 안전하게).
    def _httpx(module_name: str, attr: str):
        import importlib

        mod = importlib.import_module(module_name)
        factory = getattr(mod, attr)
        try:
            client = factory()
        finally:
            if hasattr(factory, "cache_clear"):
                factory.cache_clear()
        if client is not None:
            client.close()

    _safe("app postgres pool", _app_pg)
    _safe("openlaw postgres pool", _openlaw_pg)
    _safe("neo4j driver", _neo4j)
    _safe("mongo client", _mongo)
    _safe("search api httpx", lambda: _httpx("src.retrieval.search_api_client", "_client"))
    _safe("ner httpx", lambda: _httpx("src.guardrail.ner_client", "_client"))
    _safe("intent httpx", lambda: _httpx("src.guardrail.intent_client", "_client"))
    _log.info("[shutdown] 외부 커넥션 정리 완료")
