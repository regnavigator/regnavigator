"use client";

/**
 * 같은 기간의 실사용·내부·전체 비교표(2026-09-21 — "전체와 실사용이 확실히 구분되게").
 *
 * 세 범위는 backend 가 한 규칙(usage_weekly.compute_range)으로 계산한다 — 전체 = 실사용 + 내부.
 * "실사용 비중"은 전체 중 실사용이 차지하는 몫(내부 트래픽이 지표를 얼마나 부풀리는지).
 */
import type { UsageMetricDef, UsageMetrics, UsageScope } from "@/lib/client/admin";
import { downloadCsv, fmtMetric, metricValue, SCOPE_LABEL } from "./format";

const ALL_SCOPES: UsageScope[] = ["real", "internal", "all"];

export function ScopeBreakdown({
  breakdown,
  metrics: allMetrics,
  days,
  showInternal = true,
}: {
  breakdown: Record<UsageScope, UsageMetrics>;
  metrics: UsageMetricDef[];
  days: number;
  /** false = 실사용 열만(내부·전체·비중 숨김, 2026-09-22) */
  showInternal?: boolean;
}) {
  const ORDER: UsageScope[] = showInternal ? ALL_SCOPES : ["real"];
  // "재방문"은 전주 대비 개념 — 임의 기간 비교엔 정의가 없어 늘 0 으로 보인다(주간 섹션에만).
  const metrics = allMetrics.filter((m) => m.key !== "returning_users");
  const exportCsv = () =>
    downloadCsv(
      `medireg_usage_${days}d_breakdown.csv`,
      ["지표", "설명", ...ORDER.map((s) => SCOPE_LABEL[s]), ...(showInternal ? ["실사용 비중(%)"] : [])],
      metrics.map((m) => {
        const r = metricValue(breakdown.real, m.key);
        const a = metricValue(breakdown.all, m.key);
        return [
          m.label,
          m.desc,
          ...ORDER.map((s) => metricValue(breakdown[s], m.key)),
          ...(showInternal ? [a ? ((r / a) * 100).toFixed(1) : ""] : []),
        ];
      }),
    );

  return (
    <section aria-labelledby="scope-breakdown-title" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 id="scope-breakdown-title" className="text-[15px] font-semibold text-md-on-surface">
          {showInternal ? "실사용 · 내부 · 전체 비교" : "실사용 지표"}
        </h2>
        <span className="text-[12px] text-md-on-surface-variant">
          {showInternal
            ? `최근 ${days}일 · 내부 = 관리자·테스트 계정 + 스크립트(e2e·야간 회귀) · 전체 = 실사용 + 내부`
            : `최근 ${days}일 · 관리자·테스트 계정과 스크립트 트래픽 제외`}
        </span>
        <button
          type="button"
          onClick={exportCsv}
          className="ml-auto inline-flex items-center gap-1 rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface hover:bg-md-surface-container-low"
        >
          <span className="material-symbols-outlined text-[15px]" aria-hidden>
            download
          </span>
          CSV
        </button>
      </div>
      <div className="overflow-x-auto rounded-card border border-md-outline-variant">
        <table className="min-w-full text-body-sm">
          <thead className="bg-md-surface-container-low text-[11.5px] font-semibold text-md-on-surface-variant">
            <tr>
              <th className="px-3 py-2 text-left">지표</th>
              {ORDER.map((s) => (
                <th
                  key={s}
                  className={`px-3 py-2 text-right ${s === "real" ? "text-md-on-surface" : ""}`}
                >
                  {SCOPE_LABEL[s]}
                </th>
              ))}
              {showInternal ? <th className="w-[10rem] px-3 py-2 text-left">실사용 비중</th> : null}
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => {
              const r = metricValue(breakdown.real, m.key);
              const a = metricValue(breakdown.all, m.key);
              const share = a ? Math.round((r / a) * 100) : null;
              return (
                <tr key={m.key} className="border-t border-md-outline-variant">
                  <td className="px-3 py-1.5 text-md-on-surface" title={m.desc || undefined}>
                    {m.label}
                  </td>
                  {ORDER.map((s) => (
                    <td
                      key={s}
                      className={`px-3 py-1.5 text-right tabular-nums ${
                        s === "real" ? "font-semibold text-md-on-surface" : "text-md-on-surface-variant"
                      }`}
                    >
                      {fmtMetric(metricValue(breakdown[s], m.key), m.kind)}
                    </td>
                  ))}
                  {showInternal ? (
                  <td className="px-3 py-1.5">
                    {share === null ? (
                      <span className="text-md-on-surface-variant">—</span>
                    ) : (
                      <span className="flex items-center gap-2">
                        <span className="relative inline-block h-1.5 w-20 overflow-hidden rounded-full bg-md-surface-container-high">
                          <span
                            className="absolute inset-y-0 left-0 rounded-full bg-[var(--usage-real)]"
                            style={{ width: `${share}%` }}
                            aria-hidden
                          />
                        </span>
                        <span className="tabular-nums text-[12px] text-md-on-surface-variant">{share}%</span>
                      </span>
                    )}
                  </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
