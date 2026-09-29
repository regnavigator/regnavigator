"""단일 인스턴스 불변식의 **런타임 강제** — 2026-08-04 감사 C-4.

## 왜 필요한가

이 서비스의 동시성 제어는 전부 **프로세스 로컬**이다(CLAUDE.md §7). 감사에서
센 것만 17곳이고, 두 번째 프로세스가 뜨는 순간 동시에 무너진다:

| 상태 | 위치 | 2프로세스 시 |
|---|---|---|
| 턴 락 | `chat_loop.py` | 같은 thread 동시 요청이 분산 → 히스토리 interleave·`seq` 충돌·`tool_use↔tool_result` 짝 파손 → 턴 500 |
| LLM RPS 캡 | `llm_limits.py` | 실효 RPS = N배 → Anthropic 429 폭풍 |
| 검색 백프레셔 | `retrieval/search_api_client.py` | 단일 GPU 리랭커 thrash |
| writer 세마포어 | `report_pipeline.py` | 27B vLLM 동시 2잡 → OOM |
| 화이트리스트 캐시 | `middleware/auth.py` | admin 이 바꿔도 다른 워커는 TTL 까지 구 정책 |
| 예약 공지 큐 | `notices.py` | 같은 공지 **중복 발송**(롤백 불가) |

그런데 강제 지점은 `Dockerfile` 의 `--workers 1` 과 문서뿐이었다. compose
`command:` 오버라이드·`--scale medi-back=2`·`WEB_CONCURRENCY` 어느 쪽으로도
뚫리고, 뚫린 뒤에도 **아무 신호가 없다**. 조용한 데이터 손상이 최악이다.

## 어떻게

Postgres **세션 어드바이저리 락**을 부팅 때 잡고 프로세스 수명 동안 들고 있는다.
못 잡으면 = 다른 인스턴스가 이미 살아 있다는 뜻.

- 락은 전용 커넥션에 건다. 풀 커넥션은 반납·재사용·폐기되므로 세션 락을 못 얹는다.
- **유예 재시도**(`SINGLE_INSTANCE_WAIT_S`, 기본 20초). 배포는 compose 가 옛
  컨테이너를 내리고 새로 올리므로 보통 겹치지 않지만, 종료가 늦어질 때 새
  컨테이너가 곧바로 죽지 않도록 잠깐 기다린다.
- 접속 자체가 안 되면(=PG 다운) **통과**시킨다. 인프라 장애를 부팅 차단으로
  키우지 않는다 — 여기서 막고 싶은 건 "동시 실행"이지 "PG 장애"가 아니다.
  이 경우 `/readyz` 가 이미 degraded 로 알린다.

모드(`SINGLE_INSTANCE_LOCK`): `strict`(기본, 못 잡으면 부팅 차단) | `warn`
(경고만 — 마이그레이션 구간용) | `off`. SQLite(dev)는 락 대상이 아니라 자동 skip.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

_log = logging.getLogger(__name__)

# 락 키 — 이 서비스 전용 상수(다른 앱이 같은 DB 를 써도 충돌하지 않게).
# "medi-back:single-instance" 의 blake2b 상위 63비트. 값 자체에 의미는 없고
# **변하지 않는 것**이 중요하다(바뀌면 옛/새 인스턴스가 서로 다른 락을 잡는다).
_LOCK_KEY = 6_022_140_761_249_331_057

_conn: Any = None            # 락을 들고 있는 전용 커넥션
_state: str = "unchecked"    # unchecked | held | skipped | unavailable | conflict


def state() -> str:
    """현재 인스턴스의 락 상태 — `/readyz` 노출용."""
    return _state


def _mode() -> str:
    return (os.getenv("SINGLE_INSTANCE_LOCK") or "strict").strip().lower()


def _wait_s() -> float:
    try:
        return float((os.getenv("SINGLE_INSTANCE_WAIT_S") or "").strip() or "20")
    except ValueError:
        return 20.0


def assert_worker_count() -> None:
    """멀티 워커 지시를 **부팅 전에** 잡는다.

    락만으로도 2번째 워커는 걸리지만, uvicorn 이 죽은 워커를 계속 되살려
    crash-loop 로 보인다. 원인을 바로 알 수 있게 여기서 먼저 끊는다.
    """
    for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
        raw = (os.getenv(key) or "").strip()
        if not raw:
            continue
        try:
            n = int(raw)
        except ValueError:
            continue
        if n > 1:
            raise RuntimeError(
                f"{key}={n} — 이 서비스는 워커 1개 전제다(CLAUDE.md §7). "
                "턴 락·LLM RPS 캡·검색 백프레셔·보고서 큐가 전부 프로세스 로컬이라 "
                "워커를 늘리면 대화 히스토리 손상·429 폭풍·중복 공지가 발생한다. "
                f"수평 확장이 필요하면 그 상태들을 먼저 공유 저장소로 옮길 것. "
                f"({key} 를 1 로 두거나 지워라)"
            )


def acquire() -> str:
    """부팅 시 1회 호출. 상태 문자열 반환. strict 모드에서 충돌이면 RuntimeError."""
    global _conn, _state

    mode = _mode()
    if mode == "off":
        _state = "skipped"
        _log.info("[single-instance] SINGLE_INSTANCE_LOCK=off — 강제 안 함")
        return _state

    backend = (os.getenv("REPORTS_BACKEND") or "sqlite").strip().lower()
    dsn = (os.getenv("REPORTS_PG_DSN") or "").strip()
    if backend != "postgres" or not dsn:
        # dev(SQLite)는 단일 프로세스가 기본 — 락을 걸 공유 지점도 없다.
        _state = "skipped"
        _log.info("[single-instance] backend=%s — 락 skip(dev 단일 프로세스 전제)", backend)
        return _state

    # 로컬(dev)이 운영 PG 의 락을 두고 운영과 경쟁하지 않게 — 배포 재시작 순간 로컬이
    # 먼저 잡으면 운영 부팅이 거부된다(2026-09-17). 가드가 막으면 부팅을 멈춘다.
    from src.persistence._pg import _guard_remote_pg_from_dev

    _guard_remote_pg_from_dev(dsn)

    deadline = time.monotonic() + _wait_s()
    attempt = 0
    while True:
        attempt += 1
        got, err = _try_lock(dsn)
        if got:
            _state = "held"
            _log.info("[single-instance] 락 확보 — 이 프로세스가 유일한 인스턴스")
            return _state
        if err is not None:
            # PG 에 닿지 못함 — 인프라 장애를 부팅 차단으로 키우지 않는다.
            _state = "unavailable"
            _log.warning(
                "[single-instance] 락 확인 불가(%s) — 통과시킨다. "
                "PG 가 살아나면 재기동 시 다시 검사된다.", err)
            return _state
        if time.monotonic() >= deadline:
            break
        if attempt == 1:
            _log.warning(
                "[single-instance] 다른 인스턴스가 락 보유 — 최대 %.0f초 대기"
                "(배포 시 옛 컨테이너 종료 대기)", _wait_s())
        time.sleep(1.0)

    _state = "conflict"
    msg = (
        "다른 medi-back 인스턴스가 이미 실행 중이다(Postgres 어드바이저리 락 점유). "
        "이 서비스는 워커·인스턴스 1개 전제다(CLAUDE.md §7) — 둘 이상이면 턴 락·"
        "LLM RPS 캡·검색 백프레셔·보고서 큐가 전부 무력화돼 대화 히스토리 손상과 "
        "중복 공지가 발생한다. 옛 컨테이너를 내리고 다시 띄울 것"
        "(의도적 다중 실행이면 SINGLE_INSTANCE_LOCK=warn)."
    )
    if mode == "warn":
        _log.critical("[single-instance] %s", msg)
        return _state
    raise RuntimeError(msg)


def _try_lock(dsn: str) -> tuple[bool, Optional[str]]:
    """(획득여부, 오류사유). 오류사유가 있으면 '판정 불가'."""
    global _conn
    try:
        import psycopg

        conn = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    except Exception as e:  # noqa: BLE001 — 접속 실패는 판정 불가(충돌 아님)
        return False, type(e).__name__
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_LOCK_KEY,))
            row = cur.fetchone()
            got = bool(row and row[0])
    except Exception as e:  # noqa: BLE001
        _close(conn)
        return False, type(e).__name__
    if not got:
        _close(conn)          # 락을 못 잡았으면 커넥션을 붙들고 있을 이유가 없다
        return False, None
    _conn = conn              # 세션 락 = 이 커넥션이 살아 있는 동안만 유효
    return True, None


def release() -> None:
    """종료 시 락 해제 — 다음 인스턴스가 즉시 뜰 수 있게(배포 대기 단축)."""
    global _conn, _state
    conn, _conn = _conn, None
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    except Exception:  # noqa: BLE001 — 종료 경로, 커넥션을 닫으면 어차피 풀린다
        pass
    _close(conn)
    _state = "released"
    _log.info("[single-instance] 락 해제")


def _close(conn: Any) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def reset_for_tests() -> None:
    """테스트 격리 — 모듈 전역 상태 초기화."""
    global _conn, _state
    _close(_conn) if _conn is not None else None
    _conn = None
    _state = "unchecked"
