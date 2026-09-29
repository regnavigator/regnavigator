"use client";

/**
 * ThreadTitleHeader — 본문 상단 sticky 한 줄.
 *
 * 좌측: 사이드바 닫힘 시 ≡ 토글 (펼치기)
 * 중앙: 현재 thread 제목 + ✏ inline edit (Enter commit, Esc 취소)
 * 우측: RightPanel mode 활성 시 ↔ 토글
 *
 * thread metadata는 getThread()로 fetch. 자동 제목(R7) 갱신 이벤트 청취.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { NotificationBell } from "@/components/shell/NotificationBell";
import {
  getThread,
  renameThread,
  THREAD_LIST_CHANGED_EVENT,
  type Thread,
} from "@/lib/client/threads";

type Props = {
  threadId: string;
  threadsOpen: boolean;
  onOpenThreads: () => void;
  rightPanelToggle: { open: boolean; onToggle: () => void };
};

export function ThreadTitleHeader({
  threadId,
  threadsOpen,
  onOpenThreads,
  rightPanelToggle,
}: Props) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    const t = await getThread(threadId);
    setThread(t);
  }, [threadId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // 자동 제목(R7)이나 다른 곳에서 rename 했을 때 동기화
  useEffect(() => {
    const handler = () => void reload();
    window.addEventListener(THREAD_LIST_CHANGED_EVENT, handler);
    return () => window.removeEventListener(THREAD_LIST_CHANGED_EVENT, handler);
  }, [reload]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  function startEdit() {
    if (!thread) return;
    setDraft(thread.title);
    setEditing(true);
  }

  async function commit() {
    if (!thread) return;
    const next = draft.trim();
    setEditing(false);
    if (!next || next === thread.title) return;
    setThread({ ...thread, title: next });
    try {
      await renameThread(threadId, next);
    } catch (err) {
      console.error("[ThreadTitleHeader] rename failed", err);
      // rollback — 원본 다시 fetch
      void reload();
    }
  }

  function cancel() {
    setEditing(false);
    setDraft("");
  }

  return (
    <header
      className="sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 bg-md-surface px-3"
    >
      {!threadsOpen ? (
        <button
          type="button"
          onClick={onOpenThreads}
          aria-label="Threads 패널 열기"
          title="Threads 패널 열기"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container-low hover:text-md-on-surface"
        >
          <span className="material-symbols-outlined text-[20px]" aria-hidden>
            left_panel_open
          </span>
        </button>
      ) : null}

      <div className="flex min-w-0 flex-1 items-center gap-2">
        {editing ? (
          <input
            ref={inputRef}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => void commit()}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void commit();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancel();
              }
            }}
            className="h-7 min-w-0 flex-1 border border-md-outline-variant bg-md-surface px-2 text-[14px] font-medium text-md-on-surface outline-none focus:border-md-primary"
          />
        ) : (
          <button
            type="button"
            onClick={startEdit}
            title="제목 수정"
            className="group flex min-w-0 items-center gap-2 px-1 py-1 text-left"
          >
            <span
              className="truncate text-[16px] font-bold text-md-on-surface"
              style={{ letterSpacing: "-0.015em" }}
            >
              {thread?.title ?? "…"}
            </span>
            <span
              className="material-symbols-outlined shrink-0 text-[14px] text-md-on-surface-variant opacity-0 transition-colors group-hover:opacity-100 group-hover:text-md-primary"
              aria-hidden
            >
              edit
            </span>
          </button>
        )}
      </div>

      <NotificationBell />
      <button
        type="button"
        onClick={rightPanelToggle.onToggle}
        aria-pressed={rightPanelToggle.open}
        aria-label={rightPanelToggle.open ? "오른쪽 패널 닫기" : "오른쪽 패널 열기"}
        title={rightPanelToggle.open ? "오른쪽 패널 닫기" : "오른쪽 패널 열기"}
        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container-low hover:text-md-on-surface data-[on=true]:text-md-on-surface"
        data-on={rightPanelToggle.open}
      >
        <span className="material-symbols-outlined text-[20px]" aria-hidden>
          {rightPanelToggle.open ? "right_panel_close" : "right_panel_open"}
        </span>
      </button>
    </header>
  );
}
