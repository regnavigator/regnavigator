"use client";

/**
 * FeatureCards — 기능 카드 렌더 (2026-10-02).
 *
 * 같은 레지스트리를 두 레이아웃으로 그린다:
 *  - `tiles`: 첫 화면. **3×3 타일, 가로로 넘기는 페이지**(2026-10-05 요청 — 세로로 쭉
 *            나열하면 아래쪽 기능은 스크롤해야 보이고, 몇 개가 있는지 가늠이 안 된다).
 *  - `grid` : 스레드 내 피커. 검색과 함께 쓰는 세로 스크롤 격자.
 *
 * 레이아웃만 다르고 **정의와 실행은 공유**한다(`catalog` / `useRunFeature`).
 */

import { useMemo, useRef, useState } from "react";

import type { Feature } from "@/lib/features/catalog";


/** 기능별 아이콘(`Feature.icon`). 없으면 범용 번개. */
function icon(f: Feature): string {
  return f.icon ?? "bolt";
}

export function FeatureCards({
  features,
  layout,
  onPick,
  selected,
}: {
  features: Feature[];
  layout: "tiles" | "grid";
  onPick: (f: Feature) => void;
  /**
   * 조립 모드(2026-10-02) — 고른 기능 id 를 **고른 순서대로**. 주어지면 grid
   * 카드가 번호 배지를 달고, 클릭은 "실행"이 아니라 "선택 토글"이 된다(호출자가
   * `onPick` 의 의미를 바꾼다). 순서가 곧 실행 순서라 집합이 아니라 배열이다.
   */
  selected?: string[];
}) {
  if (!features.length) {
    return (
      <p className="px-2 py-6 text-center text-[12.5px] text-md-on-surface-variant">
        해당하는 기능이 없습니다.
      </p>
    );
  }

  if (layout === "tiles") {
    return <FeatureTiles features={features} onPick={onPick} />;
  }

  // grid — **평평한 한 격자**로 그린다(2026-10-02).
  //
  // 종전엔 카테고리로 묶었는데, 카테고리마다 카드가 하나씩이라 그룹 헤더가 줄을
  // 차지하고 카드는 한 줄에 하나씩만 보였다 — 폭이 남는데 한눈에 들어오는 수가
  // 적다는 지적(실사용). 분류는 카드 안에 작은 라벨로 넣으면 충분하다.
  return (
    <ul className="grid grid-cols-2 gap-2 xl:grid-cols-3">
      {features.map((f) => {
        const order = selected ? selected.indexOf(f.id) : -1;
        const isOn = order >= 0;
        return (
        <li key={f.title}>
          <button
            type="button"
            data-feature={f.title}
            data-selected={isOn ? order + 1 : undefined}
            aria-pressed={selected ? isOn : undefined}
            onClick={() => onPick(f)}
            title={f.expects.join("\n")}
            className={
              "flex h-full w-full flex-col gap-1 rounded-[10px] border p-3 text-left transition-colors " +
              (isOn
                ? "border-md-primary bg-md-primary-container/40"
                : "border-md-outline-variant bg-md-surface-container-lowest hover:border-md-primary hover:bg-md-surface-container-low")
            }
          >
            <span className="flex items-center gap-1.5">
              {selected ? (
                <span
                  className={
                    "inline-flex h-[17px] w-[17px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold " +
                    (isOn
                      ? "bg-md-primary text-md-on-primary"
                      : "border border-md-outline-variant text-transparent")
                  }
                  aria-hidden
                >
                  {isOn ? order + 1 : "0"}
                </span>
              ) : (
                <span
                  className="material-symbols-outlined text-[16px] text-md-primary"
                  aria-hidden
                >
                  {icon(f)}
                </span>
              )}
              <span className="text-[10.5px] font-medium tracking-[0.02em] text-md-on-surface-variant">
                {f.category}
              </span>
            </span>
            <span className="text-[13px] font-semibold leading-snug text-md-on-surface">
              {f.title}
            </span>
            <span className="text-[11.5px] leading-[1.55] text-md-on-surface-variant">
              {f.subtitle}
            </span>
            {f.expects.length ? (
              <span className="sr-only">{f.expects.join(" · ")}</span>
            ) : null}
          </button>
        </li>
        );
      })}
    </ul>
  );
}

/* ─────────────────── tiles — 3×3 페이지 ─────────────────── */

const TILES_PER_PAGE = 9;

function chunk<T>(xs: T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n));
  return out;
}

/**
 * 스냅 스크롤 페이지 — 터치는 옆으로 밀고, 마우스는 화살표·점으로 넘긴다.
 * 페이지 폭은 컨테이너 폭이라 `scrollLeft / clientWidth` 가 곧 페이지 번호다.
 * 좁은 화면(<640px)은 2열로 떨어뜨린다 — 3열이면 타일이 100px 아래로 깨진다.
 */
function FeatureTiles({
  features,
  onPick,
}: {
  features: Feature[];
  onPick: (f: Feature) => void;
}) {
  const pages = useMemo(() => chunk(features, TILES_PER_PAGE), [features]);
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
    <div className="w-full max-w-[720px]" data-testid="feature-tiles">
      <div className="relative">
        <div
          ref={ref}
          onScroll={onScroll}
          role="region"
          aria-roledescription="carousel"
          aria-label="기능 목록"
          className="flex snap-x snap-mandatory overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {pages.map((pg, i) => (
            <ul
              key={i}
              aria-label={`${i + 1} / ${total} 페이지`}
              aria-hidden={i !== page}
              className="grid w-full shrink-0 snap-start grid-cols-2 gap-2 px-0.5 sm:grid-cols-3"
            >
              {pg.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    data-feature={f.title}
                    tabIndex={i === page ? 0 : -1}
                    onClick={() => onPick(f)}
                    title={f.expects.join("\n")}
                    className="flex h-full min-h-[104px] w-full flex-col gap-1 rounded-[10px] border border-md-outline-variant bg-md-surface-container-lowest p-3 text-left transition-colors hover:border-md-primary hover:bg-md-surface-container-low"
                  >
                    <span className="flex items-center gap-1.5">
                      <span
                        className="material-symbols-outlined text-[16px] text-md-primary"
                        aria-hidden
                      >
                        {icon(f)}
                      </span>
                      <span className="truncate text-[10.5px] font-medium tracking-[0.02em] text-md-on-surface-variant">
                        {f.category}
                      </span>
                    </span>
                    <span className="text-[13px] font-semibold leading-snug text-md-on-surface">
                      {f.title}
                    </span>
                    <span className="line-clamp-2 text-[11.5px] leading-[1.5] text-md-on-surface-variant">
                      {f.subtitle}
                    </span>
                    {f.expects.length ? (
                      <span className="sr-only">{f.expects.join(" · ")}</span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          ))}
        </div>

        {total > 1 ? (
          <>
            <button
              type="button"
              aria-label="이전 기능"
              disabled={page === 0}
              onClick={() => go(page - 1)}
              className={arrow + " -left-11"}
            >
              <span className="material-symbols-outlined text-[20px]" aria-hidden>
                chevron_left
              </span>
            </button>
            <button
              type="button"
              aria-label="다음 기능"
              disabled={page >= total - 1}
              onClick={() => go(page + 1)}
              className={arrow + " -right-11"}
            >
              <span className="material-symbols-outlined text-[20px]" aria-hidden>
                chevron_right
              </span>
            </button>
          </>
        ) : null}
      </div>

      {total > 1 ? (
        <div className="mt-3 flex items-center justify-center gap-2" aria-hidden>
          {pages.map((_, i) => (
            <button
              key={i}
              type="button"
              tabIndex={-1}
              onClick={() => go(i)}
              className={
                "h-1.5 rounded-full transition-all " +
                (i === page ? "w-5 bg-md-primary" : "w-1.5 bg-md-outline-variant hover:bg-md-on-surface-variant")
              }
            />
          ))}
          <span className="ml-1 text-[11px] tabular-nums text-md-on-surface-variant">
            {page + 1} / {total}
          </span>
        </div>
      ) : null}
    </div>
  );
}
