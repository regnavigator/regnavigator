/**
 * 모니터링 대시보드 — 정렬·현황 집계 (2026-10-06). 순수 함수, vitest.
 * "변경"은 **미처리(미읽음·미해제) 누적** 기준(사용자 결정) — 보고서를 만들면 줄어든다.
 */

import type { AlertKind, MonitorThread } from "@/lib/client/monitorThreads";

export const KIND_LABEL: Record<AlertKind, string> = {
  repealed: "폐지", amended: "개정", pending: "시행 예정", effective_date: "시행일",
};

/** 수정 내용이 많은 대상이 앞 — 미읽음 → 변경 수 → 최근 변경 시각 → 관찰 수 → 최근 갱신. */
export function sortTargets(rows: MonitorThread[]): MonitorThread[] {
  return [...rows].sort((a, b) =>
    (b.unread_alerts ?? 0) - (a.unread_alerts ?? 0) ||
    (b.changed_count ?? 0) - (a.changed_count ?? 0) ||
    (b.latest_alert?.detected_at ?? "").localeCompare(a.latest_alert?.detected_at ?? "") ||
    (b.watch_count ?? 0) - (a.watch_count ?? 0) ||
    (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
}

export type Overview = {
  targets: number;
  changedTargets: number;   // 미읽음 변경이 있는 대상 수
  changedArticles: number;  // Σ 미읽음 변경
  lastCheckedAt: string | null;
};

export function overview(rows: MonitorThread[]): Overview {
  const changed = rows.filter((r) => (r.unread_alerts ?? 0) > 0);
  const checked = rows.map((r) => r.last_checked_at ?? "").filter(Boolean).sort();
  return {
    targets: rows.length,
    changedTargets: changed.length,
    changedArticles: changed.reduce((n, r) => n + (r.unread_alerts ?? 0), 0),
    lastCheckedAt: checked.at(-1) ?? null,
  };
}

export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  if (Number.isNaN(d.getTime())) return iso;
  const mm = String(d.getMonth() + 1).padStart(2, "0"), dd = String(d.getDate()).padStart(2, "0");
  return iso.length === 10 ? `${mm}-${dd}` : `${mm}-${dd} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
