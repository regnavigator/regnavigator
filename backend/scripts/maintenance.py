"""점검(유지보수) 모드 on/off CLI — 매일 4시 데이터 갱신 크론용.

관리자 화면 없이 서버 옆(같은 호스트)에서 점검 모드를 켜고 끈다. app_settings
DB 를 직접 갱신하며, 실행 중인 서버는 짧은 TTL(≤5s) 후 반영한다. 켜지면
비관리자 요청이 503, 관리자는 통과.

사용:
  python scripts/maintenance.py on  ["안내 문구"]      # 수동 점검 시작
  python scripts/maintenance.py off                    # 수동 점검 해제
  python scripts/maintenance.py status                 # 현재 상태
  python scripts/maintenance.py schedule 04:00 04:20 ["안내"]  # 매일 반복 예약 ON
  python scripts/maintenance.py schedule off           # 매일 반복 예약 OFF

매일 4시 갱신 — 두 가지 중 택1:
  ① 예약(권장, 크론 불필요): 한 번만
       python scripts/maintenance.py schedule 04:00 04:20 "데이터 갱신 중"
  ② 잡 래핑(실제 소요만 정확히 차단):
       python scripts/maintenance.py on "데이터 갱신 중"
       <데이터 갱신 실행>
       python scripts/maintenance.py off
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    from dotenv import load_dotenv
    load_dotenv()

    cmd = (argv[0].lower() if argv else "status")

    from src.maintenance import get_state, set_schedule, set_state

    if cmd in ("on", "enable", "start"):
        message = argv[1] if len(argv) > 1 else None
        st = set_state(True, message=message, updated_by="cli")
        print(f"[maintenance] 수동 ON — 비관리자 차단. message={st['message']!r}")
        return 0
    if cmd in ("off", "disable", "stop"):
        set_state(False, updated_by="cli")
        print("[maintenance] 수동 OFF.")
        return 0
    if cmd in ("schedule", "sched"):
        sub = (argv[1].lower() if len(argv) > 1 else "")
        if sub in ("off", "disable", "none"):
            set_schedule(enabled=False, start=None, end=None, updated_by="cli")
            print("[maintenance] 예약 OFF.")
            return 0
        if len(argv) < 3:
            print("사용: schedule <시작 HH:MM> <종료 HH:MM> [\"안내\"]  또는  schedule off",
                  file=sys.stderr)
            return 2
        start, end = argv[1], argv[2]
        message = argv[3] if len(argv) > 3 else None
        try:
            st = set_schedule(enabled=True, start=start, end=end,
                              message=message, updated_by="cli")
        except ValueError as e:
            print(f"오류: {e}", file=sys.stderr)
            return 2
        s = st["schedule"]
        print(f"[maintenance] 예약 ON — 매일 {s['start']}~{s['end']} ({s['tz']}) 자동 점검.")
        return 0
    if cmd in ("status", "state", ""):
        st = get_state()
        flag = "ON(점검중)" if st.get("active") else "OFF(정상)"
        src = st.get("source") or "-"
        print(f"[maintenance] {flag}  source={src}")
        print(f"  manual  : {st.get('manual')}")
        sc = st.get("schedule")
        if sc:
            en = "ON" if sc.get("enabled") else "OFF"
            print(f"  예약    : {en} 매일 {sc.get('start')}~{sc.get('end')} ({sc.get('tz')})")
        else:
            print("  예약    : 없음")
        if st.get("active"):
            print(f"  message : {st.get('message')}")
        return 0

    print(f"알 수 없는 명령: {cmd!r} — on|off|status|schedule", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
