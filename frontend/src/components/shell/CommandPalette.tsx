"use client";

/**
 * CommandPalette — Ctrl/Cmd+K 커맨드 팔레트.
 *
 * 문제: 대화 검색·새 대화·라이브러리가 사이드바에 흩어져 파워유저 동선이 김.
 * 해결: 한 입력창에서 (1) 빠른 액션(새 대화·저장한 근거), (2) 대화 검색
 * (제목+본문, /chat/search 재활용) → ↑↓/Enter 키보드 탐색.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { BookmarksDialog } from "@/components/chat/BookmarksDialog";
import {
  searchThreads,
  searchThreadsByContent,
  type Thread,
} from "@/lib/client/threads";
import {
  listRecentArticles,
  type RecentArticle,
} from "@/lib/store/recentArticles";

type Item =
  | { kind: "action"; id: string; label: string; icon: string; run: () => void }
  | {
      kind: "thread";
      id: string;
      label: string;
      icon: string;
      run: () => void;
      /** 본문 검색으로 걸린 경우 매칭 발췌 — 제목이 비슷한 대화를 구분한다. */
      snippet?: string;
    };

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [threads, setThreads] = useState<Thread[]>([]);
  const [active, setActive] = useState(0);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [recent, setRecent] = useState<RecentArticle[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // 전역 Ctrl/Cmd+K — 입력 중이어도 동작(브라우저 검색 가로채기).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // 열릴 때 초기화 + 포커스 + 최근 열람 로드.
  useEffect(() => {
    if (open) {
      setQ("");
      setThreads([]);
      setActive(0);
      setRecent(listRecentArticles());
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  // 검색 — 제목(로드 목록) + 본문(백엔드) 병합, 250ms 디바운스.
  useEffect(() => {
    if (!open) return;
    const query = q.trim();
    if (query.length < 1) {
      setThreads([]);
      return;
    }
    const ac = new AbortController();
    const t = window.setTimeout(() => {
      void (async () => {
        const [all, byContent] =
          query.length >= 2
            ? await Promise.all([
                searchThreads({ limit: 100, signal: ac.signal }),
                searchThreadsByContent(query, { signal: ac.signal }),
              ])
            : [await searchThreads({ limit: 100, signal: ac.signal }), []];
        const lower = query.toLowerCase();
        const byId = new Map<string, Thread>();
        for (const th of all)
          if ((th.title ?? "").toLowerCase().includes(lower)) byId.set(th.id, th);
        for (const th of byContent) if (!byId.has(th.id)) byId.set(th.id, th);
        setThreads([...byId.values()].slice(0, 8));
        setActive(0);
      })();
    }, 250);
    return () => {
      window.clearTimeout(t);
      ac.abort();
    };
  }, [q, open]);

  const goThread = useCallback(
    (id: string) => {
      setOpen(false);
      router.replace(`/new?threadId=${id}`);
    },
    [router],
  );

  const items = useMemo<Item[]>(() => {
    const actions: Item[] = [
      {
        kind: "action",
        id: "new",
        label: "새 대화 시작",
        icon: "add_comment",
        run: () => {
          setOpen(false);
          router.push("/new");
        },
      },
      {
        kind: "action",
        id: "bookmarks",
        label: "저장한 근거 열기",
        icon: "bookmarks",
        run: () => {
          setOpen(false);
          setLibraryOpen(true);
        },
      },
    ];
    const lower = q.trim().toLowerCase();
    const visibleActions = lower
      ? actions.filter((a) => a.label.toLowerCase().includes(lower))
      : actions;
    const threadItems: Item[] = threads.map((t) => ({
      kind: "thread",
      id: t.id,
      label: t.title || "새 대화",
      icon: "chat_bubble",
      run: () => goThread(t.id),
      snippet: t.match_snippet,
    }));
    // 빈 검색 상태 — 최근 열람 조문(인스펙터에서 본 근거)을 원문 링크로 재진입.
    const recentItems: Item[] =
      !lower && recent.length
        ? recent
            .filter((r) => r.url)
            .slice(0, 5)
            .map((r) => ({
              kind: "thread" as const,
              id: `recent-${r.id}`,
              label: `${r.title}${r.article ? ` ${r.article}` : ""}`,
              icon: "history",
              run: () => {
                setOpen(false);
                window.open(r.url!, "_blank", "noopener,noreferrer");
              },
            }))
        : [];
    return [...visibleActions, ...recentItems, ...threadItems];
  }, [q, threads, recent, router, goThread]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      items[active]?.run();
    }
  };

  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="top-[20%] max-w-md translate-y-0 p-0">
          <DialogTitle className="sr-only">커맨드 팔레트</DialogTitle>
          <div className="flex items-center gap-2 border-b border-md-outline-variant px-3">
            <span
              className="material-symbols-outlined text-[18px] text-md-on-surface-variant"
              aria-hidden
            >
              search
            </span>
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="대화 검색 또는 명령…"
              aria-label="커맨드 팔레트 검색"
              className="h-11 w-full bg-transparent text-[14px] text-md-on-surface placeholder:text-md-on-surface-variant focus:outline-none"
            />
            <kbd className="rounded bg-md-surface-container px-1.5 py-0.5 text-[10px] text-md-on-surface-variant">
              ESC
            </kbd>
          </div>
          <ul className="max-h-[320px] overflow-y-auto p-1.5" role="listbox">
            {items.length === 0 ? (
              <li className="px-3 py-6 text-center text-[12px] text-md-on-surface-variant">
                결과 없음
              </li>
            ) : (
              items.map((it, i) => (
                <li key={`${it.kind}-${it.id}`} role="option" aria-selected={i === active}>
                  <button
                    type="button"
                    onClick={it.run}
                    onMouseEnter={() => setActive(i)}
                    className={
                      "flex w-full items-start gap-2.5 rounded px-3 py-2 text-left text-[13px] transition-colors " +
                      (i === active
                        ? "bg-md-surface-container text-md-on-surface"
                        : "text-md-on-surface-variant hover:bg-md-surface-container-low")
                    }
                  >
                    <span
                      className="material-symbols-outlined mt-0.5 text-[16px]"
                      aria-hidden
                    >
                      {it.icon}
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{it.label}</span>
                      {it.kind === "thread" && it.snippet ? (
                        <span className="truncate text-[11px] text-md-on-surface-variant/80">
                          {it.snippet}
                        </span>
                      ) : null}
                    </span>
                    {it.kind === "action" ? (
                      <span className="ml-auto mt-0.5 text-[10px] text-md-on-surface-variant/70">
                        명령
                      </span>
                    ) : null}
                  </button>
                </li>
              ))
            )}
          </ul>
        </DialogContent>
      </Dialog>
      <BookmarksDialog open={libraryOpen} onOpenChange={setLibraryOpen} />
    </>
  );
}
