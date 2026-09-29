"""기존 사용자 동의 자동 처리(2026-09-23 운영자 결정) — 서버측 동의 확인 도입 전 가입자.

동의 확인이 프런트 게이트뿐이던 시기에 가입해 `legal_consent` 기록이 없는 사용자를, 서버측
확인(`privacy.require_consent`)이 막지 않도록 현행 고지 버전으로 동의 처리한다. 운영자 판단:
클로즈 베타 초대 대상은 가입 화면에서 필수 동의를 거쳤다.

감사 추적에서 본인이 직접 체크한 동의와 구분되도록 payload 에 `source="existing_user_auto"` 를 남긴다.
탈퇴 계정은 건너뛴다. 기본 DRY_RUN, `--apply` 로 기록.

usage (운영 컨테이너 안):
  python scripts/backfill_consent.py
  python scripts/backfill_consent.py --apply
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SOURCE = "existing_user_auto"


def run(*, apply: bool) -> list[str]:
    from src.persistence import get_events_repo, get_users_repo
    from src.persistence.events_repo import Event
    from src.routes.privacy import CONSENT_EVENT, REQUIRED_SCOPES, _is_agreed, _latest_consent
    from src.legal import LEGAL_VERSION

    events = get_events_repo()
    targets = [u for u in get_users_repo().list_all(limit=100000)
               if not getattr(u, "deleted_at", None) and not _is_agreed(_latest_consent(u.id))]
    for u in targets:
        print(f"  {'기록' if apply else '[DRY]'} {u.id} {getattr(u, 'email', '')}")
        if apply:
            events.emit(Event(
                id="", ts="", event_type=CONSENT_EVENT, user_id=u.id,
                payload_json=json.dumps({"version": LEGAL_VERSION, "scopes": list(REQUIRED_SCOPES),
                                         "source": SOURCE}, ensure_ascii=False)))
    print(f"[backfill-consent] 대상 {len(targets)}명 · apply={apply}")
    return [u.id for u in targets]


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    run(apply="--apply" in sys.argv)
