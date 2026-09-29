"use client";

/**
 * BookmarkButton — 인용을 개인 근거 라이브러리에 저장/해제(토글).
 *
 * 초기 saved 상태는 낙관적(false 시작) — 목록 전체를 로드하지 않고 즉시 반응.
 * 백엔드 저장은 멱등(UNIQUE user_id+citation_id)이라 중복 클릭도 안전.
 */

import { useState } from "react";
import { useQueryState } from "nuqs";
import { toast } from "sonner";
import type { Citation } from "@/lib/store/types";
import { addBookmark, removeBookmarkByCitation } from "@/lib/client/bookmarks";
import { useSavedCitations } from "@/lib/store/savedCitations";

export function BookmarkButton({
  citation,
  inline = false,
}: {
  citation: Citation;
  /** true면 아이콘+텍스트 라벨을 하나의 링크형 버튼으로 — 액션 행에서 다른 링크와 정렬용. */
  inline?: boolean;
}) {
  const [threadId] = useQueryState("threadId");
  const { isSaved, markSaved, markUnsaved } = useSavedCitations();
  const saved = isSaved(citation.id);
  const [busy, setBusy] = useState(false);

  const toggle = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (saved) {
        await removeBookmarkByCitation(citation.id);
        markUnsaved(citation.id);
        toast.success("근거 저장 해제");
      } else {
        await addBookmark(citation, { threadId });
        markSaved(citation.id);
        toast.success("근거 라이브러리에 저장됨", {
          description: "좌측 사이드바 · 저장한 근거에서 확인",
        });
      }
    } catch (e) {
      console.warn("[BookmarkButton] toggle failed", e);
      toast.error("저장 실패 — 잠시 후 다시 시도해주세요.");
    } finally {
      setBusy(false);
    }
  };

  if (inline) {
    // 액션 행에서 "법령정보센터에서 보기" 등 다른 링크와 같은 톤으로 정렬 —
    // 아이콘 + 텍스트가 한 버튼. 저장 상태면 primary 강조.
    return (
      <button
        type="button"
        onClick={() => void toggle()}
        disabled={busy}
        aria-label={saved ? "근거 저장 해제" : "근거 라이브러리에 저장"}
        title={saved ? "저장됨 — 눌러서 해제" : "근거 라이브러리에 저장"}
        className={`inline-flex items-center gap-1 text-body-sm transition-colors hover:underline disabled:opacity-50 ${
          saved ? "text-md-primary" : "text-md-secondary"
        }`}
      >
        <span
          className="material-symbols-outlined text-[16px]"
          aria-hidden
          style={saved ? { fontVariationSettings: "'FILL' 1" } : undefined}
        >
          {saved ? "bookmark" : "bookmark_add"}
        </span>
        {saved ? "저장됨" : "근거 라이브러리에 저장"}
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      disabled={busy}
      aria-label={saved ? "근거 저장 해제" : "근거 라이브러리에 저장"}
      title={saved ? "저장됨 — 눌러서 해제" : "근거 라이브러리에 저장"}
      className="shrink-0 rounded-button p-1 text-md-on-surface-variant hover:text-md-primary disabled:opacity-50"
    >
      <span
        className={`material-symbols-outlined text-[16px] ${saved ? "text-md-primary" : ""}`}
        aria-hidden
        style={saved ? { fontVariationSettings: "'FILL' 1" } : undefined}
      >
        {saved ? "bookmark" : "bookmark_add"}
      </span>
    </button>
  );
}
