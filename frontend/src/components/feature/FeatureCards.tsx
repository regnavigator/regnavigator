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

import { TilePager } from "@/components/ui/TilePager";
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

/* ─────────────────── tiles — 3×3 페이지 (TilePager 공용) ─────────────────── */

function FeatureTiles({ features, onPick }: { features: Feature[]; onPick: (f: Feature) => void }) {
  return (
    <TilePager
      items={features}
      keyOf={(f) => f.id}
      ariaLabel="기능 목록"
      testId="feature-tiles"
      render={(f, { active }) => (
        <button
          type="button"
          data-feature={f.title}
          tabIndex={active ? 0 : -1}
          onClick={() => onPick(f)}
          title={f.expects.join("\n")}
          className="flex h-full min-h-[104px] w-full flex-col gap-1 rounded-[10px] border border-md-outline-variant bg-md-surface-container-lowest p-3 text-left transition-colors hover:border-md-primary hover:bg-md-surface-container-low"
        >
          <span className="flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[16px] text-md-primary" aria-hidden>{icon(f)}</span>
            <span className="truncate text-[10.5px] font-medium tracking-[0.02em] text-md-on-surface-variant">{f.category}</span>
          </span>
          <span className="text-[13px] font-semibold leading-snug text-md-on-surface">{f.title}</span>
          <span className="line-clamp-2 text-[11.5px] leading-[1.5] text-md-on-surface-variant">{f.subtitle}</span>
          {f.expects.length ? <span className="sr-only">{f.expects.join(" · ")}</span> : null}
        </button>
      )}
    />
  );
}
