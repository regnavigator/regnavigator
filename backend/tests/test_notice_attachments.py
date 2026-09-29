"""공지 메일 첨부(2026-08-19) — 파싱·상한·전달 경로.

배경: `send_email` 은 처음부터 첨부를 지원했는데 공지 경로(`/admin/notify` →
`send_notice`)가 인자를 넘기지 않아 **홍보물 PDF 를 붙일 수 없었다**.
첨부는 수신자 수만큼 반복 전송되므로 합계 상한이 필요하다.
"""
from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from src.routes.admin import _parse_notice_attachments


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_none_or_empty_returns_empty():
    assert _parse_notice_attachments(None) == []
    assert _parse_notice_attachments([]) == []


def test_parses_filename_bytes_mime():
    got = _parse_notice_attachments(
        [{"filename": "poster.pdf", "content_b64": _b64(b"%PDF-1.4 x"),
          "mime": "application/pdf"}])
    assert got == [("poster.pdf", b"%PDF-1.4 x", "application/pdf")]


def test_mime_defaults_to_octet_stream():
    got = _parse_notice_attachments(
        [{"filename": "a.bin", "content_b64": _b64(b"\x00\x01")}])
    assert got[0][2] == "application/octet-stream"


def test_missing_fields_rejected():
    for bad in ([{"filename": "a.pdf"}], [{"content_b64": _b64(b"x")}], [{}]):
        with pytest.raises(HTTPException) as e:
            _parse_notice_attachments(bad)
        assert e.value.status_code == 422


def test_bad_base64_rejected():
    with pytest.raises(HTTPException) as e:
        _parse_notice_attachments(
            [{"filename": "a.pdf", "content_b64": "not-base64!!"}])
    assert e.value.status_code == 422


def test_non_list_rejected():
    with pytest.raises(HTTPException) as e:
        _parse_notice_attachments({"filename": "a.pdf"})
    assert e.value.status_code == 422


def test_total_size_cap_enforced():
    """상한 초과는 발송 전에 거절 — '보냈는데 일부만 도착'을 만들지 않는다."""
    big = _b64(b"x" * (5 * 1024 * 1024))
    with pytest.raises(HTTPException) as e:
        _parse_notice_attachments([
            {"filename": "a.pdf", "content_b64": big},
            {"filename": "b.pdf", "content_b64": big},
        ])
    assert e.value.status_code == 422
    assert "MB" in e.value.detail


def test_send_notice_forwards_attachments(monkeypatch):
    """send_notice 가 첨부를 send_email 로 그대로 넘기는지 — 종전 누락 지점."""
    from src import notices

    seen: dict = {}

    def _fake_send_email(**kw):
        seen.update(kw)
        return True

    monkeypatch.setattr(
        "src.observability.notifications.send_email", _fake_send_email)
    monkeypatch.setattr(
        "src.observability.notifications.is_configured", lambda: True)

    att = [("poster.pdf", b"%PDF", "application/pdf")]
    res = notices.send_notice(subject="s", body_text="b",
                              emails=["a@example.com"], attachments=att)
    assert res["sent"] == 1
    assert seen["attachments"] == att


def test_send_notice_without_attachments_passes_none(monkeypatch):
    from src import notices

    seen: dict = {}
    monkeypatch.setattr(
        "src.observability.notifications.send_email",
        lambda **kw: (seen.update(kw), True)[1])
    monkeypatch.setattr(
        "src.observability.notifications.is_configured", lambda: True)

    notices.send_notice(subject="s", body_text="b", emails=["a@example.com"])
    assert seen["attachments"] is None
