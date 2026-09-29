"use client";

/**
 * ProcedureTimeline — 인허가 절차 답변의 순서 단계를 체크 가능한 세로 타임라인으로.
 *
 * 답변 마크다운의 *최상위 순서 목록*(1. 2. 3.)을 단계로 추출(≥3개일 때만 노출).
 * RA/QA 가 진행 절차의 어디까지 왔는지 체크(로컬 저장, 단계 해시 키). 프론트 자체완결.
 */

import { useMemo, useState } from "react";

/** 마크다운에서 최상위 순서 목록 항목 텍스트를 추출. */
export function extractProcedureSteps(md: string): string[] {
  if (!md) return [];
  const steps: string[] = [];
  for (const line of md.split("\n")) {
    const m = line.match(/^\s{0,3}\d+\.\s+(.+)$/);
    if (m && m[1]) {
      const text = m[1]
        .replace(/\*\*|__|~~|`/g, "")
        .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1") // [텍스트](url) → 텍스트
        .trim();
      if (text) steps.push(text);
    }
  }
  return steps;
}

function hashKey(steps: string[]): string {
  const s = steps.join("|");
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) | 0;
  return "medi_tl_" + (h >>> 0).toString(36);
}

export function ProcedureTimeline({ steps }: { steps: string[] }) {
  const storageKey = useMemo(() => hashKey(steps), [steps]);
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState<Set<number>>(() => {
    if (typeof window === "undefined") return new Set();
    try {
      const raw = window.localStorage.getItem(storageKey);
      return new Set<number>(raw ? (JSON.parse(raw) as number[]) : []);
    } catch {
      return new Set();
    }
  });

  const toggle = (i: number) => {
    setDone((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      try {
        window.localStorage.setItem(storageKey, JSON.stringify([...next]));
      } catch {
        /* localStorage 불가 — 무시(세션 한정) */
      }
      return next;
    });
  };

  const doneCount = steps.filter((_, i) => done.has(i)).length;

  return (
    <section
      aria-label="절차 타임라인"
      className="mt-2 overflow-hidden rounded-card border border-md-outline-variant bg-md-surface-container-low"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-md-surface-container"
      >
        <span className="material-symbols-outlined text-[16px] text-md-primary" aria-hidden>
          timeline
        </span>
        <span className="text-label-caps text-md-on-surface-variant">
          절차 타임라인 · {steps.length}단계
          {doneCount > 0 ? ` · ${doneCount}/${steps.length} 완료` : ""}
        </span>
        <span
          className={
            "material-symbols-outlined ml-auto text-[16px] text-md-on-surface-variant transition-transform duration-300 " +
            (open ? "rotate-180" : "")
          }
          aria-hidden
        >
          expand_more
        </span>
      </button>

      <div
        className={
          "grid transition-[grid-template-rows] duration-300 ease-out " +
          (open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")
        }
      >
        <div className="overflow-hidden">
          <ol className="flex flex-col px-4 py-3">
            {steps.map((s, i) => {
              const isDone = done.has(i);
              const isLast = i === steps.length - 1;
              return (
                <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
                  {!isLast ? (
                    <span
                      className="absolute left-[11px] top-6 h-[calc(100%-1.25rem)] w-px bg-md-outline-variant"
                      aria-hidden
                    />
                  ) : null}
                  <button
                    type="button"
                    onClick={() => toggle(i)}
                    aria-pressed={isDone}
                    aria-label={`${i + 1}단계 ${isDone ? "완료 해제" : "완료 표시"}`}
                    className={
                      "z-10 inline-flex size-6 shrink-0 items-center justify-center rounded-full border-2 text-[11px] font-semibold transition-colors " +
                      (isDone
                        ? "border-md-primary bg-md-primary text-md-on-primary"
                        : "border-md-outline-variant bg-md-surface text-md-on-surface-variant hover:border-md-primary")
                    }
                  >
                    {isDone ? (
                      <span className="material-symbols-outlined text-[15px]" aria-hidden>
                        check
                      </span>
                    ) : (
                      i + 1
                    )}
                  </button>
                  <span
                    className={
                      "pt-0.5 text-[14px] leading-relaxed " +
                      (isDone
                        ? "text-md-on-surface-variant line-through"
                        : "text-md-on-surface")
                    }
                  >
                    {s}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}
