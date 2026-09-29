"use client";

/**
 * FeedbackButtons — 답변 또는 보고서 옆 👍/👎.
 *
 * - 👍 즉시 전송 · 활성 상태에서 재클릭 = 취소(rating "canceled" 전송)
 * - 👎 코멘트 popover (선택, ≤2000자) → 전송 또는 skip · 재클릭 = 취소
 * - 전송 후 해당 버튼 highlighted, 반대 버튼 클릭 시 새 rating으로 교체
 * - 실패 silent — 콘솔 경고만
 */

import { useState } from "react";
import {
  postMessageFeedback,
  postReportFeedback,
  type FeedbackRating,
} from "@/lib/client/quota";

type Props =
  | {
      kind: "message";
      threadId: string;
      messageId: string;
    }
  | {
      kind: "report";
      reportId: string;
    };

export function FeedbackButtons(props: Props) {
  const [submitted, setSubmitted] = useState<FeedbackRating | null>(null);
  const [submitting, setSubmitting] = useState<FeedbackRating | null>(null);
  const [showCommentFor, setShowCommentFor] = useState<FeedbackRating | null>(null);
  const [comment, setComment] = useState("");

  const post = async (rating: FeedbackRating, withComment?: string) => {
    setSubmitting(rating);
    try {
      const body = { rating, ...(withComment ? { comment: withComment } : {}) };
      if (props.kind === "message") {
        await postMessageFeedback(props.threadId, props.messageId, body);
      } else {
        await postReportFeedback(props.reportId, body);
      }
      setSubmitted(rating === "canceled" ? null : rating);
    } catch (err) {
      console.warn("[FeedbackButtons] submit failed", err);
    } finally {
      setSubmitting(null);
      setShowCommentFor(null);
      setComment("");
    }
  };

  const onClickUp = () => {
    // 재클릭 = 취소 (2026-07-16 피드백)
    void post(submitted === "thumbs_up" ? "canceled" : "thumbs_up");
  };
  const onClickDown = () => {
    if (submitted === "thumbs_down") {
      void post("canceled"); // 재클릭 = 취소
      return;
    }
    // 👎는 코멘트 popover 후 전송. 코멘트 없이도 OK.
    setShowCommentFor("thumbs_down");
  };

  const isUpActive = submitted === "thumbs_up";
  const isDownActive = submitted === "thumbs_down";

  return (
    <div className="relative flex items-center gap-1">
      <Btn
        active={isUpActive}
        loading={submitting === "thumbs_up"}
        label="좋아요"
        icon="thumb_up"
        onClick={onClickUp}
      />
      <Btn
        active={isDownActive}
        loading={submitting === "thumbs_down"}
        label="아쉬워요"
        icon="thumb_down"
        onClick={onClickDown}
      />
      {showCommentFor === "thumbs_down" ? (
        <div
          role="dialog"
          aria-label="피드백 코멘트"
          className="absolute right-0 top-9 z-10 w-72 rounded-card border border-md-outline-variant bg-md-surface p-3 shadow-lg"
        >
          <p className="mb-2 text-body-sm text-md-on-surface">
            어떤 점이 아쉬웠나요? <span className="text-md-on-surface-variant">(선택)</span>
          </p>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value.slice(0, 2000))}
            rows={3}
            placeholder="자세히 알려주시면 큰 도움이 됩니다"
            className="w-full resize-none rounded border border-md-outline-variant bg-md-surface-container-low px-2 py-1.5 text-body-sm text-md-on-surface outline-none focus:border-md-primary"
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="text-[10px] text-md-on-surface-variant">
              {comment.length}/2000
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  setShowCommentFor(null);
                  setComment("");
                }}
                className="rounded px-2 py-1 text-body-sm text-md-on-surface-variant hover:bg-md-surface-container-low"
              >
                취소
              </button>
              <button
                type="button"
                onClick={() => void post("thumbs_down", comment.trim() || undefined)}
                disabled={submitting === "thumbs_down"}
                className="rounded bg-md-primary px-3 py-1 text-body-sm font-medium text-md-on-primary hover:bg-md-primary-container disabled:opacity-50"
              >
                전송
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Btn({
  active,
  loading,
  label,
  icon,
  onClick,
}: {
  active: boolean;
  loading: boolean;
  label: string;
  icon: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={
        "inline-flex h-7 w-7 items-center justify-center rounded transition-colors hover:scale-110 " +
        (active
          ? "bg-md-primary-fixed text-md-primary"
          : "text-md-on-surface-variant hover:bg-md-surface-container hover:text-md-on-surface") +
        (loading ? " opacity-50" : "")
      }
    >
      <span
        className={
          "material-symbols-outlined text-[16px] " +
          (active ? "[font-variation-settings:'FILL'_1]" : "")
        }
        aria-hidden
      >
        {icon}
      </span>
    </button>
  );
}
