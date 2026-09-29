"""POST /files/extract — 채팅 첨부용 파일 텍스트 추출 (파일 업로드 v1, 2026-08-05).

흐름: 프런트가 파일을 여기로 업로드 → 추출 텍스트를 돌려받아 들고 있다가
전송 시 `POST /chat` 의 `attachments` 로 보낸다. **서버는 원본도 추출본도
저장하지 않는다** — 상태는 프런트가 든다. 대화에 들어간 텍스트는 기존
PII 게이트가 마스킹해 at-rest 정책이 붙여넣기와 동일하게 적용된다.

응답 200: { name, kind, chars, truncated, text }
오류(전부 한국어 detail): 413(크기 초과) · 415(미지원 형식) · 422(텍스트 없음)

인증: app 레벨 AuthMiddleware (공개 경로 아님).
라우트 규약: 추출은 블로킹 CPU 작업 — `def` 로 선언해 스레드풀 위임.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.file_extract import (
    EmptyExtract,
    UnsupportedFileType,
    extract_text,
)

_log = logging.getLogger(__name__)

router = APIRouter()


def _max_upload_bytes() -> int:
    try:
        mb = float((os.getenv("FILE_MAX_UPLOAD_MB") or "").strip() or "15")
    except ValueError:
        mb = 15.0
    return int(mb * 1024 * 1024)


@router.post("/files/extract")
def files_extract(file: UploadFile = File(...)):
    limit = _max_upload_bytes()
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 큽니다. {limit // (1024 * 1024)}MB 이하로 올려주세요.",
        )
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일입니다.")

    name = (file.filename or "파일").strip()[:200]
    try:
        result = extract_text(name, data)
    except UnsupportedFileType as e:
        raise HTTPException(status_code=415, detail=str(e))
    except EmptyExtract as e:
        raise HTTPException(status_code=422, detail=str(e))

    _log.info("files/extract: %s kind=%s chars=%d truncated=%s",
              name, result.kind, len(result.text), result.truncated)
    return {
        "name": name,
        "kind": result.kind,
        "chars": len(result.text),
        "truncated": result.truncated,
        "text": result.text,
    }
