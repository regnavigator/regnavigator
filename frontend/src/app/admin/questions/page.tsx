"use client";

/**
 * Admin · 이용 조회 — backend `GET /admin/questions` · `GET /admin/stats/search-laws`.
 *
 * 사용량 통계(/admin/stats)가 "숫자"라면, 이 화면은 "무엇을 물었고 어떤 법을 찾았나".
 * - 탭: 질문 리스트(user_question, PII 마스킹) / 법령 검색(rag_search 집계)
 * - 기간 7/30/90일
 * - 질문 탭: 최신순 질문 + 최다 질문 top20
 * - 법령 탭: 법령별 검색 랭킹 + 최다 질의 + 종별 분포
 * - is_admin 가드 (다른 admin 페이지 패턴)
 *
 * 주의: 질문/대화 본문은 backend 에서 PII 마스킹된 상태로만 적재됨(at-rest 정책).
 */

import { useEffect, useState } from "react";
import {
  getAdminQuestions,
  getAdminSearchLaws,
  getAdminClaimAudit,
  type DataScope,
  type AdminQuestions,
  type AdminSearchLaws,
  type AdminClaimAudit,
} from "@/lib/client/admin";
import { ScopeToggle } from "@/components/admin/scope-toggle";
import { AdminUserLabel, ErrorBanner, PillTab, Spinner, StatCard, fmt, formatTime } from "@/components/admin/common";

const PERIODS = [7, 30, 90] as const;
const PAGE_SIZE = 200;
type Tab = "questions" | "laws" | "audit";

export default function AdminQuestionsPage() {
  const [tab, setTab] = useState<Tab>("questions");
  const [days, setDaysRaw] = useState<number>(30);
  const [scope, setScopeRaw] = useState<DataScope>("real");
  const [offset, setOffset] = useState(0);
  const [questions, setQuestions] = useState<AdminQuestions | null>(null);
  const [laws, setLaws] = useState<AdminSearchLaws | null>(null);
  const [audit, setAudit] = useState<AdminClaimAudit | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 기간·scope 가 바뀌면 페이지 리셋 — 이전 offset 이 새 범위를 벗어날 수 있다.
  const setDays = (d: number) => {
    setDaysRaw(d);
    setOffset(0);
  };
  const setScope = (s: DataScope) => {
    setScopeRaw(s);
    setOffset(0);
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const load =
      tab === "questions"
        ? getAdminQuestions(days, PAGE_SIZE, scope, offset).then((q) => {
            if (!cancelled) setQuestions(q);
          })
        : tab === "laws"
          ? getAdminSearchLaws(days, 30, scope).then((l) => {
              if (!cancelled) setLaws(l);
            })
          : getAdminClaimAudit(days, scope).then((a) => {
              if (!cancelled) setAudit(a);
            });
    load
      .catch((err) => {
        console.error("[admin/questions] load failed", err);
        if (!cancelled) setError("데이터를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, days, scope, offset]);

  return (
    <main className="flex flex-col gap-6">
      <header>
        <h1 className="text-h1 text-md-on-surface">이용 조회</h1>
      </header>

      <ScopeToggle scope={scope} onChange={setScope} />

      {/* 탭 + 기간 */}
      <div className="flex flex-wrap items-center gap-2">
        <PillTab
          active={tab === "questions"}
          label="질문 리스트"
          onClick={() => setTab("questions")}
        />
        <PillTab
          active={tab === "laws"}
          label="법령 검색"
          onClick={() => setTab("laws")}
        />
        <PillTab
          active={tab === "audit"}
          label="사실 검증"
          onClick={() => setTab("audit")}
        />
        <span className="mx-2 h-4 w-px bg-md-outline-variant" aria-hidden />
        {PERIODS.map((p) => (
          <PillTab
            key={p}
            active={days === p}
            label={`${p}일`}
            onClick={() => setDays(p)}
          />
        ))}
        {loading ? <Spinner /> : null}
      </div>

      <ErrorBanner message={error} />

      {tab === "questions" ? (
        <QuestionsView
          data={questions}
          loading={loading}
          offset={offset}
          onOffset={setOffset}
        />
      ) : tab === "laws" ? (
        <LawsView data={laws} loading={loading} />
      ) : (
        <AuditView data={audit} loading={loading} />
      )}
    </main>
  );
}

/* ─────────────────── 사실 검증 탭 (환각률) ─────────────────── */

function AuditView({
  data,
  loading,
}: {
  data: AdminClaimAudit | null;
  loading: boolean;
}) {
  const samples = data?.samples ?? [];
  const unsupPct =
    data?.unsupported_rate != null
      ? (data.unsupported_rate * 100).toFixed(1)
      : "–";
  const supPct =
    data?.supported_rate != null
      ? (data.supported_rate * 100).toFixed(1)
      : "–";
  return (
    <div className="flex flex-col gap-6">
      <p className="text-body-sm text-md-on-surface-variant">
        답변의 정량·특정 사실(조문번호·수수료·기한·날짜·판례)이 검색 근거로 지지되는지
        판정한 결과입니다. 무인용 사실 환각의 관측 지표 — 낮을수록 좋습니다.
      </p>

      {/* 요약 카드 */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="미지지율 (환각 신호)"
          value={`${unsupPct}%`}
          sub={`근거없음+어긋남 / 전체`}
          tone="warn"
        />
        <StatCard label="지지율" value={`${supPct}%`} sub="근거 확인됨" />
        <StatCard
          label="검증 사실 수"
          value={fmt(data?.total_claims ?? 0)}
          sub={`턴 ${fmt(data?.turns_audited ?? 0)} · 유저 ${fmt(data?.unique_users ?? 0)}`}
        />
        <StatCard
          label="어긋남 / 근거없음"
          value={`${fmt(data?.contradicted ?? 0)} / ${fmt(data?.unverified ?? 0)}`}
          sub="contradicted / unverified"
          tone="warn"
        />
      </div>

      {/* 미지지 사실 샘플 */}
      <section className="flex flex-col gap-3">
        <h2 className="text-h3 text-md-on-surface">미지지 사실 샘플</h2>
        <ul className="flex flex-col gap-2">
          {samples.map((s, i) => (
            <li
              key={`${s.ts}-${i}`}
              className="rounded-card border border-md-outline-variant bg-md-surface px-4 py-3"
            >
              <header className="mb-1 flex flex-wrap items-center gap-2 text-[11.5px] text-md-on-surface-variant">
                <span
                  className={
                    "inline-flex items-center rounded-pill px-2 py-0.5 text-[10.5px] font-semibold " +
                    (s.verdict === "contradicted"
                      ? "bg-md-error-container text-md-on-error-container"
                      : "bg-md-surface-container-high text-md-on-surface-variant")
                  }
                >
                  {s.verdict === "contradicted" ? "어긋남" : "근거없음"}
                </span>
                <span className="font-mono">{formatTime(s.ts)}</span>
                {s.thread_id ? (
                  <span>
                    thread{" "}
                    <code className="font-mono">{s.thread_id.slice(0, 8)}</code>
                  </span>
                ) : null}
              </header>
              <p
                className="text-body-sm leading-relaxed text-md-on-surface"
                style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
              >
                {s.claim || (
                  <span className="italic text-md-on-surface-variant">
                    (내용 없음)
                  </span>
                )}
              </p>
            </li>
          ))}
          {samples.length === 0 && !loading ? (
            <li className="rounded-card border border-md-outline-variant px-4 py-8 text-center text-md-on-surface-variant">
              미지지 사실 샘플이 없습니다. (데이터가 쌓이는 중이거나 환각 신호 없음)
            </li>
          ) : null}
        </ul>
      </section>
    </div>
  );
}

/* ─────────────────── 질문 탭 ─────────────────── */

function QuestionsView({
  data,
  loading,
  offset,
  onOffset,
}: {
  data: AdminQuestions | null;
  loading: boolean;
  offset: number;
  onOffset: (n: number) => void;
}) {
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasMore = data?.has_more ?? false;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <section className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-h3 text-md-on-surface">최근 질문</h2>
          <span className="text-body-sm text-md-on-surface-variant">
            총 {total.toLocaleString()}건
            {total > items.length && items.length > 0
              ? ` (${(offset + 1).toLocaleString()}–${(offset + items.length).toLocaleString()})`
              : ""}{" "}
            · 유저 {data?.unique_users ?? 0}명
          </span>
        </div>
        <ul className="flex flex-col gap-2">
          {items.map((it, i) => (
            <li
              key={`${it.ts}-${i}`}
              className="rounded-card border border-md-outline-variant bg-md-surface px-4 py-3 transition-colors hover:border-md-primary-fixed-dim"
            >
              <header className="mb-1.5 flex flex-wrap items-center gap-2 text-[11.5px] text-md-on-surface-variant">
                <span className="font-mono">{formatTime(it.ts)}</span>
                {it.forced_search ? (
                  <span className="inline-flex items-center gap-1 rounded-pill bg-md-primary-fixed px-2 py-0.5 text-[10.5px] font-semibold text-md-on-primary-fixed-variant">
                    검색 강제
                  </span>
                ) : null}
                {it.thread_id ? (
                  <span>
                    thread{" "}
                    <code className="font-mono">
                      {it.thread_id.slice(0, 8)}
                    </code>
                  </span>
                ) : null}
                {/* 작성자 — 표시명(또는 이메일) + 소속·직군 배지. 미상은 익명. */}
                <span className="ml-auto flex min-w-0 items-center gap-1.5">
                  {it.affiliation || it.job_role ? (
                    <span className="truncate rounded-pill bg-md-surface-container-high px-2 py-0.5 text-[10.5px] text-md-on-surface-variant">
                      {[it.affiliation, it.job_role].filter(Boolean).join(" · ")}
                    </span>
                  ) : null}
                  <AdminUserLabel
                    displayName={it.display_name}
                    memo={it.admin_memo}
                    email={it.email}
                    userId={it.user_id}
                    className="text-[11px]"
                  />
                </span>
              </header>
              <p
                className="whitespace-pre-wrap text-body-sm leading-relaxed text-md-on-surface"
                style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
              >
                {it.question || (
                  <span className="italic text-md-on-surface-variant">
                    (본문 없음)
                  </span>
                )}
              </p>
            </li>
          ))}
          {items.length === 0 && !loading ? (
            <li className="rounded-card border border-md-outline-variant px-4 py-8 text-center text-md-on-surface-variant">
              질문이 없습니다.
            </li>
          ) : null}
        </ul>
        {offset > 0 || hasMore ? (
          <div className="flex items-center justify-between border-t border-md-outline-variant pt-3 text-body-sm">
            <button
              type="button"
              disabled={offset === 0 || loading}
              onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded px-2.5 py-1 font-medium text-md-primary hover:bg-md-surface-container-low disabled:opacity-40 disabled:hover:bg-transparent"
            >
              ← 최근
            </button>
            <span className="tabular-nums text-md-on-surface-variant">
              {Math.floor(offset / PAGE_SIZE) + 1} /{" "}
              {Math.max(1, Math.ceil(total / PAGE_SIZE))} 페이지
            </span>
            <button
              type="button"
              disabled={!hasMore || loading}
              onClick={() => onOffset(offset + PAGE_SIZE)}
              className="rounded px-2.5 py-1 font-medium text-md-primary hover:bg-md-surface-container-low disabled:opacity-40 disabled:hover:bg-transparent"
            >
              이전 →
            </button>
          </div>
        ) : null}
      </section>

      <aside className="flex flex-col gap-3">
        <h2 className="text-h3 text-md-on-surface">최다 질문</h2>
        <RankList
          items={(data?.top_questions ?? []).map((q) => ({
            label: q.question,
            count: q.count,
          }))}
          empty="집계 없음"
        />
      </aside>
    </div>
  );
}

/* ─────────────────── 법령 검색 탭 ─────────────────── */

function LawsView({
  data,
  loading,
}: {
  data: AdminSearchLaws | null;
  loading: boolean;
}) {
  const laws = data?.top_laws ?? [];
  const maxSearches = laws.reduce((m, l) => Math.max(m, l.searches || 0), 0);
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <section className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-h3 text-md-on-surface">검색된 법령</h2>
          <span className="text-body-sm text-md-on-surface-variant">
            검색 {data?.total_searches ?? 0}건 · 유저{" "}
            {data?.unique_users ?? 0}명
          </span>
        </div>
        <div className="overflow-x-auto rounded-card border border-md-outline-variant">
          <table className="min-w-full text-body-sm">
            <thead className="bg-md-surface-container-low text-[11px] font-semibold uppercase tracking-wide text-md-on-surface-variant">
              <tr>
                <th className="px-3 py-2 text-left">법령</th>
                <th className="w-[220px] px-3 py-2 text-left">검색 등장</th>
                <th className="px-3 py-2 text-right">히트</th>
              </tr>
            </thead>
            <tbody>
              {laws.map((l, i) => {
                const pct =
                  maxSearches > 0
                    ? Math.round(((l.searches || 0) / maxSearches) * 100)
                    : 0;
                return (
                  <tr
                    key={`${l.law_id}-${i}`}
                    className="border-t border-md-outline-variant hover:bg-md-surface-container-low"
                  >
                    <td className="px-3 py-2 text-md-on-surface">
                      <span className="font-medium">{l.law_title}</span>
                      <span className="ml-1.5 font-mono text-[10.5px] text-md-on-surface-variant">
                        {l.law_id}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="relative inline-block h-2 w-[120px] shrink-0 overflow-hidden rounded bg-md-surface-container-high">
                          <span
                            className="absolute inset-y-0 left-0 rounded bg-md-primary"
                            style={{ width: `${pct}%` }}
                            aria-hidden
                          />
                        </span>
                        <span className="tabular-nums text-md-on-surface-variant">
                          {l.searches}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-md-on-surface-variant">
                      {l.hits}
                    </td>
                  </tr>
                );
              })}
              {laws.length === 0 && !loading ? (
                <tr>
                  <td
                    colSpan={3}
                    className="px-3 py-8 text-center text-md-on-surface-variant"
                  >
                    검색된 법령이 없습니다.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        {data?.by_target_type &&
        Object.keys(data.by_target_type).length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.by_target_type).map(([t, n]) => (
              <span
                key={t}
                className="rounded-pill border border-md-outline-variant px-2.5 py-1 text-[11.5px] text-md-on-surface-variant"
              >
                {t} <span className="tabular-nums font-semibold">{n}</span>
              </span>
            ))}
          </div>
        ) : null}
      </section>

      <aside className="flex flex-col gap-3">
        <h2 className="text-h3 text-md-on-surface">최다 검색 질의</h2>
        <RankList
          items={(data?.top_queries ?? []).map((q) => ({
            label: q.query,
            count: q.count,
          }))}
          empty="집계 없음"
        />
      </aside>
    </div>
  );
}

/* ─────────────────── 공용 ─────────────────── */

function RankList({
  items,
  empty,
}: {
  items: { label: string; count: number }[];
  empty: string;
}) {
  if (items.length === 0) {
    return (
      <p className="rounded-card border border-md-outline-variant px-3 py-6 text-center text-body-sm text-md-on-surface-variant">
        {empty}
      </p>
    );
  }
  const max = items.reduce((m, it) => Math.max(m, it.count), 0);
  return (
    <ol className="flex flex-col gap-1.5">
      {items.map((it, i) => (
        <li
          key={`${it.label}-${i}`}
          className="rounded-card border border-md-outline-variant bg-md-surface px-3 py-2"
        >
          <div className="flex items-baseline gap-2">
            <span className="w-5 shrink-0 text-right font-mono text-[11px] text-md-on-surface-variant">
              {i + 1}
            </span>
            <span
              className="flex-1 truncate text-body-sm text-md-on-surface"
              title={it.label}
            >
              {it.label}
            </span>
            <span className="shrink-0 tabular-nums text-[12px] font-semibold text-md-primary">
              {it.count}
            </span>
          </div>
          <span className="relative mt-1 block h-1 overflow-hidden rounded bg-md-surface-container-high">
            <span
              className="absolute inset-y-0 left-0 rounded bg-md-primary-fixed-dim"
              style={{ width: `${max > 0 ? (it.count / max) * 100 : 0}%` }}
              aria-hidden
            />
          </span>
        </li>
      ))}
    </ol>
  );
}
