"""핵심 데이터 계약 — `Citation` / `Step` TypedDict.

이 둘은 코드 전반(33+ 모듈: tools·routes·report_pipeline·grounding·FE 스트림)에서
raw dict 로 주고받혀 **shape 가 암묵적**이었다. TypedDict 로 한곳에 명시 →
런타임은 dict 그대로(접근부 `c["number"]` 무변경, 동작 보존)지만 IDE·mypy 가
필드 오타·결측을 잡는다. *문서이자 타입 안전망*.

생성처: Citation = `tools/citations.py`(extract_*), Step = `steps.py`(step_start/done).
소비처: `tools/search.py`·`report_pipeline.py`·`grounding.py`·`middleware/grounding_gate.py`
        + FE 스트림 페이로드(02_INTERFACE 계약).
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class Citation(TypedDict):
    """인용 1건. web(Tavily) / doc(법령 RAG) 공통 + 종류별 선택 필드.

    필수: id·number·source_kind·title·snippet·status·verified.
    """

    id: str                       # "cite_web_<sha1>" | "cite_doc_<article_key>"
    number: int                   # turn 전역 단조 인용 번호 [n]
    source_kind: str              # "web" | "doc"
    title: str                    # 표시 제목
    snippet: str                  # 본문 발췌(≤300)
    status: str                   # "active" | "revoked" | "amended_pending"
    verified: bool                # 신뢰 출처/grounding 검증 통과

    # 공통 선택
    publisher: NotRequired[str | None]
    doc_category: NotRequired[str]
    url: NotRequired[str]              # law.go.kr / web deep-link
    date: NotRequired[str | None]

    # doc(법령) 전용
    doc_id: NotRequired[str | None]
    article: NotRequired[str | None]  # "제N조"
    # 시행 상태(2026-08-16) — status(active/revoked/amended_pending)보다 정밀한
    # 원본 라벨. FE 배지용: "시행중"|"미시행"|"구법"|"확인필요". enforced=False 는
    # 공포됐으나 시행일 미도래(= 아직 효력 없음) — 폐지와 구분해야 한다.
    effective_status: NotRequired[str | None]
    enforced: NotRequired[bool | None]
    # 버전 축(openlaw-etl RFC LAW_VERSION_CURRENT_VS_PENDING R3, 2026-08-16)
    # "current" | "pending". pending 은 현행본과 **함께** 온 개정 예정본이고
    # supersedes_article_key 로 그 현행본을 가리킨다(키 `_ef{YYYYMMDD}` 접미).
    version_status: NotRequired[str]
    supersedes_article_key: NotRequired[str]
    download_url: NotRequired[str]    # 별표 HWP
    court: NotRequired[str]           # 판례 법원
    instance: NotRequired[int]        # 판례 심급

    # legacy / 기타
    page: NotRequired[object]

    # grounding(검증·writer 입력) — FE 노출 전 strip 될 수 있음
    text: NotRequired[str]            # 근거 원문 chunk
    supporting_quote: NotRequired[str]  # claim 뒷받침 원문 span


class Step(TypedDict, total=False):
    """도구 실행 단계. step_start/step_done/step_error 가 **merge dict** 로 발행 →
    같은 id 로 reducer 가 합침(running→done). 따라서 한 payload 는 부분집합(total=False).
    """

    id: str                       # "s_<10hex>" — merge 키
    status: str                   # "running" | "done" | "error"
    label: str                    # ≤70 사용자향(start)
    ts: int                       # Unix ms(start)
    tool_name: str                # "qdrant_search" | "tavily_search" | ...
    ended_at: int                 # Unix ms(done/error)
    input_preview: str
    output_preview: str
    error_message: str            # 사용자향(error)
    citations: list[Citation]     # done 시 부착
    source_message_id: str        # 이 step 을 트리거한 human message id
    turn_idx: int                 # 0-based human 턴 순번
    # 이 검색이 지목한 문서 종별(qdrant_search 만, 미지정 검색은 없음).
    # 보고서가 **채팅 맥락을 이어받을 때** 근거 코퍼스를 계승하는 재료
    # (2026-08-25 — 보고서가 채팅이 찾아둔 급여기준 코퍼스를 못 따라가던 문제).
    doc_kinds: list[str]
