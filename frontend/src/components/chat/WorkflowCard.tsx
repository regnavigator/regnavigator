"use client";

/**
 * WorkflowCard — 기능 조합의 진행 표시와 다음 단계 (2026-10-02).
 *
 * 사용자 요청: 기능을 조합해서 쓰고 싶다. 사건파일 쟁점 검토 → 판례 검색 →
 * 조문 변동 대조 → 리포트. 선택은 **기능 골라 조립 + 단계마다 멈춤**이었다.
 *
 * `<next_steps>` 마커를 쓰지 않는 이유: 다음 단계는 조합 상태가 이미 알고 있다.
 * 모델 출력에 기대면 어휘가 흔들릴 때 조용히 끊긴다 — 기존 마커 경로가 실제로
 * `/(보고서|리포트)/` 정규식 추론에 의존하고 있다(`lib/parse/nextSteps.ts`).
 * 결정적으로 정해진 것은 결정적으로 렌더한다.
 *
 * 단계 사이의 맥락은 전달하지 않는다 — 같은 스레드의 연속된 턴이라 메시지와
 * 인용이 이미 누적된다. 프리필에 한 줄만 덧붙인다(`useRunFeature`).
 */

import type { Feature } from "@/lib/features/catalog";

type Props = {
  /** 조합에 든 기능들(실행 순서). 레지스트리에서 못 찾은 id 는 제외되어 들어온다 */
  steps: Feature[];
  /** 다음에 실행할 단계 인덱스. `steps.length` 면 완료 */
  cursor: number;
  onRun: (f: Feature, index: number) => void;
  onSkip: () => void;
  onAsk: () => void;
  onClose: () => void;
};

export function WorkflowCard({
  steps,
  cursor,
  onRun,
  onSkip,
  onAsk,
  onClose,
}: Props) {
  if (steps.length === 0) return null;
  const done = cursor >= steps.length;
  const next = done ? null : steps[cursor]!;

  return (
    <section
      data-testid="workflow-card"
      aria-label="기능 조합 진행"
      className="mt-3 rounded-[10px] border border-md-outline-variant bg-md-surface-container-lowest"
    >
      <div className="flex items-center gap-2 border-b border-md-outline-variant px-3 py-2">
        <span
          className="material-symbols-outlined text-[14px] text-md-primary"
          aria-hidden
        >
          lab_profile
        </span>
        <span className="text-label-caps text-md-on-surface-variant">
          조합 {Math.min(cursor, steps.length)}/{steps.length}
        </span>
        <button
          type="button"
          data-testid="workflow-close"
          onClick={onClose}
          title="조합 끝내기"
          className="ml-auto text-[11px] text-md-on-surface-variant underline underline-offset-2 hover:text-md-error"
        >
          끝내기
        </button>
      </div>

      <ol className="flex flex-col gap-0.5 px-3 py-2">
        {steps.map((f, i) => {
          const state =
            i < cursor ? "done" : i === cursor ? "now" : "todo";
          return (
            <li
              key={f.id}
              data-step={f.id}
              data-state={state}
              className={
                "flex items-center gap-2 text-[12px] " +
                (state === "todo"
                  ? "text-md-on-surface-variant/70"
                  : "text-md-on-surface")
              }
            >
              <span
                className={
                  "material-symbols-outlined text-[14px] " +
                  (state === "done"
                    ? "text-md-primary"
                    : state === "now"
                      ? "text-md-on-surface"
                      : "text-md-on-surface-variant/60")
                }
                aria-hidden
              >
                {state === "done"
                  ? "check_circle"
                  : state === "now"
                    ? "radio_button_checked"
                    : "radio_button_unchecked"}
              </span>
              <span className="truncate">
                {i + 1}. {f.title}
              </span>
            </li>
          );
        })}
      </ol>

      {next ? (
        <div className="border-t border-md-outline-variant px-3 py-2.5">
          <p className="mb-2 text-[12.5px] text-md-on-surface">
            다음 단계 — <b>{next.title}</b>
          </p>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              data-testid="workflow-run"
              onClick={() => onRun(next, cursor)}
              className="rounded-pill bg-md-primary px-3 py-1 text-[12px] font-semibold text-md-on-primary"
            >
              실행
            </button>
            <button
              type="button"
              data-testid="workflow-skip"
              onClick={onSkip}
              className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary"
            >
              건너뛰기
            </button>
            <button
              type="button"
              data-testid="workflow-ask"
              onClick={onAsk}
              className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary"
            >
              질문 더하기
            </button>
          </div>
        </div>
      ) : (
        <div className="border-t border-md-outline-variant px-3 py-2.5">
          <p className="text-[12.5px] text-md-on-surface-variant">
            조합을 모두 마쳤습니다. 결과는 이 대화에 그대로 쌓여 있습니다.
          </p>
        </div>
      )}
    </section>
  );
}
