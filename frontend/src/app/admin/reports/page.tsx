"use client";

/**
 * Admin · 보고서 — backend `GET /admin/reports`.
 *
 * 보고서 요청(run) → 생성 → 이메일 발송까지 전 구간을 한 표로.
 * 배경(2026-08-21): 베타 보고서 3연속 실패(writer 400)를 사용자 신고로야
 * 알았고, 발송 여부는 로그로도 확인 불가였다. email_status 는 backend 의
 * events(report_email) 조인 — 이벤트 도입 전 run 은 "기록 없음"으로 나온다.
 */

import { useEffect, useState } from "react";
import {
  getAdminReportContent,
  getAdminReports,
  type AdminReportContent,
  type AdminReportRun,
} from "@/lib/client/admin";
import { MarkdownContent } from "@/components/chat/MarkdownContent";
import { AdminUserLabel, ErrorBanner, Spinner, formatTime } from "@/components/admin/common";

const PAGE_SIZE = 50;

function StatusPill({ status, error }: { status: string; error: string | null }) {
  const cls =
    status === "completed"
      ? "bg-emerald-100 text-emerald-800"
      : status === "failed"
        ? "bg-red-100 text-red-800"
        : "bg-amber-100 text-amber-800";
  return (
    <span
      className={`inline-block rounded-pill px-2 py-0.5 text-[11px] font-semibold ${cls}`}
      title={error ?? undefined}
    >
      {status === "completed" ? "완료" : status === "failed" ? "실패" : "생성 중"}
    </span>
  );
}

function EmailPill({ r }: { r: AdminReportRun }) {
  if (r.status !== "completed")
    return <span className="text-[11px] text-md-on-surface-variant">—</span>;
  if (r.email_status === "sent")
    return (
      <span className="inline-block rounded-pill bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
        발송됨
      </span>
    );
  if (r.email_status === "failed")
    return (
      <span
        className="inline-block rounded-pill bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-800"
        title={r.email_error ?? undefined}
      >
        발송 실패
      </span>
    );
  return (
    <span
      className="text-[11px] text-md-on-surface-variant"
      title="발송 결과 이벤트 도입(8/21) 이전 run — 기록 없음"
    >
      기록 없음
    </span>
  );
}

export default function AdminReportsPage() {
  const [runs, setRuns] = useState<AdminReportRun[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 내부 트래픽(e2e·벤치·야간회귀)은 기본 숨김 — 실사용 결과에 섞여 보이던
  // 것(2026-08-26). 필요할 때만 켜서 본다.
  const [showInternal, setShowInternal] = useState(false);
  // 탭 분리(2026-08-27) — 서류(kind=doc)는 심층 보고서가 아니다. IRB·DRB
  // 산출물은 제목·요청문 키워드 기반 분류(provenance 컬럼은 후속).
  const [tab, setTab] = useState<"deep" | "doc" | "irb">("deep");
  const [viewing, setViewing] = useState<AdminReportContent | null>(null);
  const [viewLoading, setViewLoading] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAdminReports(PAGE_SIZE, offset, showInternal ? "all" : "real", tab)
      .then((r) => {
        if (cancelled) return;
        setRuns(r.runs);
        setTotal(r.total);
        setHasMore(r.has_more);
      })
      .catch((err) => {
        console.error("[admin/reports] list failed", err);
        if (!cancelled) setError("보고서 목록을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [offset, showInternal, tab]);

  const openContent = async (reportId: string) => {
    setViewLoading(reportId);
    try {
      setViewing(await getAdminReportContent(reportId));
    } catch (err) {
      console.error("[admin/reports] content failed", err);
      setError("보고서 본문을 불러오지 못했습니다(보관기간 30일 경과일 수 있음).");
    } finally {
      setViewLoading(null);
    }
  };

  return (
    <main className="flex flex-col gap-6">
      <header className="flex items-center gap-3">
        <h1 className="text-h1 text-md-on-surface">보고서</h1>
        {loading ? <Spinner size={18} /> : null}
        {/* 탭 — 심층/서류/IRB·DRB 분리(2026-08-27) */}

        <div className="flex items-center gap-1 rounded-card border border-md-outline-variant bg-md-surface-container-lowest p-1">

          {([

            ["deep", "심층 보고서"],

            ["doc", "서류"],

            ["irb", "IRB·DRB"],

          ] as const).map(([k, label]) => (

            <button

              key={k}

              type="button"

              onClick={() => { setTab(k); }}

              className={

                "rounded px-3 py-1.5 text-[12.5px] font-medium transition-colors " +

                (tab === k

                  ? "bg-md-primary text-md-on-primary"

                  : "text-md-on-surface-variant hover:bg-md-surface-container")

              }

            >

              {label}

            </button>

          ))}

        </div>
        <label className="ml-auto flex items-center gap-1.5 text-[12px] text-md-on-surface-variant">
          <input
            type="checkbox"
            checked={showInternal}
            onChange={(e) => {
              setOffset(0);
              setShowInternal(e.target.checked);
            }}
          />
          내부 테스트 포함 (e2e·벤치)
        </label>
      </header>

      <ErrorBanner message={error} />

      <div className="overflow-x-auto rounded-card border border-md-outline-variant">
        <table className="w-full min-w-[880px] text-left text-body-sm">
          <thead className="bg-md-surface-container-low text-[11px] uppercase tracking-wide text-md-on-surface-variant">
            <tr>
              <th className="px-3 py-2">요청 시각</th>
              <th className="px-3 py-2">사용자</th>
              <th className="px-3 py-2">제목 / 요청 프롬프트</th>
              <th className="px-3 py-2">상태</th>
              <th className="px-3 py-2">작성 모델</th>
              <th className="px-3 py-2">분량 / 인용</th>
              <th className="px-3 py-2">이메일</th>
              <th className="px-3 py-2">소요</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const dur =
                r.started_at && r.finished_at
                  ? Math.round(
                      (new Date(r.finished_at).getTime() -
                        new Date(r.started_at).getTime()) /
                        60000,
                    )
                  : null;
              return (
                <tr
                  key={r.idempotency_key}
                  className="border-t border-md-outline-variant align-top"
                >
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-[11.5px] text-md-on-surface-variant">
                    {formatTime(r.started_at)}
                  </td>
                  <td className="max-w-[180px] truncate px-3 py-2 text-[12px]">
                    <AdminUserLabel
                      displayName={r.user_display_name}
                      memo={r.user_admin_memo}
                      email={r.user_email}
                      userId={r.user_id}
                    />
                  </td>
                  <td className="max-w-[340px] px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      {r.report_id ? (
                        <button
                          type="button"
                          onClick={() => void openContent(r.report_id!)}
                          disabled={viewLoading === r.report_id}
                          className="truncate text-left font-medium text-md-primary underline-offset-2 hover:underline disabled:opacity-50"
                          title="본문 보기"
                        >
                          {r.report_title ?? "(제목 없음)"}
                        </button>
                      ) : (
                        <span className="truncate font-medium text-md-on-surface">
                          (미생성)
                        </span>
                      )}
                      {r.internal ? (
                        <span className="shrink-0 rounded-pill bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                          내부
                        </span>
                      ) : null}
                    </div>
                    <div className="truncate text-[11px] text-md-on-surface-variant">
                      {r.prompt || "(프롬프트 없음)"}
                    </div>
                    {r.status === "failed" && r.error ? (
                      <div className="mt-0.5 truncate font-mono text-[11px] text-red-700">
                        {r.error}
                      </div>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <StatusPill status={r.status} error={r.error} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-[11.5px]">
                    {r.writer_model ? (
                      <span className="rounded bg-md-surface-container-low px-1.5 py-0.5 font-mono text-md-on-surface">
                        {r.writer_model}
                      </span>
                    ) : (
                      <span className="text-md-on-surface-variant">—</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-[12px] text-md-on-surface-variant">
                    {r.report_chars
                      ? `${r.report_chars.toLocaleString()}자 · 인용 ${r.cites_used ?? "?"}`
                      : "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <EmailPill r={r} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-[12px] text-md-on-surface-variant">
                    {dur !== null ? `${dur}분` : r.status === "running" ? "…" : "—"}
                  </td>
                </tr>
              );
            })}
            {runs.length === 0 && !loading ? (
              <tr>
                <td
                  colSpan={8}
                  className="px-3 py-10 text-center text-md-on-surface-variant"
                >
                  보고서 요청이 없습니다.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {offset > 0 || hasMore ? (
        <div className="flex items-center justify-between text-[12px]">
          <button
            type="button"
            disabled={offset === 0 || loading}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded px-2.5 py-1.5 font-medium text-md-primary hover:bg-md-surface-container-low disabled:opacity-40 disabled:hover:bg-transparent"
          >
            ← 최근
          </button>
          <span className="tabular-nums text-md-on-surface-variant">
            {Math.floor(offset / PAGE_SIZE) + 1} /{" "}
            {Math.max(1, Math.ceil(total / PAGE_SIZE))} · 총{" "}
            {total.toLocaleString()}건
          </span>
          <button
            type="button"
            disabled={!hasMore || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded px-2.5 py-1.5 font-medium text-md-primary hover:bg-md-surface-container-low disabled:opacity-40 disabled:hover:bg-transparent"
          >
            이전 →
          </button>
        </div>
      ) : null}

      {viewing ? (
        <ReportContentDialog content={viewing} onClose={() => setViewing(null)} />
      ) : null}
    </main>
  );
}

/**
 * 보고서 본문 뷰어 — 품질 점검(모델 교체 전후 비교·인용 적정성)이 관리자
 * 화면에서 끝나게 한다(2026-08-26). 종전엔 사용자 계정으로 들어가거나 DB 를
 * 뒤져야 했다.
 */
function ReportContentDialog({
  content,
  onClose,
}: {
  content: AdminReportContent;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="보고서 본문"
      onClick={onClose}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-[900px] flex-col rounded-card bg-md-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-start gap-3 border-b border-md-outline-variant px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[15px] font-semibold text-md-on-surface">
              {content.title ?? "(제목 없음)"}
            </h2>
            <p className="mt-0.5 text-[11.5px] text-md-on-surface-variant">
              {content.chars.toLocaleString()}자 · 인용 {content.citation_count}건
              {" · "}
              <span className="font-mono">{content.report_id.slice(0, 8)}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="inline-flex size-7 items-center justify-center rounded text-md-on-surface-variant hover:bg-md-surface-container-low"
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden>
              close
            </span>
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <MarkdownContent content={content.markdown} compact />
        </div>

        {content.citations.length > 0 ? (
          <details className="shrink-0 border-t border-md-outline-variant px-4 py-2.5">
            <summary className="cursor-pointer text-[12px] font-medium text-md-on-surface-variant">
              인용 {content.citation_count}건 — 검증{" "}
              {content.citations.filter((c) => c.verified).length}건
            </summary>
            <ul className="mt-2 max-h-[180px] space-y-1 overflow-y-auto text-[11.5px]">
              {content.citations.map((c, i) => (
                <li key={i} className="flex gap-1.5 text-md-on-surface-variant">
                  <span className="shrink-0 font-mono">[{c.number ?? "?"}]</span>
                  <span className="truncate">
                    {c.title ?? "(제목 없음)"}
                    {c.publisher ? ` · ${c.publisher}` : ""}
                  </span>
                  {c.verified ? (
                    <span className="shrink-0 text-md-primary" title="원문 대조 검증됨">
                      ✓
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </div>
  );
}
