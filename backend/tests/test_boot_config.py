"""부팅 설정 검증 — lifespan 이 prod 필수 env 누락 시 경고/차단."""
from __future__ import annotations

import pytest


def test_boot_ok_when_required_set(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "s" * 32)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    from fastapi.testclient import TestClient
    from src.api import app
    with TestClient(app) as c:        # lifespan(startup) 실행
        assert c.get("/healthz").status_code == 200


def test_warns_but_boots_when_missing(monkeypatch):
    monkeypatch.delenv("STRICT_CONFIG", raising=False)
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from src.api import app
    with TestClient(app) as c:        # 경고만 — 부팅은 됨
        assert c.get("/healthz").status_code == 200


def test_strict_config_blocks_boot(monkeypatch):
    monkeypatch.setenv("STRICT_CONFIG", "1")
    monkeypatch.delenv("NEXTAUTH_SECRET", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from src.api import app
    with pytest.raises(Exception):    # lifespan 이 RuntimeError → 부팅 차단
        with TestClient(app) as c:
            c.get("/healthz")
