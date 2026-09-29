/**
 * 법령 원문 (Article) API — backend `/article`·`/law/{id}/articles`.
 *
 * - GET /article?key={article_key}        → 조문/해석례 1건 본문 + 메타
 * - GET /law/{lawId}/articles?limit=200   → 법령 내 조문 목록
 *
 * citation.id에서 prefix(`cite_doc_`) 제거 → article_key로 사용.
 * web citation은 적용 X (source_kind === "doc" 인 경우만).
 */

import { apiFetch } from "@/lib/api/client";

export type Article = {
  article_key: string;
  /** law / admrul / ordin / prec / expc ... */
  target_type: string;
  law_id: string;
  law_title: string;
  /** "제25조 (광고의 사전심의)" — law·admrul·ordin에만 존재. expc/prec엔 없음 */
  article_num?: string | null;
  department?: string | null;
  enforce_date?: string | null;
  external_url?: string | null;
  full_text: string;
};

export type ArticleListItem = {
  article_key: string;
  article_num?: string | null;
  /** 조항 제목 */
  title?: string | null;
};

export type ArticleListResponse = {
  count: number;
  items: ArticleListItem[];
};

export async function getArticle(articleKey: string): Promise<Article> {
  return apiFetch<Article>(`/article?key=${encodeURIComponent(articleKey)}`);
}

export async function listLawArticles(
  lawId: string,
  limit = 200,
): Promise<ArticleListResponse> {
  return apiFetch<ArticleListResponse>(
    `/law/${encodeURIComponent(lawId)}/articles?limit=${limit}`,
  );
}

/**
 * citation에서 *조 단위* article_key 추출.
 *
 * backend는 doc citation id를 항상 `cite_doc_<article_key>`로 발행한다
 * (medi-back search.py:645). 여기서 article_key는 조 단위 키
 * (`{law_id}_{조문키}`, 예 `009740_0004001`)다.
 *
 * **`c.doc_id` fallback 제거**: backend search.py:651에서 `doc_id`는 *법령 전체
 * id(law_id)*다. 이걸 /article key로 넘기면 그 조가 아니라 *법령 전체*가 내려와
 * "전체 말고 그 조만" 요구에 어긋난다. 조 단위 키(`cite_doc_`)가 없으면 null을
 * 반환해 CitationInspector가 backend가 보낸 `c.snippet`(= 인용된 그 조 본문)만
 * 노출하도록 한다.
 *
 *   - `id`가 `cite_doc_<key>` → strip prefix (조 단위 key)
 *   - 그 외(web citation·접두어 없는 legacy·deep report) → null
 */
import type { Citation } from "@/lib/store/types";

export function articleKeyFromCitation(c: Citation): string | null {
  if (c.source_kind !== "doc") return null;
  if (c.id?.startsWith("cite_doc_")) {
    const stripped = c.id.slice("cite_doc_".length);
    if (stripped.length > 0) return stripped;
  }
  return null;
}

/** legacy — id만 받는 버전. 새 코드는 articleKeyFromCitation 사용 권장 */
export function articleKeyFromCitationId(citationId: string): string | null {
  if (!citationId.startsWith("cite_doc_")) return null;
  return citationId.slice("cite_doc_".length);
}
