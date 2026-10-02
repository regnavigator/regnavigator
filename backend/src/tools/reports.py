"""산출물 저장 도구 — save_web_report / save_rag_report / save_report (M6a/b/c).

spec: ../06_SKILLS.md M6, ../03_ARCHITECTURE.md §4.5

idempotent 동작 (deepagents 내장 `write_file` 충돌 회피):
- state.files[path]에 이미 파일이 있으면 → 그대로 ack (저장 완료 step.done)
- 없으면 → 직전 AI 텍스트를 저장
- 둘 다 안 되면 → step.error
"""

from __future__ import annotations

import re
from typing import Optional

from langchain_core.runnables.config import ensure_config

from src.persistence import get_blob_store, get_reports_repo
from src.persistence.reports_repo import ReportMeta, _new_id
from src.text.messages import last_ai_text as _last_ai_text  # noqa: F401 — 재export(tests/test_tools_reports)
from src.steps import now_ms


# 보고서 본문에서 LLM이 자동으로 박는 "운영 메타데이터" 줄을 잡는 패턴.
# 프롬프트로 막아도 LLM이 가끔 우회하므로, 저장 직전 코드로 강제 제거.
# 패턴은 한 줄 단위로 매칭 — 본문 콘텐츠에 우연히 겹칠 가능성 낮은 키워드 위주.
_META_LINE_RE = re.compile(
    r"^\s*[-*•]?\s*"  # 옵션: 불릿 prefix
    r"(?:\*\*|__)?"  # 옵션: 굵게 강조 prefix
    r"(?:"
    r"보고서\s*작성\s*(?:일시|일자|시각|시점|날짜)"
    r"|작성\s*일시"
    r"|생성\s*일시"
    r"|검색\s*도구"
    r"|사용\s*도구"
    r"|도구\s*호출"
    r"|호출\s*횟수"
    r"|분량(?:\s*제한)?"
    r"|줄\s*수"
    r"|line\s*count"
    r"|tool\s*calls?"
    r"|generated\s*(?:at|on)"
    r")"
    r".*$",
    flags=re.IGNORECASE | re.MULTILINE,
)


def _strip_meta(body: str) -> str:
    """LLM이 자동 추가한 운영 메타 줄 제거 + 연속 빈 줄 정리.

    예시 매칭:
        "보고서 작성 일시: 2026-05-11"
        "- 검색 도구: Tavily Search (2회 호출)"
        "분량: 본문 약 95줄 (한도 100줄 이내)"
        "**작성 일시** : ..."
    """
    if not body:
        return body
    cleaned = _META_LINE_RE.sub("", body)
    # 3+ 연속 개행을 2개로 압축 (메타 라인 제거 후 잔여 공백 정리)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + ("\n" if body.endswith("\n") else "")


def _file_entry(content: str, *, step_id: str | None = None) -> dict:
    """deepagents `create_file_data` 호환 — 줄 단위 + 시각.

    R3 — `generated_by_step_id` 가 있으면 메타에 박는다.
    프런트의 ArtifactViewer는 이 필드로 생성 step을 정확히 매핑한다.
    """
    lines = content.splitlines() if content else []
    ts = now_ms()
    entry: dict = {
        "content": lines,
        "created_at": ts,
        "modified_at": ts,
        "is_streaming": False,
    }
    if step_id:
        entry["generated_by_step_id"] = step_id
    return entry


def _existing_file_text(state: dict, path: str) -> str | None:
    """state.files[path]가 있으면 본문 합쳐 반환. 없으면 None."""
    files = state.get("files") or {}
    entry = files.get(path)
    if not entry:
        return None
    content = entry.get("content") if isinstance(entry, dict) else None
    if isinstance(content, list) and content:
        return "\n".join(content)
    if isinstance(entry, str):
        return entry
    return None


_KIND_BY_PATH = {
    "/web_report.md": "web",
    "/rag_report.md": "rag",
    "/final_report.md": "final",
    # 서류(document_draft) — 보고서가 아니다(2026-08-27 책임 분리). 저장·기입
    # 인프라는 reports 레코드를 재사용하지만, kind="doc" 으로 갈라 보고서
    # 목록·카드·메일 어디에도 보고서로 안 섞인다.
    "/document.md": "doc",
}


def _extract_title(body: str, *, max_chars: int = 80) -> Optional[str]:
    """보고서 본문 첫 # H1 제목을 title로 추출.

    writer 프롬프트가 본문을 `# [주제]`로 시작하도록 강제 — 그 한 줄이 title이 됨.
    추출 실패(첫 H1 없음) 시 None — _persist_report가 path stem으로 fallback.
    """
    if not body:
        return None
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            # 대괄호 placeholder 정리: "# [주제]" 같이 LLM이 형식만 박은 경우 거부
            if title.startswith("[") and title.endswith("]"):
                return None
            return title[:max_chars] if title else None
    return None


def _extract_summary(body: str, *, max_chars: int = 400) -> Optional[str]:
    """보고서 본문에서 ## 개요/핵심 요약 섹션 추출 (없으면 첫 의미있는 단락).

    사이드바 목록·우측 패널이 보여주는 한 줄 요약. 채팅↔보고서 분리(2026-07-25)
    이후 **개요를 채팅에 append 하지 않으므로** 이 필드가 채팅 밖 요약 노출의
    주 경로다 — rp writer 가 쓰는 실제 헤더는 `## 개요`인데 구 구현이 "요약"만
    매칭해 폴백(첫 단락)으로 새고 있었다. 추출 실패 시 None(title 만 표시).
    """
    if not body:
        return None
    lines = body.splitlines()
    out: list[str] = []
    in_summary = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_summary:
                break  # 다음 섹션 시작 — 종료
            header = stripped.lstrip("#").strip().lower()
            if ("개요" in header or "요약" in header
                    or "summary" in header or "overview" in header):
                in_summary = True
                continue
        elif in_summary:
            if stripped:
                out.append(stripped)
            elif out:  # 빈 줄 — summary 끝났다고 간주
                break
    if not out:
        # ## 핵심 요약 섹션 없음 — 첫 # 제목 다음의 첫 의미있는 단락 추출
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            out.append(s)
            if sum(len(x) for x in out) >= max_chars:
                break
    text = " ".join(out)
    return text[:max_chars] if text else None


class ReportPersistError(RuntimeError):
    """보고서 영속(메타 기록·blob 업로드) 실패.

    writer 실패와 **구분**하려고 따로 둔다. 둘 다 "보고서 실패"로 뭉뚱그리면
    운영이 어디를 봐야 할지(모델 서버인지 GCS/PG인지) 알 수 없다.
    """


def _persist_report(
    *, path: str, body: str, state: dict, ctx: dict | None = None,
    citations: list[dict] | None = None,
) -> tuple[str, str] | None:
    """BlobStore에 본문 업로드 + ReportsRepo에 메타 기록.

    **예외를 올린다**(2026-08-04 변경) — 예전엔 삼키고 None 을 돌려줘서 원인이
    warning 한 줄로 사라졌다. 5~40분 writer 비용을 치른 뒤의 실패라 원인 추적이
    가능해야 한다. 호출자가 유형명을 run.error 에 남긴다.
    return: (report_id, blob_uri).

    `ctx`: configurable 명시 오버라이드(thread_id·run_id 등) — langgraph 실행
    컨텍스트 밖(자체 report_runner, ADR-0001 Phase 3)에서 호출할 때 사용.
    미전달 시 기존대로 ensure_config()(langgraph run 내부) 값.

    `citations`: **본문에 실제 인용된 것만** 명시 전달(2026-08-25). 미전달 시
    기존대로 state.steps 를 훑는데, 스레드 state 에는 *채팅 턴* step 도 들어
    있어 보고서가 쓰지도 않은 인용이 메타에 섞였다(본문 References 4건 vs
    메타 25건 — 실측). 사이드바 인용 목록이 본문과 어긋나면 근거가 있는 것처럼
    보인다.
    """
    # except 절이 참조하므로 try 밖에서 초기화(초기 단계 실패 시 NameError 방지).
    report_id = None
    chat_thread_id = "unknown"
    try:
        cfg = ensure_config()
        configurable = (cfg or {}).get("configurable") or {}
        if ctx:
            configurable = {**configurable, **ctx}
        # deep 그래프는 별도 langgraph thread 에서 (langgraph 관리 run 으로) 돌고,
        # chat thread 식별자는 config.configurable.parent_thread_id 로 들어온다.
        # reports 는 사용자 chat thread 기준으로 묶여 사이드바에 떠야 하므로 parent 우선.
        chat_thread_id = (
            configurable.get("parent_thread_id")
            or configurable.get("thread_id")
            or "unknown"
        )
        run_id = configurable.get("run_id")
        kind = _KIND_BY_PATH.get(path, "other")
        report_id = _new_id()

        # citations: 명시 전달분 우선(본문에 실제 쓰인 것) — 미전달 시에만
        # state.steps 스캔(구 경로 호환).
        if citations is None:
            steps = state.get("steps") or []
            citations = []
            for st in steps:
                if st.get("status") == "done" and st.get("citations"):
                    citations.extend(st["citations"])

        # ReportContextMiddleware가 fast 턴에 저비용으로 주입할 본문 요약 (~400자).
        # final 보고서만 (web/rag는 중간 산출물 — 사용자 답변에 직접 안 쓰임).
        summary = _extract_summary(body) if kind == "final" else None

        # title — final은 본문 첫 H1에서 추출 (예: "# 의료기기 광고 사전심의 절차"),
        # 추출 실패·중간 보고서는 path stem (final_report / web_report / rag_report).
        extracted_title = (_extract_title(body)
                           if kind in ("final", "doc") else None)
        title = extracted_title or path.lstrip("/").rsplit(".", 1)[0]

        repo = get_reports_repo()
        repo.create(
            ReportMeta(
                id=report_id,
                thread_id=chat_thread_id,
                run_id=run_id,
                mode="deep",
                kind=kind,
                status="running",
                title=title,
                summary=summary,
            )
        )

        blob_key = f"{chat_thread_id}/{report_id}.md"
        blob_uri = get_blob_store().put(blob_key, body)

        repo.update_status(
            report_id,
            status="done",
            blob_uri=blob_uri,
            citations=citations or None,
        )
        return report_id, blob_uri
    except Exception as e:
        # ⚠️ 여기서 삼키고 None 만 돌려주면 러너는 "보고서 영속 실패"로 마감하고
        # **원인(GCS 권한? PG 다운? blob 경로?)은 warning 한 줄로 사라진다**.
        # 5~40분짜리 writer 비용을 다 치른 뒤라 손실이 크고, 재발해도 어디를
        # 고쳐야 할지 알 수 없다(2026-08-04 감사 H-11).
        #
        # 예외를 그대로 올린다 — 호출자(report_pipeline→report_runner)가 유형명을
        # run.error 에 남겨 `/reports/runs` 폴링으로 운영·사용자에게 드러난다.
        # 스택은 로그에만(예외 문자열에 blob 경로·DSN 이 실릴 수 있어 저장은 유형명까지).
        import logging
        logging.getLogger(__name__).exception(
            "report persistence failed (report_id=%s, thread=%s): %s",
            report_id, chat_thread_id, e)
        raise ReportPersistError(type(e).__name__) from e
