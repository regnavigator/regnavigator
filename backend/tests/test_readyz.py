"""운영 readiness — /readyz 의존성 probe (liveness /healthz 와 분리)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # 인증 켜져 있어도 /readyz·/healthz 는 공개(PUBLIC_PATH_PREFIXES)여야 함.
    monkeypatch.setenv("NEXTAUTH_SECRET", "test-secret-32-bytes-min-padding-xx")
    yield


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _ok():
    return True, None


def _down():
    raise RuntimeError("conn refused")


def test_readyz_all_ok(monkeypatch):
    import src.routes.health as h
    monkeypatch.setattr(h, "_PROBES", [
        ("postgres", _ok, True),
        ("search_api", _ok, True),
        ("pii_ner", _ok, False),
        ("neo4j", _ok, False),
    ])
    res = _client().get("/readyz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["checks"]["postgres"]["status"] == "ok"


def test_readyz_critical_down_503(monkeypatch):
    import src.routes.health as h
    monkeypatch.setattr(h, "_PROBES", [
        ("postgres", _ok, True),
        ("search_api", _down, True),   # critical 다운
    ])
    res = _client().get("/readyz")
    assert res.status_code == 503
    assert res.json()["status"] == "degraded"
    dep = res.json()["checks"]["search_api"]
    # 보안 하드닝(2026-07-23): /readyz 는 공개 — 예외 문자열(DSN·IP 유출 위험)
    # 대신 예외 유형명만 노출. 상세는 서버 로그.
    assert dep["status"] == "down" and dep["detail"] == "RuntimeError"
    assert "conn refused" not in str(dep)


def test_readyz_optional_down_still_200(monkeypatch):
    import src.routes.health as h
    monkeypatch.setattr(h, "_PROBES", [
        ("postgres", _ok, True),
        ("neo4j", _down, False),      # optional 다운 → 전체는 ok
    ])
    res = _client().get("/readyz")
    assert res.status_code == 200
    assert res.json()["checks"]["neo4j"]["status"] == "down"


def test_healthz_stays_shallow():
    # liveness 는 의존성 안 보고 항상 200(프로세스 생존만).
    res = _client().get("/healthz")
    assert res.status_code == 200 and res.json() == {"status": "ok"}


# ── DGX 가드레일·writer probe (SPOF 가시화) ──────────────────────
def test_probe_list_covers_dgx_services():
    """DGX 가드레일·writer 가 probe 대상이어야 다운을 인지한다(SPOF 수용의 전제)."""
    from src.routes.health import _PROBES
    names = {n for n, _, _ in _PROBES}
    assert {"postgres", "search_api", "neo4j", "pii_ner", "intent",
            "report_writer"} <= names
    crit = {n for n, _, c in _PROBES if c}
    assert crit == {"postgres", "search_api"}   # 가드레일은 non-critical(폴백)


def test_http_health_unset_url_is_not_down():
    """미설정 = '비활성'(폴백 동작) — 다운으로 보고하지 않는다."""
    from src.routes.health import _http_health
    ok, detail = _http_health(None, None, "PII NER")
    assert ok is True and "미설정" in detail


def test_guardrail_down_warns_but_stays_200(monkeypatch):
    """NER 다운 → 200(대화 계속) + warning 알림(PII 마스킹 저하 = 컴플라이언스)."""
    import src.routes.health as h
    monkeypatch.setattr(h, "_PROBES", [
        ("postgres", _ok, True),
        ("search_api", _ok, True),
        ("pii_ner", _down, False),
    ])
    sent = []
    import src.observability.alerts as alerts
    monkeypatch.setattr(alerts, "send_ops_alert",
                        lambda t, b, **k: sent.append((t, k.get("severity"))))
    res = _client().get("/readyz")
    assert res.status_code == 200                     # 대화는 계속
    assert res.json()["checks"]["pii_ner"]["status"] == "down"
    assert any("pii_ner" in t and sev == "warning" for t, sev in sent)


def test_readyz_not_rate_limited_under_polling(monkeypatch):
    # LB 가 자주 폴링해도 429 안 나야(rate limit 제외). 빠른 probe 로 모킹.
    import src.routes.health as h
    monkeypatch.setattr(h, "_PROBES", [("postgres", _ok, True)])
    client = _client()
    codes = {client.get("/readyz").status_code for _ in range(80)}
    assert 429 not in codes   # rate limit 제외 확인
