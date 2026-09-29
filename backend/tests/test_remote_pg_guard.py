"""로컬(dev) → 원격 PG 연결 가드(2026-09-17).

로컬 `.env` 가 운영 PG 를 가리켜 '로컬 테스트'가 운영에 쓰고 운영의 단일 인스턴스 락을
두고 경쟁하던 사고. 설정 실수가 조용히 운영 쓰기가 되지 않게 연결 지점에서 막는다.
"""
import pytest

from src.persistence._pg import _guard_remote_pg_from_dev as guard

REMOTE = "postgresql://u:p@192.0.2.30:6001/medi"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("APP_GIT_SHA", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_PG", raising=False)


def test_dev_process_cannot_reach_remote_pg():
    with pytest.raises(RuntimeError, match="REPORTS_BACKEND=sqlite"):
        guard(REMOTE)


def test_error_message_never_leaks_credentials():
    with pytest.raises(RuntimeError) as ei:
        guard("postgresql://medi:s3cret@db.example.com:5432/medi")
    assert "s3cret" not in str(ei.value) and "db.example.com" in str(ei.value)


def test_deployed_image_and_explicit_override_pass(monkeypatch):
    monkeypatch.setenv("APP_GIT_SHA", "cba8271")
    guard(REMOTE)
    monkeypatch.delenv("APP_GIT_SHA")
    monkeypatch.setenv("ALLOW_REMOTE_PG", "1")
    guard(REMOTE)


@pytest.mark.parametrize("dsn", [
    "postgresql://postgres:test@localhost:5433/postgres",   # 통합 테스트(MEDI_TEST_PG_DSN)
    "postgresql://postgres:test@127.0.0.1/postgres",
    "postgresql://medi:pw@postgres:5432/medi",              # compose 서비스명
])
def test_local_pg_is_allowed(dsn):
    guard(dsn)


def test_single_instance_lock_refuses_remote_pg_from_dev(monkeypatch):
    """가장 위험한 경로 — 로컬이 운영의 어드바이저리 락을 잡으면 운영 부팅이 거부된다."""
    from src import single_instance

    monkeypatch.setenv("REPORTS_BACKEND", "postgres")
    monkeypatch.setenv("REPORTS_PG_DSN", REMOTE)
    monkeypatch.setenv("SINGLE_INSTANCE_LOCK", "strict")
    monkeypatch.setattr(single_instance, "_try_lock",
                        lambda dsn: pytest.fail("락 시도까지 가면 안 된다"))
    with pytest.raises(RuntimeError, match="원격 Postgres"):
        single_instance.acquire()
