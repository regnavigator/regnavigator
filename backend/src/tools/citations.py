"""Citation 추출·합성 — web(Tavily) + RAG(Qdrant openlaw-etl/legacy).

`src/tools/search.py` 에서 분리. 검색 코어(run_tavily/run_qdrant)는 search.py 에
남고, 결과 payload → frontend Citation dict 변환·외부 링크 합성·표시 제목 조립은
이 모듈이 담당한다. 모든 함수는 payload/dict 만 입력받는 순수 변환 — 검색
상태나 stream writer 에 의존하지 않는다.

spec: 02_INTERFACE.md §2.2, 06_SKILLS.md M5a / M5b, front/LAW_GO_KR_LINKS.md,
      BACKEND_REQUESTS.md R2·R4
"""

from __future__ import annotations

from src.schemas import Citation


# ---------------------------------------------------------------------------
# M5a · Web Citation extractor
# ---------------------------------------------------------------------------
def extract_web_citation(result: dict, number: int) -> Citation:
    """Tavily 결과 → Citation. id는 URL 해시로 영속."""
    import hashlib

    url = result.get("url", "")
    cid = "cite_web_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    publisher = _publisher_from_url(url)
    return {
        "id": cid,
        "number": number,
        "source_kind": "web",
        "title": result.get("title") or url,
        "url": url,
        "publisher": publisher,
        "snippet": (result.get("content") or "")[:300],
        "status": "active",
        # R1 — 검증: 신뢰 publisher 화이트리스트(정부·공공기관)에 속하면 True.
        "verified": publisher is not None,
        # R2 — 카테고리 (web는 best-effort URL 추정; 미상이면 undefined로 두고 키 생략)
        **(_doc_category_from_url(url) and {"doc_category": _doc_category_from_url(url)} or {}),
    }


# 도메인 → 한국어 기관명 (1차 단순 매핑, KU1).
# verified=True 의 정의 = 이 표에 있는 publisher.
_PUBLISHER_TABLE = {
    "mfds.go.kr": "식품의약품안전처",
    "law.go.kr": "법제처",
    "moel.go.kr": "고용노동부",
    "mohw.go.kr": "보건복지부",
    "hira.or.kr": "건강보험심사평가원",
    "nifds.go.kr": "식품의약품안전평가원",
    "korea.kr": "대한민국 정책브리핑",
    "scourt.go.kr": "대법원",
    "ccourt.go.kr": "헌법재판소",
}


def _publisher_from_url(url: str) -> str | None:
    for host, name in _PUBLISHER_TABLE.items():
        if host in url:
            return name
    return None


def _doc_category_from_url(url: str) -> str | None:
    """web URL 기반 best-effort 카테고리 추정. 매칭 실패 시 None."""
    if not url:
        return None
    if "law.go.kr" in url:
        # /lsInfoP /lsLinkProc 등 — 대부분 법령
        if "DRY" in url or "admRul" in url:
            return "행정규칙"
        return "법령"
    if "scourt.go.kr" in url:
        return "판례"
    if "ccourt.go.kr" in url:
        return "헌재결정례"
    if "mfds.go.kr" in url or "mohw.go.kr" in url:
        return "행정규칙"
    return None


# ---------------------------------------------------------------------------
# M5b · RAG Citation extractor (06_SKILLS §3 M5b)
# ---------------------------------------------------------------------------
# source_kind(payload) → frontend 13 카테고리 매핑.
# spec: front/LAW_GO_KR_LINKS.md, BACKEND_REQUESTS.md R2.
_DOC_CATEGORY_BY_SOURCE_KIND = {
    "law": "법령",
    "rule": "법령",            # 시행규칙 — 법령 하위로 분류
    "decree": "법령",          # 시행령
    "notice": "행정규칙",
    "guideline": "행정규칙",
    "case": "판례",
    "constitutional": "헌재결정례",
    "interpretation": "법령해석례",
    "annex": "법령별표서식",
    "treaty": "조약",
    "ordinance": "자치법규",
    "school_rule": "학칙공단",
}

# openlaw-etl target_type → 4 KB / 13 카테고리 매핑 (BACKEND_REQUESTS R2).
# 13개 모든 분야:
#   법령 / 영문법령 / 행정규칙 / 자치법규 / 학칙공단 / 조약 /
#   판례 / 헌재결정례 / 법령해석례 / 행정심판례 /
#   법령별표서식 / 행정규칙별표서식 / 자치법규별표서식
#
# openlaw-etl는 5개 카테고리만 인덱싱 (law/admrul/prec/expc/ordin).
# 별표·서식은 chunk_type=attachment + attachment_subtype 메타로 분기.
# spec: openlaw-etl V2_DATA_ARCHITECTURE §🎯Qdrant payload, RETRIEVAL_GUIDE §2.1
_OPENLAW_CATEGORY_BY_TARGET_TYPE = {
    "law": "법령",          # 법률·시행령·시행규칙 (단일 테이블)
    "admrul": "행정규칙",   # 고시·훈령·예규
    "ordin": "자치법규",
    "treaty": "조약",
    "prec": "판례",
    "expc": "법령해석례",
    "decc": "헌재결정례",   # 헌법재판소 결정례
    "detc": "행정심판례",   # 행정심판 재결례
    "guide": "가이드라인",  # 식약처 가이드라인·안내서 (docs_kure_v1, 2026-07-24)
}


#: doc_category(한글) → target_type. 위 표의 **역방향**(+ 별표서식 확장).
#:
#: ⚠️ 손으로 적지 말 것. 2026-09-10 응집도 점검에서, `coverage.py` 가 이 표를
#: 손으로 복제해 두고 있다가 `조약`·`헌재결정례`·`행정심판례`·`가이드라인` 4종이
#: 빠진 채 드리프트한 것이 발견됐다. `covered_kinds()` 는 매핑 실패를 조용히
#: 건너뛰므로(`if k:`), 가이드라인으로만 근거를 댄 턴이 "커버리지 0" 으로 집계돼
#: 불필요한 추가 검색을 유발했다. 파생으로 바꿔 드리프트 자체를 없앤다.
KIND_BY_DOC_CATEGORY: dict[str, str] = {
    **{v: k for k, v in _OPENLAW_CATEGORY_BY_TARGET_TYPE.items()},
    # 별표·서식은 모법령 계열로 집계한다(검색 종별에는 없는 표시용 분류).
    "법령별표서식": "law",
    "행정규칙별표서식": "admrul",
    "자치법규별표서식": "ordin",
}


# target_type → law.go.kr URL category. None 이면 외부 링크 합성 불가.
_LAW_GO_KR_PATH_BY_TARGET_TYPE = {
    "law": "법령",
    "admrul": "행정규칙",
    "ordin": "자치법규",
    "treaty": "조약",
    "prec": "판례",
    "expc": "법령해석례",
    "decc": "위원회결정문",
    "detc": "헌재결정례",
}


def _extract_annex_num(article_title: str | None, article_key: str | None) -> str | None:
    """별표 N 추출. article_title 우선, article_key fallback.

    예:
      article_title="별표 7"          → "7"
      article_title="[별표 12] 표지"  → "12"
      article_key="006364_byl_001_attachment" → "1" (leading zero strip)
    """
    import re

    if article_title:
        m = re.search(r"별표\s*제?\s*(\d+)", article_title)
        if m:
            return m.group(1)
    if article_key:
        m = re.search(r"_byl_(\d+)_attachment", article_key)
        if m:
            return str(int(m.group(1)))
    return None


def _external_url_for_citation(payload: dict, pg_meta: dict) -> str | None:
    """citation 에 박을 law.go.kr 외부 링크.

    정책(2026-05-22 정정):
      - 조 단위 path-article(`/{cat}/{명}/제N조`): 법령·행정규칙·자치법규 모두
        지원 — law.go.kr 친화 URL이 조 path 를 받음(/행정규칙/○○규정/제1조 확인).
      - 별표 path(`/별표/{N}`): *법령만* 지원. 행정규칙·자치법규 별표는 path
        미지원 → 전문 링크. display 라벨은 조·별표 단위 유지.
    """
    from urllib.parse import quote

    tt = payload.get("target_type") or "law"
    cat = _LAW_GO_KR_PATH_BY_TARGET_TYPE.get(tt)
    if not cat:
        return None
    title = (pg_meta.get("law_title") or payload.get("title") or "").strip()
    if not title:
        return None
    enc = quote(title, safe="")

    chunk_type = payload.get("chunk_type") or "article"
    # 별표/서식 — 법령만 /별표/{N} 딥링크. admrul/ordin 별표는 path 미지원 → 전문.
    if chunk_type == "attachment":
        if tt == "law":
            article_title = pg_meta.get("article_title") or payload.get("article_title") or ""
            article_key = payload.get("article_key") or ""
            n = _extract_annex_num(article_title, article_key)
            if n:
                return f"https://www.law.go.kr/{cat}/{enc}/별표/{quote(n, safe='')}"
            return f"https://www.law.go.kr/{cat}/{enc}/별표"
        return f"https://www.law.go.kr/{cat}/{enc}"  # admrul/ordin 별표 → 전문

    # 조문 path-article — 법령·행정규칙·자치법규 모두 친화 URL이 조 path 지원.
    if tt in ("law", "admrul", "ordin"):
        article_num = (pg_meta.get("article_num") or payload.get("article_num") or "").strip()
        if article_num and article_num != "별표":
            return f"https://www.law.go.kr/{cat}/{enc}/{quote(article_num, safe='')}"
    return f"https://www.law.go.kr/{cat}/{enc}"


def _download_url_for_attachment(payload: dict, pg_meta: dict) -> str | None:
    """별표/서식 HWP 다운로드 URL → 절대 URL.

    best-effort. 미발견·예외 시 None (citation 만들기엔 영향 X).

    1순위는 **검색 히트가 실어 준 `attachment_link`**(2026-08-26, ETL f247e53).
    이미 손에 있는 값이라 추가 조회가 없고, 청크 단위라 더 정확하다.
    ETL 실측: law.go.kr 수확분 44,907청크는 100% 보유, HIRA 게시판 13,126청크는
    0% — 원본이 로컬 크롤 아카이브라 가리킬 공개 URL 자체가 없다(미완성 아님).
    그래서 없을 때의 Neo4j 조회 경로를 그대로 남겨 둔다.
    """
    link: str | None = None

    # 0순위 — 검색 히트 동봉 링크(추가 조회 0).
    raw_link = str(payload.get("attachment_link") or "").strip()
    if raw_link:
        link = raw_link

    # 1순위 — article_key(= Neo4j Attachment.id) 정확 매칭. 번호 환산 불필요.
    article_key = payload.get("article_key")
    if link:
        article_key = None  # 이미 확보 — Neo4j 왕복 생략
    if article_key:
        try:
            from src.retrieval.neo4j_client import fetch_attachment_by_key

            att = fetch_attachment_by_key(str(article_key))
            if att:
                link = att.get("link")
        except Exception:
            link = None

    # fallback — legacy(article_key 없음) 또는 1순위 미스: law_id + 별표번호 fuzzy.
    if not link:
        law_id = payload.get("law_id") or pg_meta.get("law_id") or payload.get("mst_id")
        n = _extract_annex_num(
            pg_meta.get("article_title") or payload.get("article_title") or "",
            payload.get("article_key") or "",
        )
        if law_id and n:
            try:
                from src.retrieval.neo4j_client import fetch_attachment

                att = fetch_attachment(str(law_id), n)
                if att:
                    link = att.get("link")
            except Exception:
                link = None

    if not link:
        return None
    if link.startswith("http://") or link.startswith("https://"):
        return link
    return f"https://www.law.go.kr{link}"


def _refine_category_with_chunk(target_type: str, chunk_type: str | None,
                                attachment_subtype: str | None) -> str | None:
    """target_type + chunk_type/attachment_subtype 조합으로 더 좁은 카테고리 추정.

    예:
      target_type=law, chunk_type=attachment, attachment_subtype=별표 → 법령별표서식
      target_type=admrul, chunk_type=attachment → 행정규칙별표서식
      target_type=ordin, chunk_type=attachment → 자치법규별표서식
    """
    base = _OPENLAW_CATEGORY_BY_TARGET_TYPE.get(target_type)
    if not base:
        return None
    if chunk_type == "attachment" or attachment_subtype:
        if target_type == "law":
            return "법령별표서식"
        if target_type == "admrul":
            return "행정규칙별표서식"
        if target_type == "ordin":
            return "자치법규별표서식"
    return base
_OPENLAW_SOURCE_KIND_BY_TARGET_TYPE = {
    "law": "doc",
    "admrul": "doc",
    "prec": "doc",
    "expc": "doc",
    "ordin": "doc",
}


# 판례 title → 법원·심급 추출 (R4)
_COURT_PATTERNS = [
    ("대법원",       3),
    ("헌법재판소",   3),  # 단심 — 편의상 3
    ("고등법원",     2),
    ("특허법원",     2),
    ("행정법원",     1),
    ("지방법원",     1),
    ("가정법원",     1),
    ("회생법원",     1),
]


def _court_and_instance(title: str | None) -> tuple[str | None, int | None]:
    if not title:
        return None, None
    for keyword, instance in _COURT_PATTERNS:
        if keyword in title:
            return keyword, instance
    return None, None


def extract_rag_citation(point, number: int, pg_meta: dict | None = None) -> Citation:
    """Qdrant ScoredPoint → Citation.

    Payload 두 가지 스키마 지원:
      A. openlaw-etl (현재): article_key, target_type, chunk_type, law_id, mst_id,
                              article_num, title, full_text, is_current, status, ...
      B. legacy medi-back: chunk_id, source_kind, title, publisher, doc_id, article, ...

    pg_meta: openlaw-etl PG fetch 결과 (`{article_key: row}` 의 한 row). title·법령명·
    부서·시행일 등 사용자 향 메타 보강. None이면 Qdrant payload만 사용.
    """
    p = point.payload if hasattr(point, "payload") else point

    # === openlaw-etl 스키마 우선 (article_key 존재로 판별) ===
    article_key = p.get("article_key")
    target_type = p.get("target_type")
    if article_key and target_type in _OPENLAW_CATEGORY_BY_TARGET_TYPE:
        return _build_openlaw_citation(p, number, pg_meta or {})

    # === legacy medi-back 스키마 (fallback) ===
    revoked = p.get("revoked_at")
    pending = p.get("amended_pending_until")
    status = "revoked" if revoked else ("amended_pending" if pending else "active")

    source_kind = p.get("source_kind") or "doc"
    title = p.get("title", "")
    chunk_id = p.get("chunk_id") or article_key or "unknown"
    out: dict = {
        "id": f"cite_doc_{chunk_id}",
        "number": number,
        "source_kind": "doc",
        "title": title,
        "publisher": p.get("publisher"),
        "date": p.get("amended_at") or p.get("published_at"),
        "doc_id": p.get("doc_id"),
        "article": p.get("article"),
        "page": p.get("page"),
        "snippet": (p.get("text") or "")[:300],
        "status": status,
        # R1 — RAG는 큐레이션된 코퍼스에서 왔으므로 기본 verified=True (status가 revoked면 별개 표시).
        "verified": True,
    }
    # R2 — 카테고리 (있을 때만 키 추가)
    cat = _DOC_CATEGORY_BY_SOURCE_KIND.get(source_kind)
    if cat:
        out["doc_category"] = cat
    # R4 — 판례면 법원·심급 추출
    if source_kind in ("case", "constitutional"):
        court, instance = _court_and_instance(title)
        if court:
            out["court"] = court
        if instance:
            out["instance"] = instance
    return out


def _build_openlaw_citation(payload: dict, number: int, pg_meta: dict) -> Citation:
    """openlaw-etl payload + (옵션) PG metadata → Citation.

    target_type별 데이터 형식 차이 (V2_ETL_CHALLENGES §5):
      - 조문형 (law·admrul·ordin·treaty): article_num="제N조", article_title="조항 제목"
      - 문서형 (prec·expc·decc·detc): article_num="본문", article_title="사건/해석/결정/재결명"
      - 별표 (chunk_type=attachment): article_num="별표"/"서식", article_title="별표 제목"
    """
    article_key = payload["article_key"]
    target_type = payload.get("target_type") or "law"
    chunk_type = payload.get("chunk_type") or "article"
    is_current = payload.get("is_current", True)
    raw_status = payload.get("status") or "active"

    # status — is_current=False면 revoked, payload.status가 따로 있으면 그것 사용
    if not is_current:
        status = "revoked"
    elif raw_status in ("active", "revoked", "amended_pending"):
        status = raw_status
    else:
        status = "active"

    # 우선순위: PG metadata > payload (PG가 풍부)
    article_title = (
        pg_meta.get("article_title")
        or payload.get("article_title")
        or ""
    )
    law_title = pg_meta.get("law_title") or payload.get("title") or ""
    article_num = pg_meta.get("article_num") or payload.get("article_num") or ""

    display_title = _compose_citation_title(
        target_type=target_type,
        chunk_type=chunk_type,
        law_title=law_title,
        article_num=article_num,
        article_title=article_title,
        article_key=article_key,
    )

    # 본문은 Mongo가 풍부 (PG는 index, Mongo가 body) — citation snippet 보강
    full_text = pg_meta.get("full_text") or payload.get("full_text") or ""
    if (not full_text or len(full_text) < 200) and chunk_type == "article":
        try:
            from src.retrieval.mongo_client import fetch_body

            mst = pg_meta.get("mst_id") or payload.get("mst_id") or pg_meta.get("law_id")
            if mst and target_type:
                mongo_body = fetch_body(
                    target_type=target_type,
                    mst_id=str(mst),
                    article_num=article_num or None,
                    law_title=law_title or None,
                )
                if mongo_body and len(mongo_body) > len(full_text):
                    full_text = mongo_body
        except Exception:
            pass

    # snippet도 frontend 명세대로 정규화 — 항 번호 줄바꿈·헤더 dedup 등.
    snippet_text = ""
    if full_text:
        from src.text.normalize import normalize_law_text

        normalized = normalize_law_text(
            full_text,
            law_title=law_title,
            article_num=article_num,
            article_title=article_title,
            strip_leading_header=True,
        )
        snippet_text = normalized[:300]

    enforce_date = pg_meta.get("enforce_date")
    publisher = pg_meta.get("department") or _publisher_from_target_type(target_type)

    out: dict = {
        "id": f"cite_doc_{article_key}",
        "number": number,
        "source_kind": "doc",
        "title": display_title,
        "publisher": publisher,
        "date": str(enforce_date) if enforce_date else None,
        "doc_id": payload.get("law_id") or payload.get("mst_id"),
        "article": article_num or None,
        "snippet": snippet_text,
        "status": status,
        "verified": True,  # 큐레이션된 openlaw-etl 코퍼스 — 기본 True
    }
    # doc_category — chunk_type=attachment 시 별표서식 카테고리로 분기
    cat = _refine_category_with_chunk(
        target_type,
        payload.get("chunk_type"),
        payload.get("attachment_subtype"),
    )
    if cat:
        out["doc_category"] = cat
    # attachment_subtype — "별표" / "서식" / "서식별표" (2026-10-01).
    #
    # doc_category 는 `법령별표서식` 하나로 별표와 서식을 뭉뚱그린다. FE 는 그래서
    # 제목에 "서식" 이라는 글자가 있는지로 둘을 갈랐는데, `공중위생관리법 시행규칙
    # 별표: 영업신고서` 처럼 **서식인데 제목에 '별표'만 있는** 경우가 흔해
    # 기입 버튼이 뜨지 않았다(실사용 신고). 검색 API 가 이미 정확히 알려주는
    # 값을 버리고 추측하던 것 — 그 값을 그대로 넘긴다.
    sub = (payload.get("attachment_subtype") or "").strip()
    if sub:
        out["attachment_subtype"] = sub
    # url — law.go.kr 외부 링크. 별표/서식은 /별표/N 경로로 박힘. frontend
    # lawLink.ts:deriveExternalUrl 가 citation.url 최우선 사용.
    ext_url = _external_url_for_citation(payload, pg_meta)
    if ext_url:
        out["url"] = ext_url
    # download_url — 별표/서식 HWP 다운로드 (Neo4j Attachment.link). best-effort.
    if payload.get("chunk_type") == "attachment":
        dl = _download_url_for_attachment(payload, pg_meta)
        if dl:
            out["download_url"] = dl
    # 판례면 R4 — 법원·심급
    if target_type == "prec":
        court, instance = _court_and_instance(display_title)
        if court:
            out["court"] = court
        if instance:
            out["instance"] = instance
    return out


def build_citation_from_api_hit(hit: dict, number: int) -> Citation:
    """openlaw-etl `/search` API hit → Citation.

    서버가 랭킹·메타·정본 URL·별표 링크를 모두 제공하므로 PG/Mongo/Neo4j 조회
    없이 hit 필드만으로 구성한다. 인용 원문(grounding)은 별도 `/articles/bodies`.

    hit 필드: article_key·law_id·mst_id·law_title·article_num·article_title·
    target_type·chunk_type·attachment_subtype·attachment_link·article_url·
    enforcement_date·is_current·department·snippet …
    """
    article_key = hit.get("article_key") or "unknown"
    target_type = hit.get("target_type") or "law"
    chunk_type = hit.get("chunk_type") or "article"
    is_current = hit.get("is_current", True)

    # status — law.go.kr 개정상태(amend_status, ETL lawdangle enrich)가 있으면 우선:
    #   repealed(폐지)→revoked · renamed(개명/이관)→amended_pending ·
    #   pending(시행예정: 공포·시행일 미도래)→amended_pending · current→active.
    # 없거나 unknown 이면 기존 계약(is_current) 폴백 — enrich 미배포/미실행에도 안전.
    # ⚠️ pending 을 폴백에 흘리면 안 됨: 시행예정 법령은 is_current 가 null 이라
    #    revoked(폐지)로 오표기된다 — lawdangle 0.3.1 이 잡은 오판과 동일 사고.
    _amend = (hit.get("amend_status") or "").lower()
    _eff = (hit.get("effective_status") or "").strip()
    _enforced = hit.get("enforced")
    if _amend == "repealed":
        status = "revoked"
    elif _amend in ("renamed", "pending"):
        status = "amended_pending"
    elif _amend == "current":
        status = "active"
    elif _eff == "미시행" or _enforced is False:
        # 공포됐으나 시행일 미도래 — is_current 폴백에 맡기면 '폐지'로 오표기된다.
        status = "amended_pending"
    elif _eff == "구법":
        status = "revoked"
    elif _eff == "시행중":
        status = "active"
    else:
        status = "active" if is_current else "revoked"

    law_title = hit.get("law_title") or ""
    article_num = hit.get("article_num") or ""
    article_title = hit.get("article_title") or ""

    display_title = _compose_citation_title(
        target_type=target_type,
        chunk_type=chunk_type,
        law_title=law_title,
        article_num=article_num,
        article_title=article_title,
        article_key=article_key,
    )

    # snippet — 서버 snippet(헤더 중복 있을 수 있음)을 FE 명세대로 정규화.
    snippet_text = ""
    raw_snip = hit.get("snippet") or ""
    if raw_snip:
        from src.text.normalize import normalize_law_text

        snippet_text = normalize_law_text(
            raw_snip,
            law_title=law_title,
            article_num=article_num,
            article_title=article_title,
            strip_leading_header=True,
        )[:300]

    enforce_date = hit.get("enforcement_date")
    publisher = hit.get("department") or _publisher_from_target_type(target_type)

    out: dict = {
        "id": f"cite_doc_{article_key}",
        "number": number,
        "source_kind": "doc",
        "title": display_title,
        "publisher": publisher,
        "date": str(enforce_date) if enforce_date else None,
        "doc_id": hit.get("law_id") or hit.get("mst_id"),
        "article": article_num or None,
        "snippet": snippet_text,
        "status": status,
        "verified": True,  # 큐레이션된 openlaw-etl 코퍼스 — 기본 True
    }
    # 시행 상태 원본 라벨 — FE 가 '시행 예정(N월 시행)' 처럼 정확히 표기하도록.
    if _eff:
        out["effective_status"] = _eff
    if _enforced is not None:
        out["enforced"] = bool(_enforced)
    # 버전 축(ETL RFC R3) — 현행본과 짝지어 온 개정 예정본 식별.
    _vs = hit.get("version_status")
    if _vs:
        out["version_status"] = str(_vs)
    if hit.get("supersedes_article_key"):
        out["supersedes_article_key"] = str(hit["supersedes_article_key"])
    cat = _refine_category_with_chunk(
        target_type, chunk_type, hit.get("attachment_subtype")
    )
    if cat:
        out["doc_category"] = cat
    # attachment_subtype — "별표" / "서식" (2026-10-01). 위 `_build_openlaw_citation`
    # 과 같은 이유: doc_category(`법령별표서식`)만으로는 별표와 서식을 못 가른다.
    _sub = (hit.get("attachment_subtype") or "").strip()
    if _sub:
        out["attachment_subtype"] = _sub
    # url — 서버가 조합한 law.go.kr 정본 링크. http(s) 만 통과 — guide 의
    # source_url 이 인제스트 머신 로컬 경로로 오는 케이스(실측 2026-07-24) 차단
    # (깨진 링크 + 내부 경로 노출 방지).
    _u = hit.get("article_url") or ""
    if _u.startswith(("http://", "https://")):
        out["url"] = _u
    # download_url — 별표/서식 HWP (서버가 준 절대 URL).
    if chunk_type == "attachment" and hit.get("attachment_link"):
        out["download_url"] = hit["attachment_link"]
    # 판례면 R4 — 법원·심급
    if target_type == "prec":
        court, instance = _court_and_instance(display_title)
        if court:
            out["court"] = court
        if instance:
            out["instance"] = instance
    return out


def _compose_citation_title(
    *,
    target_type: str,
    chunk_type: str,
    law_title: str,
    article_num: str,
    article_title: str,
    article_key: str,
) -> str:
    """Citation 표시 title — target_type/chunk_type별 적절 조합.

    조문형: "{law_title} {article_num}"     예: "의료기기법 제25조"
    문서형: "{article_title}"                예: "성년후견인변경"
    별표:   "{law_title} {article_num}: {article_title}"
                                            예: "의료기기법 시행규칙 별표: 등급분류"
    """
    DOC_TYPES = {"prec", "expc", "decc", "detc"}

    # 가이드라인 — "{문서명} — {섹션(breadcrumb)}" (조문형 조합은 장황해짐)
    if target_type == "guide":
        head = law_title or article_key
        sect = article_title or article_num
        return f"{head} — {sect}" if sect and sect not in head else head

    # 별표/서식 (chunk_type=attachment) — 우선 분기
    if chunk_type == "attachment":
        parts = [p for p in [law_title, article_num] if p]
        head = " ".join(parts)
        if article_title and article_title not in head:
            return f"{head}: {article_title}".strip()
        return head or article_title or article_key

    # 문서형 — article_num="본문" 무시, article_title이 곧 사건·해석·결정·재결명
    if target_type in DOC_TYPES:
        return article_title or law_title or article_key

    # 조문형 — 법령명 + 조항번호
    if law_title and article_num:
        return f"{law_title} {article_num}"
    if article_title:
        return article_title
    return law_title or article_key


def _publisher_from_target_type(target_type: str) -> str | None:
    """PG metadata 미수신 시 target_type 기반 fallback publisher."""
    return {
        "law": "법제처",
        "admrul": "관할 부처",
        "ordin": "지방자치단체",
        "treaty": "외교부",
        "prec": "대법원",
        "expc": "법제처",
        "decc": "헌법재판소",
        "detc": "중앙행정심판위원회",
        "guide": "식품의약품안전처",
    }.get(target_type)


def pick_form_citation(citations: list[dict]) -> dict | None:
    """인용 목록에서 **서식 원본 파일**을 가진 인용 1건 — 서식(F) > 별표(E).

    인용 스키마(article_key·doc_category·download_url)를 해석하는 책임은
    이 모듈(인용 소유자)에 있다. 기입 엔진(`src.form_fill`)은 여기서 고른
    `download_url` 만 받아 동작한다 — 그래야 엔진을 그대로 떼어낼 수 있다
    (2026-08-25 분리).

    선별 기준: 첨부(별표·서식) 인용이면서 HWP 직링크(`flDownload` 또는
    .hwp/.hwpx)를 보유. 같은 조건이면 서식(`…F_attachment`)을 먼저 — 제출용
    양식은 별표가 아니라 서식이다.
    """
    import re

    def _rank(c: dict) -> int:
        key = str(c.get("article_key") or c.get("id") or "")
        if re.search(r"\d{2}F_attachment", key):
            return 0
        if re.search(r"\d{2}E_attachment", key):
            return 1
        return 2

    cands: list[dict] = []
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        url = str(c.get("download_url") or "")
        cat = str(c.get("doc_category") or "")
        key = str(c.get("article_key") or c.get("id") or "")
        is_attach = cat.endswith("별표서식") or key.endswith("_attachment")
        if is_attach and ("flDownload" in url or url.endswith((".hwp", ".hwpx"))):
            cands.append(c)
    if not cands:
        return None
    return sorted(cands, key=_rank)[0]
