/**
 * Reports API sidecar(port 2025) 응답 — `medi-back/docs/contracts/API.md` ReportMeta canonical.
 */

import type { Citation } from "./citation";

/**
 * **시간 표기**: `created_at`/`completed_at`은 ISO 8601 문자열.
 * **download_url**: 목록 응답엔 미포함, 단건 GET 응답에만 (gcs presigned, ttl ~1h).
 */
export type Report = {
  /** uuid hex — `?docPath=/{kind}_report.md` 매칭은 `kind`로 */
  id: string;
  thread_id: string;
  run_id: string | null;
  mode: "fast" | "deep";
  /** "doc" = 서류(서식 기입 문서) — 보고서가 아니다(책임 분리 2026-08-27).
   *  저장 인프라만 공유하며, 보고서 카드·개수·완료 토스트에서 제외된다. */
  kind: "final" | "rag" | "web" | "doc";
  status: "running" | "done" | "error";
  /** local dev: file:// uri / prod: gs:// uri */
  blob_uri: string | null;
  /** 표시 이름 — 예: "final_report" */
  title: string | null;
  /** ≤400자 요약 — final kind만 채워짐. UI 카드 부제·미리보기에 노출 */
  summary?: string | null;
  /** report 안에 포함된 인용 (deep이 끝나면 채워짐) */
  citations: Citation[] | null;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  /** 단건 GET 응답에만 — gcs presigned */
  download_url?: string;
  /** 서류 초안(document_draft) 기입값 — JSON 문자열 {항목: 값} (Phase ③) */
  filled_values?: string | null;
};
