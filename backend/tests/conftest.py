"""pytest 공통 fixture / 환경 격리."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """각 테스트는 깨끗한 env + 깨끗한 DB 로 시작 — 실 키·실 DB가 새지 않게.

    DB 격리(2026-07-19): 실 `./medi_reports.db` 의 베타 화이트리스트 행이 테스트로
    새어 게이트가 활성화(403 24건)된 사고 — 테스트마다 tmp sqlite 로 강제.
    """
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "test_reports.db"))
    # 서버측 동의 확인은 기본 끔 — 전용 테스트(test_privacy_rights)만 켠다.
    monkeypatch.setenv("CONSENT_ENFORCE", "0")
    # NER 미설정은 이제 strict 게이트가 차단한다(2026-10-02). 테스트는 NER 없이
    # 도는 게 정상이므로 dev 와 같은 방식으로 **명시적으로** 허용한다.
    monkeypatch.setenv("PII_GATE_ALLOW_NO_NER", "1")
    for k in [
        # ⚠️ PG DSN 은 반드시 차단 — 어떤 경로로든 .env 가 프로세스에 실리면
        # (실측 2026-08-16: 테스트가 load_dotenv 최상단 스크립트를 import)
        # 픽스처 이벤트가 **운영 PG** 에 적재된다(law_001 가짜 rag_search).
        "REPORTS_PG_DSN",
        "CHECKPOINT_PG_DSN",
        "BETA_GATE",
        "BETA_WHITELIST_EMAILS",
        "TAVILY_API_KEY",
        "TAVILY_MAX_RESULTS",
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "QDRANT_READ_ONLY_API_KEY",
        "QDRANT_HOST",
        "QDRANT_PORT",
        "QDRANT_COLLECTION",
        "QDRANT_TOP_K",
        "EMBEDDING_BACKBONE",
        "EMBEDDING_MODEL",
    ]:
        monkeypatch.delenv(k, raising=False)
    _clear_retrieval_caches()
    _clear_persistence_caches()
    _reset_rate_limit_windows()
    _clear_ner_caches()
    # 서식 기입 온프레미스 브레이커는 모듈 전역 — 한 테스트의 '다운'이 다음으로 새지 않게.
    from src.doc_fill import reset_onprem_state
    reset_onprem_state()
    yield
    _clear_retrieval_caches()
    _reset_rate_limit_windows()
    _clear_ner_caches()


def _clear_ner_caches() -> None:
    """NER 결과 캐시(content-hash) + 서버 기능 탐지 캐시 리셋 — 같은 텍스트를
    쓰는 테스트끼리 결과가 새면 청킹·차단 경로 검증이 조용히 스킵된다."""
    from src.guardrail import ner_client

    ner_client.reset_result_cache()
    ner_client.reset_capability_cache()


def _reset_rate_limit_windows() -> None:
    """RateLimit sliding window 초기화 — app 싱글턴에 프로세스 수명으로 누적돼
    TestClient(전부 IP="testclient")가 분당 예산을 스위트 전체에서 공유하는
    순서 오염 방지 (테스트 추가 시 무관한 테스트가 429 로 깨지던 실측 사례)."""
    from src.middleware.rate_limit import reset_windows

    reset_windows()


def _clear_persistence_caches() -> None:
    """persistence repo 싱글톤(lru_cache) + 화이트리스트 TTL 캐시 리셋 —
    REPORTS_SQLITE_PATH 격리가 이미 생성된 repo 인스턴스에도 적용되도록."""
    import src.persistence as _p

    for name in dir(_p):
        if name.startswith("get_") and name.endswith("_repo"):
            fn = getattr(_p, name)
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()
    try:
        from src.persistence.whitelist_repo import get_whitelist_repo as _gw
        if hasattr(_gw, "cache_clear"):
            _gw.cache_clear()
    except Exception:
        pass
    # 기입값 암호화 키는 env 로 결정되고 lru_cache 됨 — 테스트별 env 격리 반영.
    try:
        from src.persistence import field_crypto as _fc
        _fc.reset_cache()
    except Exception:
        pass
    # threads_repo 만 lru_cache 가 아닌 모듈 전역 싱글턴 — 위 루프가 못 잡는다.
    try:
        from src.persistence.threads_repo import reset_threads_repo_cache
        reset_threads_repo_cache()
    except Exception:
        pass
    try:
        from src.middleware.auth import invalidate_whitelist_cache
        invalidate_whitelist_cache()
    except Exception:
        pass
    # app_settings 도 모듈 전역 싱글턴 — 주간 스냅샷(usage_weekly) 등이 앞 테스트 DB 로 새지 않게.
    try:
        from src.persistence.settings_repo import reset_settings_repo_cache
        reset_settings_repo_cache()
    except Exception:
        pass
    # 업데이트 내역(공지) 캐시도 모듈 전역 — 앞 테스트 노트가 주간 보고서 등에 새지 않게.
    try:
        from src.announcements import invalidate_cache as _inv_an
        _inv_an()
    except Exception:
        pass
    # 내부 계정 집합(TTL 캐시) — 저장소가 바뀌면 키로도 걸러지지만 id() 재사용 가능성 차단.
    try:
        from src.account_class import invalidate as _inv_ac
        _inv_ac()
    except Exception:
        pass


def _clear_retrieval_caches() -> None:
    """retrieval 싱글톤 캐시 리셋 — env 격리가 lazy 팩토리에도 적용되도록.

    검색은 openlaw-etl /search API 로 위임 — httpx 클라이언트 lru 와 검색 결과
    캐시를 테스트 간 비워 stale 인스턴스·결과가 새지 않게 한다.
    """
    from src.retrieval import search_api_client as _sc

    _sc._client.cache_clear()
    _sc._search_cache.clear()


@pytest.fixture(autouse=True)
def _reset_aux_policy():
    """보조 LLM 정책(contextvar)이 테스트 사이에 새지 않게(2026-10-03)."""
    try:
        from src import chat_loop as _cl
        _cl._AUX_POLICY.set(None)
    except Exception:  # noqa: BLE001 — 아직 import 못 하는 환경이면 무시
        pass
    yield
