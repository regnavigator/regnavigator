"use client";

/**
 * SavedCitations — 내 북마크(저장한 근거)의 citation_id 셋을 한 번 로드해 공유.
 *
 * BookmarkButton 이 초기 "저장됨" 상태를 정확히 표시하도록(전엔 항상 false 시작).
 * 저장/해제·삭제 시 셋을 갱신해 UI 를 즉시 동기화.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { listBookmarks } from "@/lib/client/bookmarks";

type Ctx = {
  isSaved: (citationId: string) => boolean;
  markSaved: (citationId: string) => void;
  markUnsaved: (citationId: string) => void;
  reload: () => void;
};

const C = createContext<Ctx | null>(null);

export function SavedCitationsProvider({ children }: { children: ReactNode }) {
  const [ids, setIds] = useState<Set<string>>(new Set());

  const reload = useCallback(() => {
    void listBookmarks()
      .then((bs) => setIds(new Set(bs.map((b) => b.citation_id))))
      .catch(() => {
        /* 미인증/네트워크 실패 — 빈 셋 유지(무해) */
      });
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const isSaved = useCallback((id: string) => ids.has(id), [ids]);
  const markSaved = useCallback(
    (id: string) => setIds((p) => new Set(p).add(id)),
    [],
  );
  const markUnsaved = useCallback(
    (id: string) =>
      setIds((p) => {
        const n = new Set(p);
        n.delete(id);
        return n;
      }),
    [],
  );

  return (
    <C.Provider value={{ isSaved, markSaved, markUnsaved, reload }}>
      {children}
    </C.Provider>
  );
}

export function useSavedCitations(): Ctx {
  const ctx = useContext(C);
  if (!ctx) {
    return {
      isSaved: () => false,
      markSaved: () => {},
      markUnsaved: () => {},
      reload: () => {},
    };
  }
  return ctx;
}
