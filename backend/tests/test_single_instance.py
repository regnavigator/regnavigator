"""단일 인스턴스 강제 회귀 — 2026-08-04 감사 C-4.

사고 배경: 동시성 제어(턴 락·LLM RPS 캡·검색 백프레셔·보고서 큐·화이트리스트
캐시·예약 공지)가 전부 프로세스 로컬인데, 강제 지점이 Dockerfile CMD 와 문서뿐이라
`--scale`·`WEB_CONCURRENCY` 로 뚫렸다. 뚫려도 **아무 신호가 없는 것**이 최악이었다.

여기서 잠그는 것:
  ① WEB_CONCURRENCY>1 같은 멀티워커 지시는 부팅 전에 끊는다(원인 즉시 파악).
  ② PG 락을 못 잡으면(=다른 인스턴스 생존) strict 는 부팅 차단, warn 은 경고.
  ③ PG 에 닿지 못하는 건 '충돌'이 아니다 — 인프라 장애를 부팅 차단으로 키우지 않는다.
  ④ dev(SQLite)는 검사 대상이 아니다.
"""
from __future__ import annotations

import pytest

from src import single_instance as si


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("SINGLE_INSTANCE_LOCK", raising=False)
    monkeypatch.delenv("SINGLE_INSTANCE_WAIT_S", raising=False)
    for k in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
        monkeypatch.delenv(k, raising=False)
    # 이 파일은 **배포된 운영 프로세스**의 락 동작을 검증한다 — 배포 이미지 표식을 세운다
    # (없으면 dev→원격 PG 가드가 락 시도 전에 막는다, tests/test_remote_pg_guard.py).
    monkeypatch.setenv("APP_GIT_SHA", "test-image")
    si.reset_for_tests()
    yield
    si.reset_for_tests()


# ── ① 멀티워커 지시 차단 ────────────────────────────────────────────────────
@pytest.mark.parametrize("key", ["WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"])
def test_multi_worker_env_refuses_boot(monkeypatch, key):
    monkeypatch.setenv(key, "4")
    with pytest.raises(RuntimeError) as e:
        si.assert_worker_count()
    assert key in str(e.value)


@pytest.mark.parametrize("val", ["1", "", "notanumber"])
def test_single_or_unset_worker_env_is_fine(monkeypatch, val):
    monkeypatch.setenv("WEB_CONCURRENCY", val)
    si.assert_worker_count()  # 예외 없어야


# ── ④ dev(SQLite)는 skip ────────────────────────────────────────────────────
def test_sqlite_backend_skips_lock(monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    assert si.acquire() == "skipped"
    assert si.state() == "skipped"


def test_off_mode_skips_even_on_postgres(monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "postgres")
    monkeypatch.setenv("REPORTS_PG_DSN", "postgresql://x/y")
    monkeypatch.setenv("SINGLE_INSTANCE_LOCK", "off")
    assert si.acquire() == "skipped"


# ── ②③ 락 판정 ─────────────────────────────────────────────────────────────
def _pg(monkeypatch, result):
    """_try_lock 을 대체 — result: (획득여부, 오류사유)."""
    monkeypatch.setenv("REPORTS_BACKEND", "postgres")
    monkeypatch.setenv("REPORTS_PG_DSN", "postgresql://x/y")
    monkeypatch.setattr(si, "_try_lock", lambda dsn: result)


def test_lock_acquired_marks_held(monkeypatch):
    _pg(monkeypatch, (True, None))
    assert si.acquire() == "held"


def test_conflict_blocks_boot_in_strict_mode(monkeypatch):
    """다른 인스턴스가 살아 있으면 뜨지 않는다 — 조용한 데이터 손상보다 낫다."""
    _pg(monkeypatch, (False, None))
    monkeypatch.setenv("SINGLE_INSTANCE_WAIT_S", "0")
    with pytest.raises(RuntimeError) as e:
        si.acquire()
    assert "이미 실행 중" in str(e.value)
    assert si.state() == "conflict"


def test_conflict_only_warns_in_warn_mode(monkeypatch, caplog):
    import logging

    _pg(monkeypatch, (False, None))
    monkeypatch.setenv("SINGLE_INSTANCE_WAIT_S", "0")
    monkeypatch.setenv("SINGLE_INSTANCE_LOCK", "warn")
    with caplog.at_level(logging.CRITICAL, logger="src.single_instance"):
        assert si.acquire() == "conflict"
    assert any("이미 실행 중" in r.getMessage() for r in caplog.records)


def test_pg_unreachable_is_not_treated_as_conflict(monkeypatch):
    """PG 다운은 '동시 실행'이 아니다 — 인프라 장애를 부팅 차단으로 키우지 않는다."""
    _pg(monkeypatch, (False, "OperationalError"))
    assert si.acquire() == "unavailable"  # 예외 없이 통과


def test_waits_for_previous_instance_then_succeeds(monkeypatch):
    """배포 시 옛 컨테이너 종료를 기다린다 — 곧바로 죽으면 배포가 깨진다."""
    calls = {"n": 0}

    def _flaky(dsn):
        calls["n"] += 1
        return (calls["n"] >= 3, None)  # 3번째에 확보

    monkeypatch.setenv("REPORTS_BACKEND", "postgres")
    monkeypatch.setenv("REPORTS_PG_DSN", "postgresql://x/y")
    monkeypatch.setenv("SINGLE_INSTANCE_WAIT_S", "10")
    monkeypatch.setattr(si, "_try_lock", _flaky)
    monkeypatch.setattr(si.time, "sleep", lambda s: None)  # 대기 시간 스킵

    assert si.acquire() == "held"
    assert calls["n"] == 3


# ── /readyz 노출 ────────────────────────────────────────────────────────────
def test_readyz_exposes_lock_state(monkeypatch):
    """다중 실행(conflict)은 운영이 바로 봐야 하는 상태."""
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    si.acquire()

    from fastapi.testclient import TestClient
    from src.api import app

    res = TestClient(app).get("/readyz")
    assert res.status_code in (200, 503)
    assert res.json()["single_instance"] == "skipped"
