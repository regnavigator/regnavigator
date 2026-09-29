"""초대 메일 내용 확인·수정(2026-08-28) — app_settings 오버라이드.

관리자가 발송 전에 내용을 보고 고칠 수 있어야 한다는 요구. 수정본은 DB 에
저장돼 재기동을 견디고, 발송 직전에 읽으므로 저장 즉시 다음 발송에 반영된다.
"""
from __future__ import annotations

from src import notices


def test_default_template_when_no_override():
    notices.reset_invite_template()
    tpl = notices.get_invite_template()
    assert tpl["is_custom"] is False
    assert tpl["subject"] == notices.INVITE_SUBJECT
    assert notices.SIGNUP_URL in tpl["body"]


def test_set_and_reset_roundtrip():
    notices.set_invite_template("제목 수정본", "본문 수정본", updated_by="admin@x")
    tpl = notices.get_invite_template()
    assert tpl["is_custom"] is True
    assert tpl["subject"] == "제목 수정본"
    assert tpl["body"] == "본문 수정본"
    assert tpl["updated_by"] == "admin@x"
    notices.reset_invite_template()
    assert notices.get_invite_template()["is_custom"] is False


def test_broken_stored_value_falls_back_to_default():
    """저장값이 깨져도 발송이 죽지 않는다 — 기본 문구 폴백."""
    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(notices._INVITE_TPL_KEY, "{not json")
    tpl = notices.get_invite_template()
    assert tpl["is_custom"] is False
    assert tpl["subject"] == notices.INVITE_SUBJECT
    notices.reset_invite_template()


def test_empty_fields_ignored():
    """subject/body 가 비면 오버라이드 무효 — 빈 메일 발송 방지."""
    import json

    from src.persistence.settings_repo import get_settings_repo

    get_settings_repo().set(notices._INVITE_TPL_KEY,
                            json.dumps({"subject": " ", "body": ""}))
    assert notices.get_invite_template()["is_custom"] is False
    notices.reset_invite_template()
