"""북마크 개정 감지 — 저장 시점 대비 폐지·개정예정·시행일 변경 판정.

`GET /bookmarks/amendments`(개인 조회)와 고객사별 정기 리포트(`monitor_report`)가
**같은 판정**을 써야 하므로 라우터에서 분리했다(2026-10-01).

판정 2축:
  1) `law_amendment_status`(ETL lawdangle enrich) — law_id 로 폐지(repealed)/
     개정예정(pending) 판정.
  2) 시행일 비교 — citation `id=cite_doc_{article_key}` 에서 key 를 복원해
     현재 시행일 vs 저장 시점(date) 비교 (amended).

두 축 모두 **실패해도 예외를 올리지 않는다** — enrich 미가용·PG 다운 시 나머지 축만
돌고, 아무것도 못 얻으면 빈 리스트다. 리포트 루프가 이것 때문에 죽으면 안 된다.
"""

from __future__ import annotations

import logging
from typing import Iterable

_log = logging.getLogger(__name__)

_CITE_PREFIX = "cite_doc_"

#: 판정 종류 → 사람이 읽는 라벨 (리포트·UI 공용)
KIND_LABELS = {
    "repealed": "폐지",
    "pending": "개정예정",
    "amended": "시행일 변경",
}


def _index_by_article_key(bookmarks: Iterable) -> dict[str, dict]:
    """Bookmark[] → {article_key: {bookmark_id, citation_id, title, saved_date, folder}}.

    `cite_doc_` 접두가 아닌 인용(웹 등)은 조문 키가 없어 제외한다.
    """
    out: dict[str, dict] = {}
    for b in bookmarks:
        d = b.as_dict() if hasattr(b, "as_dict") else dict(b)
        c = d.get("citation") or {}
        cid = str(c.get("id") or "")
        if not cid.startswith(_CITE_PREFIX):
            continue
        ak = cid[len(_CITE_PREFIX):]
        if not ak or ak in out:
            continue
        out[ak] = {
            "bookmark_id": d.get("id"),
            "citation_id": cid,
            "title": c.get("title"),
            "saved_date": c.get("date"),
            "folder": d.get("folder"),
        }
    return out


def detect(bookmarks: Iterable) -> list[dict]:
    """북마크 목록 → 변경이 감지된 항목만.

    반환 각 항목: {bookmark_id, citation_id, title, saved_date, folder,
                   kind: "repealed"|"pending"|"amended", current_date?}
    """
    key_to = _index_by_article_key(bookmarks)
    if not key_to:
        return []

    out: list[dict] = []
    flagged: set[str] = set()

    # 1) 폐지·개정예정 (law_id = article_key 접두)
    try:
        from src.retrieval.pg_client import fetch_amendment_status

        law_by_ak = {ak: ak.split("_")[0] for ak in key_to}
        statuses = fetch_amendment_status(list(set(law_by_ak.values())))
        for ak, info in key_to.items():
            st = statuses.get(law_by_ak[ak])
            if st in ("repealed", "pending"):
                out.append({**info, "kind": st})
                flagged.add(ak)
    except Exception as e:  # noqa: BLE001 — enrich 미가용 시 시행일 비교만
        _log.warning("amendment status 조회 실패: %s", e)

    # 2) 시행일 비교 — 위에서 안 걸린 것만
    try:
        from src.retrieval.pg_client import fetch_articles

        rows = fetch_articles([ak for ak in key_to if ak not in flagged],
                              medical_filter=False)
    except Exception as e:  # noqa: BLE001 — PG 조회 실패는 이 축만 스킵(비차단)
        _log.warning("amendments fetch 실패: %s", e)
        rows = {}

    for ak, info in key_to.items():
        if ak in flagged:
            continue
        row = rows.get(ak)
        if not row:
            continue
        cur = row.get("enforce_date")
        cur_s = str(cur) if cur else None
        saved = info.get("saved_date")
        if cur_s and saved and cur_s != str(saved):
            out.append({**info, "kind": "amended", "current_date": cur_s})

    return out
