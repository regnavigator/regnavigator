"use client";

/**
 * 주간 이용 통계(2026-09-21) — "1주일 단위로 정리해 저장하고, 전주와 비교".
 *
 * - 주 = KST 월~일. 끝난 주는 서버에 저장(스냅샷), 이번 주는 실시간(진행 중).
 * - 헤드라인 비교는 **지난주(완료) vs 그 전주** — 진행 중인 주를 완료된 주와 비교하면
 *   요일 수가 달라 늘 감소로 보인다. 이번 주 현재값은 옆에 따로 적는다.
 * - 추이 차트: 주별 누적 막대(실사용 + 내부 = 전체). 한 축·한 지표(지표는 칩으로 전환).
 *   색은 dataviz 기준 팔레트 1·2번(검증 통과, medra 배경에서 주황 대비 2.86 → 막대 위
 *   합계 라벨 + 아래 표로 보완).
 * - 계정 라벨을 바꾸면 저장본은 그대로(stale 표시) — [다시 계산]으로 반영.
 * - showInternal=false(2026-09-22 "내부 이용은 안 보이게"): 차트·표·CSV 에서 내부·전체를
 *   빼고 실사용만 — 화면 공유·보고용.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  getWeeklyStats,
  recomputeWeeklyStats,
  type UsageMetricDef,
  type UsageMetricKey,
  type UsageScope,
  type UsageWeek,
  type WeeklyStats,
} from "@/lib/client/admin";
import { ErrorBanner, PillTab, Spinner } from "@/components/admin/common";
import { delta, downloadCsv, fmtMetric, metricValue, SCOPE_LABEL } from "./format";
import { WeeklyReportPanel } from "./WeeklyReportPanel";
import { useAdminPerms } from "@/components/admin/admin-perms";

const RANGES = [8, 12, 26] as const;
const CHART_METRICS: UsageMetricKey[] = [
  "active_users",
  "questions",
  "threads",
  "reports",
  "documents",
  "cost_usd",
];
const TILE_METRICS: UsageMetricKey[] = [
  "active_users",
  "returning_users",
  "new_users",
  "questions",
  "reports",
  "documents",
];

function shortRange(w: UsageWeek): string {
  return `${w.week_start.slice(5).replace("-", ".")}–${w.week_end.slice(5).replace("-", ".")}`;
}

export function WeeklyUsage({ showInternal = true }: { showInternal?: boolean }) {
  const { can } = useAdminPerms();
  const [range, setRange] = useState<number>(12);
  const [data, setData] = useState<WeeklyStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tableScopeRaw, setTableScope] = useState<UsageScope>("real");
  const tableScope: UsageScope = showInternal ? tableScopeRaw : "real";
  const [chartMetric, setChartMetric] = useState<UsageMetricKey>("active_users");
  const [recomputing, setRecomputing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getWeeklyStats(range));
    } catch (err) {
      console.error("[admin/stats] weekly load failed", err);
      setError("주간 통계를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    void load();
  }, [load]);

  const weeks = data?.weeks ?? []; // 최신이 앞
  const metrics = data?.metrics ?? [];
  const def = (k: UsageMetricKey) => metrics.find((m) => m.key === k);
  const current = weeks.find((w) => w.partial);
  const done = weeks.filter((w) => !w.partial);
  const last = done[0];
  const prev = done[1];
  const staleCount = weeks.filter((w) => w.stale).length;

  const recompute = async () => {
    setRecomputing(true);
    try {
      const r = await recomputeWeeklyStats();
      toast.success(
        r.recomputed.length ? `${r.recomputed.length}주 다시 계산했습니다` : "다시 계산할 주가 없습니다",
      );
      await load();
    } catch (err) {
      console.error("[admin/stats] recompute failed", err);
      toast.error("다시 계산하지 못했습니다");
    } finally {
      setRecomputing(false);
    }
  };

  const exportCsv = () => {
    const scopes: UsageScope[] = showInternal ? ["real", "internal", "all"] : ["real"];
    downloadCsv(
      `medireg_usage_weekly_${weeks.at(-1)?.week_start ?? ""}_${weeks[0]?.week_start ?? ""}.csv`,
      ["주 시작(월)", "주 끝(일)", "상태", "범위", ...metrics.map((m) => m.label)],
      [...weeks].reverse().flatMap((w) =>
        scopes.map((s) => [
          w.week_start,
          w.week_end,
          w.partial ? "진행 중" : w.stale ? "재계산 필요" : "저장됨",
          SCOPE_LABEL[s],
          ...metrics.map((m) => metricValue(w.scopes[s], m.key)),
        ]),
      ),
    );
  };

  return (
    <section aria-labelledby="weekly-title" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="weekly-title" className="text-[15px] font-semibold text-md-on-surface">
          주간 이용
        </h2>
        <span className="text-[12px] text-md-on-surface-variant">
          월~일(한국시간) · 끝난 주는 저장, 이번 주는 실시간
        </span>
        <span className="ml-auto flex items-center gap-2">
          {RANGES.map((r) => (
            <PillTab key={r} active={range === r} label={`${r}주`} onClick={() => setRange(r)} />
          ))}
          {loading ? <Spinner /> : null}
          <button
            type="button"
            onClick={exportCsv}
            disabled={!weeks.length}
            className="inline-flex items-center gap-1 rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface hover:bg-md-surface-container-low disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[15px]" aria-hidden>
              download
            </span>
            CSV
          </button>
        </span>
      </div>

      <ErrorBanner message={error} />

      {/* 주간 보고 메일 설정·발송 — '메일 발신' 권한 */}
      {can("mail") ? <WeeklyReportPanel /> : null}

      {staleCount > 0 ? (
        <div className="flex flex-wrap items-center gap-3 rounded-card border border-md-outline-variant bg-md-surface-container-low px-4 py-2.5 text-[12.5px] text-md-on-surface">
          <span className="material-symbols-outlined text-[18px] text-md-on-surface-variant" aria-hidden>
            info
          </span>
          저장 이후 계정 구분이 바뀐 주가 {staleCount}개 있습니다. 지금 기준으로 다시 계산하면 실사용·내부 숫자가 바뀝니다.
          <button
            type="button"
            onClick={() => void recompute()}
            disabled={recomputing}
            className="ml-auto rounded-pill bg-md-primary px-3 py-1 text-[12px] font-semibold text-md-on-primary disabled:opacity-60"
          >
            {recomputing ? "계산 중…" : "다시 계산"}
          </button>
        </div>
      ) : null}

      {/* 헤드라인: 지난주(완료) vs 그 전주 — 실사용 기준 */}
      {last ? (
        <div className="flex flex-col gap-2">
          <p className="text-[12px] text-md-on-surface-variant">
            실사용 · 지난주 {shortRange(last)}
            {prev ? ` vs 그 전주 ${shortRange(prev)}` : ""}
            {current ? ` · 이번 주 ${shortRange(current)} 진행 중` : ""}
          </p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {TILE_METRICS.map((k) => {
              const d = def(k);
              if (!d) return null;
              const cur = metricValue(last.scopes.real, k);
              const before = prev ? metricValue(prev.scopes.real, k) : null;
              const dd = before === null ? null : delta(cur, before);
              return (
                <div
                  key={k}
                  className="flex flex-col gap-1 rounded-card border border-md-outline-variant bg-md-surface px-3 py-2.5"
                  title={d.desc || undefined}
                >
                  <span className="text-[12px] text-md-on-surface-variant">{d.label}</span>
                  <span className="flex items-baseline gap-2">
                    <span className="text-[22px] font-semibold tabular-nums text-md-on-surface">
                      {fmtMetric(cur, d.kind)}
                    </span>
                    {dd ? (
                      <span
                        className={`inline-flex items-center text-[12px] font-medium tabular-nums ${
                          dd.dir === "up"
                            ? "text-md-success"
                            : dd.dir === "down"
                              ? "text-md-error"
                              : "text-md-on-surface-variant"
                        }`}
                      >
                        <span className="material-symbols-outlined text-[14px]" aria-hidden>
                          {dd.dir === "up" ? "arrow_upward" : dd.dir === "down" ? "arrow_downward" : "remove"}
                        </span>
                        {dd.text}
                        <span className="sr-only">(전주 대비)</span>
                      </span>
                    ) : null}
                  </span>
                  <span className="text-[11.5px] tabular-nums text-md-on-surface-variant">
                    전주 {before === null ? "—" : fmtMetric(before, d.kind)}
                    {current ? ` · 이번 주 ${fmtMetric(metricValue(current.scopes.real, k), d.kind)}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ) : !loading && !error ? (
        <p className="text-body-sm text-md-on-surface-variant">아직 끝난 주가 없습니다.</p>
      ) : null}

      {/* 추이 차트 */}
      {weeks.length ? (
        <div className="flex flex-col gap-2 rounded-card border border-md-outline-variant bg-md-surface p-4">
          <div className="flex flex-wrap items-center gap-2">
            {CHART_METRICS.map((k) => {
              const d = def(k);
              return d ? (
                <PillTab
                  key={k}
                  active={chartMetric === k}
                  label={d.label}
                  onClick={() => setChartMetric(k)}
                />
              ) : null;
            })}
            <span className="ml-auto flex items-center gap-3 text-[12px] text-md-on-surface-variant">
              <Legend swatch="var(--usage-real)" label="실사용" />
              {showInternal ? <Legend swatch="var(--usage-internal)" label="내부" /> : null}
              <Legend swatch="hatched" label="이번 주(진행 중)" />
            </span>
          </div>
          {def(chartMetric) ? (
            <WeeklyChart weeks={[...weeks].reverse()} metric={def(chartMetric)!} showInternal={showInternal} />
          ) : null}
        </div>
      ) : null}

      {/* 표 보기 — 모든 지표, 선택 범위 */}
      {weeks.length ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            {((showInternal ? ["real", "internal", "all"] : ["real"]) as UsageScope[]).map((s) => (
              <PillTab key={s} active={tableScope === s} label={SCOPE_LABEL[s]} onClick={() => setTableScope(s)} />
            ))}
            <span className="text-[12px] text-md-on-surface-variant">괄호 안은 전주 대비</span>
          </div>
          <div className="overflow-x-auto rounded-card border border-md-outline-variant">
            <table className="min-w-full text-body-sm">
              <thead className="bg-md-surface-container-low text-[11.5px] font-semibold text-md-on-surface-variant">
                <tr>
                  <th className="sticky left-0 bg-md-surface-container-low px-3 py-2 text-left">주</th>
                  {metrics.map((m) => (
                    <th key={m.key} className="whitespace-nowrap px-3 py-2 text-right" title={m.desc || undefined}>
                      {m.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {weeks.map((w, i) => {
                  const before = weeks[i + 1];
                  return (
                    <tr key={w.week_start} className="border-t border-md-outline-variant">
                      <td className="sticky left-0 whitespace-nowrap bg-md-surface px-3 py-1.5 text-md-on-surface">
                        <span className="tabular-nums">{shortRange(w)}</span>
                        {w.partial ? (
                          <span className="ml-1.5 rounded bg-md-surface-container-high px-1 text-[10.5px] text-md-on-surface-variant">
                            진행 중
                          </span>
                        ) : w.stale ? (
                          <span
                            className="ml-1.5 rounded bg-md-tertiary-fixed px-1 text-[10.5px] text-[var(--md-on-tertiary-fixed-variant)]"
                            title="저장 이후 계정 구분이 바뀜 — 다시 계산 필요"
                          >
                            재계산 필요
                          </span>
                        ) : null}
                      </td>
                      {metrics.map((m) => {
                        const v = metricValue(w.scopes[tableScope], m.key);
                        const dd =
                          before && !w.partial ? delta(v, metricValue(before.scopes[tableScope], m.key)) : null;
                        return (
                          <td key={m.key} className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums text-md-on-surface">
                            {fmtMetric(v, m.kind)}
                            {dd && dd.text !== "—" ? (
                              <span
                                className={`ml-1 text-[11px] ${
                                  dd.dir === "up" ? "text-md-success" : dd.dir === "down" ? "text-md-error" : "text-md-on-surface-variant"
                                }`}
                              >
                                ({dd.text})
                              </span>
                            ) : null}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden
        className="inline-block size-2.5 rounded-[2px]"
        style={
          swatch === "hatched"
            ? { background: "repeating-linear-gradient(45deg, var(--usage-real) 0 2px, transparent 2px 4px)" }
            : { background: swatch }
        }
      />
      {label}
    </span>
  );
}

/* ─────────────────── 누적 막대(주별) ─────────────────── */

const H = 220;
const PAD = { top: 22, right: 8, bottom: 38, left: 44 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

function WeeklyChart({
  weeks,
  metric,
  showInternal,
}: {
  weeks: UsageWeek[];
  metric: UsageMetricDef;
  showInternal: boolean;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(320, Math.floor(e!.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rows = useMemo(
    () =>
      weeks.map((w) => {
        const real = metricValue(w.scopes.real, metric.key);
        // 내부 숨김 — 막대·합계 라벨 모두 실사용만(내부가 합계로 새어 보이지 않게)
        const internal = showInternal ? metricValue(w.scopes.internal, metric.key) : 0;
        const total = showInternal ? metricValue(w.scopes.all, metric.key) || real + internal : real;
        return { w, real, internal, total };
      }),
    [weeks, metric.key, showInternal],
  );
  const max = niceMax(Math.max(...rows.map((r) => r.total), 0));
  const innerW = width - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const band = innerW / Math.max(rows.length, 1);
  const barW = Math.min(24, band * 0.6);
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
  const ticks = [0, max / 2, max];
  const fmt = (v: number) => fmtMetric(v, metric.kind);
  const GAP = 2; // 누적 구간 사이 표면색 간격
  const R = 4; // 데이터 끝 둥글기

  // 위쪽만 둥근 막대(기준선 쪽은 각짐)
  const barPath = (x: number, top: number, h: number, round: boolean) => {
    if (h <= 0) return "";
    const r = round ? Math.min(R, h, barW / 2) : 0;
    return `M${x},${top + h} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${top + h} Z`;
  };

  const hv = hover === null ? null : rows[hover];
  const hvPrev = hover !== null && hover > 0 ? rows[hover - 1] : null;

  return (
    <div ref={boxRef} className="relative w-full" onMouseLeave={() => setHover(null)}>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label={showInternal ? `주별 ${metric.label} — 실사용과 내부 누적` : `주별 ${metric.label} — 실사용`}
        className="block"
      >
        <defs>
          <pattern id="usage-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="4" height="4" fill="var(--md-surface)" />
            <rect width="2" height="4" fill="var(--usage-real)" />
          </pattern>
          <pattern id="usage-hatch-int" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="4" height="4" fill="var(--md-surface)" />
            <rect width="2" height="4" fill="var(--usage-internal)" />
          </pattern>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--md-outline-variant)" strokeWidth={1} />
            <text x={PAD.left - 6} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--md-on-surface-variant)">
              {fmt(t)}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const cx = PAD.left + band * i + band / 2;
          const x = cx - barW / 2;
          const hReal = (r.real / max) * innerH;
          const hInt = (r.internal / max) * innerH;
          const base = PAD.top + innerH;
          const realTop = base - hReal;
          const intTop = realTop - hInt - (hInt > 0 && hReal > 0 ? GAP : 0);
          const partial = r.w.partial;
          const labelEvery = Math.ceil(rows.length / Math.max(1, Math.floor(innerW / 64)));
          return (
            <g key={r.w.week_start} opacity={hover !== null && hover !== i ? 0.55 : 1}>
              <path d={barPath(x, realTop, hReal, hInt <= 0)} fill={partial ? "url(#usage-hatch)" : "var(--usage-real)"} />
              <path d={barPath(x, intTop, hInt, true)} fill={partial ? "url(#usage-hatch-int)" : "var(--usage-internal)"} />
              {r.total > 0 ? (
                <text x={cx} y={Math.min(realTop, intTop) - 5} textAnchor="middle" fontSize={11} fill="var(--md-on-surface)" className="tabular-nums">
                  {fmt(r.total)}
                </text>
              ) : null}
              {i % labelEvery === 0 || i === rows.length - 1 ? (
                // 주 = 월~일 — 시작일만 쓰면 어느 주인지 헷갈린다(2026-09-22): 두 줄로 시작·끝
                <text x={cx} y={H - 20} textAnchor="middle" fontSize={11} fill="var(--md-on-surface-variant)" className="tabular-nums">
                  <tspan x={cx}>{r.w.week_start.slice(5).replace("-", ".")}</tspan>
                  <tspan x={cx} dy={13}>~{r.w.week_end.slice(5).replace("-", ".")}</tspan>
                </text>
              ) : null}
              {/* 히트 영역 — 막대보다 넓게(밴드 전체) */}
              <rect
                x={PAD.left + band * i}
                y={PAD.top}
                width={band}
                height={innerH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                tabIndex={0}
                aria-label={
                  showInternal
                    ? `${r.w.week_start} 주 ${metric.label} 실사용 ${fmt(r.real)}, 내부 ${fmt(r.internal)}`
                    : `${r.w.week_start} 주 ${metric.label} 실사용 ${fmt(r.real)}`
                }
              />
            </g>
          );
        })}
      </svg>
      {hv && hover !== null ? (
        <div
          className="pointer-events-none absolute z-10 w-[180px] rounded-card border border-md-outline-variant bg-md-surface px-3 py-2 text-[12px] shadow-md"
          style={(() => {
            // 막대를 가리지 않게 옆에 — 오른쪽 공간이 모자라면 왼쪽
            const cx = PAD.left + band * hover + band / 2;
            const right = cx + barW / 2 + 10;
            return { left: right + 180 <= width ? right : Math.max(0, cx - barW / 2 - 10 - 180), top: 4 };
          })()}
        >
          <p className="font-semibold text-md-on-surface">
            {shortRange(hv.w)}
            {hv.w.partial ? " · 진행 중" : ""}
          </p>
          <p className="mt-1 flex justify-between gap-4 text-md-on-surface">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block size-2 rounded-[2px] bg-[var(--usage-real)]" aria-hidden />
              실사용
            </span>
            <span className="tabular-nums">{fmt(hv.real)}</span>
          </p>
          {showInternal ? (
            <>
              <p className="flex justify-between gap-4 text-md-on-surface">
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block size-2 rounded-[2px] bg-[var(--usage-internal)]" aria-hidden />
                  내부
                </span>
                <span className="tabular-nums">{fmt(hv.internal)}</span>
              </p>
              <p className="mt-1 flex justify-between gap-4 border-t border-md-outline-variant pt-1 text-md-on-surface-variant">
                <span>전체</span>
                <span className="tabular-nums">{fmt(hv.total)}</span>
              </p>
            </>
          ) : null}
          {hvPrev && !hv.w.partial ? (
            <p className="text-md-on-surface-variant">
              실사용 전주 대비 {delta(hv.real, hvPrev.real).text}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
