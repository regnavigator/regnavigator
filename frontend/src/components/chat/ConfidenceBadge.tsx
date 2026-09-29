"use client";

/**
 * ConfidenceBadge — 답변 최상단 *근거 요약 바*.
 *
 * 신뢰를 첫 화면에서 전달: 근거 구성(법령·별표/서식·판례·웹) + 검증 비율 + 현행성 경고.
 *  - 분류: doc_category(별표서식/판례류) · source_kind(web) 기준.
 *  - 검증: `verified` 인용 / 전체. 비율로 신뢰도 tier(🟢≥80 / 🟡≥30 / 🔴).
 *  - 현행성: status revoked(폐지)·amended_pending(개정 예정) 건수 경고.
 *
 * 인용 0건이면 미렌더.
 */

import { citationKindCounts } from "@/components/chat/MarkdownContent";
import type { Citation } from "@/lib/store/types";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

type Props = {
  citations: Citation[];
};

export function ConfidenceBadge({ citations }: Props) {
  if (!citations || citations.length === 0) return null;

  const total = citations.length;
  let revoked = 0;
  let amended = 0;
  for (const c of citations) {
    if (c.status === "revoked") revoked += 1;
    else if (c.status === "amended_pending") amended += 1;
  }

  const hasVerifiedField = citations.some(
    (c) => typeof c.verified === "boolean",
  );
  const verified = citations.filter((c) => c.verified === true).length;
  const ratio = hasVerifiedField ? verified / total : null;

  const tier =
    ratio === null ? "none" : ratio >= 0.8 ? "high" : ratio >= 0.3 ? "medium" : "low";
  const dot =
    tier === "high"
      ? "bg-md-primary"
      : tier === "medium"
        ? "bg-md-tertiary"
        : tier === "low"
          ? "bg-md-error"
          : "bg-md-outline";
  const tierLabel =
    tier === "high"
      ? "신뢰도 높음"
      : tier === "medium"
        ? "신뢰도 보통"
        : tier === "low"
          ? "신뢰도 낮음"
          : "근거";

  // 근거 구성 조각 — 출처 목록 범례와 같은 분류·같은 숫자(2026-09-21: 종전엔 가이드라인·
  // 행정규칙을 "법령"에 합쳐 세서 범례와 숫자가 달랐다). 0건 종별은 생략.
  const parts = citationKindCounts(citations).map((k) => `${k.label} ${k.n}`);

  const ariaBits = [
    `근거 ${total}건`,
    parts.join(", "),
    ratio !== null ? `검증 ${verified}/${total}건` : "",
    revoked ? `폐지 ${revoked}건` : "",
    amended ? `개정 예정 ${amended}건` : "",
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${ariaBits}. 눌러서 기준 보기`}
          className="-mt-1 mb-1 inline-flex w-fit flex-wrap items-center gap-x-2 gap-y-0.5 rounded-pill text-[11px] text-md-on-surface-variant hover:text-md-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary focus-visible:ring-offset-1"
        >
          <span className="inline-flex items-center gap-1.5">
            <span className={`size-1.5 rounded-full ${dot}`} aria-hidden />
            <span>{tierLabel}</span>
            {ratio !== null ? (
              <span className="text-md-on-surface-variant">
                · 검증 {verified}/{total}
              </span>
            ) : null}
          </span>
          {parts.length ? (
            <span className="text-md-on-surface-variant/80">
              {parts.join(" · ")}
            </span>
          ) : null}
          {revoked || amended ? (
            <span className="inline-flex items-center gap-1 font-medium text-md-error">
              <span className="material-symbols-outlined text-[13px]" aria-hidden>
                warning
              </span>
              {revoked ? `폐지 ${revoked}` : ""}
              {revoked && amended ? " · " : ""}
              {amended ? `개정 예정 ${amended}` : ""}
            </span>
          ) : null}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="max-w-[320px] px-3 py-2.5 text-[12px] leading-relaxed"
      >
        <p className="font-medium text-md-on-surface">근거 구성</p>
        <p className="mt-0.5 text-md-on-surface-variant">
          {parts.length ? parts.join(" · ") : "근거 없음"} (총 {total}건)
        </p>
        {ratio !== null ? (
          <p className="mt-2 text-md-on-surface-variant">
            <span className="font-medium text-md-on-surface">검증 {verified}/{total}</span>{" "}
            — 인용 문장을 <b>법령 원문과 대조 확인</b>한 건수(웹 출처는 화이트리스트 매칭). 미검증은 참고용.
          </p>
        ) : null}
        {revoked || amended ? (
          <p className="mt-2 text-md-error">
            ⚠️ {revoked ? `폐지 ${revoked}건 ` : ""}
            {amended ? `개정 예정 ${amended}건 ` : ""}
            — 최신 시행 여부를 원문에서 확인하세요.
          </p>
        ) : null}
        <a
          href="/landing#trust"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-0.5 font-medium text-md-secondary underline-offset-2 hover:underline"
        >
          신뢰도 기준 자세히 →
        </a>
      </PopoverContent>
    </Popover>
  );
}
