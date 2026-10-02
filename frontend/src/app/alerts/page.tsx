"use client";

/**
 * `/alerts` — 규제 변경 알람 **모아보기** (2026-10-02).
 *
 * 스레드마다 들어가 확인하게 하면 결국 아무도 안 본다. 전 스레드 알람을 한
 * 화면에 모으고, 읽음·보관으로 줄여 나가게 한다.
 *
 * 설계: `backend/docs/spec/monitor-threads-design.md`.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  dismissAlert,
  listAlerts,
  readAlert,
  type MonitorAlert,
} from "@/lib/client/monitorThreads";

const KIND_LABEL: Record<string, string> = {
  repealed: "폐지",
  pending: "개정예정",
  amended: "시행일 변경",
  effective_date: "시행일 변경",
};

const KIND_TONE: Record<string, string> = {
  repealed: "bg-md-error-container text-md-on-error-container",
  pending: "bg-md-tertiary-fixed text-md-on-tertiary-fixed-variant",
  amended: "bg-md-surface-container text-md-on-surface-variant",
  effective_date: "bg-md-surface-container text-md-on-surface-variant",
};

export default function AlertsPage() {
  const [rows, setRows] = useState<MonitorAlert[] | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [kind, setKind] = useState("");
  const [total, setTotal] = useState(0);

  const load = useCallback(async () => {
    try {
      const r = await listAlerts({ unread: unreadOnly, kind: kind || undefined });
      setRows(r.alerts);
      setTotal(r.unread_total);
    } catch {
      setRows([]);
      toast.error("알람을 불러오지 못했습니다.");
    }
  }, [unreadOnly, kind]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, what: "read" | "dismiss") => {
    try {
      await (what === "read" ? readAlert(id) : dismissAlert(id));
      await load();
    } catch {
      toast.error("처리하지 못했습니다.");
    }
  };

  return (
    <main className="min-h-screen bg-md-surface px-6 py-10">
      <div className="mx-auto w-full max-w-[880px]">
        <header className="mb-6">
          <div className="flex items-center gap-2">
            <h1 className="text-[22px] font-bold text-md-primary">규제 변경 알람</h1>
            {total > 0 ? (
              <span className="rounded-pill bg-md-error px-2 py-0.5 text-[11px] font-semibold text-md-on-error">
                미읽음 {total}
              </span>
            ) : null}
          </div>
          <p className="mt-1.5 text-[13px] leading-relaxed text-md-on-surface-variant">
            관찰 중인 조문의 폐지 · 개정예정 · 시행일 변경을 모아 보여 줍니다.
            <br />
            <b>알람이 없다는 것이 변경이 없다는 뜻은 아닙니다</b> — 법령 DB를 조회할 수
            없던 구간에는 알람이 생성되지 않습니다.
          </p>
        </header>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="alerts-unread-filter"
            onClick={() => setUnreadOnly((v) => !v)}
            className={
              "rounded-pill border px-3 py-1 text-[12px] transition-colors " +
              (unreadOnly
                ? "border-md-primary bg-md-primary-container text-md-on-primary-container"
                : "border-md-outline-variant text-md-on-surface-variant hover:border-md-primary")
            }
          >
            미읽음만
          </button>
          {["", "repealed", "pending", "amended"].map((k) => (
            <button
              key={k || "all"}
              type="button"
              onClick={() => setKind(k)}
              className={
                "rounded-pill border px-3 py-1 text-[12px] transition-colors " +
                (kind === k
                  ? "border-md-primary bg-md-primary-container text-md-on-primary-container"
                  : "border-md-outline-variant text-md-on-surface-variant hover:border-md-primary")
              }
            >
              {k ? KIND_LABEL[k] : "전체"}
            </button>
          ))}
        </div>

        {rows === null ? (
          <p className="py-10 text-center text-[13px] text-md-on-surface-variant">
            불러오는 중…
          </p>
        ) : rows.length === 0 ? (
          <p
            data-testid="alerts-empty"
            className="rounded-[10px] border border-md-outline-variant bg-md-surface-container-lowest px-5 py-10 text-center text-[13px] leading-relaxed text-md-on-surface-variant"
          >
            표시할 알람이 없습니다.
            <br />
            모니터링 스레드에서 조문을 관찰 목록에 담으면 변경이 여기 쌓입니다.
          </p>
        ) : (
          <ul
            data-testid="alerts-list"
            className="divide-y divide-md-outline-variant overflow-hidden rounded-[10px] border border-md-outline-variant bg-md-surface-container-lowest"
          >
            {rows.map((a) => (
              <li
                key={a.id}
                data-alert={a.id}
                className={
                  "flex items-start gap-3 px-4 py-3 " + (a.unread ? "" : "opacity-65")
                }
              >
                <span
                  className={
                    "mt-[2px] shrink-0 rounded-[4px] px-1.5 py-0.5 text-[10.5px] font-medium " +
                    (KIND_TONE[a.kind] ?? KIND_TONE.amended)
                  }
                >
                  {KIND_LABEL[a.kind] ?? a.kind}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] leading-snug text-md-on-surface">
                    {a.summary}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-md-on-surface-variant">
                    <Link
                      href={`/new?threadId=${encodeURIComponent(a.thread_id)}`}
                      className="underline underline-offset-2 hover:text-md-primary"
                    >
                      {a.thread_title || "모니터링 스레드"}
                    </Link>
                    <span>· {a.detected_at}</span>
                    <code className="text-[10.5px]">{a.article_key}</code>
                  </span>
                </span>
                <span className="flex shrink-0 gap-1">
                  {a.unread ? (
                    <button
                      type="button"
                      onClick={() => void act(a.id, "read")}
                      className="rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary"
                    >
                      읽음
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => void act(a.id, "dismiss")}
                    className="rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant hover:border-md-error hover:text-md-error"
                  >
                    보관
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
