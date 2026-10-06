"use client";

/**
 * TilePager — 3×3 타일을 **가로 페이지**로 넘기는 공용 페이저 (2026-10-06 분리).
 *
 * 전문가 첫 화면 기능 타일(`FeatureCards`)과 모니터링 대시보드 카드가 같은 페이징을 쓴다.
 * 스냅 스크롤 — 터치는 옆으로 밀고, 마우스는 화살표·점으로. 페이지 폭 = 컨테이너 폭이라
 * `scrollLeft / clientWidth` 가 곧 페이지 번호. 좁은 화면(<640px)은 2열.
 */

import { useMemo, useRef, useState, type ReactNode } from "react";

export const TILES_PER_PAGE = 9;

export function chunk<T>(xs: T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n));
  return out;
}

export function TilePager<T>({
  items,
  keyOf,
  render,
  ariaLabel,
  testId,
  perPage = TILES_PER_PAGE,
}: {
  items: T[];
  keyOf: (item: T) => string;
  /** 타일 하나 — 호출자가 `<li>` 안 내용을 그린다 */
  render: (item: T, opts: { active: boolean }) => ReactNode;
  ariaLabel: string;
  testId?: string;
  perPage?: number;
}) {
  const pages = useMemo(() => chunk(items, perPage), [items, perPage]);
  const ref = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(0);
  const total = pages.length;

  const go = (i: number) => {
    const el = ref.current;
    if (!el) return;
    const n = Math.max(0, Math.min(i, total - 1));
    el.scrollTo({ left: n * el.clientWidth, behavior: "smooth" });
    setPage(n);
  };
  const onScroll = () => {
    const el = ref.current;
    if (!el || !el.clientWidth) return;
    setPage(Math.round(el.scrollLeft / el.clientWidth));
  };

  const arrow =
    "absolute top-1/2 hidden h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-md-outline-variant bg-md-surface-container-lowest text-md-on-surface-variant shadow-sm transition-colors hover:border-md-primary hover:text-md-primary disabled:cursor-default disabled:opacity-25 disabled:hover:border-md-outline-variant disabled:hover:text-md-on-surface-variant sm:inline-flex";

  return (
    <div className="w-full max-w-[720px]" data-testid={testId}>
      <div className="relative">
        <div
          ref={ref}
          onScroll={onScroll}
          role="region"
          aria-roledescription="carousel"
          aria-label={ariaLabel}
          className="flex snap-x snap-mandatory overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {pages.map((pg, i) => (
            <ul
              key={i}
              aria-label={`${i + 1} / ${total} 페이지`}
              aria-hidden={i !== page}
              className="grid w-full shrink-0 snap-start grid-cols-2 gap-2 px-0.5 sm:grid-cols-3"
            >
              {pg.map((it) => (
                <li key={keyOf(it)}>{render(it, { active: i === page })}</li>
              ))}
            </ul>
          ))}
        </div>

        {total > 1 ? (
          <>
            <button type="button" aria-label="이전" disabled={page === 0}
                    onClick={() => go(page - 1)} className={arrow + " -left-11"}>
              <span className="material-symbols-outlined text-[20px]" aria-hidden>chevron_left</span>
            </button>
            <button type="button" aria-label="다음" disabled={page >= total - 1}
                    onClick={() => go(page + 1)} className={arrow + " -right-11"}>
              <span className="material-symbols-outlined text-[20px]" aria-hidden>chevron_right</span>
            </button>
          </>
        ) : null}
      </div>

      {total > 1 ? (
        <div className="mt-3 flex items-center justify-center gap-2" aria-hidden>
          {pages.map((_, i) => (
            <button key={i} type="button" tabIndex={-1} onClick={() => go(i)}
                    className={"h-1.5 rounded-full transition-all " +
                      (i === page ? "w-5 bg-md-primary" : "w-1.5 bg-md-outline-variant hover:bg-md-on-surface-variant")} />
          ))}
          <span className="ml-1 text-[11px] tabular-nums text-md-on-surface-variant">{page + 1} / {total}</span>
        </div>
      ) : null}
    </div>
  );
}
