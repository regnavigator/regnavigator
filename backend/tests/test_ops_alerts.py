"""운영 장애 알림 — send_ops_alert dedup + /readyz 발화."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    from src.observability import alerts
    alerts.reset_dedup()
    monkeypatch.setenv("NEXTAUTH_SECRET", "x" * 32)
    yield
    alerts.reset_dedup()


class _FakeClient:
    posts: list = []

    def __init__(self, *a, **k):
        ...

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None):
        _FakeClient.posts.append(json)


def test_send_alert_sends_then_dedups(monkeypatch):
    from src.observability import alerts
    monkeypatch.setenv("OPS_ALERT_WEBHOOK_URL", "http://hook")
    _FakeClient.posts = []
    monkeypatch.setattr("httpx.Client", _FakeClient)
    assert alerts.send_ops_alert("의존성 다운", "x", dedup_key="k") is True   # 1차 전송
    assert alerts.send_ops_alert("의존성 다운", "x", dedup_key="k") is False  # dedup
    assert len(_FakeClient.posts) == 1
    assert "의존성 다운" in _FakeClient.posts[0]["text"]


def test_send_alert_no_webhook(monkeypatch):
    from src.observability import alerts
    monkeypatch.delenv("OPS_ALERT_WEBHOOK_URL", raising=False)
    assert alerts.send_ops_alert("x", dedup_key="nohook") is False  # 미설정 → 로그만


def _down():
    raise RuntimeError("conn refused")


def test_readyz_fires_alert_on_critical_down(monkeypatch):
    import src.routes.health as h
    monkeypatch.setattr(h, "_PROBES", [("embedding", _down, True)])
    calls = []
    monkeypatch.setattr("src.observability.alerts.send_ops_alert",
                        lambda *a, **k: calls.append((a, k)) or True)
    from fastapi.testclient import TestClient
    from src.api import app
    res = TestClient(app).get("/readyz")
    assert res.status_code == 503
    assert len(calls) == 1
    assert calls[0][1].get("dedup_key") == "dep_down:embedding"
