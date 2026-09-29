"""LangSmith 트레이스 → citation 추출 공유 코어.

채팅(fast, graph=agent)·보고서(deep, graph=agent_deep)의 qdrant_search/tavily_search
run 에서 인용된 출처(citation)를 읽어내는 공통 로직. 백엔드 hot path 와 무관한
**오프라인 읽기 전용** 모듈 — `rag_usage_langsmith.py`(통계)·`cited_docs_export.py`
(DB 시드 추출) 가 공유.

추출 경로 (트레이스 탐침으로 확정):
    query     ← inputs["input"]  (repr 문자열 "{'query': '...'}")
    citations ← outputs["output"]["update"]["steps"][*]["citations"]
    mode/who  ← extra.metadata.{graph_id, thread_id, user_id}

env (.env 자동 로드): LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGSMITH_ENDPOINT.
"""
from __future__ import annotations

import ast
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional


GRAPH_LABEL = {"agent": "채팅", "agent_deep": "보고서"}


def load_env() -> None:
    """standalone 실행 시 .env 로드 (langgraph dev 없이)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
    except Exception:
        pass  # 셸에 이미 있으면 무방


def get_client_and_project():
    """(langsmith.Client, project_name) 반환. 환경 미비 시 ValueError."""
    try:
        from langsmith import Client
    except ImportError as e:
        raise ValueError("langsmith SDK 필요: pip install langsmith") from e
    proj = (os.environ.get("LANGSMITH_PROJECT") or "").strip('"')
    if not proj or not os.environ.get("LANGSMITH_API_KEY"):
        raise ValueError("LANGSMITH_PROJECT / LANGSMITH_API_KEY 가 .env 또는 셸에 필요.")
    return Client(), proj


def parse_query(inputs) -> Optional[str]:
    raw = (inputs or {}).get("input")
    if isinstance(raw, dict):
        return raw.get("query")
    if isinstance(raw, str):
        try:
            return ast.literal_eval(raw).get("query")
        except (ValueError, SyntaxError, AttributeError):
            return raw[:120]
    return None


def extract_citations(outputs) -> list[dict]:
    """outputs.output.update.steps[*].citations 평탄화 → list[dict]."""
    out = (outputs or {}).get("output")
    if not isinstance(out, dict):
        return []
    steps = ((out.get("update") or {}).get("steps")) or []
    cits: list[dict] = []
    for st in steps:
        if isinstance(st, dict):
            for c in (st.get("citations") or []):
                if isinstance(c, dict):
                    cits.append(c)
    return cits


def publisher_name(ci: dict) -> str:
    """publisher → 문자열. dict / dict-repr 문자열 정규화 버그 케이스 flatten."""
    p = ci.get("publisher")
    if isinstance(p, str) and p.startswith("{") and "content" in p:
        try:
            p = ast.literal_eval(p)
        except (ValueError, SyntaxError):
            pass
    if isinstance(p, dict):
        p = p.get("content") or json.dumps(p, ensure_ascii=False)
    return p if p else "(미상/미검증 웹)"


def parse_since(since: Optional[str], *, default_days: int = 30) -> datetime:
    if since:
        return datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(days=default_days)


def iter_runs(
    client, project: str, *, tool: str, since: datetime, limit: int,
) -> Iterator[dict]:
    """qdrant_search/tavily_search run 을 정규화 dict 로 yield.

    yield: {graph_id, mode, thread_id, user_id, ts, query, citations[]}.
    limit 은 SDK 페이지 크기(max 100)가 아니라 우리 루프 상한 → list_runs 는
    자동 페이지네이션에 맡기고 여기서 끊는다.
    """
    runs = client.list_runs(
        project_name=project,
        filter=f'eq(name, "{tool}")',
        start_time=since,
    )
    seen = 0
    for r in runs:
        if seen >= limit:
            break
        seen += 1
        md = (r.extra or {}).get("metadata") or {}
        graph = md.get("graph_id") or "(unknown)"
        yield {
            "graph_id": graph,
            "mode": GRAPH_LABEL.get(graph, graph),
            "thread_id": md.get("thread_id"),
            "user_id": md.get("user_id"),
            "ts": r.start_time.isoformat() if r.start_time else None,
            "query": parse_query(r.inputs),
            "citations": extract_citations(r.outputs),
        }
