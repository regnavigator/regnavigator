"""BlobStore — 보고서 본문(.md) 블롭 저장.

인터페이스 1개, 구현 2개:
- `LocalBlobStore`: dev — `{root}/{thread_id}/{report_id}.md` 파일
- `GCSBlobStore`: production — `gs://{bucket}/{thread_id}/{report_id}.md`

uri 형식:
- local → `file://abs/path/...`
- gcs   → `gs://bucket/key`

`iter_uris`·`delete` 는 보존정책 정리(`scripts/prune_blobs.py`)용 — blob 은 무한
증가하므로 만료(reports.created_at) + orphan(참조 없는 파일) 을 주기 삭제한다.
"""

from __future__ import annotations

import pathlib
from typing import Iterator, Protocol


class BlobStore(Protocol):
    def put(self, key: str, body: str) -> str:
        """key(상대 경로 형태)에 body(.md 텍스트)를 저장. 영속 uri 반환."""
        ...

    def get(self, uri: str) -> str:
        """저장된 uri를 읽어 본문(str) 반환."""
        ...

    def presigned_url(self, uri: str, ttl_seconds: int = 3600) -> str | None:
        """다운로드용 presigned URL. local 백엔드는 None."""
        ...

    def iter_uris(self) -> Iterator[str]:
        """저장된 모든 blob uri 순회(보존정책 정리용)."""
        ...

    def delete(self, uri: str) -> bool:
        """blob 삭제. 없으면 False(멱등)."""
        ...


class LocalBlobStore:
    def __init__(self, root: str = "./reports_blobs"):
        self.root = pathlib.Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_from_key(self, key: str) -> pathlib.Path:
        # key는 'thread_id/report_id.md' 형태. ../ 같은 escape 차단.
        rel = pathlib.PurePosixPath(key)
        if rel.is_absolute() or any(part == ".." for part in rel.parts):
            raise ValueError(f"Invalid key: {key!r}")
        return self.root.joinpath(*rel.parts)

    def put(self, key: str, body: str) -> str:
        p = self._path_from_key(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return f"file://{p.as_posix()}"

    def get(self, uri: str) -> str:
        if not uri.startswith("file://"):
            raise ValueError(f"Not a local uri: {uri!r}")
        return pathlib.Path(uri[len("file://"):]).read_text(encoding="utf-8")

    def presigned_url(self, uri: str, ttl_seconds: int = 3600) -> str | None:
        return None  # 로컬 — 별도 라우트로 직접 서빙

    def iter_uris(self) -> Iterator[str]:
        for p in self.root.rglob("*.md"):
            if p.is_file():
                yield f"file://{p.as_posix()}"

    def delete(self, uri: str) -> bool:
        if not uri.startswith("file://"):
            raise ValueError(f"Not a local uri: {uri!r}")
        p = pathlib.Path(uri[len("file://"):])
        # root 밖 삭제 차단(경로 조작 방어).
        try:
            p.resolve().relative_to(self.root)
        except ValueError:
            raise ValueError(f"blob root 밖: {uri!r}") from None
        try:
            p.unlink()
        except FileNotFoundError:
            return False
        # 빈 thread 디렉토리 정리(best-effort).
        try:
            p.parent.rmdir()
        except OSError:
            pass
        return True


class GCSBlobStore:
    """production 자리표. 실제 업로드는 09_DEPLOYMENT 단계에서 활성화."""

    def __init__(self, bucket: str):
        self.bucket = bucket

    def _client(self):
        from google.cloud import storage  # lazy — google-cloud-storage 패키지

        return storage.Client()

    def put(self, key: str, body: str) -> str:
        client = self._client()
        blob = client.bucket(self.bucket).blob(key)
        blob.upload_from_string(body, content_type="text/markdown; charset=utf-8")
        return f"gs://{self.bucket}/{key}"

    def get(self, uri: str) -> str:
        prefix = f"gs://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError(f"Not in bucket {self.bucket}: {uri!r}")
        client = self._client()
        return client.bucket(self.bucket).blob(uri[len(prefix):]).download_as_text(
            encoding="utf-8"
        )

    def presigned_url(self, uri: str, ttl_seconds: int = 3600) -> str | None:
        from datetime import timedelta

        prefix = f"gs://{self.bucket}/"
        if not uri.startswith(prefix):
            return None
        client = self._client()
        blob = client.bucket(self.bucket).blob(uri[len(prefix):])
        return blob.generate_signed_url(
            version="v4", expiration=timedelta(seconds=ttl_seconds), method="GET"
        )

    def iter_uris(self) -> Iterator[str]:
        client = self._client()
        for b in client.list_blobs(self.bucket):
            if b.name.endswith(".md"):
                yield f"gs://{self.bucket}/{b.name}"

    def delete(self, uri: str) -> bool:
        prefix = f"gs://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError(f"Not in bucket {self.bucket}: {uri!r}")
        from google.api_core.exceptions import NotFound

        try:
            self._client().bucket(self.bucket).blob(uri[len(prefix):]).delete()
        except NotFound:
            return False
        return True
