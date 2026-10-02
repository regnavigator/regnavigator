"use client";

/**
 * FeatureCards — 기능 카드 렌더 (2026-10-02).
 *
 * 같은 레지스트리를 두 레이아웃으로 그린다:
 *  - `list` : 첫 화면. 세로 나열, 설명이 길게 들어간다.
 *  - `grid` : 스레드 내 피커. 카테고리별 격자 — 기능이 20개가 돼도 버틴다.
 *
 * 레이아웃만 다르고 **정의와 실행은 공유**한다(`catalog` / `useRunFeature`).
 */

import type { Feature } from "@/lib/features/catalog";

const CATEGORY_ICON: Record<string, string> = {
  // 전문가 — 기능 단위
  "규제 경로 분해": "checklist",
  "서식 작성": "description",
  "기밀 검토": "lock",
  "문서 검토": "attach_file",
  "판례 검토": "balance",
  "조문 변동": "difference",
  "규정 점검": "rule",
  "의무 정리": "fact_check",
  "지역 비교": "map",
  유권해석: "quick_reference_all",
  "인용 검증": "verified",
  "제재 가늠": "scale",
  "개정 추적": "update",
  "영향 분석": "hub",
  "서면 작성": "draft",
  // 일반 — 상황 단위
  "생활·계약": "home_work",
  일터: "work",
  "창업·영업": "storefront",
  행정처분: "gavel",
  // 모니터링 — 종전엔 빠져 있어 전부 fallback(bolt)으로 그려졌다.
  "대상 정의": "track_changes",
  "자료 검토": "upload_file",
  "변경 추적": "notifications_active",
};

function icon(f: Feature): string {
  return CATEGORY_ICON[f.category] ?? "bolt";
}

export function FeatureCards({
  features,
  layout,
  onPick,
  selected,
}: {
  features: Feature[];
  layout: "list" | "grid";
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

  if (layout === "list") {
    return (
      <ul className="w-full max-w-[560px] divide-y divide-md-outline-variant/70 border-y border-md-outline-variant/70">
        {features.map((f) => (
          <li key={f.title}>
            <button
              type="button"
              data-feature={f.title}
              onClick={() => onPick(f)}
              className="group relative flex w-full items-center gap-3 px-1 py-3 text-left transition-colors hover:bg-md-surface-container-low"
            >
              <span
                className="material-symbols-outlined shrink-0 text-[19px] text-md-on-surface-variant group-hover:text-md-primary"
                aria-hidden
              >
                {icon(f)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium text-md-on-surface">
                  {f.title}
                </span>
                <span className="block truncate text-[12px] text-md-on-surface-variant">
                  {f.category} · {f.subtitle}
                </span>
              </span>
              <span
                className="material-symbols-outlined shrink-0 text-[18px] text-md-on-surface-variant/50 group-hover:text-md-primary"
                aria-hidden
              >
                chevron_right
              </span>

              {/* 호버 말풍선 — 이 기능으로 무엇을 얻는지. 설명을 아래에 블록으로
                  따로 두면 카드와 같은 말을 두 번 하게 된다(2026-10-02 지적).
                  좁은 화면(터치)에서는 숨긴다 — 호버가 없는 환경이라 가려지기만 한다. */}
              {f.expects.length ? (
                <span
                  role="tooltip"
                  data-tooltip={f.title}
                  className="pointer-events-none absolute left-full top-1/2 z-20 ml-3 hidden w-[260px] -translate-y-1/2 rounded-[10px] border border-md-outline-variant bg-md-surface-container-lowest px-3 py-2 opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100 lg:block"
                >
                  <span className="mb-1 block text-[10.5px] font-semibold tracking-[0.02em] text-md-on-surface-variant">
                    {f.category}
                  </span>
                  {f.expects.map((e) => (
                    <span key={e} className="mt-0.5 flex gap-1.5">
                      <span
                        className="material-symbols-outlined mt-[1px] text-[13px] text-md-primary"
                        aria-hidden
                      >
                        check_small
                      </span>
                      <span className="text-[11.5px] leading-[1.5] text-md-on-surface-variant">
                        {e}
                      </span>
                    </span>
                  ))}
                </span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    );
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
