"use client";

/**
 * Admin · 대화 원문 뷰어 — backend `GET /admin/threads` · `GET /admin/threads/{id}`.
 *
 * 좌: 전체 사용자 대화 목록(최근순) / 우: 선택 대화 원문(질문·AI답변·tool 호출).
 * - is_admin 가드
 * - 본문은 PII 마스킹본(at-rest 정책) — 개인정보는 안 보이고 대화 흐름만.
 */

import { useEffect, useState } from "react";
import {
  getAdminThreads,
  type DataScope,
  getAdminThread,
  type AdminThreadListItem,
  type AdminThreadDetail,
  type AdminThreadMessage,
} from "@/lib/client/admin";
import { ScopeToggle } from "@/components/admin/scope-toggle";
import { AdminUserLabel, ErrorBanner, Spinner, formatTime } from "@/components/admin/common";

const PAGE_SIZE = 200;

export default function AdminThreadsPage() {
  const [threads, setThreads] = useState<AdminThreadListItem[]>([]);
  const [scope, setScope] = useState<DataScope>("real");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminThreadDetail | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 딥링크(?thread=<id>) — 답변 검수 화면의 "대화 전체 보기"에서 진입(2026-09-17).
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("thread");
    if (t) setSelected(t);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    setError(null);
    getAdminThreads(PAGE_SIZE, scope, offset)
      .then((r) => {
        if (cancelled) return;
        setThreads(r.threads);
        setTotal(r.total ?? r.threads.length);
        setHasMore(r.has_more ?? false);
      })
      .catch((err) => {
        console.error("[admin/threads] list failed", err);
        if (!cancelled) setError("대화 목록을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scope, offset]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setDetailLoading(true);
    setDetail(null);
    getAdminThread(selected)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        console.error("[admin/threads] detail failed", err);
        if (!cancelled) setError("대화 원문을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  return (
    <main className="flex flex-col gap-6">
      <header>
        <h1 className="text-h1 text-md-on-surface">대화 원문</h1>
      </header>

      <ScopeToggle
        scope={scope}
        onChange={(s) => {
          setScope(s);
          setOffset(0);
        }}
      />

      <ErrorBanner message={error} />

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        {/* 좌: 대화 목록 */}
        <aside className="flex max-h-[75vh] flex-col gap-1.5 overflow-y-auto rounded-card border border-md-outline-variant p-2">
          <div className="flex items-center justify-between px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-md-on-surface-variant">
            <span>
              대화 {total.toLocaleString()}건
              {total > threads.length
                ? ` (${(offset + 1).toLocaleString()}–${(offset + threads.length).toLocaleString()})`
                : ""}
            </span>
            {listLoading ? <Spinner size={16} /> : null}
          </div>
          {threads.map((t) => (
            <button
              key={t.thread_id}
              type="button"
              onClick={() => setSelected(t.thread_id)}
              className={
                "flex flex-col gap-0.5 rounded px-2.5 py-2 text-left transition-colors " +
                (selected === t.thread_id
                  ? "bg-md-primary-fixed text-md-on-primary-fixed-variant"
                  : "hover:bg-md-surface-container-low")
              }
            >
              <span className="truncate text-body-sm font-medium text-md-on-surface">
                {t.title || "(제목 없음)"}
              </span>
              <span className="flex items-center gap-1.5 text-[10.5px] text-md-on-surface-variant">
                <span className="font-mono">{formatTime(t.updated_at)}</span>
                <AdminUserLabel
                  displayName={t.user_display_name}
                  memo={t.user_admin_memo}
                  email={t.user_email}
                  userId={t.user_id}
                  className="text-[10.5px]"
                />
              </span>
            </button>
          ))}
          {threads.length === 0 && !listLoading ? (
            <p className="px-2 py-6 text-center text-body-sm text-md-on-surface-variant">
              대화가 없습니다.
            </p>
          ) : null}
          {offset > 0 || hasMore ? (
            <div className="mt-1 flex items-center justify-between border-t border-md-outline-variant px-2 pt-2 text-[11px]">
              <button
                type="button"
                disabled={offset === 0 || listLoading}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded px-2 py-1 font-medium text-md-primary hover:bg-md-surface-container-low disabled:opacity-40 disabled:hover:bg-transparent"
              >
                ← 최근
              </button>
              <span className="tabular-nums text-md-on-surface-variant">
                {Math.floor(offset / PAGE_SIZE) + 1} /{" "}
                {Math.max(1, Math.ceil(total / PAGE_SIZE))}
              </span>
              <button
                type="button"
                disabled={!hasMore || listLoading}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded px-2 py-1 font-medium text-md-primary hover:bg-md-surface-container-low disabled:opacity-40 disabled:hover:bg-transparent"
              >
                이전 →
              </button>
            </div>
          ) : null}
        </aside>

        {/* 우: 원문 */}
        <section className="min-h-[300px] rounded-card border border-md-outline-variant p-4">
          {!selected ? (
            <p className="flex h-full items-center justify-center py-16 text-body-sm text-md-on-surface-variant">
              왼쪽에서 대화를 선택하세요.
            </p>
          ) : detailLoading ? (
            <p className="flex h-full items-center justify-center py-16 text-body-sm text-md-on-surface-variant">
              불러오는 중…
            </p>
          ) : detail ? (
            <div className="flex flex-col gap-4">
              <header className="border-b border-md-outline-variant pb-3">
                <h2 className="text-h3 text-md-on-surface">
                  {detail.title || "(제목 없음)"}
                </h2>
                <p className="mt-1 flex flex-wrap gap-3 text-[11px] text-md-on-surface-variant">
                  <span>
                    thread{" "}
                    <code className="font-mono">{detail.thread_id}</code>
                  </span>
                  <AdminUserLabel
                    displayName={detail.user_display_name}
                    memo={detail.user_admin_memo}
                    email={detail.user_email}
                    userId={detail.user_id}
                  />
                  <span>{formatTime(detail.updated_at)}</span>
                  <span>메시지 {detail.messages.length}</span>
                  {detail.turns && detail.turns.length > 0 ? (
                    <span title="사용자 질문 저장 → 최종 AI 답변 완성까지">
                      응답 {detail.turns.length}턴 · 평균{" "}
                      {formatElapsed(
                        detail.turns.reduce((a, t) => a + t.elapsed_s, 0) /
                          detail.turns.length,
                      )}{" "}
                      · 최대{" "}
                      {formatElapsed(
                        Math.max(...detail.turns.map((t) => t.elapsed_s)),
                      )}
                    </span>
                  ) : null}
                </p>
              </header>
              <ul className="flex flex-col gap-3">
                {detail.messages.map((m, i) => (
                  <MessageBubble key={m.id ?? i} m={m} />
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}

function MessageBubble({ m }: { m: AdminThreadMessage }) {
  const [expanded, setExpanded] = useState(false);
  const type = m.type ?? "";
  if (type === "tool") {
    const long = (m.content?.length ?? 0) > 160;
    return (
      <li className="ml-6 rounded border border-dashed border-md-outline-variant bg-md-surface-container-low px-3 py-1.5 text-[11.5px] text-md-on-surface-variant">
        <div className="flex items-center gap-2">
          <span className="font-mono">tool 결과</span>
          {m.content ? (
            <span className="tabular-nums opacity-50">
              {m.content.length.toLocaleString()}자
            </span>
          ) : null}
          {long ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="ml-auto rounded px-1.5 py-0.5 text-[10.5px] font-medium text-md-primary hover:bg-md-surface-container-high"
            >
              {expanded ? "접기" : "전문 보기"}
            </button>
          ) : null}
        </div>
        {m.content ? (
          <pre
            className={
              "mt-1 whitespace-pre-wrap font-mono text-[11px] leading-relaxed opacity-80 " +
              (expanded ? "" : "line-clamp-2")
            }
            style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
          >
            {m.content}
          </pre>
        ) : null}
      </li>
    );
  }
  const isHuman = type === "human";
  return (
    <li className={"flex flex-col " + (isHuman ? "items-end" : "items-start")}>
      <span className="mb-0.5 px-1 text-[10.5px] font-semibold uppercase tracking-wide text-md-on-surface-variant">
        {isHuman ? "사용자" : "AI"}
        {typeof m.elapsed_s === "number" ? (
          <span
            className="ml-1.5 rounded bg-md-surface-container-high px-1 py-px font-mono normal-case tabular-nums text-md-primary"
            title="사용자 질문 저장 → 이 답변 완성까지"
          >
            {formatElapsed(m.elapsed_s)}
          </span>
        ) : null}
      </span>
      <div
        className={
          "max-w-[85%] rounded-card px-3.5 py-2.5 text-body-sm leading-relaxed " +
          (isHuman
            ? "bg-md-primary text-md-on-primary"
            : "border border-md-outline-variant bg-md-surface text-md-on-surface")
        }
        style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
      >
        {m.content ? (
          <span className="whitespace-pre-wrap">{m.content}</span>
        ) : (
          <span className="italic opacity-60">(본문 없음)</span>
        )}
        {m.tool_calls && m.tool_calls.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {m.tool_calls.map((tc, i) => (
              <span
                key={`${tc}-${i}`}
                className="rounded-pill bg-md-surface-container-high px-2 py-0.5 font-mono text-[10px] text-md-on-surface-variant"
              >
                🔧 {tc}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </li>
  );
}

/** 초 → "12.3s" / "5분 10초" */
function formatElapsed(s: number): string {
  if (!Number.isFinite(s)) return "-";
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return `${m}분 ${r}초`;
}
