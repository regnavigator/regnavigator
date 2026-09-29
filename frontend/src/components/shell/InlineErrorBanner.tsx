"use client";

/**
 * InlineErrorBanner — 04 §4.3, P5.9·P8.2.
 *
 * 채팅 상단 sticky 1줄. 시스템 에러(네트워크·인증·스트림 끊김)만. 도메인 에러
 * (검색 0건·인용 폐지 등)는 토스트·카드/칩으로 표시 (04 §4.4 정책).
 */

type Props = {
  message: string;
  retriable?: boolean;
  onRetry?: () => void;
  onDismiss?: () => void;
};

export function InlineErrorBanner({ message, retriable = true, onRetry, onDismiss }: Props) {
  // sticky 제거 — 헤더(sticky top-0 z-10) 뒤로 숨던 문제 해결.
  // 헤더 직후 자연 흐름으로 박혀 본문 스크롤과 함께 위로 사라짐 → 사용자가 항상 인지 가능.
  // 세로 정렬(2026-09-09 "에러박스가 위로 쏠려"): 우측 버튼(h-7)보다 한 줄 문구가 낮아
  // items-start 면 글자가 위에 붙는다 → 바깥은 center, 문구·아이콘 묶음은 버튼 높이만큼.
  return (
    <div
      role="alert"
      className="mx-6 mt-3 flex items-center justify-between gap-2 rounded border border-md-error bg-md-error-container px-3 py-1.5 text-body-sm text-md-on-error-container"
    >
      <div className="flex min-h-7 min-w-0 items-center gap-2">
        <span className="material-symbols-outlined shrink-0 text-[18px]" aria-hidden>
          error
        </span>
        <span className="min-w-0 break-words leading-snug">{message}</span>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {retriable && onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded px-2 py-1 text-body-sm font-medium text-md-on-error-container hover:bg-md-error/15"
          >
            재시도
          </button>
        ) : null}
        {onDismiss ? (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="닫기"
            className="material-symbols-outlined inline-flex h-7 w-7 items-center justify-center rounded text-[18px] hover:bg-md-error/15"
          >
            close
          </button>
        ) : null}
      </div>
    </div>
  );
}
