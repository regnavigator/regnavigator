"use client";

/**
 * CitationEvidenceTooltip — 인용 근거 팝오버 (UX 배치 #2·#4).
 *
 * `citation.supporting_quote`(grounding 검증 원문 스팬)가 있으면 인용 chip 클릭 시
 * 팝오버로 원문 근거를 노출. quote 없으면 팝오버 없이 children 그대로(기존 동작).
 *
 * **클릭 팝오버**(hover 툴팁 아님) — 안에 링크·신고 버튼이 있어 터치/키보드에서도
 * 접근 가능해야 하기 때문. 신고 사유는 팝오버 내 테마 입력(500자 가드)으로 받는다.
 *
 * 인라인 chip(MarkdownContent)과 References(CitationFootnotes) 양쪽에서 사용.
 */

import { useState, type ReactNode } from "react";
import { useQueryState } from "nuqs";
import { toast } from "sonner";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { Citation } from "@/lib/store/types";
import { deriveExternalUrl } from "@/lib/parse/lawLink";
import { reportCitation } from "@/lib/client/quota";

type Props = {
  citation: Citation;
  /** trigger 엘리먼트 — 단일 엘리먼트 (Radix asChild) */
  children: ReactNode;
};

export function CitationEvidenceTooltip({ citation, children }: Props) {
  const quote = (citation.supporting_quote ?? "").trim();
  // quote 없으면 팝오버 없이 기존 동작.
  if (!quote) return <>{children}</>;
  return (
    <EvidencePopoverInner citation={citation} quote={quote}>
      {children}
    </EvidencePopoverInner>
  );
}

function EvidencePopoverInner({
  citation,
  quote,
  children,
}: Props & { quote: string }) {
  const [threadId] = useQueryState("threadId");
  const url = deriveExternalUrl(citation) ?? citation.url ?? null;
  const [reporting, setReporting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const resetForm = () => {
    setReporting(false);
    setReason("");
  };

  const submitReport = async () => {
    if (!threadId) {
      toast.error("대화 컨텍스트가 없어 신고할 수 없습니다.");
      return;
    }
    setBusy(true);
    try {
      await reportCitation(threadId, {
        citationId: citation.id,
        citationNumber: citation.number,
        citationTitle: citation.title,
        reason: reason.trim().slice(0, 500) || undefined,
      });
      toast.success("신고가 접수됐습니다", {
        description: "검토 후 검색 품질 개선에 반영됩니다. 감사합니다.",
      });
      resetForm();
    } catch (err) {
      console.warn("[CitationEvidenceTooltip] report failed", err);
      toast.error("신고 전송에 실패했습니다. 잠시 후 다시 시도해주세요.", {
        duration: 6000,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Popover onOpenChange={(open) => !open && resetForm()}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="max-w-[360px] px-3 py-2.5 text-[12px] leading-relaxed"
      >
        <p className="mb-1 text-[10.5px] font-semibold text-md-on-surface-variant">
          검증된 원문 근거
        </p>
        <p
          className="text-md-on-surface"
          style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
        >
          &ldquo;{quote}&rdquo;
        </p>
        <div className="mt-2 flex items-center gap-3 border-t border-md-outline-variant/60 pt-1.5">
          {url ? (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-md-secondary underline-offset-2 hover:underline"
            >
              원문 보기
            </a>
          ) : null}
          {!reporting ? (
            <button
              type="button"
              onClick={() => setReporting(true)}
              className="font-medium text-md-error underline-offset-2 hover:underline"
            >
              이 인용 신고
            </button>
          ) : null}
        </div>
        {reporting ? (
          <div className="mt-2">
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={500}
              rows={2}
              autoFocus
              placeholder="신고 사유 (선택, 500자 이내)"
              className="w-full resize-none rounded-input border border-md-outline-variant bg-md-surface px-2 py-1.5 text-[12px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
            />
            <div className="mt-1.5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={resetForm}
                className="text-[12px] text-md-on-surface-variant hover:text-md-on-surface"
              >
                취소
              </button>
              <button
                type="button"
                onClick={() => void submitReport()}
                disabled={busy}
                className="rounded-button bg-md-error px-2.5 py-1 text-[12px] font-medium text-md-on-error hover:bg-md-error/90 disabled:opacity-50"
              >
                신고
              </button>
            </div>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
