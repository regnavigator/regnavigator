"use client";

/**
 * ThreadLoadingBanner — 04 §4.2, P6.1.4.
 *
 * 기존 thread 로딩 중 sticky 1줄. 풀화면 spinner overlay 금지(00 §6 F-S2).
 */

export function ThreadLoadingBanner({ message = "대화를 불러오는 중…" }: { message?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="sticky top-0 z-[1] flex items-center gap-2 border-b border-md-outline-variant bg-md-surface-container-low px-4 py-2 text-body-sm text-md-on-surface-variant"
    >
      <span
        className="material-symbols-outlined animate-md-pulse text-[16px]"
        aria-hidden
      >
        progress_activity
      </span>
      <span>{message}</span>
    </div>
  );
}
