"""과거 공지 발송 이력을 `beta_whitelist.invited_at` 에 채운다 (2026-08-05).

왜 필요한가 — `invited_at` 은 초대 버튼(2026-08-05)이 생긴 뒤의 발송만 안다.
그런데 베타 오픈 공지("[MediReg AI] 베타 서비스를 시작합니다")는 그 전에
`to=beta_testers`, 즉 **화이트리스트 전체**에 나갔다(2026-08-02, requested 16 /
sent 16). 그대로 두면 화면이 16명 전원을 '미발송'으로 보여주고, 관리자가
성실하게 버튼을 누를수록 **전원에게 같은 메일이 두 번** 간다.

무엇을 하는가 — 발송 완료(`status=sent`)된 공지를 훑어 수신자를 복원하고,
`invited_at` 이 비어 있는 항목에만 그 공지의 발송 시각을 찍는다.

  · `to: "beta_testers"` → 그 공지 **발송 시각 이전에 등록된** 화이트리스트 항목
    (수신자 목록은 발송 시점에 해석되므로, 그 뒤 추가된 사람은 못 받았다)
  · `to: [명시 목록]`    → 그 주소들
  · `to: "all"/"admins"/"whitelisted"` → 건너뜀. 서비스 안내 공지가 아니라
    수신자 재구성이 부정확하고, 초대 이력으로 볼 근거도 약하다.

멱등 — 이미 `invited_at` 이 있는 항목은 건드리지 않는다. 기본은 dry-run.

사용:
    python scripts/backfill_invite_history.py             # 미리보기
    python scripts/backfill_invite_history.py --apply     # 실제 기록
    python scripts/backfill_invite_history.py --subject 베타   # 제목 필터
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mask(e: str) -> str:
    name, _, dom = e.partition("@")
    return f"{name[:5]}…@{dom}" if dom else e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제로 기록(미지정 시 미리보기만)")
    ap.add_argument("--subject", default="",
                    help="이 문자열이 제목에 있는 공지만 대상")
    args = ap.parse_args()

    from src.persistence.settings_repo import get_settings_repo
    from src.persistence.whitelist_repo import get_whitelist_repo

    raw = get_settings_repo().get("admin.scheduled_notices")
    notices = json.loads(raw) if raw else []
    repo = get_whitelist_repo()
    rows = {r["entry"]: r for r in repo.list()}

    plan: dict[str, tuple[str, str]] = {}   # entry → (invited_at, by)
    for n in notices:
        if n.get("status") != "sent":
            continue
        subject = n.get("subject") or ""
        if args.subject and args.subject not in subject:
            continue
        sent_at = n.get("sent_at")
        if not sent_at:
            continue
        by = n.get("created_by") or "backfill"
        to = n.get("to")

        if isinstance(to, list):
            targets = [str(e).strip().lower() for e in to if str(e).strip()]
        elif to == "beta_testers":
            # 발송 시점에 이미 등록돼 있던 항목만 받았다.
            targets = [e for e, r in rows.items()
                       if (r.get("created_at") or "") < sent_at]
        else:
            print(f"  건너뜀 — to={to!r}: {subject}")
            continue

        for e in targets:
            r = rows.get(e)
            if not r or r.get("invited_at"):
                continue          # 화이트리스트 밖이거나 이미 이력 있음
            if "@" not in e or e.startswith("@"):
                continue          # 도메인 항목은 수신자가 없다
            # 여러 공지가 겹치면 **가장 최근** 발송으로 남긴다.
            prev = plan.get(e)
            if prev is None or prev[0] < sent_at:
                plan[e] = (sent_at, by)
        print(f"  대상 {len(targets):>3}건 ← {subject} ({sent_at})")

    print(f"\n화이트리스트 {len(rows)}건 · 이력 채울 항목 {len(plan)}건")
    for e, (at, by) in sorted(plan.items()):
        print(f"  {_mask(e):<28} invited_at={at} by={by}")

    if not plan:
        print("\n채울 것이 없습니다.")
        return 0
    if not args.apply:
        print("\n[dry-run] 실제로 기록하려면 --apply")
        return 0

    done = 0
    for e, (at, by) in plan.items():
        # 실제 발송 시각을 그대로 찍는다 — 화면이 발송일을 보여주므로 오늘
        # 날짜로 찍으면 "8/5에 보냈다"는 거짓이 남는다.
        if repo.mark_invited(e, invited_by=f"{by} (과거 공지 이력 이관)", at=at):
            done += 1
    print(f"\n{done}건 기록 완료. 화면에서 '발송완료'로 보입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
