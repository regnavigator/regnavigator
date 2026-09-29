"""compose 가 **실제로 렌더하는 env** 검사 — CI(`docker-build` 잡)에서 실행.

`tests/test_compose_env_mapping.py` 는 YAML 텍스트를 정규식으로 본다. 그걸로는
**기본값 함정**을 못 잡는다:

    LANGSMITH_TRACING: ${LANGSMITH_TRACING:-true}

`.env.docker` 에서 그 줄을 지우면 꺼질 것 같지만, 값이 없으면 `:-true` 가 먹어
**켜진다**. 2026-09-10 에 트레이싱이 꺼진 줄 알았는데 운영 컨테이너에서
`LANGSMITH_TRACING=true` 로 살아 있던 게 이 함정이었다(대화 원문이 국외로 나가는
경로라 개인정보 이슈였다).

그래서 여기서는 `docker compose config` 로 **변수를 실제로 치환한 결과**를 보고,
빈 .env(=키가 하나도 없는 최악의 경우)에서도 위험한 기본값이 켜지지 않는지 본다.

사용: python scripts/check_compose_render.py   (docker compose 필요)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

#: 빈 env 로 렌더했을 때 **이 값이어야** 하는 키. 기본값이 조용히 위험한 쪽으로
#: 켜지면 안 되는 것들.
MUST_EQUAL = {
    # 대화 원문 국외 전송 경로 — 기본값으로라도 절대 켜지면 안 된다(2026-09-10).
    "LANGSMITH_TRACING": "false",
}

#: 렌더 결과에 **존재하면 안 되는** 키(제거한 통합의 잔재가 되살아나는지).
MUST_ABSENT = ("LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT")

#: 단일 인스턴스 불변식(CLAUDE.md §7) — 스케일이 올라가면 동시성 제어가 무너진다.
MUST_SCALE_1 = True


def render() -> dict:
    """빈 .env 로 compose 를 렌더 → medi-back 서비스 정의.

    compose 에 `env_file: [.env.docker]` 가 있어 그 파일이 없으면 렌더 자체가
    실패한다(dev·CI 에는 없다). 없을 때만 빈 파일을 만들고 반드시 지운다 —
    **이미 있으면 절대 건드리지 않는다**(운영 VM 의 실제 시크릿 파일).
    """
    created = False
    if not os.path.exists(".env.docker"):
        open(".env.docker", "w").close()
        created = True
    try:
        with tempfile.TemporaryDirectory() as td:
            empty = os.path.join(td, "empty.env")
            open(empty, "w").close()
            p = subprocess.run(
                ["docker", "compose", "--env-file", empty, "-f", "docker-compose.yml",
                 "config", "--format", "json"],
                capture_output=True, text=True, timeout=180,
            )
    finally:
        if created:
            os.remove(".env.docker")
    if p.returncode != 0:
        raise SystemExit(f"docker compose config 실패:\n{(p.stderr or p.stdout)[-2000:]}")
    return json.loads(p.stdout)


def main() -> None:
    cfg = render()
    svc = (cfg.get("services") or {}).get("medi-back")
    if not svc:
        raise SystemExit("medi-back 서비스를 찾지 못함")
    env = {k: ("" if v is None else str(v)) for k, v in (svc.get("environment") or {}).items()}

    fails: list[str] = []

    for key, want in MUST_EQUAL.items():
        got = env.get(key)
        if got is None:
            fails.append(f"{key} 미매핑 — 명시적으로 {want!r} 를 주입해야 한다")
        elif got.strip().lower() != want:
            fails.append(f"{key} = {got!r} (기대 {want!r}) — 빈 env 에서 위험한 기본값이 켜짐")
        else:
            print(f"  OK   {key} = {got}")

    for key in MUST_ABSENT:
        if key in env:
            fails.append(f"{key} 매핑이 되살아남 — 제거된 통합이다")
        else:
            print(f"  OK   {key} 없음")

    if MUST_SCALE_1:
        replicas = (((svc.get("deploy") or {}).get("replicas")) or 1)
        if int(replicas) != 1:
            fails.append(f"medi-back replicas={replicas} — 단일 인스턴스 불변식 위반")
        else:
            print("  OK   replicas = 1")
        cmd = " ".join(svc.get("command") or []) if isinstance(svc.get("command"), list) else str(svc.get("command") or "")
        if "--workers" in cmd and "--workers 1" not in cmd:
            fails.append(f"uvicorn workers 가 1 이 아니다: {cmd}")

    if fails:
        print("\ncompose 렌더 검사 실패:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("\ncompose 렌더 검사 통과")


if __name__ == "__main__":
    main()
