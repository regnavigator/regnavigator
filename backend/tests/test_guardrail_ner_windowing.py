"""guardrail-ner 서버측 윈도잉 + 클라이언트 자동 전환 — 2026-08-04.

배경: 토큰분류 파이프라인은 모델 상한(512토큰)을 넘으면 뒷부분을 조용히 버린다.
처음엔 medi-back 이 잘라 보내는 것으로 우회했는데, 그러면 **입력 길이에 비례해
HTTP 왕복이 늘어** 큐 대기가 지배적이 됐다(36,000자 → 64왕복 → 45~100초).

`guardrail-server/serve.py` 는 medi-back 레포가 원본이므로(README: "여기가 원본",
미러 → DGX `git pull` + `deploy.sh`) 서버에서 제대로 고쳤다: 토크나이저 오프셋으로
정확히 윈도를 뜨고 **한 번의 GPU 배치**로 추론한다.

이 파일은 두 가지를 잠근다:
  ① 윈도 계산 — 전 구간 커버 · 모델 상한 준수 · 경계 스팬 보호용 겹침
  ② 클라이언트 자동 전환 — 새 서버면 통짜, 구 서버면 종전대로 클라이언트 청킹
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest


_SERVE = pathlib.Path("guardrail-server/serve.py")


def _load_serve(monkeypatch):
    """serve.py 는 패키지가 아니라 단독 스크립트 — 경로로 로드한다."""
    monkeypatch.setenv("GUARDRAIL_API_KEY", "k")
    spec = importlib.util.spec_from_file_location("guardrail_serve", _SERVE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Tok:
    """1글자=1토큰 가짜 토크나이저(실모델과 같은 512 상한)."""

    model_max_length = 512

    def __call__(self, text, **kw):
        return {"offset_mapping": [(i, i + 1) for i in range(len(text))]}


@pytest.mark.skipif(not _SERVE.exists(), reason="guardrail-server 없음")
@pytest.mark.parametrize("n", [400, 510, 511, 1200, 5000, 12000])
def test_windows_cover_everything_within_model_limit(monkeypatch, n):
    """어느 구간도 빠지면 안 된다 — 빠진 구간의 PII 는 조용히 미마스킹된다."""
    serve = _load_serve(monkeypatch)
    tok = _Tok()
    limit = serve._max_window_tokens(tok)

    text = "가" * n
    wins = serve._windows(text, tok)

    covered = set()
    for s, e in wins:
        covered |= set(range(s, e))
    assert covered == set(range(n)), "윈도가 원문 전 구간을 덮지 않는다"
    assert all((e - s) <= limit for s, e in wins), "윈도가 모델 상한을 넘는다"


@pytest.mark.skipif(not _SERVE.exists(), reason="guardrail-server 없음")
def test_windows_overlap_so_boundary_spans_survive(monkeypatch):
    """경계에 걸친 이름이 양쪽에서 문맥을 잃으면 아예 탐지되지 않는다."""
    serve = _load_serve(monkeypatch)
    wins = serve._windows("가" * 3000, _Tok())

    assert len(wins) > 1
    assert all(wins[i + 1][0] < wins[i][1] for i in range(len(wins) - 1)), \
        "윈도가 겹치지 않는다 — 경계 스팬이 유실된다"


@pytest.mark.skipif(not _SERVE.exists(), reason="guardrail-server 없음")
def test_short_text_is_single_window(monkeypatch):
    serve = _load_serve(monkeypatch)
    assert serve._windows("의료기기 광고 사전심의", _Tok()) == [(0, 12)]


# ── 클라이언트 자동 전환 ────────────────────────────────────────────────────
def _fake_health(monkeypatch, payload):
    from src.guardrail import ner_client

    class _R:
        def raise_for_status(self): ...
        def json(self): return payload

    monkeypatch.setattr(
        ner_client, "_client",
        lambda: type("C", (), {"get": staticmethod(lambda *a, **k: _R())})())
    ner_client.reset_capability_cache()
    return ner_client


def test_new_server_gets_whole_text_in_one_request(monkeypatch):
    """서버가 윈도잉하면 자를 이유가 없다 — 왕복 1회가 항상 빠르다."""
    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")
    ner_client = _fake_health(monkeypatch, {"status": "ok", "long_input": True})

    calls = []
    monkeypatch.setattr(ner_client, "_post_chunk",
                        lambda t, s, e, timeout=None: calls.append((s, e)) or [])
    ner_client.detect("가" * 30000)

    assert calls == [(0, 30000)], f"통짜로 안 보냈다: {calls[:3]}"
    ner_client.reset_capability_cache()


def test_old_server_still_gets_client_side_chunks(monkeypatch):
    """구 서버(long_input 없음)에서는 종전대로 잘라 보낸다 — 하위호환."""
    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")
    monkeypatch.setenv("PII_NER_CHUNK_CHARS", "600")
    ner_client = _fake_health(monkeypatch, {"status": "ok"})   # 구 서버 응답

    calls = []
    monkeypatch.setattr(ner_client, "_post_chunk",
                        lambda t, s, e, timeout=None: calls.append((s, e)) or [])
    ner_client.detect("가" * 5000)

    assert len(calls) > 1, "구 서버인데 통짜로 보냈다 — 뒷부분이 미탐된다"
    ner_client.reset_capability_cache()


def test_capability_probe_failure_falls_back_to_chunking(monkeypatch):
    """탐지 실패는 구 서버로 간주(보수적) — 자르는 쪽이 안전하다."""
    from src.guardrail import ner_client

    monkeypatch.setenv("PII_NER_API_URL", "http://ner.test")
    monkeypatch.setenv("PII_NER_API_KEY", "k")
    monkeypatch.setenv("PII_NER_CHUNK_CHARS", "600")

    def _boom(*a, **k):
        raise RuntimeError("unreachable")

    monkeypatch.setattr(
        ner_client, "_client",
        lambda: type("C", (), {"get": staticmethod(_boom)})())
    ner_client.reset_capability_cache()

    calls = []
    monkeypatch.setattr(ner_client, "_post_chunk",
                        lambda t, s, e, timeout=None: calls.append((s, e)) or [])
    ner_client.detect("가" * 5000)

    assert len(calls) > 1
    ner_client.reset_capability_cache()


# ── 줄 단위 윈도 — 이름 리콜 회복 ───────────────────────────────────────────
@pytest.mark.skipif(not _SERVE.exists(), reason="guardrail-server 없음")
def test_lines_become_their_own_windows(monkeypatch):
    """이름이 자기 줄에 있으면 앞 문맥 0자로 평가돼야 한다.

    이 모델은 앞 문맥 100자만 붙어도 이름 score 가 임계 아래로 떨어진다
    (실측: 0자 0.707 / 40자 0.534 / 100자+ 미탐). 512토큰 윈도로 정확히 잘라도
    윈도 **내부**에 앞 문맥이 남아 `담당자: 홍길동` 을 놓쳤다(2/3).
    줄 단위로 쪼개면 3/3 으로 회복된다.
    """
    serve = _load_serve(monkeypatch)
    doc = "1. 검토사항\n2. 다른 항목\n담당자: 홍길동\n작성자: 김영수"
    wins = serve._line_windows(doc)

    segs = [doc[s:e] for s, e in wins]
    assert "담당자: 홍길동" in segs, f"이름 줄이 독립 윈도가 아니다: {segs}"
    assert all("\n" not in s for s in segs), "윈도가 줄을 넘어간다"


@pytest.mark.skipif(not _SERVE.exists(), reason="guardrail-server 없음")
def test_long_line_is_split_and_nothing_is_lost(monkeypatch):
    """긴 줄은 모델 상한을 넘으므로 토큰 윈도로 재분할 — 내용 유실 금지."""
    serve = _load_serve(monkeypatch)
    tok = _Tok()
    doc = "짧은 줄\n" + ("가" * 1500) + "\n담당자: 홍길동"

    wins = []
    for ls, le in serve._line_windows(doc):
        for ws, we in serve._windows(doc[ls:le], tok):
            wins.append((ls + ws, ls + we))

    covered = set()
    for s, e in wins:
        covered |= set(range(s, e))
    content = {i for i, c in enumerate(doc) if c != "\n"}
    assert covered >= content, "줄바꿈 외 내용이 검사에서 빠졌다"
    assert all((e - s) <= serve._max_window_tokens(tok) for s, e in wins)


@pytest.mark.skipif(not _SERVE.exists(), reason="guardrail-server 없음")
def test_blank_lines_do_not_create_empty_windows(monkeypatch):
    serve = _load_serve(monkeypatch)
    wins = serve._line_windows("가\n\n\n나")
    assert [w for w in wins if w[0] == w[1]] == []
    assert len(wins) == 2
