/**
 * 법적 고지·문서 클라이언트 — 백엔드가 정본(single source of truth).
 *
 * - `GET /legal`       : 면책·핵심 고지 (푸터/배너 상시 노출용, 인증 X)
 * - `GET /legal/{doc}` : 약관·개인정보처리방침 markdown 정본 (인증 X)
 *
 * 프런트에 본문을 하드코딩하면 두 벌이 되어 실제 동작과 어긋난다(실제로 §3
 * 보유기간·§5 이전받는 자가 어긋나 있었다). 연동 스펙: medi-back
 * `docs/frontend_legal_handoff.md`.
 */

import { apiFetch } from "@/lib/api/client";

export type LegalNotice = {
  version: string;
  disclaimer_short: string;
  disclaimer_report: string;
  key_points: string[];
  docs: Record<string, string>;
};

export type LegalDocId = "terms" | "privacy";

export type LegalDocument = {
  doc: LegalDocId;
  version: string;
  format: "markdown";
  content: string;
};

export async function fetchLegalNotice(): Promise<LegalNotice> {
  return apiFetch<LegalNotice>("/legal");
}

// 면책 문구는 모든 채팅 화면에 상시 노출 — 마운트마다 재요청하지 않게 모듈 캐시.
// 실패 시 캐시하지 않아 다음 마운트에서 재시도.
let noticeCache: Promise<LegalNotice> | null = null;

export function getLegalNoticeCached(): Promise<LegalNotice> {
  if (!noticeCache) {
    noticeCache = fetchLegalNotice().catch((err) => {
      noticeCache = null;
      throw err;
    });
  }
  return noticeCache;
}

export async function fetchLegalDocument(doc: LegalDocId): Promise<LegalDocument> {
  return apiFetch<LegalDocument>(`/legal/${doc}`);
}
