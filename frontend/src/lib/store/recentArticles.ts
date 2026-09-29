/**
 * recentArticles — 최근 열람 조문/근거 히스토리 (localStorage, 최대 10).
 *
 * RA 는 같은 조문을 반복 조회 — 인스펙터에서 본 근거를 기록해 커맨드 팔레트
 * (빈 검색 상태)에서 바로 재진입. 스레드가 달라도 원문 링크로 열 수 있게 url 보관.
 */

const KEY = "medi_recent_articles_v1";
const MAX = 10;

export type RecentArticle = {
  id: string;
  title: string;
  article?: string | null;
  url?: string | null;
  ts: number;
};

export function listRecentArticles(): RecentArticle[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    const arr = raw ? (JSON.parse(raw) as RecentArticle[]) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function recordRecentArticle(a: Omit<RecentArticle, "ts">): void {
  if (typeof window === "undefined" || !a.id || !a.title) return;
  try {
    const list = listRecentArticles().filter((x) => x.id !== a.id);
    list.unshift({ ...a, ts: Date.now() });
    window.localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX)));
  } catch {
    /* localStorage 불가 — 무시 */
  }
}
