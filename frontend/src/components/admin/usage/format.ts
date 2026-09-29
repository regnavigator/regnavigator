/**
 * 이용 통계 공용 포맷·CSV (2026-09-21).
 * 지표 정의(라벨·종류)는 backend `src/usage_weekly.py:METRICS` 가 응답으로 준다.
 */
import type { UsageMetricDef, UsageMetrics, UsageScope } from "@/lib/client/admin";

export const SCOPE_LABEL: Record<UsageScope, string> = {
  real: "실사용",
  internal: "내부",
  all: "전체",
};

export function fmtMetric(v: number | undefined, kind: UsageMetricDef["kind"]): string {
  const n = v ?? 0;
  if (kind === "usd") return `$${n.toFixed(2)}`;
  return n.toLocaleString("ko-KR");
}

/** 전주 대비 — 전주 0 이면 비율 대신 "신규"/"—". */
export function delta(cur: number, prev: number): { text: string; dir: "up" | "down" | "flat" } {
  if (prev === 0 && cur === 0) return { text: "—", dir: "flat" };
  if (prev === 0) return { text: "신규", dir: "up" };
  const pct = ((cur - prev) / prev) * 100;
  if (Math.abs(pct) < 0.5) return { text: "0%", dir: "flat" };
  return { text: `${pct > 0 ? "+" : ""}${pct.toFixed(0)}%`, dir: pct > 0 ? "up" : "down" };
}

/** CSV 한 줄 — 쉼표·따옴표·줄바꿈 이스케이프. */
function row(cells: (string | number)[]): string {
  return cells
    .map((c) => {
      const s = String(c);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    })
    .join(",");
}

/** CSV 파일 저장 — 엑셀 한글 깨짐 방지로 BOM 부착. */
export function downloadCsv(filename: string, header: (string | number)[], rows: (string | number)[][]): void {
  const text = "﻿" + [row(header), ...rows.map(row)].join("\r\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function metricValue(m: UsageMetrics | undefined, key: UsageMetricDef["key"]): number {
  return m ? Number(m[key] ?? 0) : 0;
}
