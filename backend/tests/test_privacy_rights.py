"""정보주체 권리 + 국외이전 동의 — 방침이 약속한 걸 코드가 실제로 하는가.

방침에 적고 구현하지 않으면 **허위 고지**가 된다. 이 테스트가 그 괴리를 막는다.

⚠️ 앱(TestClient)을 거치지 않고 **라우트 함수를 직접 호출**한다. 이유: `AuthMiddleware`
dev-bypass 가 공용 DB 에 사용자를 upsert 하고, persistence 가 `lru_cache` 싱글턴이라
TestClient 로 돌리면 `test_quota_admin` 등 다른 테스트를 깨뜨린다(실측). 라우트 함수는
`request.state.user_id` 만 필요하므로 가짜 Request 로 결정적으로 검증 가능하다.
(엔드포인트 레벨 동작은 e2e 로 확인 — CHANGELOG 참조.)
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.legal import LEGAL_VERSION
from src.persistence.events_repo import Event, SqliteEventsRepo
from src.persistence.users_repo import SqliteUsersRepo
from src.routes import privacy as R

UID = "u-test"


def _req(uid: str | None = UID):
    return SimpleNamespace(state=SimpleNamespace(user_id=uid),
                           json=lambda: asyncio.sleep(0, result={}))


@pytest.fixture
def repos(monkeypatch, tmp_path):
    db = str(tmp_path / "t.db")
    events, users = SqliteEventsRepo(db), SqliteUsersRepo(db)
    users.upsert(id=UID, email="a@b.com")
    monkeypatch.setattr(R, "get_events_repo", lambda: events)
    monkeypatch.setattr(R, "get_users_repo", lambda: users)
    monkeypatch.setattr(R, "_check_auth", lambda a: None)
    return SimpleNamespace(events=events, users=users)


def _body(d):
    async def _j():
        return d
    return _j


# ── 국외이전 동의 (법 제28조의8) ──────────────────────────────────
def test_consent_needed_initially(repos):
    d = json.loads(R.consent_status(_req()).body)
    assert d["current_version"] == LEGAL_VERSION
    assert d["needs_consent"] is True and d["agreed_version"] is None


def test_consent_recorded_and_audited(repos):
    req = _req(); req.json = _body({"version": LEGAL_VERSION,
                                    "scopes": ["terms", "transfer", "marketing"]})
    r = json.loads(asyncio.run(R.give_consent(req)).body)
    assert r["ok"] is True and set(r["scopes"]) == {"terms", "transfer", "marketing"}

    d = json.loads(R.consent_status(_req()).body)
    assert d["needs_consent"] is False and d["agreed_version"] == LEGAL_VERSION and d["agreed_at"]
    assert set(d["agreed_scopes"]) >= set(R.REQUIRED_SCOPES)
    # 감사 추적: 누가·언제·어느 버전·어느 항목
    evs = repos.events.list_for_user(UID, event_type=R.CONSENT_EVENT, limit=5)
    p = json.loads(evs[0].payload_json)
    assert len(evs) == 1 and p["version"] == LEGAL_VERSION and "transfer" in p["scopes"]


def test_missing_required_scope_rejected(repos):
    """국외이전(transfer)은 **별도 동의** — 빠지면 400."""
    from fastapi import HTTPException
    req = _req(); req.json = _body({"version": LEGAL_VERSION, "scopes": ["terms"]})
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.give_consent(req))
    assert e.value.status_code == 400 and "transfer" in str(e.value.detail)


def test_partial_consent_still_needs_consent(repos):
    """필수 항목 일부만 기록돼 있으면 재동의를 받아야 한다."""
    repos.events.emit(Event(id="", ts="", event_type=R.CONSENT_EVENT, user_id=UID,
                            payload_json=json.dumps({"version": LEGAL_VERSION,
                                                     "scopes": ["terms"]})))
    assert json.loads(R.consent_status(_req()).body)["needs_consent"] is True


def test_consent_version_mismatch_rejected(repos):
    from fastapi import HTTPException
    req = _req(); req.json = _body({"version": "1999-01-01"})
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.give_consent(req))
    assert e.value.status_code == 409


def test_stale_consent_requires_reconsent(repos):
    """LEGAL_VERSION 이 오르면 재동의를 받아야 한다."""
    repos.events.emit(Event(id="", ts="", event_type=R.CONSENT_EVENT, user_id=UID,
                            payload_json=json.dumps({"version": "2020-01-01"})))
    assert json.loads(R.consent_status(_req()).body)["needs_consent"] is True


# ── 열람 요구 (법 제35조) ─────────────────────────────────────────
def test_me_data_discloses_retention_and_transfer(repos):
    d = json.loads(R.my_data(_req()).body)
    assert d["user"]["email"] == "a@b.com"
    assert "retention" in d and "국외이전" in d
    assert any("Anthropic" in x for x in d["국외이전"])   # 국외이전 수령자 고지


def test_me_data_transfer_list_matches_privacy_policy(repos):
    """/me/data 의 국외이전 수령자는 방침 §5 표와 같아야 한다(LangSmith 는 9/10 제거 — 9/23 잔존 발견)."""
    import re
    from pathlib import Path
    d = json.loads(R.my_data(_req()).body)
    policy = Path("docs/legal/privacy.md").read_text(encoding="utf-8")
    for name in d["국외이전"]:
        assert name.split("(")[0] in policy, name
    assert not any("LangSmith" in x for x in d["국외이전"])
    assert re.search(r"30일", d["retention"]["심층 보고서"])


# ── 삭제 요구 (법 제36·37조) ──────────────────────────────────────
def test_erase_request_accepted_and_audited(repos, monkeypatch):
    monkeypatch.setattr("src.observability.alerts.send_ops_alert",
                        lambda *a, **k: True)
    req = _req(); req.json = _body({"reason": "테스트"})
    r = json.loads(asyncio.run(R.request_erasure(req)).body)
    assert r["status"] == "accepted"
    evs = repos.events.list_for_user(UID, event_type=R.ERASE_EVENT, limit=5)
    assert len(evs) == 1   # 접수 자체가 감사 추적으로 남는다


def test_unauthenticated_rejected(repos):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        R.my_data(_req(uid=None))
    assert e.value.status_code == 401


# ── 실제 파기 (erase_user.py 가 의존하는 repo 메서드) ──────────────
def test_events_delete_for_user_keeps_audit_trail(tmp_path):
    e = SqliteEventsRepo(str(tmp_path / "e.db"))
    e.emit(Event(id="", ts="", event_type=R.CONSENT_EVENT, user_id="u1"))
    e.emit(Event(id="", ts="", event_type="chat", user_id="u1"))
    e.emit(Event(id="", ts="", event_type="chat", user_id="other"))
    assert e.delete_for_user("u1", keep_types=(R.CONSENT_EVENT,)) == 1
    assert [x.event_type for x in e.list_for_user("u1", limit=9)] == [R.CONSENT_EVENT]
    assert len(e.list_for_user("other", limit=9)) == 1   # 남의 데이터는 무사


def test_users_delete(tmp_path):
    u = SqliteUsersRepo(str(tmp_path / "u.db"))
    u.upsert(id="u1", email="a@b.com")
    u.delete("u1")
    assert u.get("u1") is None



# ── 안내 메일 수신거부 (정보통신망법 §50④, 2026-09-10 → 09-14 재도입) ────
# 뉴스레터 푸터가 "설정에서 수신 여부를 바꿀 수 있다"고 안내하려면, 그 설정이
# 실제로 존재하고 발송 경로가 그걸 존중해야 한다 — 없으면 허위 고지.
def test_notice_email_opt_in_default_on_and_togglable(repos, monkeypatch):
    # privacy.py 는 함수 안에서 `from src.persistence import get_users_repo` 하므로
    # 모듈 속성(R.get_users_repo) 패치로는 안 잡힌다 — 원본을 갈아끼운다.
    monkeypatch.setattr("src.persistence.get_users_repo", lambda: repos.users)
    d = R.get_my_prefs(_req())
    assert d["notice_email_opt_in"] is True

    req = _req(); req.json = _body({"notice_email_opt_in": False})
    r = asyncio.run(R.patch_my_prefs(req))
    assert r["notice_email_opt_in"] is False
    assert R.get_my_prefs(_req())["notice_email_opt_in"] is False

    req = _req(); req.json = _body({"notice_email_opt_in": True})
    assert asyncio.run(R.patch_my_prefs(req))["notice_email_opt_in"] is True


def test_notice_email_opt_in_rejects_non_bool(repos, monkeypatch):
    monkeypatch.setattr("src.persistence.get_users_repo", lambda: repos.users)
    import fastapi
    req = _req(); req.json = _body({"notice_email_opt_in": "no"})
    with pytest.raises(fastapi.HTTPException) as e:
        asyncio.run(R.patch_my_prefs(req))
    assert e.value.status_code == 422


def test_notice_optout_filter_drops_only_optouts(repos, monkeypatch):
    """발송 경로가 거부자를 실제로 뺀다 — 설정만 있고 안 쓰면 무의미."""
    from src import notices

    repos.users.upsert(id="u2", email="opt@out.com")
    repos.users.set_notice_email_opt_in("u2", False)
    monkeypatch.setattr("src.persistence.get_users_repo", lambda: repos.users)

    out = notices.filter_notice_optout(["a@b.com", "opt@out.com", "ghost@x.com"])
    # 거부자만 빠지고, 가입 이력이 없는 주소(ghost)는 그대로 둔다
    assert out == ["a@b.com", "ghost@x.com"]
    # 운영 필수 연락(admins)·개별 지정은 거부를 적용하지 않는다
    assert notices.honors_notice_optout("beta_testers")
    assert not notices.honors_notice_optout("admins")
    assert not notices.honors_notice_optout(["x@y.com"])


# ── 서버측 동의 확인 (2026-09-23) ─────────────────────
def _agree(repos, scopes):
    repos.events.emit(Event(id="", ts="", event_type=R.CONSENT_EVENT, user_id=UID,
                            payload_json=json.dumps({"version": LEGAL_VERSION, "scopes": scopes})))


def _state_req(uid=UID, admin=False):
    return SimpleNamespace(state=SimpleNamespace(user_id=uid, is_admin=admin))


def test_require_consent_blocks_until_agreed(repos, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setenv("CONSENT_ENFORCE", "1")
    R._CONSENT_OK.clear()
    with pytest.raises(HTTPException) as e:
        R.require_consent(_state_req())
    assert e.value.status_code == 403 and "동의" in e.value.detail
    _agree(repos, ["terms", "transfer"])
    R.require_consent(_state_req())          # 통과
    R.require_consent(_state_req(admin=True, uid="other"))  # 관리자 예외
    monkeypatch.setenv("CONSENT_ENFORCE", "0")
    R.require_consent(_state_req(uid="nobody"))  # 우회 스위치
