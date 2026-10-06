import { describe, expect, it } from "vitest";

import type { MonitorThread } from "@/lib/client/monitorThreads";
import { fmtWhen, overview, sortTargets } from "@/lib/monitor/dashboard";

const t = (id: string, o: Partial<MonitorThread> = {}): MonitorThread =>
  ({ id, title: id, watch_count: 0, unread_alerts: 0, changed_count: 0, ...o });

describe("sortTargets — 수정 내용이 많은 대상이 앞", () => {
  it("미읽음 → 변경 수 → 최근 변경 → 관찰 수 순", () => {
    const rows = [
      t("quiet", { watch_count: 9 }),
      t("read-only", { changed_count: 3, unread_alerts: 0 }),
      t("hot", { changed_count: 2, unread_alerts: 2, latest_alert: { summary: "", kind: "amended", detected_at: "2026-10-05" } }),
      t("hot-old", { changed_count: 2, unread_alerts: 2, latest_alert: { summary: "", kind: "amended", detected_at: "2026-10-01" } }),
    ];
    expect(sortTargets(rows).map((r) => r.id)).toEqual(["hot", "hot-old", "read-only", "quiet"]);
  });
  it("입력 배열을 바꾸지 않는다", () => {
    const rows = [t("a", { unread_alerts: 0 }), t("b", { unread_alerts: 1 })];
    sortTargets(rows);
    expect(rows.map((r) => r.id)).toEqual(["a", "b"]);
  });
});

describe("overview — 미처리 누적", () => {
  it("미읽음이 있는 대상 수와 조문 수를 합산하고 마지막 점검을 고른다", () => {
    const ov = overview([
      t("a", { unread_alerts: 3, last_checked_at: "2026-10-05T09:00:00Z" }),
      t("b", { unread_alerts: 0, changed_count: 2, last_checked_at: "2026-10-06T09:00:00Z" }),
      t("c", { unread_alerts: 1 }),
    ]);
    expect(ov).toEqual({ targets: 3, changedTargets: 2, changedArticles: 4, lastCheckedAt: "2026-10-06T09:00:00Z" });
  });
  it("빈 목록", () => {
    expect(overview([])).toEqual({ targets: 0, changedTargets: 0, changedArticles: 0, lastCheckedAt: null });
  });
});

describe("fmtWhen", () => {
  it("날짜만이면 MM-DD, 시각이 있으면 MM-DD HH:mm", () => {
    expect(fmtWhen("2026-10-06")).toBe("10-06");
    expect(fmtWhen("2026-10-06T09:05:00")).toBe("10-06 09:05");
    expect(fmtWhen(null)).toBe("");
  });
});
