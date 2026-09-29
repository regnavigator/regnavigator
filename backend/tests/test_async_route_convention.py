"""async 규약 회귀 — 2026-08-04 감사 C-3.

사고: 워커가 1개로 고정된 구조에서(CLAUDE.md §7) `async def` 라우트가 동기
SQLite/PG repo·SMTP·urllib 을 직접 호출해 **이벤트 루프를 점유**했다. 조회 하나가
느려지면 진행 중인 SSE 스트림과 보고서 잡이 전부 멈춘다. 최악은 `/admin/notify`
로, 수신자 수만큼 순차 SMTP(각 최대 15초) → 100명 공지 = 서버 전체 수 분 무응답.

문제의 본질은 "한 코드베이스에 두 규약이 공존"이었다 — `chat_loop.py` 는 동기
호출을 43곳에서 `asyncio.to_thread` 로 감싸는데 라우트는 그냥 불렀다.

여기서 잠그는 규약:
  ① 라우트 핸들러가 `async def` 면 반드시 await 가 있어야 한다. 없으면 그냥
     `def` — FastAPI 가 스레드풀에서 돌려 루프를 비운다.
  ② 알려진 장시간 블로킹 호출(SMTP·webhook·정비 폴링)은 async 함수 안에서
     **맨몸으로 부르지 않는다**. `asyncio.to_thread` 로 넘길 것.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


ROUTES_DIR = pathlib.Path("src/routes")

# 이벤트 루프에서 직접 부르면 안 되는 동기 함수 (초 단위로 블로킹)
_BLOCKING = {
    "send_notice",            # 수신자 수 × SMTP(15s 타임아웃)
    "send_email",             # SMTP
    "send_ops_alert",         # webhook httpx (5s)
    "_upstream_maintenance",  # urllib 3+4s, 20초 주기 반복
    "resolve_recipients",     # 전체 회원 DB 조회
}


def _route_handlers(tree: ast.AST):
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if any("router" in ast.unparse(d) for d in n.decorator_list):
                yield n


def _py_files(*dirs: str):
    for d in dirs:
        yield from sorted(pathlib.Path(d).rglob("*.py"))


def test_async_route_handlers_actually_await():
    """await 없는 `async def` 핸들러는 루프를 점유만 한다 → `def` 여야 한다."""
    offenders = []
    for p in _py_files("src/routes"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for fn in _route_handlers(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            if not any(isinstance(x, (ast.Await, ast.AsyncFor, ast.AsyncWith))
                       for x in ast.walk(fn)):
                offenders.append(f"{p}:{fn.lineno}  {fn.name}")

    assert not offenders, (
        "await 없는 async 라우트 — `def` 로 선언해 스레드풀에 맡길 것"
        "(동기 DB 호출이 이벤트 루프를 막는다):\n  " + "\n  ".join(offenders)
    )


def _to_thread_wrapped(fn: ast.AST) -> set[int]:
    """`asyncio.to_thread(...)` 인자로 넘어간 노드들의 id 집합."""
    wrapped: set[int] = set()
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        src = ast.unparse(n.func)
        if src.endswith("to_thread"):
            for a in list(n.args) + [k.value for k in n.keywords]:
                for sub in ast.walk(a):
                    wrapped.add(id(sub))
    return wrapped


@pytest.mark.parametrize("target", ["src/routes", "src/report_runner.py"])
def test_blocking_calls_are_offloaded_in_async_code(target):
    """SMTP·webhook·정비 폴링을 async 함수에서 맨몸으로 부르지 않는다."""
    paths = (_py_files(target) if pathlib.Path(target).is_dir()
             else [pathlib.Path(target)])
    offenders = []
    for p in paths:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            wrapped = _to_thread_wrapped(fn)
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call) or id(n) in wrapped:
                    continue
                name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                if name in _BLOCKING:
                    offenders.append(f"{p}:{n.lineno}  {name}() in async {fn.name}")

    assert not offenders, (
        "이벤트 루프에서 동기 블로킹 호출 — `await asyncio.to_thread(...)` 로 넘길 것:\n  "
        + "\n  ".join(offenders)
    )
