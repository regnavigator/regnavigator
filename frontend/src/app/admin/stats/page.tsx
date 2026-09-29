"use client";

/**
 * Admin · 사용 통계 — backend `GET /admin/stats?days=N` (events 테이블 일별 집계).
 *
 * - 상단 합계 카드 4개: LLM 콜 · 활성 사용자 최대치 · 총 토큰 · 총 비용($)
 * - 일별 테이블(최신순) — 토큰 열은 CSS width 바 시각화 (라이브러리 X)
 * - 기간 선택 7/30/90일
 * - is_admin 가드 (users 페이지 패턴)
 * - 2026-09-21: 주간 이용(저장·전주 비교) + 같은 기간 실사용·내부·전체 비교표 + CSV.
 *   날짜는 한국시간 기준(backend daily_stats). "실사용"에서 빠지는 계정 = 사용자 관리 › 구분.
 * - 2026-09-22: [내부 이용 표시] 토글 — 기본 꺼짐(실사용만). 켜야 내부·전체가 주간 차트·비교표·일별에 나온다.
 *   선택은 브라우저에 기억(localStorage — 관리자 개인 편의).
 */

import { useEffect, useState } from "react";
import { getAdminStats, type AdminStats, type DataScope } from "@/lib/client/admin";
import { ScopeToggle } from "@/components/admin/scope-toggle";
import { ErrorBanner, PillTab, Spinner, StatCard, fmt } from "@/components/admin/common";
import { ScopeBreakdown } from "@/components/admin/usage/ScopeBreakdown";
import { WeeklyUsage } from "@/components/admin/usage/WeeklyUsage";
import { downloadCsv } from "@/components/admin/usage/format";

const PERIODS = [7, 30, 90] as const;
const SHOW_INTERNAL_KEY = "admin.stats.showInternal";

export default function AdminStatsPage() {
  const [days, setDays] = useState<number>(30);
  const [scopeRaw, setScope] = useState<DataScope>("real");
  // 기본 = 실사용만(2026-09-22 운영자: "토글로 켜야만 전체 사용량") — 켠 상태만 기억한다.
  const [showInternal, setShowInternal] = useState(false);
  useEffect(() => {
    try {
      if (localStorage.getItem(SHOW_INTERNAL_KEY) === "1") setShowInternal(true);
    } catch {
      /* 저장소 차단 — 기본값(표시) */
    }
  }, []);
  const toggleInternal = (v: boolean) => {
    setShowInternal(v);
    try {
      localStorage.setItem(SHOW_INTERNAL_KEY, v ? "1" : "0");
    } catch {
      /* 무시 */
    }
  };
  // 내부 숨김이면 일별 표도 실사용 고정("전체"는 내부를 포함하므로)
  const scope: DataScope = showInternal ? scopeRaw : "real";
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void getAdminStats(days, scope)
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch((err) => {
        console.error("[admin/stats] load failed", err);
        if (!cancelled) setError("통계를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days, scope]);

  // 최신순 정렬 보장 + 파생값
  const daily = (stats?.daily ?? [])
    .slice()
    .sort((a, b) => b.day.localeCompare(a.day));
  const totals = stats?.totals;
  const maxActiveUsers = daily.reduce(
    (m, d) => Math.max(m, d.active_users || 0),
    0,
  );
  const totalTokens = totals ? totals.input_tokens + totals.output_tokens : 0;
  const maxDayTokens = daily.reduce(
    (m, d) => Math.max(m, (d.input_tokens || 0) + (d.output_tokens || 0)),
    0,
  );

  return (
    <main className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-h1 text-md-on-surface">사용 통계</h1>
        <button
          type="button"
          role="switch"
          aria-checked={showInternal}
          onClick={() => toggleInternal(!showInternal)}
          title="끄면 관리자·테스트 계정과 스크립트(e2e·야간 회귀) 이용을 화면에서 모두 숨깁니다"
          className="ml-auto inline-flex items-center gap-2 text-[13px] text-md-on-surface"
        >
          <span
            className={`relative inline-block h-5 w-9 rounded-full transition-colors ${
              showInternal ? "bg-md-primary" : "bg-md-outline-variant"
            }`}
            aria-hidden
          >
            <span
              className={`absolute top-0.5 size-4 rounded-full bg-md-surface shadow transition-all ${
                showInternal ? "left-[18px]" : "left-0.5"
              }`}
            />
          </span>
          내부 이용 표시
        </button>
      </header>

      <WeeklyUsage showInternal={showInternal} />

      <hr className="border-md-outline-variant" />

      <ErrorBanner message={error} />

      {showInternal ? (
        <ScopeToggle scope={scope} onChange={setScope} />
      ) : (
        <p className="text-[12px] text-md-on-surface-variant">
          실사용만 표시 중 — 관리자·테스트 계정과 스크립트 이용은 숨겨져 있습니다.
        </p>
      )}

      {/* 기간 선택 */}
      <div className="flex items-center gap-2">
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

      {/* 합계 카드 4개 */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon="smart_toy"
          label="LLM 콜"
          value={fmt(totals?.llm_calls ?? 0)}
        />
        <StatCard
          icon="group"
          label="활성 사용자 (일 최대)"
          value={fmt(maxActiveUsers)}
        />
        <StatCard
          icon="token"
          label="총 토큰"
          value={fmt(totalTokens)}
          sub={
            totals
              ? `입력 ${fmt(totals.input_tokens)} · 출력 ${fmt(totals.output_tokens)}`
              : undefined
          }
        />
        <StatCard
          icon="payments"
          label="총 비용 (USD)"
          value={`$${(totals?.cost_usd ?? 0).toFixed(2)}`}
          sub={
            totals
              ? `쿼터 차단 ${fmt(totals.quota_blocked)} · 인용 신고 ${fmt(totals.citation_reports)}`
              : undefined
          }
        />
      </div>

      {stats?.breakdown && stats.metrics ? (
        <ScopeBreakdown
          breakdown={stats.breakdown}
          metrics={stats.metrics}
          days={days}
          showInternal={showInternal}
        />
      ) : null}

      <div className="flex items-center gap-2">
        <h2 className="text-[15px] font-semibold text-md-on-surface">일별</h2>
        <span className="text-[12px] text-md-on-surface-variant">
          {scope === "real" ? "실사용" : "전체"} · 한국시간 날짜
        </span>
        <button
          type="button"
          disabled={!daily.length}
          onClick={() =>
            downloadCsv(
              `medireg_usage_daily_${scope}_${days}d.csv`,
              ["날짜", "LLM 콜", "활성 사용자", "입력 토큰", "출력 토큰", "비용(USD)", "쿼터 차단", "인용 신고"],
              [...daily].reverse().map((d) => [
                d.day, d.llm_calls || 0, d.active_users || 0, d.input_tokens || 0,
                d.output_tokens || 0, (d.cost_usd || 0).toFixed(4), d.quota_blocked || 0,
                d.citation_reports || 0,
              ]),
            )
          }
          className="ml-auto inline-flex items-center gap-1 rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface hover:bg-md-surface-container-low disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[15px]" aria-hidden>download</span>
          CSV
        </button>
      </div>

      {/* 일별 테이블 — 최신순, 토큰 열 막대 시각화 */}
      <div className="overflow-x-auto rounded-card border border-md-outline-variant">
        <table className="min-w-full text-body-sm">
          <thead className="bg-md-surface-container-low text-[11px] font-semibold uppercase tracking-wide text-md-on-surface-variant">
            <tr>
              <th className="px-3 py-2 text-left">날짜</th>
              <th className="px-3 py-2 text-right">LLM 콜</th>
              <th className="px-3 py-2 text-right">활성 사용자</th>
              <th className="w-[280px] px-3 py-2 text-left">토큰 (입력+출력)</th>
              <th className="px-3 py-2 text-right">비용 ($)</th>
              <th className="px-3 py-2 text-right">쿼터 차단</th>
              <th className="px-3 py-2 text-right">인용 신고</th>
            </tr>
          </thead>
          <tbody>
            {daily.map((d) => {
              const tokens = (d.input_tokens || 0) + (d.output_tokens || 0);
              const pct =
                maxDayTokens > 0 ? Math.round((tokens / maxDayTokens) * 100) : 0;
              return (
                <tr
                  key={d.day}
                  className="border-t border-md-outline-variant hover:bg-md-surface-container-low"
                >
                  <td className="px-3 py-2 font-medium tabular-nums text-md-on-surface">
                    {d.day}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-md-on-surface">
                    {fmt(d.llm_calls || 0)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-md-on-surface">
                    {fmt(d.active_users || 0)}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="relative inline-block h-2 w-[140px] shrink-0 overflow-hidden rounded bg-md-surface-container-high">
                        <span
                          className="absolute inset-y-0 left-0 rounded bg-md-primary"
                          style={{ width: `${pct}%` }}
                          aria-hidden
                        />
                      </span>
                      <span className="tabular-nums text-md-on-surface-variant">
                        {fmt(tokens)}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-md-on-surface-variant">
                    {(d.cost_usd || 0).toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-md-on-surface-variant">
                    {d.quota_blocked ? fmt(d.quota_blocked) : "–"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-md-on-surface-variant">
                    {d.citation_reports ? fmt(d.citation_reports) : "–"}
                  </td>
                </tr>
              );
            })}
            {daily.length === 0 && !loading ? (
              <tr>
                <td
                  colSpan={7}
                  className="px-3 py-8 text-center text-md-on-surface-variant"
                >
                  집계된 통계가 없습니다.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </main>
  );
}
