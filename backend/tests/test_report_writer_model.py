"""writer 모델 노브 회귀 — 스트림 침묵 타임아웃(2026-08-02 보고서 실패).

langchain-openai 의 `stream_chunk_timeout` 기본값은 **120초**다. 이 값은
httpx read timeout 과 달리 keepalive 로 리셋되지 않는 '콘텐츠 침묵' 타이머라,
긴 프롬프트 prefill 중에 터진다 — `REPORT_WRITER_TIMEOUT_S=1800` 을 줘도 소용없다.
실제로 보고서 e2e 가 400초 지점에서 StreamChunkTimeoutError 로 failed 됐다.
"""
from __future__ import annotations

import pytest

# writer 는 `[writer-vllm]` extras — CI 는 base 의존만 설치하므로 없으면 스킵.
# (배포 이미지는 prod extras 를 깔므로 거기선 실제로 검증된다.)
pytest.importorskip("langchain_openai",
                    reason="langchain-openai 미설치(base CI) — writer 노브 검증 스킵")


@pytest.fixture(autouse=True)
def _writer_env(monkeypatch):
    monkeypatch.setenv("REPORT_WRITER_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("REPORT_WRITER_MODEL", "test-writer")  # /models 조회 회피
    monkeypatch.setenv("REPORT_WRITER_API_KEY", "EMPTY")
    monkeypatch.delenv("REPORT_WRITER_STREAM_CHUNK_TIMEOUT_S", raising=False)


def test_writer_overrides_stream_chunk_timeout():
    from src.models import report_writer_model

    m = report_writer_model()
    # 기본 120s 를 그대로 두면 긴 prefill 에서 보고서가 죽는다.
    assert getattr(m, "stream_chunk_timeout", None) == 900.0
    assert m.request_timeout == 1800.0


def test_writer_stream_chunk_timeout_env_override(monkeypatch):
    from src.models import report_writer_model

    monkeypatch.setenv("REPORT_WRITER_STREAM_CHUNK_TIMEOUT_S", "300")
    assert report_writer_model().stream_chunk_timeout == 300.0


def test_writer_stream_chunk_timeout_bad_value_falls_back(monkeypatch):
    from src.models import report_writer_model

    monkeypatch.setenv("REPORT_WRITER_STREAM_CHUNK_TIMEOUT_S", "쓰레기")
    assert report_writer_model().stream_chunk_timeout == 900.0
