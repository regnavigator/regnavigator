"use client";

/**
 * StepCarousel — 03 §4 (rev). StepCard stack을 *한 칸 carousel*로 교체.
 *
 * 사용자 요구: 진행 단계가 채팅창에 누적되어 공간을 너무 차지함. 한 칸으로 압축하고
 * `< / >`로 이전/다음 step 탐색.
 *
 * 동작:
 *  - 기본 *최신 step(running 또는 마지막 done)* 표시. autoFollow=true.
 *  - 사용자가 `<` `>` 또는 dot 클릭 → autoFollow=false (수동 모드).
 *  - "최신으로" 버튼 또는 헤더 카운터 클릭 → autoFollow=true 재활성 + 마지막 step으로.
 *  - 새 step 도착 시 autoFollow=true면 자동 이동.
 *  - 단일 step이면 nav 컨트롤 숨김.
 *
 * 시각:
 *  - StepCard의 펼침 본문 그대로 재사용 (도구·쿼리·결과·오류·발견한 출처).
 *  - 헤더: 상태 dot/아이콘 · label · 소요 시간 · 카운터(클릭=최신 복귀) · `<` `>` 버튼.
 *  - aria-live="polite" 외곽 (P6.2.7).
 */

import { useEffect, useRef, useState } from "react";
import type { Step } from "@/lib/store/types";
import { useRightPanel } from "@/lib/store/rightPanel";

type Props = {
  steps: Step[];
};

export function StepCarousel({ steps }: Props) {
  const [index, setIndex] = useState(() => Math.max(0, steps.length - 1));
  const [autoFollow, setAutoFollow] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [hasUserToggled, setHasUserToggled] = useState(false);
  const lastSeenLenRef = useRef(steps.length);

  // 새 step 도착 시 autoFollow면 최신으로 이동
  useEffect(() => {
    if (steps.length === 0) {
      setIndex(0);
      lastSeenLenRef.current = 0;
      return;
    }
    if (autoFollow) {
      setIndex(steps.length - 1);
    }
    lastSeenLenRef.current = steps.length;
  }, [steps.length, autoFollow]);

  if (steps.length === 0) return null;

  const safeIndex = Math.min(index, steps.length - 1);
  const step = steps[safeIndex];
  if (!step) return null;

  // 자동 펼침/접힘:
  //   - running step → 펼침 (사용자가 진행 보게)
  //   - done/error step → 접힘 (작업 끝나면 자동 fold, 채팅 영역 깔끔)
  //   - 사용자가 한 번 클릭하면 그 이후 수동.
  const autoExpanded = step.status === "running";
  const isExpanded = hasUserToggled ? expanded : autoExpanded;

  const isFirst = safeIndex === 0;
  const isLast = safeIndex === steps.length - 1;
  const showNav = steps.length > 1;
  const goPrev = () => {
    if (isFirst) return;
    setAutoFollow(false);
    setIndex((i) => Math.max(0, i - 1));
  };
  const goNext = () => {
    if (isLast) return;
    setAutoFollow(false);
    setIndex((i) => Math.min(steps.length - 1, i + 1));
  };
  const goLatest = () => {
    setAutoFollow(true);
    setIndex(steps.length - 1);
  };

  const elapsedMs =
    step.ended_at && step.ts ? step.ended_at - step.ts : Date.now() - step.ts;

  const toggle = () => {
    setHasUserToggled(true);
    setExpanded(!isExpanded);
  };

  const isRunning = step.status === "running";

  return (
    <article
      aria-live="polite"
      aria-label="진행 단계"
      className={
        "rounded-card border bg-md-surface-container-lowest " +
        (isRunning
          ? "border-md-outline-variant animate-md-border-pulse"
          : "border-md-outline-variant")
      }
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={isExpanded}
        className={
          "flex w-full items-center gap-2 px-3 py-2 text-left transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container-low " +
          (isExpanded ? "border-b border-md-outline-variant bg-md-surface-container-low" : "")
        }
      >
        <StatusGlyph status={step.status} />
        <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
          <span className="truncate text-body-sm font-medium text-md-on-surface">
            {step.label}
          </span>
          {isRunning ? <TypingDots /> : null}
        </span>
        {/* 헤더 요약 라인 — done이면 output_preview 우선, 없으면 progress_message가 fallback.
            running이면 progress_message(라이브 phase). */}
        {(() => {
          const summary = isRunning
            ? step.progress_message
            : step.output_preview || step.progress_message;
          if (!summary) return null;
          if (!isRunning && isExpanded) return null;
          return (
            <span className="hidden truncate text-body-sm text-md-on-surface-variant sm:inline">
              {summary}
            </span>
          );
        })()}
        <span className="font-mono text-[10px] text-md-on-surface-variant">
          {formatElapsed(elapsedMs, step.status)}
        </span>
        {showNav ? (
          <>
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                goLatest();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.stopPropagation();
                  goLatest();
                }
              }}
              title={autoFollow ? "최신 자동 따라가기 활성" : "최신으로"}
              aria-label={autoFollow ? "최신 자동 따라가기 활성" : "최신으로 이동"}
              className={
                "rounded-pill px-2 py-0.5 text-[11px] font-mono " +
                (autoFollow
                  ? "bg-md-primary-fixed text-md-on-primary-fixed-variant"
                  : "bg-md-surface-container text-md-on-surface-variant hover:bg-md-surface-container-high")
              }
            >
              {safeIndex + 1}/{steps.length}
            </span>
            <NavButtonInline dir="prev" disabled={isFirst} onClick={goPrev} />
            <NavButtonInline dir="next" disabled={isLast} onClick={goNext} />
          </>
        ) : null}
        <span
          className="material-symbols-outlined text-[16px] text-md-on-surface-variant"
          aria-hidden
        >
          {isExpanded ? "expand_less" : "expand_more"}
        </span>
      </button>

      {isExpanded ? <StepBody step={step} /> : null}
    </article>
  );
}

/* ─────────────────── 본문 — StepCard 펼침과 동일 구조 ─────────────────── */

function StepBody({ step }: { step: Step }) {
  return (
    <div className="px-3 py-3">
      {step.tool_name ? (
        <Row label="도구">
          <span className="font-mono text-code text-md-on-surface">
            {step.tool_name}
          </span>
        </Row>
      ) : null}
      {step.input_preview ? (
        <Row label="쿼리">
          <span className="font-mono text-code text-md-on-surface">
            {step.input_preview}
          </span>
        </Row>
      ) : null}
      {step.status === "running" && step.progress_message ? (
        <Row label="진행">
          <span className="text-body-sm text-md-on-surface-variant">
            {step.progress_message}
          </span>
        </Row>
      ) : null}
      {step.output_preview ? (
        <Row label="결과">
          <span className="text-body-sm text-md-on-surface">
            {step.output_preview}
          </span>
        </Row>
      ) : step.status !== "running" && step.progress_message ? (
        // done인데 output_preview가 없으면 마지막 progress_message를 결과로 보존.
        <Row label="결과">
          <span className="text-body-sm text-md-on-surface">
            {step.progress_message}
          </span>
        </Row>
      ) : null}
      {step.status === "error" && step.error_message ? (
        <Row label="오류">
          <span className="text-body-sm text-md-on-error-container">
            {step.error_message}
          </span>
        </Row>
      ) : null}
      {step.citations && step.citations.length > 0 ? (
        <Row label="발견한 출처">
          <ul className="flex flex-col gap-1">
            {step.citations.map((c) => (
              <CitationRow
                key={c.id}
                number={c.number}
                id={c.id}
                title={c.title}
              />
            ))}
          </ul>
        </Row>
      ) : null}
      {!step.tool_name && !step.input_preview && !step.output_preview ? (
        <p className="text-body-sm text-md-on-surface-variant">
          (이 단계의 디테일이 없습니다)
        </p>
      ) : null}
    </div>
  );
}

/* ─────────────────── glyph + helpers ─────────────────── */

function StatusGlyph({ status }: { status: Step["status"] }) {
  if (status === "running") {
    return (
      <span className="inline-flex h-4 w-4 items-center justify-center" aria-label="진행 중">
        <span className="inline-block h-2.5 w-2.5 animate-md-pulse rounded-full bg-md-warning" />
      </span>
    );
  }
  if (status === "done") {
    return (
      <span
        className="material-symbols-outlined text-[18px] text-md-success"
        aria-label="완료"
      >
        check_circle
      </span>
    );
  }
  return (
    <span className="material-symbols-outlined text-[18px] text-md-error" aria-label="오류">
      error
    </span>
  );
}

function NavButtonInline({
  dir,
  disabled,
  onClick,
}: {
  dir: "prev" | "next";
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <span
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      aria-label={dir === "prev" ? "이전 단계" : "다음 단계"}
      onClick={(e) => {
        if (disabled) return;
        e.stopPropagation();
        onClick();
      }}
      onKeyDown={(e) => {
        if (disabled) return;
        if (e.key === "Enter" || e.key === " ") {
          e.stopPropagation();
          onClick();
        }
      }}
      className={
        "rounded-button p-1 text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container " +
        (disabled ? "opacity-30 hover:bg-transparent cursor-default" : "cursor-pointer")
      }
    >
      <span className="material-symbols-outlined text-[18px]" aria-hidden>
        {dir === "prev" ? "chevron_left" : "chevron_right"}
      </span>
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2 flex flex-col gap-1 last:mb-0 sm:flex-row sm:items-baseline sm:gap-3">
      <span className="text-label-caps text-md-on-surface-variant sm:w-24 sm:shrink-0">
        {label}
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function TypingDots() {
  return (
    <span aria-hidden className="inline-flex items-baseline gap-0.5">
      <span
        className="inline-block size-1 rounded-full bg-md-primary animate-md-typing-dot"
        style={{ animationDelay: "0ms" }}
      />
      <span
        className="inline-block size-1 rounded-full bg-md-primary animate-md-typing-dot"
        style={{ animationDelay: "200ms" }}
      />
      <span
        className="inline-block size-1 rounded-full bg-md-primary animate-md-typing-dot"
        style={{ animationDelay: "400ms" }}
      />
    </span>
  );
}

function CitationRow({
  number,
  id,
  title,
}: {
  number: number;
  id: string;
  title: string;
}) {
  const {
    citation: activeCitation,
    setCitation,
    open: rpOpen,
    setOpen: setRpOpen,
  } = useRightPanel();
  return (
    <li>
      <button
        type="button"
        onClick={() => {
          if (id === activeCitation) {
            setRpOpen(!rpOpen);
          } else {
            setCitation(id);
            setRpOpen(true);
          }
        }}
        className="flex w-full items-baseline gap-2 rounded px-1 text-left text-body-sm text-md-on-surface hover:bg-md-surface-container hover:text-md-primary"
      >
        <span className="font-semibold text-md-primary">[{number}]</span>
        <span className="truncate">{title}</span>
      </button>
    </li>
  );
}

function formatElapsed(ms: number, status: Step["status"]): string {
  if (!Number.isFinite(ms) || ms < 0) ms = 0;
  if (status === "running") return `${Math.floor(ms / 1000)}s`;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
