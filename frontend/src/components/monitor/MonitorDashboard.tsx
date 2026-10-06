"use client";

/**
 * MonitorDashboard — 규제 모니터링 모드의 첫 화면 (2026-10-06).
 *
 * 사용자 지침: 모니터링의 메인은 **대상 대시보드**다. 대상(=모니터링 스레드)마다 카드,
 * 많아지면 전문가 타일처럼 옆으로 넘긴다. 전체 현황(변경된 대상·조문 수)은 인사 자리에.
 * 수정 내용이 많은 대상이 앞. 카드를 누르면 그 스레드로.
 *
 * "변경"은 미처리(미읽음) 누적 — 그 스레드의 변경 보고서를 만들면 줄어든다(§2-5).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { MONITOR_CHANGED_EVENT } from "@/components/thread/ThreadList";
import { TilePager } from "@/components/ui/TilePager";
import {
  createMonitorThread,
  listMonitorThreads,
  type MonitorThread,
} from "@/lib/client/monitorThreads";
import { THREAD_LIST_CHANGED_EVENT } from "@/lib/client/threads";
import { fmtWhen, KIND_LABEL, overview, sortTargets } from "@/lib/monitor/dashboard";

type Tile = { kind: "target"; t: MonitorThread } | { kind: "add" };

export function MonitorDashboard({ greeting }: { greeting: string }) {
  const router = useRouter();
  const [rows, setRows] = useState<MonitorThread[] | null>(null);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    listMonitorThreads().then((r) => setRows(r.threads)).catch(() => setRows([]));
  }, []);
  useEffect(() => {
    load();
    window.addEventListener(MONITOR_CHANGED_EVENT, load);
    window.addEventListener(THREAD_LIST_CHANGED_EVENT, load);
    return () => {
      window.removeEventListener(MONITOR_CHANGED_EVENT, load);
      window.removeEventListener(THREAD_LIST_CHANGED_EVENT, load);
    };
  }, [load]);

  const sorted = useMemo(() => sortTargets(rows ?? []), [rows]);
  const ov = useMemo(() => overview(rows ?? []), [rows]);
  const tiles = useMemo<Tile[]>(
    () => [...sorted.map((t) => ({ kind: "target" as const, t })), { kind: "add" as const }],
    [sorted],
  );

  const create = async () => {
    const n = name.trim();
    if (!n || busy) return;
    setBusy(true);
    try {
      const r = await createMonitorThread(n);
      window.dispatchEvent(new Event(THREAD_LIST_CHANGED_EVENT));
      router.push(`/new?threadId=${encodeURIComponent(r.thread_id)}`);
    } catch {
      toast.error("모니터링 대상을 만들지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const headline = rows === null
    ? "모니터링 대상을 불러오는 중…"
    : ov.targets === 0
      ? "아직 모니터링 대상이 없습니다. 첫 대상을 만들어 보세요."
      : ov.changedTargets > 0
        ? `확인 안 한 변경 — 대상 ${ov.changedTargets} · 조문 ${ov.changedArticles}건`
        : `확인 안 한 변경 없음${ov.lastCheckedAt ? ` · 마지막 점검 ${fmtWhen(ov.lastCheckedAt)}` : ""}`;

  return (
    <div className="relative flex flex-col items-center gap-8 px-4" data-testid="monitor-dashboard">
      <div className="max-w-[560px] text-center">
        <h1 className="text-[26px] font-semibold leading-[1.2] text-md-on-surface sm:text-[30px]"
            style={{ letterSpacing: "-0.02em" }}>
          {greeting}
        </h1>
        <p className="mt-2.5 text-[15px] text-md-on-surface-variant" data-testid="monitor-overview">
          {rows !== null && ov.targets > 0 ? `관찰 대상 ${ov.targets}개 · ` : ""}
          {ov.changedTargets > 0 ? <span className="font-semibold text-md-error">{headline}</span> : headline}
        </p>
      </div>

      <TilePager
        items={tiles}
        keyOf={(x) => (x.kind === "add" ? "__add" : x.t.id)}
        ariaLabel="모니터링 대상"
        testId="monitor-tiles"
        render={(x, { active }) =>
          x.kind === "add" ? (
            naming ? (
              <form
                data-testid="monitor-add-form"
                onSubmit={(e) => { e.preventDefault(); void create(); }}
                className="flex h-full min-h-[128px] w-full flex-col justify-between rounded-[10px] border border-md-primary bg-md-surface-container-lowest p-3"
              >
                <label className="text-[11px] text-md-on-surface-variant" htmlFor="monitor-add-name">
                  모니터링 대상 이름 <span className="text-md-error">*</span>
                </label>
                <input id="monitor-add-name" autoFocus value={name} maxLength={120}
                       onChange={(e) => setName(e.target.value)}
                       onKeyDown={(e) => { if (e.key === "Escape") { setNaming(false); setName(""); } }}
                       placeholder="예: 아크로제약 수입규제"
                       className="w-full rounded-[6px] border border-md-outline-variant bg-md-surface px-2 py-1 text-[12.5px] outline-none focus:border-md-primary" />
                <div className="flex gap-1.5">
                  <button type="submit" disabled={!name.trim() || busy}
                          className="flex-1 rounded-pill bg-md-primary px-3 py-1 text-[12px] font-semibold text-md-on-primary disabled:opacity-40">
                    만들기
                  </button>
                  <button type="button" onClick={() => { setNaming(false); setName(""); }}
                          className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface-variant">
                    취소
                  </button>
                </div>
              </form>
            ) : (
              <button type="button" data-testid="monitor-add" tabIndex={active ? 0 : -1}
                      onClick={() => setNaming(true)}
                      className="flex h-full min-h-[128px] w-full flex-col items-center justify-center gap-1.5 rounded-[10px] border border-dashed border-md-outline-variant text-md-on-surface-variant transition-colors hover:border-md-primary hover:text-md-primary">
                <span className="material-symbols-outlined text-[24px]" aria-hidden>add_circle</span>
                <span className="text-[13px] font-medium">모니터링 대상 추가</span>
              </button>
            )
          ) : (
            <TargetCard t={x.t} active={active}
                        onOpen={() => router.push(`/new?threadId=${encodeURIComponent(x.t.id)}`)} />
          )
        }
      />
    </div>
  );
}

function TargetCard({ t, active, onOpen }: { t: MonitorThread; active: boolean; onOpen: () => void }) {
  const changed = t.changed_count ?? 0;
  const unread = t.unread_alerts ?? 0;
  const kinds = Object.entries(t.kinds ?? {}).filter(([, n]) => (n ?? 0) > 0) as [keyof typeof KIND_LABEL, number][];
  return (
    <button
      type="button"
      data-monitor-card={t.id}
      data-unread={unread}
      tabIndex={active ? 0 : -1}
      onClick={onOpen}
      className={
        "flex h-full min-h-[128px] w-full flex-col gap-1 rounded-[10px] border p-3 text-left transition-colors hover:bg-md-surface-container-low " +
        (unread > 0 ? "border-md-error/60 bg-md-surface-container-lowest hover:border-md-error"
                    : "border-md-outline-variant bg-md-surface-container-lowest hover:border-md-primary")
      }
    >
      <span className="flex items-center gap-1.5">
        <span className={"material-symbols-outlined text-[16px] " + (unread > 0 ? "text-md-error" : "text-md-primary")} aria-hidden>
          {unread > 0 ? "notifications_active" : "visibility"}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold leading-snug text-md-on-surface">
          {t.title || "이름 없는 대상"}
        </span>
        {unread > 0 ? (
          <span className="shrink-0 rounded-pill bg-md-error px-1.5 text-[10px] font-semibold text-md-on-error">{unread}</span>
        ) : null}
      </span>
      <span className="text-[11.5px] text-md-on-surface-variant">
        관찰 {t.watch_count} · 변경 {changed}
        {unread > 0 && unread !== changed ? ` (미확인 ${unread})` : ""}
      </span>
      {kinds.length ? (
        <span className="flex flex-wrap gap-1">
          {kinds.map(([k, n]) => (
            <span key={k} className="rounded-pill bg-md-surface-container px-1.5 py-px text-[10px] text-md-on-surface-variant">
              {KIND_LABEL[k]} {n}
            </span>
          ))}
        </span>
      ) : t.watch_count === 0 ? (
        <span className="text-[11px] text-md-on-surface-variant/80">조문을 아직 담지 않음</span>
      ) : null}
      {t.latest_alert ? (
        <span className="line-clamp-2 text-[11px] leading-[1.45] text-md-on-surface">{t.latest_alert.summary}</span>
      ) : null}
      <span className="mt-auto text-[10.5px] text-md-on-surface-variant/80">
        {t.last_checked_at ? `마지막 확인 ${fmtWhen(t.last_checked_at)}` : t.created_at ? `생성 ${fmtWhen(t.created_at)}` : ""}
      </span>
    </button>
  );
}
