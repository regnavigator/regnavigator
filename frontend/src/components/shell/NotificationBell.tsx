"use client";

/**
 * NotificationBell — 헤더 벨 알림 센터.
 *
 * 문제: 개정 알림(저장한 근거의 시행일 변경)이 라이브러리를 *열어야만* 보였다.
 * 해결: 마운트 시 1회 /bookmarks/amendments 체크 → 벨 배지 + 팝오버 목록.
 * 자체완결(BookmarksDialog 자체 호스팅) — 어느 헤더에나 꽂을 수 있음.
 */

import { useEffect, useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { BookmarksDialog } from "@/components/chat/BookmarksDialog";
import { type Amendment, getBookmarkAmendments } from "@/lib/client/bookmarks";

export function NotificationBell() {
  const [amendments, setAmendments] = useState<Amendment[]>([]);
  const [libraryOpen, setLibraryOpen] = useState(false);

  useEffect(() => {
    // 세션당 과도 호출 방지 — 마운트 1회(헤더는 상시 마운트라 사실상 세션 1회).
    void getBookmarkAmendments().then(setAmendments);
  }, []);

  const n = amendments.length;

  return (
    <>
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            data-tour="bell"
            aria-label={n > 0 ? `알림 ${n}건 — 저장한 근거 개정됨` : "알림 없음"}
            title={n > 0 ? `저장한 근거 ${n}건 개정됨` : "알림"}
            className="relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container-low hover:text-md-on-surface"
          >
            <span className="material-symbols-outlined text-[20px]" aria-hidden>
              {n > 0 ? "notifications_active" : "notifications"}
            </span>
            {n > 0 ? (
              <span
                aria-hidden
                className="absolute right-0.5 top-0.5 inline-flex min-w-[16px] items-center justify-center rounded-pill bg-md-error px-1 text-[10px] font-bold leading-4 text-md-on-error"
              >
                {n > 9 ? "9+" : n}
              </span>
            ) : null}
          </button>
        </PopoverTrigger>
        <PopoverContent side="bottom" align="end" className="w-[320px] p-0">
          <div className="border-b border-md-outline-variant/60 px-3 py-2">
            <p className="text-[12px] font-semibold text-md-on-surface">알림</p>
          </div>
          {n === 0 ? (
            <p className="px-3 py-6 text-center text-[12px] text-md-on-surface-variant">
              새 알림이 없습니다.
              <br />
              저장한 근거의 법령이 개정되면 여기에 표시됩니다.
            </p>
          ) : (
            <>
              <ul className="max-h-[280px] overflow-y-auto">
                {amendments.map((a) => (
                  <li
                    key={a.bookmark_id}
                    className="border-b border-md-outline-variant/40 px-3 py-2 last:border-b-0"
                  >
                    <p className="flex items-center gap-1 text-[12px] font-medium text-md-on-surface">
                      <span
                        className="material-symbols-outlined text-[13px] text-md-error"
                        aria-hidden
                      >
                        warning
                      </span>
                      <span className="min-w-0 truncate" title={a.title ?? ""}>
                        {a.title ?? a.citation_id}
                      </span>
                    </p>
                    <p className="mt-0.5 text-[11px] text-md-on-surface-variant">
                      {a.kind === "repealed"
                        ? "폐지됨 — 승계 법령 확인 필요"
                        : a.kind === "pending"
                          ? "개정 예정 — 변경 내용 확인 필요"
                          : `시행일 ${a.saved_date ?? "?"} → ${a.current_date ?? "?"} · 원문 확인 필요`}
                    </p>
                  </li>
                ))}
              </ul>
              <div className="border-t border-md-outline-variant/60 p-2">
                <button
                  type="button"
                  onClick={() => setLibraryOpen(true)}
                  className="w-full rounded-button bg-md-surface-container px-3 py-1.5 text-[12px] font-medium text-md-on-surface transition-colors hover:bg-md-surface-container-high"
                >
                  저장한 근거 라이브러리 열기
                </button>
              </div>
            </>
          )}
        </PopoverContent>
      </Popover>
      <BookmarksDialog open={libraryOpen} onOpenChange={setLibraryOpen} />
    </>
  );
}
