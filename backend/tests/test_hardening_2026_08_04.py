"""감사 High 대응 회귀 — 2026-08-04.

- H-2  X-Forwarded-For 위조로 IP rate limit 우회 + 버킷 무한 증가
- H-4  관리자 권한이 다음 요청에 되돌아감(env 가 DB 를 덮어씀)
- H-11 보고서 영속 실패가 두 겹으로 은폐돼 원인이 사라짐
- H-14 보안 킬스위치가 레지스트리·`/admin/config` 밖
- H-17 init_schema 가 리포 생성 부작용으로 최대 9회 재실행
"""
from __future__ import annotations

import pytest


# ── H-2 XFF 신뢰 ────────────────────────────────────────────────────────────
class _Req:
    def __init__(self, headers: dict, host: str = "10.0.0.9"):
        self.headers = headers
        self.client = type("C", (), {"host": host})()


def test_xff_ignored_by_default(monkeypatch):
    """프록시가 없으면 XFF 는 그냥 클라이언트가 쓴 값 — 신뢰하지 않는다."""
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    from src.middleware.rate_limit import _client_ip

    ip = _client_ip(_Req({"x-forwarded-for": "1.2.3.4, 5.6.7.8"}))
    assert ip == "10.0.0.9"


def test_xff_uses_rightmost_trusted_hop(monkeypatch):
    """nginx 1홉이면 오른쪽 끝(프록시가 덧붙인 값)만 신뢰. 왼쪽은 위조 가능."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    from src.middleware.rate_limit import _client_ip

    # 공격자가 앞에 아무거나 채워 넣어도 마지막 값이 실제 접속원이다.
    ip = _client_ip(_Req({"x-forwarded-for": "9.9.9.9, 8.8.8.8, 203.0.113.7"}))
    assert ip == "203.0.113.7"


def test_spoofed_xff_cannot_mint_unlimited_buckets(monkeypatch):
    """헤더를 매번 바꿔도 버킷이 무한히 늘지 않는다(메모리 고갈 차단)."""
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    from src.middleware.rate_limit import _SlidingWindow

    w = _SlidingWindow(limit=10_000, window_seconds=60)
    monkeypatch.setattr(type(w), "MAX_BUCKETS", 100, raising=False)
    for i in range(500):
        w.record(f"ip:{i}")
    assert len(w._buckets) <= 100


# ── H-4 관리자 권한 진실원 ──────────────────────────────────────────────────
def test_db_granted_admin_survives_next_request(monkeypatch, tmp_path):
    """PATCH 로 준 권한이 그 사용자의 다음 요청에 취소되면 안 된다."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "u.db"))
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    from src.persistence import get_users_repo

    get_users_repo.cache_clear()
    repo = get_users_repo()
    repo.upsert(id="u-1", email="staff@x.com")
    repo.set_admin("u-1", True)

    # 다음 요청의 upsert 재현 — env 목록 밖이라 예전엔 False 로 덮어썼다.
    repo.upsert(id="u-1", email="staff@x.com", is_admin=None)
    assert repo.get("u-1").is_admin is True

    get_users_repo.cache_clear()


def test_env_listed_email_is_still_promoted(monkeypatch, tmp_path):
    """env 는 부트스트랩 역할을 계속한다(운영자 잠금 방지)."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "u2.db"))
    from src.persistence import get_users_repo

    get_users_repo.cache_clear()
    repo = get_users_repo()
    repo.upsert(id="u-2", email="boss@x.com", is_admin=True)
    assert repo.get("u-2").is_admin is True
    get_users_repo.cache_clear()


# ── H-11 영속 실패를 드러낸다 ───────────────────────────────────────────────
def test_persist_failure_raises_typed_error(monkeypatch):
    """조용히 None 을 돌려주면 27B 비용을 태우고도 원인이 사라진다."""
    import src.tools.reports as tr

    def _boom():
        raise RuntimeError("GCS 403")

    monkeypatch.setattr(tr, "get_reports_repo", lambda: _boom())
    with pytest.raises(tr.ReportPersistError) as e:
        tr._persist_report(path="/final_report.md", body="# 본문",
                           state={}, ctx={"thread_id": "t-1"})
    # 유형명이 실려야 운영이 모델 서버가 아니라 저장소를 본다.
    assert "RuntimeError" in str(e.value)


# ── H-14 킬스위치 가시성 ────────────────────────────────────────────────────
@pytest.mark.parametrize("key", [
    "RATE_LIMIT_DISABLE", "SECURITY_HEADERS_DISABLE", "MEDICAL_FILTER_DISABLE",
    "CHAT_GROUNDING_GATE_DISABLE", "LLM_RATE_LIMIT_DISABLE",
    "DISABLE_TOKEN_LOGGER", "TRUSTED_PROXY_HOPS", "CSP",
    "STRICT_TRANSPORT_SECURITY", "API_CORS_ORIGINS",
])
def test_security_knobs_are_registered(key):
    """레지스트리에 없으면 /admin/config 에 안 떠서, 꺼져 있어도 아무도 모른다."""
    from src.config import ENV_REGISTRY

    assert key in {s.key for s in ENV_REGISTRY}


def test_no_env_read_outside_registry():
    """코드가 읽는 env 는 전부 레지스트리에 있어야 한다(H-14 재발 방지)."""
    import ast
    import pathlib
    import re

    from src.config import ENV_REGISTRY

    known = {s.key for s in ENV_REGISTRY}
    found: set[str] = set()
    for p in pathlib.Path("src").rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and ast.unparse(n.func) in (
                    "os.getenv", "os.environ.get"):
                if n.args and isinstance(n.args[0], ast.Constant):
                    found.add(n.args[0].value)
            if (isinstance(n, ast.Subscript)
                    and ast.unparse(n.value) == "os.environ"
                    and isinstance(n.slice, ast.Constant)):
                found.add(n.slice.value)

    missing = sorted(
        k for k in found - known
        if isinstance(k, str) and re.fullmatch(r"[A-Z0-9_]+", k)
    )
    assert not missing, (
        "코드가 읽는데 ENV_REGISTRY 에 없다 — /admin/config 에 안 보인다:\n  "
        + "\n  ".join(missing))


# ── H-17 스키마 DDL 반복 실행 ───────────────────────────────────────────────
def test_init_schema_runs_once_per_process(monkeypatch):
    """리포 9개가 각자 호출해도 DDL 은 한 번만 — 부팅 지연·운영 DB 난타 방지."""
    from src.persistence import _pg

    calls = {"n": 0}

    class _Cur:
        def execute(self, *a, **kw):
            calls["n"] += 1

    from contextlib import contextmanager

    @contextmanager
    def _fake_cursor(dsn):
        yield _Cur()

    monkeypatch.setattr(_pg, "pg_cursor", _fake_cursor)
    _pg.reset_schema_cache()

    for _ in range(9):
        _pg.init_schema("postgresql://x/y")
    assert calls["n"] == 1

    _pg.init_schema("postgresql://x/y", force=True)   # 명시 요청은 실행
    assert calls["n"] == 2

    _pg.reset_schema_cache()
