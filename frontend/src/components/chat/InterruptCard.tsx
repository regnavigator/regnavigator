"use client";

/**
 * InterruptCard — clarify / approve_action 인터럽트 렌더 + resume.
 *
 * 백엔드가 `ask_clarify`(질문 + 선택지 + 자유입력 허용) 또는 `approve_action`을
 * 인터럽트로 보내면 `applyInterrupt`가 `turn.interrupt`에 박는다. 이 컴포넌트가
 * 그것을 사용자에게 노출하고, 응답을 `onResume(payload)`로 돌려보낸다.
 *
 * resume 페이로드 (data-contract §8):
 *  - clarify        : { type:"clarify", choice?:string, free_text?:string }
 *  - approve_action : { type:"approve_action", decision:"accept"|"reject" }
 *
 * 백엔드가 보낸 question/description/options 텍스트는 *그대로* 표시 (가공 X).
 */

import { useState } from "react";
import type { InterruptValue } from "@/lib/store/types";

type Props = {
  interrupt: InterruptValue;
  /** useChatState.resume — 인터럽트 응답 스트림 재개 */
  onResume: (value: unknown) => void;
};

export function InterruptCard({ interrupt, onResume }: Props) {
  // 한 번 응답하면 잠금 — 중복 resume 방지 (resume이 새 스트림을 띄움).
  const [submitted, setSubmitted] = useState(false);
  const [freeText, setFreeText] = useState("");

  const lock = () => setSubmitted(true);

  if (interrupt.type === "clarify") {
    const send = (payload: Record<string, unknown>) => {
      if (submitted) return;
      lock();
      onResume({ type: "clarify", ...payload });
    };
    const canSendFree = interrupt.allow_free_text && freeText.trim().length > 0;
    return (
      <section
        aria-label="추가 확인"
        className="rounded-card border border-md-primary/40 bg-md-surface-container-lowest p-4"
      >
        <div className="mb-3 flex items-center gap-2">
          <span
            className="material-symbols-outlined text-[18px] text-md-primary"
            aria-hidden
          >
            help
          </span>
          <span className="text-body-sm font-semibold text-md-on-surface">
            추가 확인이 필요해요
          </span>
        </div>
        <p className="mb-3 whitespace-pre-wrap text-body-base text-md-on-surface">
          {interrupt.question}
        </p>

        {interrupt.options && interrupt.options.length > 0 ? (
          <ul className="flex flex-col gap-2">
            {interrupt.options.map((opt, i) => (
              <li key={`${i}-${opt}`}>
                <button
                  type="button"
                  disabled={submitted}
                  onClick={() => send({ choice: opt })}
                  className="w-full rounded-button border border-md-outline-variant px-3 py-2 text-left text-body-sm text-md-on-surface transition-colors hover:border-md-primary hover:bg-md-surface-container-low disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {opt}
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        {interrupt.allow_free_text ? (
          <div className="mt-3 flex flex-col gap-2">
            <textarea
              value={freeText}
              disabled={submitted}
              onChange={(e) => setFreeText(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing &&
                  canSendFree
                ) {
                  e.preventDefault();
                  send({ free_text: freeText.trim() });
                }
              }}
              rows={2}
              placeholder="직접 입력 (Enter 전송)"
              className="w-full resize-none rounded-button border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none disabled:opacity-50"
            />
            <div className="flex justify-end">
              <button
                type="button"
                disabled={!canSendFree || submitted}
                onClick={() => send({ free_text: freeText.trim() })}
                className="rounded-button bg-md-primary px-4 py-1.5 text-body-sm font-medium text-md-on-primary transition-colors hover:bg-md-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                보내기
              </button>
            </div>
          </div>
        ) : null}

        {submitted ? (
          <p className="mt-3 text-[12px] text-md-on-surface-variant">
            응답을 전송했어요. 이어서 진행 중…
          </p>
        ) : null}
      </section>
    );
  }

  // approve_action — 형제 인터럽트도 안 그리면 같은 "왜 안 보임" 버그라 함께 처리.
  const decide = (decision: "accept" | "reject") => {
    if (submitted) return;
    lock();
    onResume({ type: "approve_action", decision });
  };
  return (
    <section
      aria-label="작업 승인"
      className="rounded-card border border-md-primary/40 bg-md-surface-container-lowest p-4"
    >
      <div className="mb-3 flex items-center gap-2">
        <span
          className="material-symbols-outlined text-[18px] text-md-primary"
          aria-hidden
        >
          task_alt
        </span>
        <span className="text-body-sm font-semibold text-md-on-surface">
          작업 승인이 필요해요
        </span>
      </div>
      <p className="mb-1 whitespace-pre-wrap text-body-base text-md-on-surface">
        {interrupt.description}
      </p>
      <p className="mb-3 text-[12px] text-md-on-surface-variant">
        {interrupt.action_name}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={submitted}
          onClick={() => decide("accept")}
          className="rounded-button bg-md-primary px-4 py-1.5 text-body-sm font-medium text-md-on-primary transition-colors hover:bg-md-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          수락
        </button>
        <button
          type="button"
          disabled={submitted}
          onClick={() => decide("reject")}
          className="rounded-button border border-md-outline-variant px-4 py-1.5 text-body-sm text-md-on-surface transition-colors hover:bg-md-surface-container-low disabled:cursor-not-allowed disabled:opacity-50"
        >
          거절
        </button>
      </div>
      {submitted ? (
        <p className="mt-3 text-[12px] text-md-on-surface-variant">
          전송했어요. 이어서 진행 중…
        </p>
      ) : null}
    </section>
  );
}
