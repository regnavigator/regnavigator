"""openlaw-etl Mongo raw 본문 fetch — PG는 index, Mongo가 body.

원래 설계 (V2_DATA_ARCHITECTURE):
- PG: 메타·인덱스 (article_key·법령명·조항번호·시행일)
- Mongo: 본문 raw archive (MOLEG API 원본)

각 카테고리별 raw 구조 다름 — 본 모듈이 추상화:

조문형:
  raw_law:    raw.법령.조문.조문단위[*].{조문번호, 조문제목, 조문내용,
              항[*].{항내용, 호[*].{호내용, 목[*].목내용}}}  # 항→호→목 중첩
  raw_admrul: raw.AdmRulService.조문.{조문번호[i], 조문내용[i], 조문제목[i]} (parallel)
  raw_ordin:  raw.LawService.조문.조[*].{조번호, 조내용}
  raw_treaty: (현재 0건)

문서형 (article_num="본문" 단일):
  raw_prec: raw.PrecService.{판시사항, 판결요지, 참조조문, ...}
  raw_expc: raw.ExpcService.{질의요지, 이유, 안건명, ...}
  raw_decc: raw.PrecService.{재결요지, 이유, 청구취지, ...}
  raw_detc: raw.DetcService.{판시사항, 결정요지, 사건명, ...}

별표(byl):
  raw_admbyl·raw_licbyl·raw_ordinbyl: 메타·다운로드 링크만. 본문은 PG/Neo4j에 있음.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

_log = logging.getLogger(__name__)

_client = None
_db = None
_lock = threading.Lock()


def close_client() -> None:
    """pymongo 클라이언트 종료(종료 경로 전용, 재호출 안전)."""
    global _client, _db
    cli, _client, _db = _client, None, None
    if cli is None:
        return
    try:
        cli.close()
    except Exception:  # noqa: BLE001
        pass


def _get_db():
    """pymongo client lazy init. 미설정·미설치 시 None."""
    global _client, _db
    if _db is not None:
        return _db

    uri = (os.getenv("MONGO_URI") or "").strip()
    if not uri:
        return None

    with _lock:
        if _db is not None:
            return _db
        try:
            import pymongo
        except ImportError:
            _log.warning("pymongo 미설치 — Mongo body fetch 비활성")
            return None
        try:
            _client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
            _db = _client[os.getenv("MONGO_DB", "openlaw")]
            _client.server_info()  # 연결 검증
            _log.info("Mongo connected")
        except Exception as e:
            _log.warning("Mongo 연결 실패: %s", e)
            return None
    return _db


def fetch_body(
    *,
    target_type: str,
    mst_id: str,
    article_num: Optional[str] = None,
    law_title: Optional[str] = None,
) -> Optional[str]:
    """카테고리별 raw에서 본문 추출. 실패 시 None.

    Args:
        target_type: law·admrul·ordin·prec·expc·decc·detc
        mst_id: Mongo `_id` 우선 매칭. PG의 mst_id가 law_id로 잘못 박힌 경우
                `law_title` fallback 사용.
        article_num: 조문형일 때 매칭할 조 번호 (예: "제4조"). 문서형은 무시.
        law_title: mst_id 매칭 실패 시 법령명으로 fallback 검색.
    """
    db = _get_db()
    if db is None:
        return None

    collection = f"raw_{target_type}"
    doc = None
    try:
        doc = db[collection].find_one({"_id": mst_id})
    except Exception as e:
        _log.warning("Mongo find_one 실패 (%s/%s): %s", collection, mst_id, e)

    # Fallback — mst_id 매칭 실패 시 law_title로 검색 (PG의 mst_id가 잘못 박혀있는 케이스).
    if not doc and law_title and target_type in ("law", "admrul", "ordin", "treaty"):
        doc = _find_by_title(db, target_type, law_title)

    if not doc:
        return None

    raw = doc.get("raw") or {}

    if target_type == "law":
        return _extract_law_body(raw, article_num)
    if target_type == "admrul":
        return _extract_admrul_body(raw, article_num)
    if target_type == "ordin":
        return _extract_ordin_body(raw, article_num)
    if target_type == "treaty":
        return _extract_law_body(raw, article_num)  # 동일 패턴
    if target_type == "prec":
        return _extract_prec_body(raw)
    if target_type == "expc":
        return _extract_expc_body(raw)
    if target_type == "decc":
        return _extract_decc_body(raw)
    if target_type == "detc":
        return _extract_detc_body(raw)

    return None


# ---------------------------------------------------------------------------
# Title 기반 fallback — PG mst_id가 잘못된 경우용 (캐시)
# ---------------------------------------------------------------------------
_title_cache: dict[tuple[str, str], Optional[dict]] = {}


def _find_by_title(db, target_type: str, title: str) -> Optional[dict]:
    """raw_{cat} 컬렉션에서 법령명 매칭 — mst_id fallback.

    각 카테고리의 title 키 다름:
      raw_law:    raw.법령.기본정보.법령명_한글
      raw_admrul: raw.AdmRulService.행정규칙기본정보.행정규칙명
      raw_ordin:  raw.LawService.자치법규기본정보.자치법규명

    검색은 nested key path 인덱스 없으면 collection scan — 느림.
    매 호출 후 캐시 (동일 (cat, title) 재요청 시 즉시 반환).
    """
    cache_key = (target_type, title)
    if cache_key in _title_cache:
        return _title_cache[cache_key]

    title_paths = {
        "law": "raw.법령.기본정보.법령명_한글",
        "admrul": "raw.AdmRulService.행정규칙기본정보.행정규칙명",
        "ordin": "raw.LawService.자치법규기본정보.자치법규명",
        "treaty": "raw.법령.기본정보.법령명_한글",
    }
    path = title_paths.get(target_type)
    if not path:
        _title_cache[cache_key] = None
        return None

    collection = f"raw_{target_type}"
    try:
        doc = db[collection].find_one({path: title})
    except Exception as e:
        _log.warning("Mongo title fallback 실패: %s", e)
        doc = None

    _title_cache[cache_key] = doc
    return doc


# ---------------------------------------------------------------------------
# 조문형 — article_num 매칭 + 조문내용 + 항.항내용 합침
# ---------------------------------------------------------------------------
def _normalize_article_num(s: str) -> str:
    """문자열에서 숫자만 추출 — '제4조'→'4', '제4조의2'→'4_2', '0004'→'4'."""
    import re
    s = str(s).strip()
    # '제N조'·'제N조의M'
    m = re.match(r"제?(\d+)조?(?:의(\d+))?", s)
    if m:
        n = m.group(1).lstrip("0") or "0"
        sub = m.group(2)
        return f"{n}_{sub}" if sub else n
    return s.lstrip("0") or "0"


def _extract_law_body(raw: dict, article_num: Optional[str]) -> Optional[str]:
    """raw_law: raw.법령.조문.조문단위[*]에서 article_num 매칭."""
    law = raw.get("법령") or {}
    units_root = law.get("조문") or {}
    units = units_root.get("조문단위")
    if not units:
        return None
    if isinstance(units, dict):
        units = [units]
    if not article_num:
        return None
    target_norm = _normalize_article_num(article_num)
    for u in units:
        if not isinstance(u, dict):
            continue
        # 장·절·편 헤더 유닛(조문여부="전문")은 *다음 조와 같은 조문번호*를 갖고
        # 배열상 그 조 앞에 온다 (예: 의료기기법 제15조 앞 "제2절 수입업" 유닛의
        # 조문번호=15). 첫 매칭을 반환하던 기존 로직이 절 시작 조문마다 본문 대신
        # 절 제목만 돌려주던 원인 — 실제 조문(조문여부="조문")만 대상.
        if str(u.get("조문여부") or "").strip() == "전문":
            continue
        u_num = _normalize_article_num(str(u.get("조문번호") or ""))
        # "제N조의M"의 M은 조문번호가 아니라 별도 필드(조문가지번호)에 있다 —
        # 미반영 시 제15조의2 요청이 제15조 유닛과 오매칭되거나 항상 miss.
        branch = str(u.get("조문가지번호") or "").strip().lstrip("0")
        if branch:
            u_num = f"{u_num}_{branch}"
        if u_num != target_norm:
            continue
        # 조문내용 + 항.항내용 합치기
        parts = []
        title = u.get("조문제목")
        if title:
            parts.append(str(title))
        body = u.get("조문내용")
        if body:
            parts.append(str(body))
        # 항 → 호 → 목 재귀. 기존엔 항내용만 긁어 호("각 호의 사항")가 빠짐.
        parts.extend(_flatten_clauses(u.get("항")))
        # 항 없이 조문 직속 호가 있는 경우(드묾)도 흡수.
        parts.extend(_flatten_clauses(u.get("호"), _key="호내용", _child="목"))
        return "\n".join(p for p in parts if p) if parts else None
    return None


def _flatten_clauses(node, *, _key: str = "항내용", _child: str = "호") -> list[str]:
    """항/호/목 중첩을 본문 순서대로 평탄화.

    항 → 항내용 + (호 → 호내용 + (목 → 목내용)). law.go.kr 표준 중첩.
    누락된 레벨은 건너뛰고, 있는 텍스트만 순서 보존 수집.
    """
    if node is None:
        return []
    if isinstance(node, dict):
        node = [node]
    if not isinstance(node, list):
        return []
    _grandchild = {"호": "목", "목": None}.get(_child)
    out: list[str] = []
    for item in node:
        if not isinstance(item, dict):
            if item:
                out.append(str(item))
            continue
        text = item.get(_key)
        if text:
            out.append(str(text))
        if _child:
            child_key = "호내용" if _child == "호" else "목내용"
            out.extend(
                _flatten_clauses(item.get(_child), _key=child_key,
                                 _child=_grandchild)
            )
    return out


def _extract_admrul_body(raw: dict, article_num: Optional[str]) -> Optional[str]:
    """raw_admrul: parallel arrays — 조문번호[i] ↔ 조문내용[i] ↔ 조문제목[i]."""
    svc = raw.get("AdmRulService") or {}
    art = svc.get("조문") or {}
    nums = art.get("조문번호") or []
    bodies = art.get("조문내용") or []
    titles = art.get("조문제목") or []
    if isinstance(nums, str):
        nums = [nums]
    if isinstance(bodies, str):
        bodies = [bodies]
    if isinstance(titles, str):
        titles = [titles]
    if not nums or not bodies:
        return None
    if not article_num:
        return None
    target_norm = _normalize_article_num(article_num)
    for i, n in enumerate(nums):
        if _normalize_article_num(str(n)) == target_norm:
            parts = []
            if i < len(titles):
                parts.append(str(titles[i] or ""))
            parts.append(str(bodies[i] or ""))
            return "\n".join(p for p in parts if p) or None
    return None


def _extract_ordin_body(raw: dict, article_num: Optional[str]) -> Optional[str]:
    """raw_ordin: raw.LawService.조문.조[*].{조번호, 조내용}."""
    svc = raw.get("LawService") or {}
    art = svc.get("조문") or {}
    units = art.get("조") or art.get("조문단위")
    if not units:
        return None
    if isinstance(units, dict):
        units = [units]
    if not article_num:
        return None
    target_norm = _normalize_article_num(article_num)
    for u in units:
        if not isinstance(u, dict):
            continue
        u_num = _normalize_article_num(str(u.get("조번호") or u.get("조문번호") or ""))
        if u_num != target_norm:
            continue
        parts = []
        title = u.get("조제목") or u.get("조문제목")
        if title:
            parts.append(str(title))
        body = u.get("조내용") or u.get("조문내용")
        if body:
            parts.append(str(body))
        # 항도 있으면
        hangs = u.get("항") or []
        if isinstance(hangs, dict):
            hangs = [hangs]
        if isinstance(hangs, list):
            for h in hangs:
                if isinstance(h, dict):
                    hb = h.get("항내용")
                    if hb:
                        parts.append(str(hb))
        return "\n".join(parts) if parts else None
    return None


# ---------------------------------------------------------------------------
# 문서형 — 단일 문서, article_num 무관. 모든 본문 필드 합침
# ---------------------------------------------------------------------------
def _extract_prec_body(raw: dict) -> Optional[str]:
    """raw_prec: 판시사항 + 판결요지 + 참조조문."""
    svc = raw.get("PrecService") or {}
    parts = []
    for k in ("사건명", "법원명", "선고일자", "사건종류명",
              "판시사항", "판결요지", "참조조문", "참조판례"):
        v = svc.get(k)
        if v:
            parts.append(f"[{k}] {v}")
    return "\n".join(parts) if parts else None


def _extract_expc_body(raw: dict) -> Optional[str]:
    """raw_expc: 안건명 + 질의요지 + 이유."""
    svc = raw.get("ExpcService") or {}
    parts = []
    for k in ("안건명", "안건번호", "해석기관명", "해석일자",
              "질의요지", "이유", "회답"):
        v = svc.get(k)
        if v:
            parts.append(f"[{k}] {v}")
    return "\n".join(parts) if parts else None


def _extract_decc_body(raw: dict) -> Optional[str]:
    """raw_decc: 재결요지 + 이유 (PrecService 키 사용)."""
    svc = raw.get("PrecService") or raw.get("DeccService") or {}
    parts = []
    for k in ("사건번호", "재결청", "처분청", "재결례유형명",
              "청구취지", "재결요지", "이유", "주문"):
        v = svc.get(k)
        if v:
            parts.append(f"[{k}] {v}")
    return "\n".join(parts) if parts else None


def _extract_detc_body(raw: dict) -> Optional[str]:
    """raw_detc: 결정요지 + 판시사항 + 이유."""
    svc = raw.get("DetcService") or raw.get("PrecService") or {}
    parts = []
    for k in ("사건번호", "사건종류명", "종국일자",
              "심판대상조문", "판시사항", "결정요지", "이유"):
        v = svc.get(k)
        if v:
            parts.append(f"[{k}] {v}")
    return "\n".join(parts) if parts else None
