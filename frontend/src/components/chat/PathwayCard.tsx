"use client";

/**
 * PathwayCard — 규제 경로 분해 체크리스트 (2026-10-01).
 *
 * "무엇을 → 어디에 → 어떤 서식으로 → 언제까지" 를 단계로 보여준다.
 * 본문 산문에 묻히면 추적이 안 되므로 전용 카드로 분리했다(`<next_steps>` 와 같은 이유).
 *
 * 체크 상태는 **브라우저에만** 둔다(localStorage). 서버로 보내면 "진행 상황"이라는
 * 새 계약이 생기고, 그건 이 기능의 범위가 아니다. 사용자가 읽는 동안 자기 자리를
 * 잃지 않게 하는 용도다.
 *
 * 근거 없는 단계(`cites` 빈 배열)는 눈에 띄게 표시한다 — 모델이 상식으로 채운
 * 단계일 수 있고, 변호사가 그걸 구분하지 못하면 체크리스트가 위험해진다.
 */

import { useCallback, useEffect, useState } from "react";

import type { PathwayStep } from "@/lib/store/types/state";

type Props = {
  steps: PathwayStep[];
  /** 인용 번호 클릭 → 우측 패널의 해당 인용 */
  onCite?: (n: number) => void;
  /** 체크 상태 보존 키 — 보통 답변 message_id */
  storageKey?: string;
};

function loadChecked(key: string): Set<number> {
  try {
    const raw = window.localStorage.getItem(`regnav_pathway_${key}`);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr.filter((x) => typeof x === "number") : []);
  } catch {
    return new Set();
  }
}

export function PathwayCard({ steps, onCite, storageKey }: Props) {
  const [checked, setChecked] = useState<Set<number>>(() => new Set());

  useEffect(() => {
    if (storageKey) setChecked(loadChecked(storageKey));
  }, [storageKey]);

  const toggle = useCallback(
    (no: number) => {
      setChecked((prev) => {
        const next = new Set(prev);
        if (next.has(no)) next.delete(no);
        else next.add(no);
        if (storageKey) {
          try {
            window.localStorage.setItem(
              `regnav_pathway_${storageKey}`,
              JSON.stringify([...next]),
            );
          } catch {
            /* 무시 */
          }
        }
        return next;
      });
    },
    [storageKey],
  );

  if (!steps?.length) return null;

  const done = steps.filter((s) => checked.has(s.no)).length;
  const uncited = steps.filter((s) => !s.cites?.length).length;

  return (
    <section
      data-testid="pathway-card"
      className="mt-4 overflow-hidden rounded-card border border-md-outline-variant bg-md-surface-container-lowest"
    >
      <header className="flex items-center justify-between gap-2 border-b border-md-outline-variant px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined text-[17px] text-md-primary" aria-hidden>
            checklist
          </span>
          <h3 className="text-[13.5px] font-bold">규제 경로</h3>
          <span className="text-[11.5px] text-md-on-surface-variant">
            {steps.length}단계
          </span>
        </div>
        <span className="text-[11.5px] tabular-nums text-md-on-surface-variant">
          {done} / {steps.length} 완료
        </span>
      </header>

      <ol className="divide-y divide-md-outline-variant">
        {steps.map((s) => {
          const isDone = checked.has(s.no);
          return (
            <li key={s.no} className="flex gap-3 px-4 py-3">
              <button
                type="button"
                onClick={() => toggle(s.no)}
                aria-pressed={isDone}
                aria-label={`${s.title} ${isDone ? "완료 해제" : "완료 표시"}`}
                className={
                  "mt-[1px] flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[4px] border transition-colors " +
                  (isDone
                    ? "border-md-primary bg-md-primary text-md-on-primary"
                    : "border-md-outline-variant hover:border-md-primary")
                }
              >
                {isDone ? (
                  <span className="material-symbols-outlined text-[13px]" aria-hidden>
                    check
                  </span>
                ) : (
                  <span className="text-[10px] font-bold text-md-on-surface-variant">
                    {s.no}
                  </span>
                )}
              </button>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span
                    className={
                      "text-[13.5px] font-semibold " +
                      (isDone ? "text-md-on-surface-variant line-through" : "")
                    }
                  >
                    {s.title}
                  </span>
                  {s.when ? (
                    <span className="rounded-[4px] bg-md-surface-container px-1.5 py-0.5 text-[11px] text-md-on-surface-variant">
                      {s.when}
                    </span>
                  ) : null}
                  {!s.cites?.length ? (
                    <span
                      title="이 단계에는 답변 본문의 근거 인용이 붙어 있지 않습니다. 직접 확인하십시오."
                      className="rounded-[4px] bg-md-error-container px-1.5 py-0.5 text-[11px] text-md-on-error-container"
                    >
                      근거 없음
                    </span>
                  ) : null}
                </div>

                {s.what ? (
                  <p className="mt-1 text-[12.5px] leading-[1.6] text-md-on-surface-variant">
                    {s.what}
                  </p>
                ) : null}

                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-md-on-surface-variant">
                  {s.where ? (
                    <span className="inline-flex items-center gap-1">
                      <span className="material-symbols-outlined text-[13px]" aria-hidden>
                        location_on
                      </span>
                      {s.where}
                    </span>
                  ) : null}
                  {s.form ? (
                    <span className="inline-flex items-center gap-1">
                      <span className="material-symbols-outlined text-[13px]" aria-hidden>
                        description
                      </span>
                      {s.form}
                    </span>
                  ) : null}
                  {s.cites?.length ? (
                    <span className="inline-flex items-center gap-1">
                      {s.cites.map((n) => (
                        <button
                          key={n}
                          type="button"
                          onClick={() => onCite?.(n)}
                          className="rounded-[3px] bg-md-surface-container px-1 font-medium text-md-primary transition-colors hover:bg-md-primary-container"
                        >
                          [{n}]
                        </button>
                      ))}
                    </span>
                  ) : null}
                </div>

                {s.note ? (
                  <p className="mt-1.5 text-[11.5px] leading-[1.6] text-md-on-surface-variant/80">
                    ※ {s.note}
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      <footer className="border-t border-md-outline-variant px-4 py-2 text-[11px] leading-[1.6] text-md-on-surface-variant">
        {uncited > 0
          ? `근거 인용이 없는 단계가 ${uncited}개 있습니다. 해당 단계는 원문으로 직접 확인하십시오.`
          : "각 단계의 근거는 답변 본문의 인용과 연결돼 있습니다. 관할 기관에서 최종 확인하십시오."}
      </footer>
    </section>
  );
}
