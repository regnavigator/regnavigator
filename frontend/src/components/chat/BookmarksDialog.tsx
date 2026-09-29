"use client";

/**
 * BookmarksDialog — 개인 근거 라이브러리 뷰. 저장한 인용(조문·별표/서식·판례)을
 * 최신순으로 나열, 원문 링크·삭제 제공. 열 때마다 최신 목록 로드.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  type Bookmark,
  deleteBookmark,
  getBookmarkAmendments,
  listBookmarks,
  setBookmarkFolder,
} from "@/lib/client/bookmarks";
import { useSavedCitations } from "@/lib/store/savedCitations";
import { deriveExternalUrl } from "@/lib/parse/lawLink";

export function BookmarksDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [items, setItems] = useState<Bookmark[]>([]);
  const [loading, setLoading] = useState(false);
  // 개정 감지 — citation_id → Amendment(kind: 폐지/개정예정/개정됨).
  const [amended, setAmended] = useState<Map<string, import("@/lib/client/bookmarks").Amendment>>(new Map());
  // 개정 배지 "확인함" 처리(2026-08-27) — 배지는 알림이 아니라 **상태 표시**라
  // 조문이 개정 상태인 한 계속 뜬다("열람했는데도 계속 주의마크" 지적). 사실은
  // 유지하되(개정된 건 여전히 개정된 것), 한 번 열람한 배지는 톤을 낮추고
  // "확인함"을 병기한다. 기기 단위 localStorage — 서버 스키마 변경 없이 시작.
  const [seenAmends, setSeenAmends] = useState<Record<string, string>>(() => {
    if (typeof window === "undefined") return {};
    try {
      return JSON.parse(window.localStorage.getItem("medi.bookmark.amend.seen") || "{}");
    } catch {
      return {};
    }
  });
  // 폴더 필터(null=전체) + 항목별 폴더 편집 상태.
  const [folderFilter, setFolderFilter] = useState<string | null>(null);
  const [editingFolderId, setEditingFolderId] = useState<string | null>(null);
  const [folderDraft, setFolderDraft] = useState("");
  const { markUnsaved } = useSavedCitations();

  // 다이얼로그를 닫는 시점 = "열람 완료" — 현재 떠 있던 배지를 확인 처리.
  const prevOpen = useRef(open);
  useEffect(() => {
    if (prevOpen.current && !open && amended.size) {
      setSeenAmends((prev) => {
        const next = { ...prev };
        for (const [cid, am] of amended) next[cid] = am.kind ?? "";
        try {
          window.localStorage.setItem(
            "medi.bookmark.amend.seen", JSON.stringify(next));
        } catch {
          /* 저장 실패 = 다음에 다시 강조될 뿐 */
        }
        return next;
      });
    }
    prevOpen.current = open;
  }, [open, amended]);

  const folders = [...new Set(items.map((b) => b.folder).filter(Boolean))] as string[];
  const visible = folderFilter
    ? items.filter((b) => b.folder === folderFilter)
    : items;

  const commitFolder = async (id: string) => {
    const val = folderDraft.trim() || null;
    try {
      await setBookmarkFolder(id, val);
      setItems((prev) =>
        prev.map((b) => (b.id === id ? { ...b, folder: val } : b)),
      );
    } catch (e) {
      console.warn("[BookmarksDialog] folder set failed", e);
      toast.error("폴더 변경 실패");
    } finally {
      setEditingFolderId(null);
      setFolderDraft("");
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [bs, ams] = await Promise.all([
        listBookmarks(),
        getBookmarkAmendments(),
      ]);
      setItems(bs);
      setAmended(new Map(ams.map((a) => [a.citation_id, a])));
    } catch (e) {
      console.warn("[BookmarksDialog] load failed", e);
      toast.error("저장한 근거를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const remove = async (id: string) => {
    try {
      await deleteBookmark(id);
      const removed = items.find((b) => b.id === id);
      if (removed) markUnsaved(removed.citation_id);
      setItems((prev) => prev.filter((b) => b.id !== id));
    } catch (e) {
      console.warn("[BookmarksDialog] delete failed", e);
      toast.error("삭제 실패");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>저장한 근거</DialogTitle>
          <DialogDescription>
            답변에서 저장한 조문·별표/서식·판례. 원 대화가 지워져도 유지됩니다.
          </DialogDescription>
        </DialogHeader>

        {folders.length > 0 ? (
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setFolderFilter(null)}
              className={
                "rounded-pill px-2.5 py-1 text-[11px] font-medium transition-colors " +
                (folderFilter === null
                  ? "bg-md-primary text-md-on-primary"
                  : "bg-md-surface-container text-md-on-surface-variant hover:bg-md-surface-container-high")
              }
            >
              전체 {items.length}
            </button>
            {folders.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFolderFilter(folderFilter === f ? null : f)}
                className={
                  "rounded-pill px-2.5 py-1 text-[11px] font-medium transition-colors " +
                  (folderFilter === f
                    ? "bg-md-primary text-md-on-primary"
                    : "bg-md-surface-container text-md-on-surface-variant hover:bg-md-surface-container-high")
                }
              >
                📁 {f} {items.filter((b) => b.folder === f).length}
              </button>
            ))}
          </div>
        ) : null}

        <div className="mt-2 max-h-[60vh] overflow-y-auto">
          {loading ? (
            <p className="py-8 text-center text-[13px] text-md-on-surface-variant">
              불러오는 중…
            </p>
          ) : items.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-md-on-surface-variant">
              저장한 근거가 없습니다. 답변 인용의{" "}
              <span className="material-symbols-outlined align-[-3px] text-[16px]" aria-hidden>
                bookmark_add
              </span>{" "}
              북마크 아이콘으로 저장하세요.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {visible.map((b) => {
                const c = b.citation;
                const title = c?.title ?? b.citation_id;
                const url = c ? deriveExternalUrl(c) ?? c.url ?? null : null;
                const download = c?.download_url ?? null;
                const isAnnex =
                  c?.doc_category === "법령별표서식" ||
                  c?.doc_category === "행정규칙별표서식" ||
                  c?.doc_category === "자치법규별표서식";
                return (
                  <li
                    key={b.id}
                    className="flex items-start gap-2 rounded-card border border-md-outline-variant bg-md-surface-container-low p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        {isAnnex ? (
                          <span className="rounded-pill bg-md-secondary-fixed px-1.5 py-0.5 text-[10px] font-medium text-md-on-secondary-fixed-variant">
                            별표/서식
                          </span>
                        ) : c?.doc_category ? (
                          <span className="rounded-pill bg-md-surface-container-high px-1.5 py-0.5 text-[10px] text-md-on-surface-variant">
                            {c.doc_category}
                          </span>
                        ) : null}
                        <span className="min-w-0 truncate text-[13px] font-medium text-md-on-surface" title={title}>
                          {title}
                        </span>
                        {(() => {
                          const am = amended.get(b.citation_id);
                          if (!am) return null;
                          const label =
                            am.kind === "repealed" ? "폐지됨"
                            : am.kind === "pending" ? "개정 예정"
                            : "개정됨";
                          const tip =
                            am.kind === "repealed" ? "law.go.kr 기준 폐지된 법령 — 승계 법령 확인 필요"
                            : am.kind === "pending" ? "개정 예정(공포·시행 대기) — 변경 내용 확인 필요"
                            : `시행일이 ${am.current_date}로 변경됨 — 원문 확인 필요`;
                          // 확인함 = 같은 종류의 개정을 이미 열람 — 톤다운.
                          // 폐지→개정 등 **상태가 바뀌면** seen 불일치로 다시 강조된다.
                          const seen = seenAmends[b.citation_id] === am.kind;
                          const cls = seen
                            ? "border border-md-outline-variant text-md-on-surface-variant"
                            : am.kind === "pending"
                              ? "bg-md-tertiary/15 text-md-tertiary"
                              : "bg-md-error/10 text-md-error";
                          return (
                            <span
                              className={`inline-flex shrink-0 items-center gap-0.5 rounded-pill px-1.5 py-0.5 text-[10px] font-medium ${cls}`}
                              title={seen ? `${tip} (확인함)` : tip}
                            >
                              <span className="material-symbols-outlined text-[11px]" aria-hidden>
                                {seen ? "check" : "warning"}
                              </span>
                              {label}
                              {seen ? " · 확인함" : ""}
                            </span>
                          );
                        })()}
                      </div>
                      {c?.article ? (
                        <p className="mt-0.5 text-[11.5px] text-md-on-surface-variant">
                          {c.article}
                          {c.publisher ? ` · ${c.publisher}` : ""}
                        </p>
                      ) : null}
                      {c?.snippet ? (
                        <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-md-on-surface-variant">
                          “{c.snippet}”
                        </p>
                      ) : null}
                      {b.folder && editingFolderId !== b.id ? (
                        <p className="mt-1 text-[11px] text-md-on-surface-variant">
                          📁 {b.folder}
                        </p>
                      ) : null}
                      {editingFolderId === b.id ? (
                        <div className="mt-1.5 flex items-center gap-1.5">
                          <input
                            value={folderDraft}
                            onChange={(e) => setFolderDraft(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") void commitFolder(b.id);
                              if (e.key === "Escape") setEditingFolderId(null);
                            }}
                            maxLength={100}
                            autoFocus
                            placeholder="폴더명 (비우면 해제)"
                            className="h-7 w-[180px] rounded-input border border-md-outline-variant bg-md-surface px-2 text-[12px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
                          />
                          <button
                            type="button"
                            onClick={() => void commitFolder(b.id)}
                            className="rounded-button bg-md-primary px-2 py-1 text-[11px] font-medium text-md-on-primary hover:bg-md-primary/90"
                          >
                            저장
                          </button>
                        </div>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-0.5">
                      {download ? (
                        <a
                          href={download}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label="원본 내려받기"
                          title="별표/서식 원본 내려받기"
                          className="rounded-button p-1 text-md-on-surface-variant hover:text-md-primary"
                        >
                          <span className="material-symbols-outlined text-[16px]" aria-hidden>
                            download
                          </span>
                        </a>
                      ) : null}
                      {url ? (
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label="원문 열기"
                          title="원문 새 탭에서 열기"
                          className="rounded-button p-1 text-md-on-surface-variant hover:text-md-secondary"
                        >
                          <span className="material-symbols-outlined text-[16px]" aria-hidden>
                            north_east
                          </span>
                        </a>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => {
                          setEditingFolderId(b.id);
                          setFolderDraft(b.folder ?? "");
                        }}
                        aria-label="폴더 지정"
                        title="폴더 지정/변경"
                        className="rounded-button p-1 text-md-on-surface-variant hover:text-md-primary"
                      >
                        <span className="material-symbols-outlined text-[16px]" aria-hidden>
                          folder
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => void remove(b.id)}
                        aria-label="저장 해제"
                        title="라이브러리에서 삭제"
                        className="rounded-button p-1 text-md-on-surface-variant hover:text-md-error"
                      >
                        <span className="material-symbols-outlined text-[16px]" aria-hidden>
                          delete
                        </span>
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
