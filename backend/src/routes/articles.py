"""법령 원문 endpoint — citation 클릭 → 원문 모달용 (조문·별표·문서형).

- /annex, /annex/list : 별표·서식 (Neo4j Attachment + Mongo raw 보조)
- /article            : article_key 1건 본문 + 메타 (PG 8카테고리 + Mongo 본문)
- /law/{lawId}/articles : 법령에 속한 조문 목록 (Neo4j CONTAINS)
"""

from __future__ import annotations

from typing import Optional

import re
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


# ---------------------------------------------------------------------------
# Tier-0 — 자연어 조문 지정 즉답 (LLM 에이전트 루프 없이 결정형 조회)
# ---------------------------------------------------------------------------
@router.get("/article/lookup")
def lookup_article(q: str = Query(..., description="예: 의료기기법 제25조 인용해줘")):
    """자연어 "법령명 제N조" → 조문 원문 즉답(zero-LLM).

    "의료기기법 제25조" 같은 *명시적 조문 지정* 질의를 LLM 없이 PG 직접조회로 해석해
    `/article` 과 동일한 페이로드를 반환한다. 프런트가 조문지정 질의를 감지해 채팅
    대신 호출 → 즉답·저비용. 식별 실패 시 404(프런트가 일반 채팅으로 폴백).
    """
    from src.retrieval.pg_client import resolve_article_by_name
    from src.text.article_query import parse_article_query

    parsed = parse_article_query(q)
    if not parsed:
        raise HTTPException(
            status_code=404,
            detail={"message": "조문을 식별하지 못했습니다", "q": q,
                    "hint": "예: 의료기기법 제25조"},
        )
    law, article_num = parsed
    resolved = resolve_article_by_name(law, article_num)
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail={"message": f"해당 조문을 찾지 못했습니다: {law} {article_num}",
                    "q": q, "parsed": {"law": law, "article_num": article_num}},
        )
    # /article 핸들러 그대로 재사용(본문 fetch·정규화·헤더·external_url 동일).
    # 둘 다 동기 def — FastAPI 가 스레드풀에서 돌린다(2026-08-04 감사 C-3).
    return get_article(resolved["article_key"])


# ---------------------------------------------------------------------------
# R5 — 별표 endpoint (Neo4j Attachment + Mongo raw 보조)
# ---------------------------------------------------------------------------
@router.get("/annex")
def get_annex(
    lawId: str,
    annexNum: str,
    type: Optional[str] = Query(None, description="별표 | 서식 — 같은 번호 공존 시 구분"),
):
    """법령 별표·서식 본문 조회.

    Query:
      - lawId: 법령 ID (예: "006364")
      - annexNum: 별표 번호 (예: "19", "19의2", 또는 정규화된 "byl_001")

    응답:
      {
        "law_id": str,
        "annex_num": str,        # 입력값 그대로
        "attachment_key": str,   # openlaw-etl ID (006364_byl_001_attachment 등)
        "title": str,
        "type": str,             # 별표 / 서식 / ...
        "markdown": str,         # 본문 (Neo4j Attachment.content)
        "source_uri": str | null # 원본 URL (있으면) — 추후 Mongo raw_law fetch
      }

    404: 미발견 (법령 또는 별표 번호 잘못된 경우)
    """
    from src.retrieval.neo4j_client import fetch_attachment_by_key
    from src.retrieval.pg_client import fetch_attachment_pg

    if not lawId or not annexNum:
        raise HTTPException(status_code=422, detail="lawId·annexNum 모두 필요")

    # PG 정본 우선(2026-08-25) — 종전엔 Neo4j 우선이었으나 Attachment 0건이라
    # 실질 서빙은 늘 PG 였다. ETL 이 Attachment 40만 건을 적재하면서 Neo4j
    # `fetch_attachment` 의 CONTAINS 퍼지 매칭이 처음 활성화됐는데, 번호 "1"이
    # 제목·id 부분문자열에 걸려 엉뚱한 첨부를 반환한다(실측: 별표 1 요청에
    # 서식이 반환). 본문은 kind 필터 되는 PG 정본으로 확정하고, Neo4j 는
    # attachment_key **정확 매칭**(by_key)으로 다운로드 링크만 enrich —
    # 고아 노드(Law 관계 없음 16,860건)도 by_key 로 커버된다.
    att = fetch_attachment_pg(lawId, annexNum, kind=type)
    if not att:
        raise HTTPException(
            status_code=404,
            detail=f"별표를 찾을 수 없습니다: lawId={lawId}, annexNum={annexNum}",
        )
    # link는 law.go.kr 상대 path (/LSW/flDownload.do?flSeq=...).
    # 절대 URL로 변환해 frontend가 새 창 다운로드 가능하게.
    link = att.get("link")
    if not link and att.get("attachment_key"):
        try:
            neo = fetch_attachment_by_key(str(att["attachment_key"]))
            link = (neo or {}).get("link")
        except Exception:  # noqa: BLE001 — 링크 enrich 실패가 본문 조회를 막으면 안 됨
            link = None
    download_url = None
    if link:
        if link.startswith("http://") or link.startswith("https://"):
            download_url = link
        else:
            download_url = f"https://www.law.go.kr{link}"

    # 별표 markdown 본문 정규화 — ASCII 박스 표·항 번호 줄바꿈·헤더 중복 제거.
    # 별표 본문은 법령명·별표제목이 본문 시작에 반복되는 경우가 많아 dedup 활성화.
    from src.text.normalize import normalize_law_text

    markdown = normalize_law_text(
        att["content"] or "",
        article_title=att.get("title"),
        strip_leading_header=True,
    )

    return {
        "law_id": lawId,
        "annex_num": annexNum,
        "attachment_key": att["attachment_key"],
        "title": att["title"],
        "type": att["type"],
        "markdown": markdown,
        "download_url": download_url,
        "source_uri": link,
    }


_FILLABLE_CACHE: dict[str, tuple[float, dict]] = {}
_FORM_SIGNALS = (
    r"신청인|신고인|제출인|보고인", r"서명\s*또는\s*인|\(인\)", r"접수번호|접수일", r"처리기간",
    r"년\s+월\s+일", r"귀하", r"[□☐■]", r"생년월일|법인등록번호|사업자등록번호",
)
_FILLABLE_TTL_S = 3600.0


@router.get("/annex/fillable")
def annex_fillable(key: str):
    """별표·서식에 **기입 항목이 있는가**(2026-09-08) — 프런트 [작성] 버튼 노출 판정.

    운영자 지적 "입력 못하는 별표(기준표)에 입력하라는 안내가 없어야". 종전엔 제목의
    '별표/서식' 문자열만 보고 버튼을 냈고, 실제 항목 추출(`form_intake.intake`)은 항목이
    없으면 바닥값 항목을 채워 기준표도 "기입 문서"로 열렸다.

    판정은 `fields_from_text` 만(원본 HWP 라벨은 열 때 별도) — 본문에 기입란이 하나도
    안 잡히면 fillable=False. 본문은 검색 API 전문, 없으면 인용 조립 경로의 발췌.
    결과는 프로세스 캐시(1h). 응답: {key, fillable, field_count, sample[:8]}
    """
    import time as _time

    from src.form_intake import fields_from_text

    key = (key or "").strip()
    if not key or len(key) > 160:
        raise HTTPException(status_code=422, detail="key 필요")
    hit = _FILLABLE_CACHE.get(key)
    now = _time.monotonic()
    if hit and now - hit[0] < _FILLABLE_TTL_S:
        return hit[1]
    text = ""
    try:
        from src.retrieval.search_api_client import fetch_bodies
        text = str(((fetch_bodies([key]) or {}).get(key) or {}).get("full_text") or "")
    except Exception:  # noqa: BLE001 — 전문 실패 시 발췌로
        text = ""
    if not text:
        try:
            from src.report_pipeline import pinned_form_asset
            cites = pinned_form_asset(key) or []
            text = str((cites[0] if cites else {}).get("text") or "")
        except Exception:  # noqa: BLE001
            text = ""
    fields = fields_from_text(text) if text else []
    # 텍스트 파서는 표 셀을 라벨로 느슨하게 잡아 기준표도 "항목"이 나온다 —
    # 서식 고유 신호(신청인·서명 또는 인·접수번호·처리기간·년 월 일·귀하·체크박스)로
    # 한 번 더 거른다. 키 종별이 '서식'이면 그것만으로 인정.
    signals = sum(1 for pat in _FORM_SIGNALS if re.search(pat, text))
    kind = None
    try:
        from src.retrieval.pg_client import parse_annex_segment
        seg = parse_annex_segment(key)
        kind = seg[2] if seg else None
    except Exception:  # noqa: BLE001
        kind = None
    fillable = bool(fields) and (kind == "서식" or signals >= 2)
    out = {"key": key, "fillable": fillable, "field_count": len(fields) if fillable else 0,
           "sample": fields[:8] if fillable else [], "has_text": bool(text),
           "kind": kind, "signals": signals}
    _FILLABLE_CACHE[key] = (now, out)
    return out


@router.get("/annex/view")
def annex_view(key: str):
    """별표·서식 원본 HWP → 문서 뷰어 HTML(2026-09-08, `src/annex_view.py`).

    응답 {key, html, reason} — 프런트가 sandbox iframe srcdoc 에 넣는다. 변환 불가(HWPX·링크
    없음·도구 실패)는 **200 + html null + reason**(2026-09-09; 종전 503 은 브라우저 콘솔에
    "Failed to load resource" 로 남고 프런트는 사유를 못 봤다). 프런트는 원본 링크로 안내.
    """
    import logging

    from src.annex_view import AnnexViewError, view_html

    key = (key or "").strip()
    if not key or len(key) > 160:
        raise HTTPException(status_code=422, detail="key 필요")
    try:
        html = view_html(key)
    except AnnexViewError as e:
        logging.getLogger(__name__).warning("annex/view 불가 key=%s: %s", key, str(e)[:300])
        return {"key": key, "html": None, "reason": str(e)}
    return {"key": key, "html": html, "reason": None}


@router.get("/annex/list")
def list_law_annexes(lawId: str):
    """법령에 속한 별표·서식 목록 — 화면 사이드 패널·선택용.

    응답:
      { "law_id": str, "count": int, "items": [{attachment_key, title, type}] }
    """
    from src.retrieval.neo4j_client import list_attachments
    from src.retrieval.pg_client import list_attachments_pg

    if not lawId:
        raise HTTPException(status_code=422, detail="lawId required")
    # Neo4j 미적재(2026-07-10: Attachment 0건) 시 PG fallback.
    items = list_attachments(lawId) or list_attachments_pg(lawId)
    return {"law_id": lawId, "count": len(items), "items": items}


# ---------------------------------------------------------------------------
# 법령 원문 endpoint — citation 클릭 → 원문 모달용
# ---------------------------------------------------------------------------
def _fetch_body_from_search_api(key: str) -> dict | None:
    """법령 외 문서(가이드라인 등) 본문 — 검색 API `/articles/bodies` 경유.

    openlaw PG 는 법령 8종만 갖고 있다. 가이드라인·안내서는 별도 코퍼스라
    검색 API 만 본문을 안다. 응답 shape 은 `/article` 계약에 맞춘다.

    `external_url` 은 **검색 API 가 준 source_url 이 있을 때만** 채운다 —
    법령정보센터 링크를 지어내지 않는다(2026-08-04 사고: 법령정보센터에 없는
    가이드라인에 그 링크가 붙어 출처 신뢰를 깎았다).
    """
    import logging as _logging

    from src.retrieval import search_api_client as _sc

    _log = _logging.getLogger(__name__)
    try:
        body = (_sc.fetch_bodies([key]) or {}).get(key)
    except Exception as e:  # noqa: BLE001 — 폴백 실패는 404 로 이어진다
        _log.info("/article search-API 폴백 실패 key=%s: %s", key, type(e).__name__)
        return None
    if not body:
        return None
    full_text = (body.get("full_text") or "").strip()
    if not full_text:
        return None
    return {
        "article_key": key,
        "target_type": "guide",
        "law_id": None,
        "law_title": body.get("law_title") or body.get("title") or "",
        "article_num": None,
        "article_title": body.get("breadcrumb") or body.get("title"),
        "full_text": full_text,
        "department": body.get("publisher"),
        "enforce_date": None,
        # 원문 링크는 ETL 이 source_url 을 채워야 생긴다(미채움 시 null).
        "external_url": body.get("source_url") or None,
        "page": body.get("page"),
        "page_end": body.get("page_end"),
    }


@router.get("/article")
def get_article(key: str):
    """article_key 1건의 본문 + 메타 — 사용자가 citation 클릭 시 원문 모달 띄움.

    Query:
      - key: article_key (예: "009705_0001000", "313150_DOC")

    응답:
      {
        "article_key": str,
        "target_type": str,           # law | admrul | ordin | treaty | prec | expc | decc | detc
        "law_id": str | null,
        "law_title": str,             # 법령명
        "article_num": str | null,    # "제25조" 등
        "article_title": str | null,  # 조항 제목 (있으면)
        "full_text": str,             # 본문 (HTML 태그 정리됨)
        "department": str | null,     # 관할 부처
        "enforce_date": str | null,   # 시행일 ISO
        "external_url": str | null,   # law.go.kr deep-link (있으면)
      }

    조회 전략:
      1) PG 8개 카테고리 UNION 쿼리 (조문형 4 + 문서형 4)
      2) 1차 실패 시 카테고리별 1건씩 폴백 (테이블 스키마 차이로 UNION이 통째 깨질 때 대비)
      3) 모두 실패 → 404 + 서버 로그에 키·원인 기록

    article_key 매핑:
      Qdrant payload `article_key` ↔ PG `{target}_articles.article_key` 동일 컬럼.
      포맷: 조문형 `{law_id}_{조문키}` (예: `009740_0004001`),
            문서형 `{doc_id}_DOC` (예: `313150_DOC`),
            별표 `{law_id}_{annex_num}_attachment`.

    404: article_key 미존재 또는 PG fetch 전부 실패
    """
    import logging as _logging

    from src.retrieval.pg_client import _get_pool, fetch_articles

    _log = _logging.getLogger(__name__)

    if not key:
        raise HTTPException(status_code=422, detail="key required")

    diag: dict = {"key": key, "stages": []}

    # 0차: PG pool 자체 진단 — 서버 컨텍스트에서 _get_pool()이 None 반환하는지 확인.
    try:
        _pool = _get_pool()
        diag["pg_pool"] = "ok" if _pool is not None else "none"
    except Exception as e:
        # diag 는 404 응답으로 클라이언트에 나간다 — 예외 문자열(DSN·호스트)은
        # 로그로만, 응답엔 유형명까지만.
        _log.warning("/article pg_pool probe 실패: %s", e)
        diag["pg_pool"] = f"error: {type(e).__name__}"

    # 1차: 8 카테고리 일괄 fetch (조문형 + 문서형 모두). medical filter 끔.
    try:
        rows = fetch_articles(
            [key],
            target_types=[
                "law", "admrul", "ordin", "treaty",
                "prec", "expc", "decc", "detc",
            ],
            medical_filter=False,
        )
        diag["stages"].append({"stage": "union_8", "matched": list(rows.keys())})
    except Exception as e:
        rows = {}
        _log.warning("/article union_8 실패: %s", e)
        diag["stages"].append({"stage": "union_8", "error": type(e).__name__})
    meta = rows.get(key)

    # 2차 폴백: 일괄 쿼리가 어떤 테이블 스키마 차이로 통째 실패한 경우, 카테고리별로 1건씩 시도.
    # (pg_client는 UNION 쿼리 1개라 한 카테고리만 컬럼 누락이어도 전체 빈 dict 반환)
    if not meta:
        for tt in (
            "law", "admrul", "ordin", "treaty",
            "prec", "expc", "decc", "detc",
        ):
            try:
                one = fetch_articles([key], target_types=[tt], medical_filter=False)
                hit = bool(one.get(key))
                diag["stages"].append({"stage": f"per_type:{tt}", "hit": hit})
                if hit:
                    meta = one[key]
                    _log.info(
                        "/article fallback hit on target_type=%s for key=%s", tt, key
                    )
                    break
            except Exception as e:
                diag["stages"].append(
                    {"stage": f"per_type:{tt}", "error": type(e).__name__}
                )
                _log.debug("/article fallback %s failed: %s", tt, e)

    if not meta:
        # 법령이 아닌 문서(가이드라인·안내서 등)는 openlaw PG 에 없다 — 별도
        # 코퍼스(docs_kure_v1)라 검색 API 가 본문을 가진다. 여기서 폴백한다.
        #
        # 왜 필요한가(2026-08-04): 가이드라인 인용에 붙던 법령정보센터 링크를
        # 걷어냈는데(법령정보센터에 없는 문서라 잘못된 링크였다), 그러고 나니
        # **원문 접근 경로가 통째로 사라졌다** — PG 조회는 404 라 프런트가
        # snippet 만 보여주고, 외부 링크도 없는 상태가 됐다. 규제 상담에서
        # 근거 전문을 못 여는 건 치명적이라 앱 안에서 열 수 있게 한다.
        guide_meta = _fetch_body_from_search_api(key)
        if guide_meta:
            diag["stages"].append({"stage": "search_api_bodies", "hit": True})
            _log.info("/article search-API 폴백 적중 key=%s", key)
            return guide_meta
        diag["stages"].append({"stage": "search_api_bodies", "hit": False})

        _log.warning(
            "/article 404 — key=%r, diag=%r. "
            "Check PG connectivity (PG_HOST/PORT/USER/PASS) and that key exists in *_articles tables.",
            key, diag,
        )
        # 404 detail에 진단 dict를 직접 동봉 — frontend·백엔드 협업 디버깅용.
        # 운영에서 노이즈가 되면 LOG_LEVEL=WARNING으로 detail 축약 가능.
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"article을 찾을 수 없습니다: {key}",
                "diag": diag,
            },
        )

    # external_url — law.go.kr 검색 deep-link (target_type별)
    external_url = _build_law_go_kr_url(meta, article_key=key)

    target_type = meta.get("target_type")
    article_num = meta.get("article_num")
    article_title = meta.get("article_title")
    law_title = meta.get("law_title")

    # 사용자 향 display_title — target_type별 적절 조합 (조문형 vs 문서형 vs 별표).
    # 별표는 law_title+article_num 만으로 부족(article_title=별표 실제 제목) →
    # search.py:_compose_citation_title 과 동일 패턴으로 합성.
    DOC_TYPES = {"prec", "expc", "decc", "detc"}
    is_attachment = key.endswith("_attachment") or article_num == "별표"
    if is_attachment:
        head = " ".join(p for p in [law_title, article_num] if p)
        at = (article_title or "").strip()
        if at and at not in head:
            display_title = f"{head}: {at}"
        else:
            display_title = head or at or key
    elif target_type in DOC_TYPES:
        display_title = article_title or law_title or key
    elif law_title and article_num:
        display_title = f"{law_title} {article_num}"
    else:
        display_title = article_title or law_title or key

    # === 본문 fetch ===
    # 원래 설계: PG=index, Mongo=body. 별표는 PG attachment에 풍부하게 들어있음.
    # 따라서:
    #   - 별표(article_key endswith _attachment): PG full_text 사용
    #   - 그 외 article: Mongo raw에서 fetch, 실패 시 PG fallback
    pg_body = meta.get("full_text") or ""
    body_source = "pg"
    full_text = pg_body
    is_attachment = key.endswith("_attachment")

    if not is_attachment and target_type:
        try:
            from src.retrieval.mongo_client import fetch_body

            mst_id = meta.get("mst_id") or meta.get("law_id")
            mongo_body = fetch_body(
                target_type=target_type,
                mst_id=mst_id,
                article_num=article_num,
                law_title=law_title,  # PG mst_id가 잘못된 경우 title fallback
            )
            # Mongo = 조문 단위 본문(설계상 authoritative, api.py 위 주석 참조).
            # PG full_text 는 카테고리별로 조문 단위가 아닐 수 있음 — 특히
            # admrul(행정규칙)은 PG에 *문서 전문*이 통째로 들어가 있어서, 기존
            # "Mongo가 더 길 때만 채택" 휴리스틱이 짧은 조문 Mongo 본문을 버리고
            # PG 전문을 노출시켰음(law는 PG도 조 단위라 무증상). → Mongo가 조문을
            # 뽑았으면 그걸 우선, 못 뽑았을 때만(빈값) PG fallback.
            if mongo_body and mongo_body.strip():
                full_text = mongo_body
                body_source = "mongo"
        except Exception:
            pass

    # 본문 정규화 (frontend 명세 따라 backend가 깔끔 markdown 보냄).
    # normalize_law_text: CRLF/BOM, 헤더 중복, 항·호 줄바꿈, 가로 구분선, ASCII 박스 표,
    # 0-padded 조항 번호 등 일괄 처리.
    if full_text:
        from src.text.normalize import normalize_law_text

        full_text = normalize_law_text(
            full_text,
            law_title=law_title,
            article_num=article_num,
            article_title=article_title,
            strip_leading_header=target_type not in {"prec", "expc", "decc", "detc"},
        )
        # 조문형/별표 본문 시작부에 "법령명 제N조 (제목)" 통합 헤더 prepend.
        if target_type not in {"prec", "expc", "decc", "detc"} and (law_title or article_num):
            header_parts = [p for p in [law_title, article_num] if p]
            header = " ".join(header_parts)
            if article_title and article_title not in header:
                header = f"{header} ({article_title})"
            full_text = f"{header}\n\n{full_text}"

    return {
        "article_key": key,
        "target_type": target_type,
        "law_id": meta.get("law_id"),
        "law_title": law_title,
        "article_num": article_num,
        "article_title": article_title,
        "display_title": display_title,
        "full_text": full_text,
        "body_source": body_source,  # "pg" | "mongo" — 디버깅·UI 메타
        "is_body_complete": len(full_text) >= 200,  # 휴리스틱 — frontend 경고 표시용
        "department": meta.get("department"),
        "enforce_date": (
            str(meta["enforce_date"]) if meta.get("enforce_date") else None
        ),
        "external_url": external_url,
    }


def _build_law_go_kr_url(meta: dict, *, article_key: str | None = None) -> Optional[str]:
    """law.go.kr 외부 링크 — 법령명 기반 path URL.

    중요: openlaw-etl의 `law_id` (예: 의료기기법=009514)는 law.go.kr의 `lsiSeq`(개정
    이력별 시퀀스)와 **다른 체계**. `lsiSeq=009514`는 국토이용관리법(폐지)으로 잘못
    연결됨. 따라서 ID 매핑 대신 *법령명 path URL*로 우회 — 현행 버전 자동 매칭.

    참고:
      - 법령: /법령/{법령명}                → 최신본
      - 조 단위 딥링크 /{cat}/{명}/제N조     → 법령·행정규칙·자치법규 모두
        law.go.kr 친화 URL이 조 path 지원(예: /행정규칙/○○규정/제1조 동작 확인).
      - 별표: /법령/{법령명}/별표/{N}         → *법령만* 딥링크. 행정규칙·자치법규
        별표는 path-별표 미지원 → 전문 링크.
      - 판례·해석례: 검색 fallback
    """
    from urllib.parse import quote

    tt = meta.get("target_type")
    title = (meta.get("law_title") or "").strip()
    article_num = (meta.get("article_num") or "").strip()
    article_title = (meta.get("article_title") or "").strip()
    if not title:
        return None
    enc = quote(title, safe="")

    # 별표/서식 — 법령만 /별표/{N} 딥링크. admrul/ordin 별표는 path 미지원 → 전문.
    is_attachment = (
        article_num == "별표" or (article_key or "").endswith("_attachment")
    )
    if is_attachment:
        if tt == "law":
            from src.tools.search import _extract_annex_num
            n = _extract_annex_num(article_title, article_key)
            if n:
                return f"https://www.law.go.kr/법령/{enc}/별표/{quote(n, safe='')}"
            return f"https://www.law.go.kr/법령/{enc}/별표"
        cat = {"admrul": "행정규칙", "ordin": "자치법규"}.get(tt)
        if cat:
            return f"https://www.law.go.kr/{cat}/{enc}"  # 별표 전문

    art_frag = f"/{quote(article_num, safe='')}" if article_num else ""

    if tt == "law":
        # /법령/의료기기법 또는 /법령/의료기기법/제6조
        return f"https://www.law.go.kr/법령/{enc}{art_frag}"
    if tt == "admrul":
        # 조 path 지원 — /행정규칙/{규칙명}/제N조 동작 확인.
        return f"https://www.law.go.kr/행정규칙/{enc}{art_frag}"
    if tt == "ordin":
        # 조 path 지원 — admrul 와 동일 친화 URL 체계.
        return f"https://www.law.go.kr/자치법규/{enc}{art_frag}"
    if tt == "treaty":
        return f"https://www.law.go.kr/조약/{enc}"
    if tt == "prec":
        # 판례는 법원 사이트 검색 — 사건명/사건번호로 조회
        return f"https://www.law.go.kr/판례/{enc}"
    if tt == "expc":
        return f"https://www.law.go.kr/법령해석례/{enc}"
    if tt == "decc":
        return f"https://www.law.go.kr/위원회결정문/{enc}"
    if tt == "detc":
        return f"https://www.law.go.kr/헌재결정례/{enc}"
    return None


@router.get("/law/{lawId}/articles")
def list_law_articles(lawId: str, limit: int = 200):
    """법령에 속한 조문 목록 — 화면에 "이 법령의 다른 조항 보기" 등.

    Neo4j (Law)-[:CONTAINS]->(Article) 관계로 fetch. PG보다 그래프가 단일 query라 빠름.

    응답:
      { "law_id": str, "count": int, "items": [{article_key, article_num, article_title}] }
    """
    if not lawId:
        raise HTTPException(status_code=422, detail="lawId required")

    from src.retrieval.neo4j_client import _get_driver

    driver = _get_driver()
    if driver is None:
        raise HTTPException(status_code=503, detail="Neo4j 연결 비활성")

    # 실제 그래프 스키마(2026-07-10 라이브 확인): Law 키 속성은 `lawId`(`id` 아님),
    # Article 에는 article_num/article_title 이 없고 `jo`(조)·`gaji`(가지)·`title`.
    # 기존 쿼리는 Law {id:} 로 매칭 0건 — 항상 빈 목록을 반환하던 배선 오류.
    try:
        with driver.session() as s:
            rows = s.run(
                """
                MATCH (l:Law {lawId: $law_id})-[:CONTAINS]->(a:Article)
                RETURN a.id AS article_key,
                       a.jo AS jo,
                       a.gaji AS gaji,
                       a.title AS title
                ORDER BY toInteger(a.jo), toInteger(a.gaji)
                LIMIT $limit
                """,
                law_id=lawId,
                limit=int(limit),
            ).data()
    except Exception as e:
        # 예외 문자열엔 Neo4j URI·드라이버 내부가 실릴 수 있다 — 상세는 로그로만.
        import logging as _lg
        _lg.getLogger(__name__).exception("law-graph 조회 실패 law=%s: %s", lawId, e)
        raise HTTPException(status_code=500, detail="법령 그래프 조회에 실패했습니다")

    # Neo4j Article.id 는 6자리 suffix — PG/Qdrant 정준 키(7자리)로 변환해야
    # 프런트가 그대로 `/article?key=` 조회 가능 (pg_client.resolve_article_keys).
    # 조문 제목도 PG 에서 — Neo4j Article.title 은 *법령명*이라 목록에 무용.
    from src.retrieval.pg_client import fetch_article_titles, resolve_article_keys

    raw_keys = [r["article_key"] for r in rows if r.get("article_key")]
    canonical = resolve_article_keys(raw_keys)
    titles = fetch_article_titles(list(canonical.values()))

    items = []
    for r in rows:
        jo = str(r.get("jo") or "").strip()
        gaji = str(r.get("gaji") or "0").strip()
        if not jo:
            continue
        article_num = f"제{jo}조" + (f"의{gaji}" if gaji not in ("", "0") else "")
        key = canonical.get(r["article_key"], r["article_key"])
        items.append({
            "article_key": key,
            "article_num": article_num,
            "article_title": titles.get(key),
        })
    return {"law_id": lawId, "count": len(items), "items": items}
