"""이벤트 보존정리 — 방침 §3 이행 (2026-08-03).

`events` 는 성격이 섞여 한 기간으로 자를 수 없다. 내용은 삭제, 지표는 비식별화,
증빙은 보존. **새 event_type 을 분류에 넣지 않으면 영원히 안 지워진다** — 그
누락을 CI 가 잡는다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.prune_events import AUDIT_TYPES, CONTENT_TYPES, METRIC_TYPES


def test_every_emitted_event_type_is_classified():
    src = " ".join(p.read_text(encoding="utf-8") for p in Path("src").rglob("*.py"))
    emitted = set(re.findall(r'event_type="([a-z_]+)"', src))
    # 변수형 emit(`event_type=WITHDRAW_EVENT` 류)도 잡는다 — account_withdraw 가
    # 리터럴 정규식만으로는 안 걸려 분류 누락이 잠복했었다(2026-08-11 발견).
    # 관례: 이벤트 상수는 `X_EVENT = "타입"` 형태로 선언된다.
    emitted |= set(re.findall(r'[A-Z_]*_?EVENT\s*=\s*"([a-z_]+)"', src))
    covered = set(CONTENT_TYPES) | set(METRIC_TYPES) | set(AUDIT_TYPES)
    missing = sorted(emitted - covered)
    assert not missing, (
        f"보존정리 분류 누락 — 이 타입들은 영원히 남는다: {missing}. "
        "scripts/prune_events.py 의 CONTENT/METRIC/AUDIT_TYPES 에 넣을 것.")


def test_classifications_do_not_overlap():
    """한 타입이 삭제와 비식별화 양쪽에 들어가면 동작이 모호해진다."""
    assert not (set(CONTENT_TYPES) & set(METRIC_TYPES))
    assert not (set(CONTENT_TYPES) & set(AUDIT_TYPES))
    assert not (set(METRIC_TYPES) & set(AUDIT_TYPES))


def test_audit_types_match_erase_script():
    """삭제요구 증빙 목록이 erase_user.py 와 어긋나면 한쪽이 증빙을 지운다."""
    src = Path("scripts/erase_user.py").read_text(encoding="utf-8")
    m = re.search(r"_AUDIT\s*=\s*\(([^)]*)\)", src)
    assert m, "erase_user.py 의 _AUDIT 를 찾지 못함"
    erase_audit = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    assert erase_audit == set(AUDIT_TYPES), (
        f"증빙 목록 불일치: erase_user={sorted(erase_audit)} "
        f"prune_events={sorted(AUDIT_TYPES)}")


def test_content_types_include_user_written_text():
    """사용자가 쓴 텍스트가 담기는 타입은 반드시 '삭제' 쪽이어야 한다."""
    for t in ("user_question", "user_feedback", "citation_report", "rag_search"):
        assert t in CONTENT_TYPES, f"{t} 는 내용 이벤트로 분류돼야 한다"


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_BACKEND", "sqlite")
    monkeypatch.setenv("REPORTS_SQLITE_PATH", str(tmp_path / "e.db"))
    from src import persistence as P
    P.get_events_repo.cache_clear()
    yield P.get_events_repo()
    P.get_events_repo.cache_clear()


def _emit(repo, *, ts, etype, user="u-1"):
    from src.persistence import Event
    repo.emit(Event(id="", ts=ts, event_type=etype, user_id=user,
                    thread_id="t-1", input_tokens=10, output_tokens=5,
                    cost_usd=0.01, payload_json='{"question": "질문 원문"}'))


def test_content_deleted_metrics_anonymized_audit_kept(repo):
    old, recent = "2026-01-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00"
    _emit(repo, ts=old, etype="user_question")
    _emit(repo, ts=old, etype="llm_call")
    _emit(repo, ts=old, etype="legal_consent")
    _emit(repo, ts=recent, etype="user_question")
    cut = "2026-06-01T00:00:00+00:00"

    assert repo.delete_older_than(cutoff_iso=cut, types=CONTENT_TYPES) == 1
    assert repo.anonymize_older_than(cutoff_iso=cut, types=METRIC_TYPES) == 1

    rows = repo.list_for_user("u-1", limit=50)
    kinds = sorted(e.event_type for e in rows)
    # 오래된 질문만 사라지고, 최근 질문·증빙은 남는다.
    assert kinds == ["legal_consent", "user_question"]
    # 비식별화된 지표는 user_id 가 없어 list_for_user 에 안 잡히지만 행은 남는다.
    assert repo.count_older_than(cutoff_iso=cut, types=METRIC_TYPES) == 1


def test_anonymize_keeps_metrics_for_stats(repo):
    """비식별화 후에도 토큰·비용이 남아 통계가 과거를 잃지 않아야 한다."""
    _emit(repo, ts="2026-01-01T00:00:00+00:00", etype="llm_call")
    repo.anonymize_older_than(cutoff_iso="2026-06-01T00:00:00+00:00",
                              types=METRIC_TYPES)
    daily = repo.daily_stats(since="2025-01-01T00:00:00+00:00")
    total = sum((d["input_tokens"] or 0) + (d["output_tokens"] or 0) for d in daily)
    assert total == 15, "비식별화가 토큰 집계까지 지웠다"
