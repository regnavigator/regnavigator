"use client";

/**
 * FeatureMessage — 기능 카드로 보낸 턴의 사용자 말풍선 (2026-10-06).
 *
 * 종전엔 기능 템플릿 **프롬프트 전문**이 말풍선에 그대로 떴다("…단계별 절차로 분해해줘.
 * 각 단계마다 어디에 접수하는지…"). 사용자가 쓴 것은 입력값 몇 개뿐인데 지시문이 화면을
 * 채웠다. 여기선 기능 제목 + 입력값만 보이고, 프롬프트는 접힌 채 확인만 가능하다 —
 * 숨기되 감추지는 않는다.
 */

import { useState } from "react";

import { UserMessage } from "@/components/chat/UserMessage";
import type { FeatureMeta } from "@/lib/store/types";

type Props = {
  feature: FeatureMeta;
  /** 원문(프롬프트 전문) — "프롬프트 보기"로만 */
  content: string;
  /** 보고서 절 안에서는 오른쪽 정렬 말풍선이 아니라 절 머리 밑 한 줄 */
  variant?: "bubble" | "section";
};

export function FeatureMessage({ feature, content, variant = "bubble" }: Props) {
  const [showPrompt, setShowPrompt] = useState(false);
  const vals = Object.entries(feature.values ?? {}).filter(([, v]) => (v ?? "").trim());

  const body = (
    <>
      {variant === "bubble" ? (
        <div className="flex items-center gap-1.5">
          <span className="material-symbols-outlined text-[16px] text-md-primary" aria-hidden>
            {feature.icon ?? "bolt"}
          </span>
          <span className="text-[13px] font-semibold text-md-on-surface">{feature.title}</span>
        </div>
      ) : null}
      {vals.length ? (
        <dl className={"grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[12.5px] " + (variant === "bubble" ? "mt-1.5" : "")}>
          {vals.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-md-on-surface-variant">{k}</dt>
              <dd className="whitespace-pre-wrap break-words text-md-on-surface">{v.trim()}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className={"text-[12px] text-md-on-surface-variant " + (variant === "bubble" ? "mt-1" : "")}>
          {feature.run && feature.run.index > 0 ? "입력: 앞 단계 결과" : "입력 없음 — 대화 내용으로"}
        </p>
      )}
      <button
        type="button"
        onClick={() => setShowPrompt((v) => !v)}
        aria-expanded={showPrompt}
        data-testid="feature-prompt-toggle"
        className="mt-1.5 inline-flex items-center gap-0.5 text-[11px] text-md-on-surface-variant hover:text-md-primary"
      >
        <span className="material-symbols-outlined text-[13px]" aria-hidden>
          {showPrompt ? "expand_less" : "expand_more"}
        </span>
        {showPrompt ? "프롬프트 접기" : "프롬프트 보기"}
      </button>
      {showPrompt ? (
        <div className="mt-1.5 border-t border-md-outline-variant/60 pt-1.5 text-[12px] text-md-on-surface-variant">
          <UserMessage content={content} />
        </div>
      ) : null}
    </>
  );

  if (variant === "section") {
    return <div data-testid="feature-section-input" className="px-1">{body}</div>;
  }
  return (
    <div className="flex w-full justify-end">
      <div
        data-testid="feature-message"
        className="max-w-[80%] rounded-2xl border border-md-outline-variant bg-md-surface-container px-4 py-2.5"
      >
        {body}
      </div>
    </div>
  );
}
