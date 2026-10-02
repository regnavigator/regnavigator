"use client";

/**
 * MonitorWorkDialog — 모니터링 스레드의 작업 창 (2026-10-02).
 *
 * 세 가지를 한 창에서 한다: **관찰 목록 관리 · 짧은 보고서 생성 · 선택 발송**.
 * 설계: `backend/docs/spec/monitor-threads-design.md`.
 *
 * 보고서와 발송을 한 창에 둔 이유: 보고서를 만든 **직후**가 보낼 시점이다.
 * 화면을 옮기게 하면 만들어 놓고 안 보내는 일이 생긴다.
 */

import { useCallback, useState } from "react";
import { toast } from "sonner";

import { RecipientPicker } from "@/components/monitor/RecipientPicker";
import { WatchPanel } from "@/components/monitor/WatchPanel";
import { MONITOR_CHANGED_EVENT } from "@/components/thread/ThreadList";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  buildThreadReport,
  sendThreadReport,
} from "@/lib/client/monitorThreads";

export function MonitorWorkDialog({
  open,
  threadId,
  onClose,
}: {
  open: boolean;
  threadId: string;
  onClose: () => void;
}) {
  const [report, setReport] = useState<{ id: string; title: string; alerts: number } | null>(
    null,
  );
  const [recipients, setRecipients] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const notifySidebar = useCallback(() => {
    try {
      window.dispatchEvent(new CustomEvent(MONITOR_CHANGED_EVENT));
    } catch {
      /* 무시 */
    }
  }, []);

  const makeReport = useCallback(async () => {
    setBusy(true);
    const t = toast.loading("보고서를 만드는 중…");
    try {
      const r = await buildThreadReport(threadId);
      setReport({ id: r.report_id, title: r.title, alerts: r.alerts });
      toast.success(
        r.alerts ? `변경 ${r.alerts}건으로 보고서를 만들었습니다.`
                 : "변경 0건 보고서를 만들었습니다.",
        { id: t },
      );
    } catch {
      toast.error("보고서를 만들지 못했습니다.", { id: t });
    } finally {
      setBusy(false);
    }
  }, [threadId]);

  const send = useCallback(async () => {
    if (!report || !recipients.length) return;
    setBusy(true);
    const t = toast.loading("보내는 중…");
    try {
      const r = await sendThreadReport(threadId, report.id, recipients);
      if (r.ok) {
        toast.success(`${r.recipients.length}명에게 보냈습니다.`, { id: t });
        setRecipients([]);
      } else {
        // 조용히 성공하지 않는다 — 안 갔는데 갔다고 하면 안 된다.
        toast.error("보내지 못했습니다", {
          id: t,
          description: "메일 서버(SMTP)가 설정되어 있지 않습니다.",
          duration: 9000,
        });
      }
    } catch {
      toast.error("보내지 못했습니다.", { id: t });
    } finally {
      setBusy(false);
    }
  }, [report, recipients, threadId]);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        data-testid="monitor-work"
        className="h-[80vh] max-w-[860px] gap-0 overflow-hidden border border-md-outline-variant bg-md-surface p-0 text-md-on-surface"
      >
        <DialogTitle className="sr-only">규제 모니터링 작업</DialogTitle>
        <div className="grid h-full grid-cols-1 md:grid-cols-[1fr_320px]">
          <div className="min-h-0 overflow-hidden border-r border-md-outline-variant">
            <WatchPanel threadId={threadId} onChanged={notifySidebar} />
          </div>

          <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto p-3">
            <section>
              <h4 className="mb-1.5 text-[12px] font-bold">변경 보고서</h4>
              <p className="mb-2 text-[11px] leading-snug text-md-on-surface-variant">
                감지된 변경만 모아 짧게 만듭니다. 정기 발송과 별개로, 필요할 때
                뽑습니다.
              </p>
              <button
                type="button"
                data-testid="monitor-make-report"
                disabled={busy}
                onClick={() => void makeReport()}
                className="w-full rounded-pill bg-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40"
              >
                보고서 만들기
              </button>
              {report ? (
                <p className="mt-1.5 text-[11.5px] text-md-on-surface-variant">
                  <b>{report.title}</b> · 변경 {report.alerts}건
                </p>
              ) : null}
            </section>

            {report ? (
              <section>
                <h4 className="mb-1.5 text-[12px] font-bold">보내기</h4>
                <RecipientPicker selected={recipients} onChange={setRecipients} />
                <button
                  type="button"
                  data-testid="monitor-send"
                  disabled={busy || recipients.length === 0}
                  onClick={() => void send()}
                  className="mt-2 w-full rounded-pill border border-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-primary disabled:opacity-40"
                >
                  {recipients.length}명에게 보내기
                </button>
              </section>
            ) : null}
          </aside>
        </div>
      </DialogContent>
    </Dialog>
  );
}
