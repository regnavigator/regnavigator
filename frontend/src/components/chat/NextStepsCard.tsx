"use client";

/**
 * NextStepsCard — 답변 본문 끝 `<next_steps>` 마커에서 추출한 후속 질문.
 *
 * - parseNextStepsMarker가 본문 파싱 + 마커 strip 담당 + `kind` 추론.
 * - `kind:"chat"` → 클릭 시 ChatInput prefill(`onPick`).
 * - `kind:"report"` → 클릭 시 즉시 report-mode dispatch(`onTriggerReport`,
 *   ~5분 결정적 파이프라인). 카드 시각도 차별화(보고서 라벨/아이콘).
 * - host가 두 핸들러를 분리해 받음 — 카드는 item 단위로 라우팅만.
 */

import type { NextStep } from "@/lib/parse/nextSteps";

type Props = {
  items: NextStep[];
  /** `kind:"chat"` 항목 클릭 시 — host가 ChatInput prefill 등 결정 */
  onPick: (prompt: string) => void;
  /** `kind:"report"` 항목 클릭 시 — host가 report-mode dispatch (purpose 동반) */
  onTriggerReport?: (prompt: string, purpose?: string) => void;
};

export function NextStepsCard({ items, onPick, onTriggerReport }: Props) {
  if (items.length === 0) return null;
  return (
    <section
      aria-label="이어서 물어볼 만한 것"
      className="mt-3 border-y border-md-outline-variant"
    >
      <div className="flex items-center gap-2 px-1 py-2">
        <span
          className="material-symbols-outlined text-[14px] text-md-on-surface-variant"
          aria-hidden
        >
          arrow_forward
        </span>
        <span className="text-label-caps text-md-on-surface-variant">
          이어서 물어볼 만한 것
        </span>
      </div>
      <ul className="divide-y divide-md-outline-variant border-t border-md-outline-variant">
        {items.map((it, i) => {
          const isReport = it.kind === "report";
          // report 항목은 onTriggerReport, chat은 onPick. onTriggerReport 미연결
          // 시 fallback으로 onPick(prefill) — 후방호환.
          const handleClick = isReport
            ? onTriggerReport
              ? () => onTriggerReport(it.prompt, it.purpose)
              : () => onPick(it.prompt)
            : () => onPick(it.prompt);
          return (
            <li key={`${i}-${it.prompt}`}>
              <button
                type="button"
                onClick={handleClick}
                className="group flex w-full items-start justify-between gap-3 px-3 py-2.5 text-left transition-colors hover:bg-md-surface-container-low active:bg-md-surface-container"
              >
                <span className="flex min-w-0 flex-col gap-0.5 ">
                  <span className="flex items-center gap-1.5">
                    <span
                      className={
                        "text-[13.5px] font-medium leading-snug " +
                        (isReport ? "text-md-primary" : "text-md-on-surface")
                      }
                    >
                      {it.title}
                    </span>
                    {isReport ? (
                      <span className="rounded-pill bg-md-primary-fixed px-1.5 py-0.5 text-[10px] font-semibold text-md-on-primary-fixed-variant">
                        보고서 · 5~20분
                      </span>
                    ) : null}
                  </span>
                  <span className="truncate text-[12px] leading-snug text-md-on-surface-variant">
                    {it.prompt}
                  </span>
                </span>
                <span
                  className="material-symbols-outlined mt-0.5 shrink-0 text-[16px] text-md-on-surface-variant/60"
                  aria-hidden
                >
                  {isReport ? "summarize" : "north_east"}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
