"""배포 이미지 스모크 — **컨테이너 안에서** 실행한다(CI `docker-build` 잡).

## 왜 필요한가

같은 유형의 사고가 세 번 났다. 전부 "로컬 통과·운영 실패"였고, 공통점은
**dev 환경에는 우연히 있던 것이 이미지에는 없었다**는 것:

| 날짜 | 사고 | 왜 기존 검사를 통과했나 |
|---|---|---|
| 2026-08-02 | `EMAIL_FROM` 미매핑 → 보고서 메일 전건 550 | compose 는 키별 매핑인데 `.env.docker` 만 봤다 |
| 2026-09-09 | `six` 누락 → 서식 뷰어 전건 503 | `six` 를 import 하는 건 **pyhwp**(서드파티)라 `check_imports.py`(src/ 만 스캔)에 안 잡힘. dev venv 는 python-dateutil 이 끌고 와 가려짐 |
| 2026-09-10 | `LANGSMITH_TRACING` 이 꺼진 줄 알았으나 켜져 있었음 | compose 기본값이 `${…:-true}` — `.env.docker` 에서 줄을 지워도 켜진다 |

기존 CI 의 `docker-build` 잡은 **빌드만 하고 이미지를 실행하지 않았다.** 그래서
"빌드는 되는데 임포트가 깨지는" 위 2번을 원천적으로 못 잡았다. 이 스크립트가
그 구멍을 메운다 — 이미지를 실제로 **실행**해서 확인한다.

## 검사 항목

1. `src/` 전 모듈 import — 이미지 안에서. 지연 import 로 숨은 의존성까지 끌어낸다.
2. **서브프로세스 의존** 실행 가능 여부 — 코드가 `sys.executable -c` 또는 PATH
   바이너리로 shell-out 하는 것들. 여기서 깨진 게 `six` 사고였다.
3. FastAPI 앱 구성 — 라우트가 실제로 붙는지(임포트만으로는 미검출).

DB·LLM·검색 등 외부 의존은 **닿지 않는다**(전부 지연 연결). 네트워크 없이 돈다.
"""
from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys
import traceback

FAILS: list[str] = []


def check(label: str):
    def deco(fn):
        try:
            fn()
            print(f"  OK   {label}")
        except Exception as e:  # noqa: BLE001
            FAILS.append(f"{label}: {type(e).__name__}: {e}")
            print(f"  FAIL {label}: {type(e).__name__}: {e}")
            traceback.print_exc()
        return fn
    return deco


# ── 1) src/ 전 모듈 import ────────────────────────────────────────────
# 임포트 시점에 외부 연결을 여는 모듈은 없다(설계상 전부 지연). 있으면 여기서
# 드러나는 게 맞다 — 그것도 배포 위험이다.
print("[1] src/ 전 모듈 import")
_import_fail: list[str] = []
import src  # noqa: E402

for mod in pkgutil.walk_packages(src.__path__, prefix="src."):
    name = mod.name
    try:
        importlib.import_module(name)
    except Exception as e:  # noqa: BLE001
        _import_fail.append(f"{name}: {type(e).__name__}: {e}")

if _import_fail:
    for f in _import_fail:
        print(f"  FAIL {f}")
    FAILS.extend(_import_fail)
else:
    print(f"  OK   전 모듈 import ({len(list(pkgutil.walk_packages(src.__path__, prefix='src.')))}개)")


# ── 2) 서브프로세스 의존 ──────────────────────────────────────────────
# 코드가 별도 프로세스로 부르는 것들. 부모 프로세스가 import 하지 않으므로
# 위 1) 로는 절대 안 잡힌다 — `six` 사고가 정확히 이 구멍이었다.
print("\n[2] 서브프로세스 의존")


@check("hwp5html 임포트 가능(별표·서식 뷰어)")
def _hwp5html():
    # src/annex_view.py 가 실제로 쓰는 것과 **같은 형태**로 부른다.
    p = subprocess.run(
        [sys.executable, "-c", "from hwp5.hwp5html import main; print('ok')"],
        capture_output=True, text=True, timeout=60,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[-500:])


@check("hwp5html 변환 경로 — 비HWP 입력을 형식 오류로 거절")
def _hwp5_convert():
    # 도구 체인이 살아 있으면 AnnexViewError(형식), 죽어 있으면 다른 예외가 난다.
    from src.annex_view import AnnexViewError, convert_hwp_bytes
    try:
        convert_hwp_bytes(b"PK\x03\x04" + b"x" * 300)
    except AnnexViewError:
        return  # 기대 동작
    raise RuntimeError("형식 오류가 발생하지 않음 — 판정 로직 이상")


@check("kordoc 바이너리(서식 기입) — 없으면 경고만")
def _kordoc():
    from src.form_fill import kordoc_cmd
    if not kordoc_cmd():
        # prod 이미지엔 있어야 하지만, 빌드 스테이지 구성에 따라 없을 수 있어
        # 실패로 올리지 않는다. 대신 눈에 띄게 남긴다.
        print("       (주의) kordoc 미탑재 — 서식 기입 기능 확인 필요")


# ── 3) 앱 구성 ────────────────────────────────────────────────────────
print("\n[3] FastAPI 앱 구성")


@check("app 생성 + 핵심 라우트 등록")
def _app():
    from src.api import app
    # `app.routes` 는 이 FastAPI 버전에서 include_router 결과를 래퍼 객체로 담아
    # `.path` 가 없다 — OpenAPI 스펙이 실제 등록 경로의 진실원이다.
    paths = set(app.openapi().get("paths") or {})
    missing = [p for p in ("/healthz", "/readyz", "/load", "/chat", "/reports")
               if p not in paths]
    if missing:
        raise RuntimeError(f"라우트 누락: {missing} (등록 {len(paths)}개)")
    print(f"       등록 경로 {len(paths)}개")


# ── 결과 ──────────────────────────────────────────────────────────────
print()
if FAILS:
    print(f"이미지 스모크 실패 {len(FAILS)}건:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("이미지 스모크 통과")
