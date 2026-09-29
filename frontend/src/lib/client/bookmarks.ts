/**
 * 개인 근거 라이브러리(북마크) 클라이언트 — 인용 저장·조회·삭제.
 * 백엔드: POST/GET/DELETE /bookmarks (user 스코프). 계약: medi-back routes/bookmarks.py.
 */

import { apiFetch } from "@/lib/api/client";
import type { Citation } from "@/lib/store/types";

export type Bookmark = {
  id: string;
  user_id: string;
  citation_id: string;
  citation: Citation | null;
  note?: string | null;
  folder?: string | null;
  thread_id?: string | null;
  created_at: string;
};

/** 폴더 지정/해제(null). */
export async function setBookmarkFolder(
  id: string,
  folder: string | null,
): Promise<void> {
  await apiFetch(`/bookmarks/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ folder }),
  });
}

export async function addBookmark(
  citation: Citation,
  opts?: { note?: string; threadId?: string | null },
): Promise<{ ok: boolean; bookmark_id: string }> {
  return apiFetch<{ ok: boolean; bookmark_id: string }>("/bookmarks", {
    method: "POST",
    body: JSON.stringify({
      citation,
      note: opts?.note,
      thread_id: opts?.threadId ?? undefined,
    }),
  });
}

export async function listBookmarks(): Promise<Bookmark[]> {
  const res = await apiFetch<{ count: number; items: Bookmark[] }>("/bookmarks");
  return res.items ?? [];
}

export async function deleteBookmark(id: string): Promise<void> {
  await apiFetch(`/bookmarks/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** citation.id 로 저장 해제(토글) — 프런트에서 bookmark id 를 모를 때. */
export async function removeBookmarkByCitation(citationId: string): Promise<void> {
  await apiFetch(`/bookmarks/by-citation/${encodeURIComponent(citationId)}`, {
    method: "DELETE",
  });
}

export type Amendment = {
  bookmark_id: string;
  citation_id: string;
  title?: string | null;
  /** repealed=폐지 · pending=개정 예정 · amended=시행일 변경(개정됨) */
  kind?: "repealed" | "pending" | "amended";
  saved_date?: string | null;
  current_date?: string | null;
};

/** 저장 시점 대비 시행일이 바뀐 북마크(개정 가능성) — 라이브러리 배지용. */
export async function getBookmarkAmendments(): Promise<Amendment[]> {
  try {
    const res = await apiFetch<{ amendments: Amendment[] }>("/bookmarks/amendments");
    return res.amendments ?? [];
  } catch (err) {
    console.debug("[getBookmarkAmendments] failed", err);
    return [];
  }
}
