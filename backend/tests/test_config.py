"""중앙 설정 — 타입 접근자·prod 검증·레지스트리."""
from __future__ import annotations

from src import config


def test_env_typed_accessors(monkeypatch):
    monkeypatch.setenv("QDRANT_TOP_K", "12")
    assert config.env_int("QDRANT_TOP_K") == 12
    monkeypatch.delenv("QDRANT_TOP_K", raising=False)
    assert config.env_int("QDRANT_TOP_K") == 12       # 레지스트리 기본값
    assert config.env_int("NOPE_KEY", 99) == 99       # 미등록 → 호출 기본값


def test_env_bool(monkeypatch):
    for v in ("1", "true", "YES", "on"):
        monkeypatch.setenv("USE_QDRANT_HYBRID", v)
        assert config.env_bool("USE_QDRANT_HYBRID") is True
    monkeypatch.setenv("USE_QDRANT_HYBRID", "0")
    assert config.env_bool("USE_QDRANT_HYBRID") is False


def test_missing_prod_required(monkeypatch):
    # prod_required 전체를 명시적으로 설정 — ambient env(.env)에 의존하지 않게(hermetic).
    for k in [s.key for s in config.ENV_REGISTRY if s.prod_required]:
        monkeypatch.setenv(k, "x")
    assert config.missing_prod_required() == []       # 전부 설정
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    assert "NEXTAUTH_SECRET" in config.missing_prod_required()


def test_registry_unique_keys():
    keys = [s.key for s in config.ENV_REGISTRY]
    assert len(keys) == len(set(keys))                # 중복 없음


def test_dump_masks_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-super-secret")
    rows = {r["key"]: r for r in config.dump()}
    assert rows["ANTHROPIC_API_KEY"]["value"] == "***set***"   # 마스킹
    assert rows["ANTHROPIC_API_KEY"]["set"] is True


def test_settings_accessors(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert config.settings.llm_model == "anthropic:claude-sonnet-4-6"
