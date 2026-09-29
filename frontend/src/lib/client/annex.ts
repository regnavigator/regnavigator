/**
 * 별표 / 서식 (Annex) API — backend R5 신규 endpoint.
 *
 * - GET /annex/list?lawId=X        → { count, items: [{ attachment_key, title, type }] }
 * - GET /annex?lawId=X&annexNum=N  → { title, markdown, type, download_url, source_uri }
 *
 * citation의 doc_category가 *별표서식*일 때 AnnexModal에서 사용.
 */

import { apiFetch } from "@/lib/api/client";

export type AnnexListItem = {
  attachment_key: string;
  title: string;
  /** "별표" | "서식" | null(키 미해석) */
  type?: string | null;
  /** "19" | "19의2" — /annex?annexNum= 에 그대로 */
  annex_num?: string | null;
};

export type AnnexListResponse = {
  count: number;
  items: AnnexListItem[];
};

export type AnnexDetail = {
  attachment_key?: string;
  title: string;
  markdown: string;
  type?: string;
  /** 외부 다운로드 — law.go.kr presigned 또는 source_uri */
  download_url?: string | null;
  source_uri?: string | null;
};

export async function listAnnex(lawId: string): Promise<AnnexListResponse> {
  return apiFetch<AnnexListResponse>(
    `/annex/list?lawId=${encodeURIComponent(lawId)}`,
  );
}

export type AnnexFillable = {
  key: string;
  /** 본문에서 기입 항목이 하나라도 잡히는가 — false 면 기준표류(참고용). */
  fillable: boolean;
  field_count: number;
  sample: string[];
};

/** 기입 가능 여부(2026-09-08) — 별표·서식 [작성] 버튼 노출 판정. 실패는 null(판정 불가). */
export async function getAnnexFillable(attachmentKey: string): Promise<AnnexFillable | null> {
  try {
    return await apiFetch<AnnexFillable>(`/annex/fillable?key=${encodeURIComponent(attachmentKey)}`);
  } catch {
    return null;
  }
}

/**
 * 본문 파싱 실패 판정(2026-09-08) — 표를 옮기지 못해 깨진 마크다운을 그대로 보이면
 * "미리보기가 제대로 안 나온다". 짧거나, 한글이 거의 없거나, 깨진 문자가 많으면 실패로 본다.
 */
export function looksGarbled(markdown: string | null | undefined): boolean {
  const md = (markdown ?? "").trim();
  if (md.length < 80) return true;
  const hangul = (md.match(/[가-힣]/g) ?? []).length;
  const bad = (md.match(/[\uFFFD\u0000-\u0008\u000B\u000C\u000E-\u001F]/g) ?? []).length;
  if (bad > 5) return true;
  if (hangul / md.length < 0.08) return true;
  // 표 구분자만 잔뜩이고 글자가 거의 없는 경우
  const pipes = (md.match(/\|/g) ?? []).length;
  if (pipes > 40 && hangul < pipes) return true;
  return false;
}

export type AnnexView = { html: string | null; reason: string | null };

/**
 * 원본 HWP → 문서 뷰어 HTML(2026-09-08, backend `src/annex_view.py` · pyhwp). 법령정보센터
 * 뷰어와 같은 방식 — 표·칸이 문서 그대로. 변환 불가는 200 + html null + reason(2026-09-09,
 * 종전 503 은 브라우저 콘솔에 에러로 남고 프런트가 사유 없이 "형식" 탓만 했다).
 */
export async function getAnnexViewHtml(attachmentKey: string): Promise<AnnexView> {
  try {
    const r = await apiFetch<{ key: string; html: string | null; reason?: string | null }>(
      `/annex/view?key=${encodeURIComponent(attachmentKey)}`,
    );
    return { html: r.html || null, reason: r.html ? null : (r.reason ?? null) };
  } catch (err) {
    return { html: null, reason: err instanceof Error ? err.message : "요청 실패" };
  }
}

export async function getAnnex(
  lawId: string,
  annexNum: string | number,
  type?: "별표" | "서식" | string | null,
): Promise<AnnexDetail> {
  // type: 같은 번호가 별표·서식에 공존(예: 009740 의 별표 3 / 별지 제3호 서식) — 구분 없이
  // 부르면 엉뚱한 쪽이 온다(2026-09-08 실측). 아는 경우 반드시 넘긴다.
  const t = type ? `&type=${encodeURIComponent(type)}` : "";
  return apiFetch<AnnexDetail>(
    `/annex?lawId=${encodeURIComponent(lawId)}&annexNum=${encodeURIComponent(String(annexNum))}${t}`,
  );
}

/**
 * attachment_key → {annexNum, type}. 두 형식을 안다(2026-09-08 실측):
 *  - `009740_000300F_attachment` : 4자리 번호 + 2자리 가지 + E(별표)/F(서식)
 *  - `{lawId}_19_2_attachment`   : 번호[_가지]
 */
export function parseAttachmentKey(key: string): { annexNum: string | null; type: "별표" | "서식" | null } {
  let m = key.match(/_(\d{4})(\d{2})([EF])_attachment$/);
  if (m) {
    const n = parseInt(m[1]!, 10);
    const b = parseInt(m[2]!, 10);
    return { annexNum: b ? `${n}의${b}` : String(n), type: m[3] === "F" ? "서식" : "별표" };
  }
  m = key.match(/_(\d+)(?:_(\d+))?_attachment$/);
  if (m) return { annexNum: m[2] ? `${m[1]}의${m[2]}` : m[1]!, type: null };
  return { annexNum: null, type: null };
}

/**
 * citation.article에서 별표 번호 추출. 예:
 *   "별표 7"     → "7"
 *   "별표7"      → "7"
 *   "[별표 12]"  → "12"
 *   "제45조"     → null  (별표 아님)
 */
export function extractAnnexNum(article?: string): string | null {
  if (!article) return null;
  const m = article.match(/별표\s*제?\s*(\d+)/);
  return m ? m[1]! : null;
}
