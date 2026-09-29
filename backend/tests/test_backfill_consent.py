"""기존 사용자 동의 자동 처리(2026-09-23) — 기록 없는 활성 사용자만, 출처를 남겨서."""
from __future__ import annotations

import json


def test_backfill_consent_marks_only_missing_active_users():
    from scripts import backfill_consent as B
    from src.persistence import get_events_repo, get_users_repo
    from src.persistence.events_repo import Event
    from src.legal import LEGAL_VERSION

    users, events = get_users_repo(), get_events_repo()
    users.upsert(id="u-old", email="old@example.com")
    users.upsert(id="u-ok", email="ok@example.com")
    users.upsert(id="u-gone", email="gone@example.com")
    users.soft_delete("u-gone")
    events.emit(Event(id="", ts="", event_type="legal_consent", user_id="u-ok",
                      payload_json=json.dumps({"version": LEGAL_VERSION,
                                               "scopes": ["terms", "transfer"]})))

    assert "u-old" in B.run(apply=False)
    assert events.list_for_user("u-old", event_type="legal_consent") == []   # DRY 는 기록 안 함

    done = B.run(apply=True)
    assert "u-old" in done and "u-ok" not in done and "u-gone" not in done
    p = json.loads(events.list_for_user("u-old", event_type="legal_consent", limit=1)[0].payload_json)
    assert p["version"] == LEGAL_VERSION and p["source"] == "existing_user_auto"
    assert B.run(apply=False) == []   # 다시 돌려도 대상 없음(멱등)
