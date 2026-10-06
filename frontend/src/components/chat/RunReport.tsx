"use client";

/**
 * RunReport — 연계 실행 1회를 **보고서 한 편**으로 (2026-10-06).
 *
 * 사용자 요구: "연계로 질의했으니 하나의 종합적인 보고서를 보는 느낌" — 심층 보고서와는
 * 다른 개념(그 자리에서 바로 보이는 것). 단계 턴 = 절(section). 중간 말풍선 없음, 종합
 * 턴 없음. 각 절은 기존 `Turn` 컴포넌트가 그리되 사용자 말풍선만 절 머리로 바꾼다.
 */

import { useCallback, useMemo } from "react";
import { toast } from "sonner";

import { Turn as TurnView } from "@/components/chat/Turn";
import { downloadFromMemory } from "@/lib/client/reports";
import { runReportMarkdown } from "@/lib/export/runReport";
import type { Turn } from "@/lib/store/types";

type Props = {
  runId: string;
  name?: string;
  total: number;
  turns: Turn[];
  /** 마지막 턴이 아직 돌고 있으면 그 절에 스트리밍 표시 */
  activeTurnId?: string | null;
  liveProgress?: string | null;
  liveResults?: React.ComponentProps<typeof TurnView>["liveResults"];
  onUseAsForm?: (articleKey: string, title: string) => void;
  onResume?: (v: unknown) => void;
  /** 종점 기능 버튼 — 마지막 단계가 서면/서식일 때 호스트가 준다 */
  endAction?: { label: string; icon: string; onClick: () => void } | null;
};

export function RunReport({
  runId, name, total, turns, activeTurnId, liveProgress, liveResults,
  onUseAsForm, onResume, endAction,
}: Props) {
  const done = turns.filter((t) => t.status === "done").length;
  const running = turns.some((t) => t.status === "running" || t.id === activeTurnId);
  const date = useMemo(() => new Date(turns[0]?.started_at ?? Date.now()), [turns]);
  const ymd = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

  const save = useCallback(() => {
    const md = runReportMarkdown({ name, turns, date });
    const fname = `${(name || "기능연계 보고서").replace(/[\\/:*?"<>|]+/g, " ").trim()} ${ymd}.md`;
    downloadFromMemory(fname, md);
    toast.success("보고서를 저장했습니다", { description: fname });
  }, [name, turns, date, ymd]);

  return (
    <section
      data-testid="run-report"
      data-run={runId}
      aria-label={name ?? "기능연계 보고서"}
      className="flex flex-col gap-3 rounded-[14px] border border-md-outline-variant bg-md-surface-container-lowest p-4 sm:p-5"
    >
      {/* 헤더 — 제목 · 단계 수 · 날짜 · 목차 */}
      <header className="flex flex-col gap-2 border-b border-md-outline-variant pb-3">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-[20px] text-md-primary" aria-hidden>summarize</span>
          <h2 className="min-w-0 flex-1 truncate text-[15px] font-bold text-md-on-surface">
            {name ?? "기능연계"}
          </h2>
          <span className="shrink-0 text-[11.5px] tabular-nums text-md-on-surface-variant">
            {done}/{total}단계 · {ymd}
          </span>
        </div>
        <ol className="flex flex-wrap gap-1.5" aria-label="목차">
          {turns.map((t, i) => {
            const st = t.status === "done" ? "done" : t.status === "error" ? "error" : "running";
            return (
              <li key={t.id}>
                <a
                  href={`#run-${runId}-${i}`}
                  className={
                    "inline-flex items-center gap-1 rounded-pill border px-2 py-0.5 text-[11px] " +
                    (st === "done"
                      ? "border-md-outline-variant text-md-on-surface-variant hover:border-md-primary hover:text-md-primary"
                      : st === "error"
                        ? "border-md-error/60 text-md-error"
                        : "border-md-primary text-md-primary")
                  }
                >
                  <span className="material-symbols-outlined text-[12px]" aria-hidden>
                    {st === "done" ? "check_circle" : st === "error" ? "error" : "progress_activity"}
                  </span>
                  {i + 1}. {t.feature?.title ?? "질문"}
                </a>
              </li>
            );
          })}
          {Array.from({ length: Math.max(0, total - turns.length) }).map((_, k) => (
            <li key={`todo-${k}`} className="inline-flex items-center gap-1 rounded-pill border border-dashed border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant/70">
              {turns.length + k + 1}. …
            </li>
          ))}
        </ol>
      </header>

      {/* 절 — 단계마다 */}
      {turns.map((t, i) => (
        <article key={t.id} id={`run-${runId}-${i}`} data-run-section={i} className="flex flex-col gap-2 scroll-mt-20">
          <h3 className="flex items-center gap-2 border-l-[3px] border-md-primary pl-2.5 text-[14px] font-semibold text-md-on-surface">
            <span className="material-symbols-outlined text-[16px] text-md-primary" aria-hidden>
              {t.feature?.icon ?? "bolt"}
            </span>
            {i + 1}. {t.feature?.title ?? "질문"}
            {t.status === "running" || t.id === activeTurnId ? (
              <span className="ml-auto text-[11px] font-normal text-md-primary">진행 중</span>
            ) : t.status === "error" ? (
              <span className="ml-auto text-[11px] font-normal text-md-error">오류</span>
            ) : null}
          </h3>
          <TurnView
            turn={t}
            sectionMode
            onUseAsForm={onUseAsForm}
            onResume={onResume}
            streamingActive={t.id === activeTurnId}
            liveProgress={t.id === activeTurnId ? liveProgress ?? null : null}
            liveResults={t.id === activeTurnId ? liveResults ?? null : null}
          />
        </article>
      ))}

      {/* 하단 — 종점·저장 */}
      {!running ? (
        <footer className="flex flex-wrap items-center gap-2 border-t border-md-outline-variant pt-3">
          {endAction ? (
            <button type="button" onClick={endAction.onClick} data-testid="run-end-action"
                    className="inline-flex items-center gap-1.5 rounded-pill bg-md-primary px-3.5 py-1.5 text-[12.5px] font-semibold text-md-on-primary">
              <span className="material-symbols-outlined text-[16px]" aria-hidden>{endAction.icon}</span>
              {endAction.label}
            </button>
          ) : null}
          <button type="button" onClick={save} data-testid="run-save-md"
                  className="inline-flex items-center gap-1.5 rounded-pill border border-md-outline-variant px-3.5 py-1.5 text-[12.5px] font-medium text-md-on-surface-variant hover:border-md-primary hover:text-md-primary">
            <span className="material-symbols-outlined text-[16px]" aria-hidden>download</span>
            보고서로 저장 (.md)
          </button>
        </footer>
      ) : null}
    </section>
  );
}
