"""보고 노트(관리자 전용) 관리 CLI — 기능 배포 후 개발 쪽이 올린다 (2026-09-21).

운영 컨테이너 안에서 실행(운영 app_settings 에 쓴다):
  gcloud compute ssh … --command "cd /opt/medi-back && sudo docker compose --env-file .env.docker \\
    exec -T -w /app -e PYTHONPATH=/app medi-back python scripts/report_note.py add \\
    --title '출처 종류를 색으로 구분해 보여줘요' --feature '검색·답변' \\
    --item '…' --item '…' --ref f1c5969"

  list [--since YYYY-MM-DD]      최근 노트
  add  --title T [--item I]… [--feature F] [--date D] [--exclude] [--ref C]…
  include|exclude ID             보고 레터 포함/해제
  delete ID

작성 기준: 사용자가 체감하는 기능 변화 1건 = 노트 1개, 사용자 언어, 내부 수정·버그 수정은 올리지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str]) -> int:
    from src import report_notes as rn

    p = argparse.ArgumentParser(prog="report_note")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--since")
    a = sub.add_parser("add")
    a.add_argument("--title", required=True)
    a.add_argument("--item", action="append", default=[])
    a.add_argument("--feature")
    a.add_argument("--date")
    a.add_argument("--exclude", action="store_true", help="보고 레터에서 뺀 상태로 추가")
    a.add_argument("--ref", action="append", default=[])
    for name in ("include", "exclude", "delete"):
        sub.add_parser(name).add_argument("id")
    args = p.parse_args(argv)

    by = "agent:report_note.py"
    if args.cmd == "list":
        for n in rn.list_notes(since=args.since):
            mark = "포함" if n.get("include", True) else "해제"
            print(f'{n["date"]} [{mark}] {n["id"]} [{n.get("feature") or "-"}] {n["title"]}')
        return 0
    if args.cmd == "add":
        n = rn.add(title=args.title, items=args.item, feature=args.feature, day=args.date,
                   include=not args.exclude, by=by, refs=args.ref)
        print(json.dumps(n, ensure_ascii=False))
        return 0
    if args.cmd in ("include", "exclude"):
        n = rn.update(args.id, include=(args.cmd == "include"), by=by)
        print(json.dumps(n, ensure_ascii=False) if n else "not found")
        return 0 if n else 1
    if args.cmd == "delete":
        ok = rn.delete(args.id, by=by)
        print("deleted" if ok else "not found")
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
