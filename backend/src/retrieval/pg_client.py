"""openlaw-etl PostgreSQL 클라이언트 — article 메타·full_text fetch.

Qdrant payload엔 chunk text·기본 메타만 들어있고, *법령명·시행일·부서* 등 사용자 향
인용에 필요한 메타는 PG의 metadata 테이블에 있음. article_key 리스트로 한 번에 fetch.

RETRIEVAL_GUIDE §2.3 참조 — target_type별로 다른 테이블:
  - law      → law_articles + law_metadata
  - admrul   → admrul_articles + admrul_metadata
  - prec     → prec_articles + prec_metadata (등 — 실제 테이블명 확인 필요)
  - expc     → expc_articles + expc_metadata
  - ordin    → ordin_articles + ordin_metadata

본 클라이언트는 Phase 1에서 law·admrul만 우선 지원. 다른 카테고리는 LLM 답변에
인용으로 등장 시 동일 패턴으로 추가.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

_log = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()


def close_pool() -> None:
    """openlaw PG 풀 종료(종료 경로 전용, 재호출 안전)."""
    global _pool
    pool, _pool = _pool, None
    if pool is None:
        return
    try:
        pool.close()
    except Exception:  # noqa: BLE001
        pass


def is_available() -> bool:
    """법령 PG 를 실제로 쓸 수 있는가 — 미설정·드라이버 없음·풀 생성 실패면 False.

    이 모듈의 조회 함수들은 실패를 `{}` 로 **삼킨다**. 그래서 호출자가 "결과 없음"과
    "조회 못 함"을 구분하려면 이걸 먼저 봐야 한다. 개정 감지 리포트가 DB 다운 중에
    '변경 없음'이라고 단언하는 사고를 막기 위해 공개했다(2026-10-01).
    """
    try:
        return _get_pool() is not None
    except Exception:  # noqa: BLE001 — 판정 자체가 죽으면 '못 씀'으로 본다
        return False


def _get_pool():
    """psycopg ConnectionPool — lazy init.

    PG_HOST·PG_PORT·PG_NAME·PG_USER·PG_PASS 필요. 미설정 시 None 반환 (호출자가
    fallback 처리).
    """
    global _pool
    if _pool is not None:
        return _pool

    host = (os.getenv("PG_HOST") or "").strip()
    if not host:
        return None

    with _pool_lock:
        if _pool is not None:
            return _pool

        try:
            import psycopg  # noqa: F401 — 가용성 프로브(미설치면 ImportError 로 폴백)
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError:
            _log.warning(
                "psycopg + psycopg_pool 미설치 — `pip install medi-back[prod]` 필요. "
                "PG fetch 비활성화 — Qdrant payload 메타만 사용."
            )
            return None

        port = int((os.getenv("PG_PORT") or "").strip() or "5432")
        dbname = (os.getenv("PG_NAME") or "openlaw").strip()
        user = (os.getenv("PG_USER") or "").strip()
        password = (os.getenv("PG_PASS") or "").strip()

        dsn = (
            f"host={host} port={port} dbname={dbname} "
            f"user={user} password={password}"
        )
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=int((os.getenv("PG_POOL_MAX") or "").strip() or "5"),
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        _pool.open()
        _pool.wait()
        _log.info("openlaw PG pool opened: %s:%s/%s", host, port, dbname)

    return _pool


def _medical_filter_clause() -> str:
    """의료 도메인 prefilter SQL 조각 — m.department·m.title 화이트리스트.

    `MEDICAL_FILTER_DISABLE=1` 시 빈 문자열 (필터 없음).
    빈 문자열 반환 시 호출자가 그대로 무시.
    """
    if (os.getenv("MEDICAL_FILTER_DISABLE") or "").strip() == "1":
        return ""
    # 부처: 식약처 / 보건복지부 / 식품의약품안전평가원 / 한국의료기기안전정보원
    # 법령명 키워드: 의료·약사·의약품·의료기기·식품·생명윤리·개인정보(의료 데이터)
    return (
        " AND ("
        " m.department LIKE '%식품의약품%'"
        " OR m.department LIKE '%보건복지%'"
        " OR m.department LIKE '%의료기기%'"
        " OR m.title LIKE '%의료%'"
        " OR m.title LIKE '%약사%'"
        " OR m.title LIKE '%의약품%'"
        " OR m.title LIKE '%의료기기%'"
        " OR m.title LIKE '%생명윤리%'"
        " OR m.title LIKE '%식품%'"
        " OR m.title LIKE '%화장품%'"
        " OR m.title LIKE '%건강기능식품%'"
        ")"
    )


def fetch_articles(
    article_keys: list[str],
    *,
    target_types: Optional[list[str]] = None,
    medical_filter: bool = True,
) -> dict[str, dict]:
    """article_key 리스트 → 메타·본문 dict (`{article_key: row}`).

    target_types 미지정 시 law + admrul (Phase 1 default). 향후 prec/expc/ordin 추가.
    medical_filter=True 면 부처·법령명 의료 화이트리스트 적용 (env로 끔: MEDICAL_FILTER_DISABLE=1).

    반환 row 키:
      target_type, article_key, law_id, article_num, article_title, full_text,
      law_title, enforce_date, department
    """
    if not article_keys:
        return {}

    pool = _get_pool()
    if pool is None:
        # PG 비활성화 — 빈 dict 반환. 호출자는 Qdrant payload 메타로 fallback.
        return {}

    keys = list(article_keys)
    # openlaw-etl 8 카테고리 — 조문형(law·admrul·ordin·treaty) + 문서형(prec·expc·decc·detc).
    # spec: V2_DATA_ARCHITECTURE §🍃 + V2_ETL_CHALLENGES §5.
    types = target_types or [
        "law", "admrul", "ordin", "treaty",
        "prec", "expc", "decc", "detc",
    ]

    # PG metadata 테이블 컬럼이 카테고리마다 다를 수 있음. 안전하게 모든 카테고리 동일
    # 컬럼 (title, enforce_date, department)만 fetch — 결측이면 NULL.
    union_parts = []
    # medical_filter는 의미 있는 카테고리(법령·행정규칙·자치법규)에만 적용.
    # 판례·해석례·헌재결정례·행정심판례는 의료 무관 확률 적고 더 넓게 두기.
    medical_clause_for = {"law", "admrul", "ordin"}
    medical_clause = _medical_filter_clause() if medical_filter else ""
    for t in types:
        clause = medical_clause if t in medical_clause_for else ""
        # 테이블 존재 가정 — 실제 스키마와 다르면 ProgrammingError. 호출자 catch.
        union_parts.append(
            f"""SELECT '{t}' AS target_type,
                       a.article_key,
                       a.law_id,
                       a.mst_id,
                       a.article_num,
                       a.article_title,
                       a.full_text,
                       a.chunk_type,
                       m.title AS law_title,
                       m.enforce_date,
                       m.department
                FROM {t}_articles a
                LEFT JOIN {t}_metadata m ON a.law_id = m.law_id
                WHERE a.article_key = ANY(%s){clause}"""
        )
    sql = "\nUNION ALL\n".join(union_parts)

    out: dict[str, dict] = {}
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # type별로 같은 keys 파라미터 반복
                cur.execute(sql, [keys] * len(types))
                rows = cur.fetchall()
        for r in rows:
            ak = r.get("article_key")
            if ak:
                row = dict(r)
                # full_text의 HTML 잔존 태그 정리 (판례 등에 <br/> 잔존)
                ft = row.get("full_text")
                if ft:
                    row["full_text"] = _strip_html_artifacts(ft)
                # department가 dict-repr 문자열로 박힌 경우 정리.
                # 예: "{'content': '식품의약품안전처', '소관부처코드': '1471000'}"
                row["department"] = _parse_department(row.get("department"))
                out[ak] = row
    except Exception as e:
        _log.warning("PG fetch_articles failed: %s — Qdrant payload만 사용", e)
        return {}

    return out


def resolve_article_keys(
    keys: list[str],
    *,
    target_types: Optional[list[str]] = None,
) -> dict[str, str]:
    """Neo4j `Article.id` ↔ PG/Qdrant `article_key` 포맷 차이를 prefix 로 해소.

    Neo4j 그래프 노드 id 는 `{lawId}_{jo4}{gaji2}`(6자리 suffix)인데, PG/Qdrant
    `article_key` 는 끝에 1자리 더(`...1`) 붙은 7자리다(2026-06-18 라이브 검증, 1:1).
    `article_key LIKE '{key}%'` 로 정준(canonical) 키를 찾는다. 이미 정준 키면
    자기 자신에 매칭되므로 양쪽 포맷 모두 안전.

    반환: `{입력 key: 정준 article_key}` (미발견 키는 생략).
    """
    keys = [k for k in (keys or []) if k]
    if not keys:
        return {}
    pool = _get_pool()
    if pool is None:
        return {}
    types = target_types or [
        "law", "admrul", "ordin", "treaty",
        "prec", "expc", "decc", "detc",
    ]
    patterns = [k + "%" for k in keys]
    union = "\nUNION ALL\n".join(
        f"SELECT article_key FROM {t}_articles WHERE article_key LIKE ANY(%s)"
        for t in types
    )
    found: list[str] = []
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(union, [patterns] * len(types))
                found = [dict(r).get("article_key") for r in cur.fetchall()]
    except Exception as e:
        _log.warning("PG resolve_article_keys failed: %s", e)
        return {}

    out: dict[str, str] = {}
    for k in keys:
        cand = [f for f in found if f and f.startswith(k)]
        if cand:
            # 1:1 검증됨 — 다중이면 가장 짧은(=조 단위) 것 채택.
            out[k] = min(cand, key=len)
    return out


def resolve_article_by_name(
    law_title: str,
    article_num: str,
    *,
    target_types: tuple[str, ...] = ("law", "admrul", "ordin"),
) -> Optional[dict]:
    """법령명 + article_num("제25조") → article_key (Tier-0 결정형 조회).

    제목 정확 매칭. 법령명 후보 앞에 잡소리("다음", "관련" 등)가 붙었을 수 있어
    leading token 을 하나씩 떼며 재시도(가장 구체적인 매칭 우선). law→admrul→ordin
    순. 미발견 None.
    """
    pool = _get_pool()
    if pool is None or not law_title or not article_num:
        return None
    toks = law_title.split()
    candidates = [" ".join(toks[i:]) for i in range(len(toks)) if toks[i:]]
    for cand in candidates:
        for t in target_types:
            try:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""SELECT a.article_key
                                FROM {t}_articles a
                                JOIN {t}_metadata m ON a.law_id = m.law_id
                                WHERE m.title = %s AND a.article_num = %s
                                LIMIT 1""",
                            (cand, article_num),
                        )
                        row = cur.fetchone()
                if row:
                    return {
                        "article_key": dict(row)["article_key"],
                        "target_type": t,
                        "law_title": cand,
                    }
            except Exception as e:  # noqa: BLE001 — 테이블/컬럼 차이는 다음 후보로
                _log.debug("resolve_article_by_name %s/%s 실패: %s", t, cand, e)
                continue
    return None


def fetch_article_titles(
    article_keys: list[str],
    *,
    target_types: tuple[str, ...] = ("law", "admrul", "ordin"),
) -> dict[str, Optional[str]]:
    """article_key → article_title 경량 배치 조회 (full_text 미포함).

    /law/{id}/articles 목록용 — Neo4j Article.title 은 법령명이라 조문 제목은
    PG 에서 가져와야 한다.
    """
    keys = [k for k in (article_keys or []) if k]
    if not keys:
        return {}
    pool = _get_pool()
    if pool is None:
        return {}
    union = "\nUNION ALL\n".join(
        f"SELECT article_key, article_title FROM {t}_articles "
        "WHERE article_key = ANY(%s)"
        for t in target_types
    )
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(union, [keys] * len(target_types))
                return {
                    dict(r)["article_key"]: dict(r).get("article_title")
                    for r in cur.fetchall()
                }
    except Exception as e:
        _log.warning("PG fetch_article_titles 실패: %s", e)
        return {}


# ---------------------------------------------------------------------------
# 별표·서식 (attachment) — PG 가 정본. Neo4j 는 Attachment 노드가 적재돼 있지
# 않아(2026-07-10 라이브 확인: 0건) /annex 계열이 전부 miss 였다.
# ---------------------------------------------------------------------------

#: article_key 의 attachment 세그먼트 — `{law_id}_{NNNN}{BB}{E|F}_attachment`
#: NNNN=번호(zero-pad 4), BB=가지(2), E=별표 / F=서식.
#: 예: 009740_000100E_attachment = 의료기기법 시행규칙 별표 1.
import re as _re

_ANNEX_SEG_RE = _re.compile(r"^(\d{4})(\d{2})([EF])$")


def parse_annex_segment(article_key: str) -> Optional[tuple[int, int, str]]:
    """attachment article_key → (번호, 가지, 종류). 미해석 None.

    예: "009740_000100E_attachment" → (1, 0, "별표")
        "009740_001902E_attachment" → (19, 2, "별표")  # 별표 19의2
    """
    parts = (article_key or "").split("_")
    if len(parts) < 3 or parts[-1] != "attachment":
        return None
    m = _ANNEX_SEG_RE.match(parts[-2])
    if not m:
        return None
    kind = "별표" if m.group(3) == "E" else "서식"
    return int(m.group(1)), int(m.group(2)), kind


def parse_annex_num(annex_num: str) -> Optional[tuple[int, int]]:
    """표시형 별표 번호 → (번호, 가지). "19"→(19,0), "19의2"→(19,2). 미해석 None."""
    m = _re.match(r"^\s*(\d+)\s*(?:의\s*(\d+))?\s*$", str(annex_num or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def list_attachments_pg(law_id: str) -> list[dict]:
    """법령의 별표·서식 목록 — law/admrul articles 테이블의 `*_attachment` rows.

    반환: [{attachment_key, title, type("별표"|"서식"), annex_num("19"|"19의2")}]
    """
    pool = _get_pool()
    if pool is None or not law_id:
        return []
    pattern = f"{law_id}\\_%\\_attachment"
    union = "\nUNION ALL\n".join(
        f"SELECT article_key, article_title FROM {t}_articles "
        "WHERE article_key LIKE %s ESCAPE '\\'"
        for t in ("law", "admrul")
    )
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(union, [pattern, pattern])
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        _log.warning("PG list_attachments_pg 실패: %s", e)
        return []
    out = []
    for r in sorted(rows, key=lambda x: x.get("article_key") or ""):
        seg = parse_annex_segment(r.get("article_key") or "")
        num, branch, kind = seg if seg else (None, None, None)
        display = None
        if num is not None:
            display = f"{num}의{branch}" if branch else str(num)
        out.append({
            "attachment_key": r.get("article_key"),
            "title": r.get("article_title"),
            # 키 미해석(일련번호형 등)이면 None — "별표"로 단정하면 오표기.
            "type": kind,
            "annex_num": display,
        })
    return out


def fetch_attachment_pg(
    law_id: str, annex_num: str, *, kind: Optional[str] = None,
) -> Optional[dict]:
    """법령 ID + 별표 번호("19"·"19의2") → 별표 본문 (PG full_text).

    kind("별표"|"서식") 지정 시 해당 종류만 조회 — 별표1·서식1처럼 같은 번호가
    공존하는 법령에서 서식이 별표에 가려지는 것 방지. 미지정 시 별표 우선.
    """
    parsed = parse_annex_num(annex_num)
    if not parsed:
        return None
    n, b = parsed
    pool = _get_pool()
    if pool is None or not law_id:
        return None
    kind_chars: tuple[str, ...]
    if kind == "별표":
        kind_chars = ("E",)
    elif kind == "서식":
        kind_chars = ("F",)
    else:
        kind_chars = ("E", "F")
    for kind_char in kind_chars:
        key = f"{law_id}_{n:04d}{b:02d}{kind_char}_attachment"
        union = "\nUNION ALL\n".join(
            f"SELECT article_key, article_title, full_text FROM {t}_articles "
            "WHERE article_key = %s"
            for t in ("law", "admrul")
        )
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(union, [key, key])
                    row = cur.fetchone()
        except Exception as e:
            _log.warning("PG fetch_attachment_pg 실패: %s", e)
            return None
        if row:
            r = dict(row)
            return {
                "attachment_key": r.get("article_key"),
                "title": r.get("article_title"),
                "type": "별표" if kind_char == "E" else "서식",
                "content": _strip_html_artifacts(r.get("full_text") or ""),
                "link": None,  # PG 에는 law.go.kr 다운로드 링크 없음
            }
    return None


def _parse_department(raw):
    """openlaw-etl `m.department`가 Python dict repr 문자열로 박혀있는 케이스 정리.

    예: "{'content': '식품의약품안전처', '소관부처코드': '1471000'}" → "식품의약품안전처"
    이미 깨끗한 string이면 그대로 반환.
    """
    if not raw:
        return raw
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    if not s.startswith("{"):
        return s
    try:
        import ast
        d = ast.literal_eval(s)
        if isinstance(d, dict):
            # MOLEG API 컨벤션 — content 필드가 부서명
            return d.get("content") or d.get("name") or s
    except Exception:
        pass
    return s


def _strip_html_artifacts(text: str) -> str:
    """openlaw-etl 본문에 잔존하는 단순 HTML 태그·엔티티 정리.

    판례의 `<br/>` 같은 줄바꿈 태그를 실제 개행으로. 다른 태그는 그대로 두거나
    필요 시 확장. 비-HTML 콘텐츠엔 영향 0.
    """
    import re
    # <br>, <br/>, <br /> → 개행
    text = re.sub(r"<br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    # 흔한 HTML 엔티티 디코드 (보수적으로)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"')
    return text


def fetch_amendment_status(law_ids: list[str]) -> dict[str, str]:
    """law_id → api_status(current/repealed/pending 등) — ETL lawdangle enrich 의
    `law_amendment_status`(openlaw PG) 조회. 미판정(NULL)·미존재는 결과에서 제외.
    PG 비활성/테이블 미존재 시 빈 dict(비차단)."""
    ids = [str(x) for x in law_ids if x]
    if not ids:
        return {}
    pool = _get_pool()
    if pool is None:
        return {}
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT law_id, api_status FROM law_amendment_status "
                "WHERE law_id = ANY(%s) AND api_status IS NOT NULL",
                (ids,),
            )
            return {str(r["law_id"]): str(r["api_status"]) for r in cur.fetchall()}
    except Exception:  # noqa: BLE001 — enrich 미배포 등, 조용히 빈 결과
        return {}
