"use client";

/**
 * App-level error boundary — Next.js가 자동 사용. 컴포넌트 throw 시 fallback.
 */

import { useEffect } from "react";
import Link from "next/link";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[app] uncaught", error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-md-surface px-6">
      <div className="w-full max-w-sm rounded-card border border-md-outline-variant bg-md-surface-container-low p-6 text-center">
        <div
          className="mx-auto mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-md-error-container text-md-on-error-container"
          aria-hidden
        >
          <span className="material-symbols-outlined text-[24px]">error</span>
        </div>
        <h1 className="text-h2 text-md-on-surface">문제가 발생했어요</h1>
        <p className="mt-2 text-body-sm text-md-on-surface-variant">
          페이지를 그리는 중 오류가 발생했습니다. 다시 시도해 주세요.
        </p>
        {error.digest ? (
          <p className="mt-3 font-mono text-[10px] text-md-on-surface-variant">
            ref: {error.digest}
          </p>
        ) : null}
        <div className="mt-5 flex justify-center gap-2">
          <button
            type="button"
            onClick={() => reset()}
            className="inline-flex h-9 items-center gap-1 rounded bg-md-primary px-4 text-body-sm font-medium text-md-on-primary transition-opacity duration-[var(--motion-fast)] hover:opacity-90 active:opacity-80"
          >
            <span className="material-symbols-outlined text-[16px]" aria-hidden>
              refresh
            </span>
            다시 시도
          </button>
          <Link
            href="/"
            className="inline-flex h-9 items-center rounded border border-md-outline-variant px-4 text-body-sm text-md-on-surface hover:bg-md-surface-container-low"
          >
            홈으로
          </Link>
        </div>
      </div>
    </div>
  );
}
