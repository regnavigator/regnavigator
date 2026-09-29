"""파일 업로드 v1 회귀 — src/file_extract + POST /files/extract + /chat attachments.

픽스처는 전부 인메모리 생성(pdf 는 오프셋 계산해 손조립) — 바이너리 커밋 없음.
"""
from __future__ import annotations

import io
import time
import zipfile

import jwt as pyjwt
import pytest

SECRET = "test-secret-32-bytes-min-padding-for-hs256"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_BACKEND", "local")
    monkeypatch.setenv("BLOB_LOCAL_DIR", str(tmp_path / "blobs"))
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "medi.db"))
    monkeypatch.setenv("NEXTAUTH_SECRET", SECRET)
    monkeypatch.delenv("AUTH_DEV_BYPASS_USER", raising=False)
    monkeypatch.delenv("FILE_MAX_UPLOAD_MB", raising=False)
    monkeypatch.delenv("FILE_MAX_EXTRACT_CHARS", raising=False)
    from src import persistence as P
    for f in (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo):
        f.cache_clear()
    yield
    for f in (P.get_blob_store, P.get_reports_repo, P.get_users_repo,
              P.get_events_repo, P.get_feedback_repo):
        f.cache_clear()


def _token(*, sub="u-1", email="alice@example.com"):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "email": email, "email_verified": True,
         "iat": now, "exp": now + 3600},
        SECRET, algorithm="HS256",
    )


def _client():
    from fastapi.testclient import TestClient
    from src.api import app
    return TestClient(app)


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


# ---------------------------------------------------------------------------
# 픽스처 빌더
# ---------------------------------------------------------------------------
def _mini_pdf(text: str = "Hello PDF") -> bytes:
    """xref 오프셋까지 계산한 최소 유효 PDF 1페이지."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
         b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF".encode()
    )
    return out.getvalue()


def _mini_hwpx(paragraphs: list[str]) -> bytes:
    """HWPX 최소 구조 — Contents/section0.xml 의 <hp:t>."""
    ns = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    body = "".join(
        f'<hp:p><hp:run><hp:t>{p}</hp:t></hp:run></hp:p>' for p in paragraphs
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><hml xmlns:hp="{ns}">{body}</hml>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Contents/section0.xml", xml)
    return buf.getvalue()


def _mini_docx(paragraphs: list[str]) -> bytes:
    from docx import Document
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 추출 단위
# ---------------------------------------------------------------------------
def test_extract_txt_and_cp949():
    from src.file_extract import extract_text
    r = extract_text("a.txt", "의료기기 허가 절차\n\n\n\n2단계".encode("utf-8"))
    assert r.kind == "txt" and "허가 절차" in r.text
    assert "\n\n\n" not in r.text  # 빈 줄 정리
    r2 = extract_text("b.txt", "한글 인코딩".encode("cp949"))
    assert "한글 인코딩" in r2.text


def test_extract_pdf():
    from src.file_extract import extract_text
    r = extract_text("doc.pdf", _mini_pdf("Medical Device 510k"))
    assert r.kind == "pdf" and "Medical Device 510k" in r.text


def test_extract_hwpx_including_hwp_extension_zip():
    from src.file_extract import extract_text
    data = _mini_hwpx(["제25조 광고 심의", "위반 시 벌칙"])
    r = extract_text("공문.hwpx", data)
    assert r.kind == "hwpx" and "제25조 광고 심의" in r.text and "벌칙" in r.text
    # 확장자만 .hwp 인 zip(실제 hwpx) — 매직으로 구제
    r2 = extract_text("공문.hwp", data)
    assert r2.kind == "hwpx"


def test_extract_docx():
    from src.file_extract import extract_text
    r = extract_text("기술문서.docx", _mini_docx(["GMP 심사 대응", "보완 요청 사항"]))
    assert r.kind == "docx" and "GMP 심사 대응" in r.text


def test_extract_rejects_legacy_hwp_and_unknown():
    from src.file_extract import UnsupportedFileType, extract_text
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
    with pytest.raises(UnsupportedFileType, match="HWPX"):
        extract_text("old.hwp", ole)
    with pytest.raises(UnsupportedFileType, match="지원하지 않는 형식"):
        extract_text("img.png", b"\x89PNG....")


def test_extract_empty_pdf_rejected():
    from src.file_extract import EmptyExtract, extract_text
    with pytest.raises(EmptyExtract, match="스캔"):
        extract_text("scan.pdf", _mini_pdf(" "))


def test_extract_truncates_at_cap(monkeypatch):
    monkeypatch.setenv("FILE_MAX_EXTRACT_CHARS", "1000")
    from src.file_extract import extract_text
    r = extract_text("big.txt", ("가" * 5000).encode("utf-8"))
    assert r.truncated is True and len(r.text) == 1000


# ---------------------------------------------------------------------------
# POST /files/extract 라우트
# ---------------------------------------------------------------------------
def test_files_extract_route_ok():
    client = _client()
    res = client.post(
        "/files/extract", headers=_auth(),
        files={"file": ("메모.txt", b"add-on vs upgrade", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "메모.txt" and body["kind"] == "txt"
    assert body["truncated"] is False and "add-on" in body["text"]


def test_files_extract_route_unsupported_415():
    client = _client()
    res = client.post(
        "/files/extract", headers=_auth(),
        files={"file": ("x.png", b"\x89PNG", "image/png")},
    )
    assert res.status_code == 415
    assert "지원하지 않는" in res.json()["detail"]


def test_files_extract_route_too_large_413(monkeypatch):
    monkeypatch.setenv("FILE_MAX_UPLOAD_MB", "0.001")  # ~1KB
    client = _client()
    res = client.post(
        "/files/extract", headers=_auth(),
        files={"file": ("big.txt", b"a" * 5000, "text/plain")},
    )
    assert res.status_code == 413


def test_files_extract_requires_auth():
    client = _client()
    res = client.post(
        "/files/extract",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# /chat attachments 검증·합성
# ---------------------------------------------------------------------------
def test_chat_attachment_caps(monkeypatch):
    monkeypatch.setenv("CHAT_MAX_ATTACHMENTS", "2")
    monkeypatch.setenv("CHAT_MAX_TOTAL_INPUT_CHARS", "5000")
    client = _client()
    # 개수 초과
    res = client.post("/chat", headers=_auth(), json={
        "message": "검토해줘",
        "attachments": [{"name": f"f{i}.txt", "text": "x"} for i in range(3)],
    })
    assert res.status_code == 422 and "2개" in res.json()["detail"]
    # 합산 길이 초과
    res = client.post("/chat", headers=_auth(), json={
        "message": "검토해줘",
        "attachments": [{"name": "big.txt", "text": "가" * 6000}],
    })
    assert res.status_code == 422 and "합친 길이" in res.json()["detail"]


def test_chat_compose_message_format():
    from src.routes.chat import ChatAttachment, _compose_message
    out = _compose_message(
        "이 문서 검토해줘",
        [ChatAttachment(name="공문.hwpx", text="제25조 내용")],
    )
    assert out.startswith("이 문서 검토해줘")
    assert '<attachment name="공문.hwpx">' in out
    assert "제25조 내용" in out and out.rstrip().endswith("</attachment>")
    # 첨부 없음 — 원문 그대로
    assert _compose_message("질문", None) == "질문"


def test_chat_per_attachment_cap_follows_extract_cap(monkeypatch):
    """파일당 방어 상한이 추출 상한(FILE_MAX_EXTRACT_CHARS)을 따른다.

    2026-09-14 상한 상향(30,000→120,000) 때 종전 `_max_input_chars()*2`(64,000)
    가 그대로면 /files/extract 가 정상 반환한 100,000자 첨부를 /chat 이 거절한다.
    """
    monkeypatch.setenv("FILE_MAX_EXTRACT_CHARS", "100000")
    monkeypatch.setenv("CHAT_MAX_TOTAL_INPUT_CHARS", "150000")
    monkeypatch.setenv("CHAT_LOOP_DISABLE", "0")
    client = _client()
    res = client.post("/chat", headers=_auth(), json={
        "message": "검토해줘",
        "attachments": [{"name": "계획서.pdf", "text": "가" * 100000}],
    })
    # 상한 검증은 통과해야 한다 — 422 "너무 큽니다" 가 아니어야 함.
    assert not (res.status_code == 422 and "너무 큽니다" in res.text), res.text
