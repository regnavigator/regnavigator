"use client";

/**
 * Admin · 피드백 조회 — backend `/admin/feedback`.
 *
 * - kind 토글: user_feedback (@feedback 자유 코멘트) / feedback (👍/👎 평가)
 * - 페이지네이션 (limit=50)
 * - is_admin 가드 — 일반 유저는 / 로 redirect
 */

import { useCallback, useEffect, useState } from "react";
import {
  listAdminFeedback,
  type AdminFeedbackItem,
  type AdminFeedbackKind,
} from "@/lib/client/admin";
import { ErrorBanner, PillTab, formatTime } from "@/components/admin/common";

const PAGE_SIZE = 50;

export default function AdminFeedbackPage() {
  const [kind, setKind] = useState<AdminFeedbackKind>("user_feedback");
  const [items, setItems] = useState<AdminFeedbackItem[]>([]);
  const [count, setCount] = useState(0);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(
    async (resetKind: AdminFeedbackKind, reset: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const next = reset ? 0 : offset;
        const page = await listAdminFeedback({
          kind: resetKind,
          limit: PAGE_SIZE,
          offset: next,
        });
        setItems((prev) => (reset ? page.items : [...prev, ...page.items]));
        setCount(page.count);
        setHasMore(page.items.length === PAGE_SIZE);
        if (reset) setOffset(0);
      } catch (err) {
        console.error("[admin/feedback] list failed", err);
        setError("피드백 목록을 불러오지 못했습니다.");
      } finally {
        setLoading(false);
      }
    },
    [offset],
  );

  useEffect(() => {
    void reload(kind, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  async function loadMore() {
    if (loading || !hasMore) return;
    const newOffset = offset + PAGE_SIZE;
    setOffset(newOffset);
    setLoading(true);
    try {
      const page = await listAdminFeedback({
        kind,
        limit: PAGE_SIZE,
        offset: newOffset,
      });
      setItems((prev) => [...prev, ...page.items]);
      setHasMore(page.items.length === PAGE_SIZE);
    } catch (err) {
      console.error("[admin/feedback] loadMore failed", err);
      setError("더 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex flex-col gap-6">
      <header>
        <h1 className="text-h1 text-md-on-surface">피드백 조회</h1>
      </header>

      {/* kind 토글 */}
      <div className="flex items-center gap-2">
        <PillTab
          active={kind === "user_feedback"}
          label="자유 피드백 (@feedback)"
          onClick={() => setKind("user_feedback")}
        />
        <PillTab
          active={kind === "feedback"}
          label="평가 (👍/👎)"
          onClick={() => setKind("feedback")}
        />
        <span className="ml-auto text-body-sm text-md-on-surface-variant">
          총 {count}건
        </span>
      </div>

      <ErrorBanner message={error} />

      <ul className="flex flex-col gap-3">
        {items.map((it) => (
          <FeedbackRow key={it.id} item={it} kind={kind} />
        ))}
        {items.length === 0 && !loading ? (
          <li className="rounded-card border border-md-outline-variant px-4 py-8 text-center text-md-on-surface-variant">
            피드백이 없습니다.
          </li>
        ) : null}
      </ul>

      {hasMore ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={loading}
            className="rounded border border-md-outline-variant px-4 py-1.5 text-body-sm text-md-on-surface-variant hover:bg-md-surface-container-low disabled:opacity-50"
          >
            {loading ? "불러오는 중..." : "더 보기"}
          </button>
        </div>
      ) : null}
    </main>
  );
}

function FeedbackRow({
  item,
  kind,
}: {
  item: AdminFeedbackItem;
  kind: AdminFeedbackKind;
}) {
  const p = item.payload as {
    comment?: string;
    rating?: string;
    comment_length?: number;
    source?: string;
  };
  const ts = formatTime(item.ts);
  return (
    <li className="rounded-card border border-md-outline-variant bg-md-surface px-4 py-3 transition-colors hover:border-md-primary-fixed-dim">
      <header className="mb-2 flex flex-wrap items-center gap-2 text-[12px] text-md-on-surface-variant">
        {kind === "feedback" && p.rating ? (
          <span
            className={
              "inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-[11px] font-semibold " +
              (p.rating === "thumbs_up"
                ? "bg-md-primary-fixed text-md-on-primary-fixed-variant"
                : "bg-md-error-container text-md-on-error-container")
            }
          >
            {p.rating === "thumbs_up" ? "👍 좋아요" : "👎 별로예요"}
          </span>
        ) : null}
        {p.source ? (
          <code className="rounded bg-md-surface-container-low px-1.5 py-0.5 font-mono text-[10.5px]">
            {p.source}
          </code>
        ) : null}
        <span className="font-mono">{ts}</span>
        <span className="ml-auto truncate font-mono text-[10.5px] opacity-70">
          {item.user_id.slice(0, 12)}…
        </span>
      </header>
      {p.comment ? (
        <p
          className="whitespace-pre-wrap text-body-sm leading-relaxed text-md-on-surface"
          style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
        >
          {p.comment}
        </p>
      ) : (
        <p className="text-body-sm italic text-md-on-surface-variant">
          (코멘트 없음)
        </p>
      )}
      {(item.thread_id || item.message_id) ? (
        <footer className="mt-2 flex flex-wrap gap-3 text-[11px] text-md-on-surface-variant">
          {item.thread_id ? (
            <span>
              thread <code className="font-mono">{item.thread_id.slice(0, 8)}</code>
            </span>
          ) : null}
          {item.message_id ? (
            <span>
              msg <code className="font-mono">{item.message_id.slice(0, 8)}</code>
            </span>
          ) : null}
        </footer>
      ) : null}
    </li>
  );
}
