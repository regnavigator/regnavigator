/**
 * 규제 모니터링 클라이언트 — 배송 설정 CRUD · 미리보기 · 수동 발송.
 * 백엔드: /monitor/targets (user 스코프). 계약: backend routes/monitor.py.
 */

import { apiFetch } from "@/lib/api/client";

export type Cadence = "weekly" | "monthly";

export type MonitorTarget = {
  id: string;
  user_id: string;
  folder: string;
  label: string | null;
  display_name: string;
  recipients: string[];
  cadence: Cadence;
  send_weekday: number;
  send_hour: number;
  enabled: boolean;
  last_sent_at: string | null;
  created_at: string;
  next_run_at: string;
  watched: number;
};

export type MonitorTargetInput = {
  folder: string;
  recipients: string;
  label?: string;
  cadence?: Cadence;
  send_weekday?: number;
  send_hour?: number;
  enabled?: boolean;
};

export type AmendmentKind = "repealed" | "pending" | "amended";

export type MonitorChange = {
  bookmark_id: string;
  citation_id: string;
  title: string | null;
  saved_date?: string | null;
  current_date?: string | null;
  folder?: string | null;
  kind: AmendmentKind;
};

export type MonitorPreview = {
  subject: string;
  html: string;
  text: string;
  changes: MonitorChange[];
  counts: Record<AmendmentKind, number>;
  watched: number;
  degraded: boolean;
  generated_at: string;
};

export type MonitorSendResult = {
  target_id: string;
  subject?: string;
  changes: number;
  degraded?: boolean;
  skipped?: "no_change" | "degraded";
  sent: string[];
  failed: string[];
  smtp_configured: boolean;
};

export const KIND_LABEL: Record<AmendmentKind, string> = {
  repealed: "폐지",
  pending: "개정예정",
  amended: "시행일 변경",
};

export const WEEKDAY_LABEL = ["월", "화", "수", "목", "금", "토", "일"];

export async function listMonitorTargets(): Promise<{
  targets: MonitorTarget[];
  folders: string[];
}> {
  return apiFetch("/monitor/targets");
}

export async function createMonitorTarget(
  input: MonitorTargetInput,
): Promise<MonitorTarget> {
  return apiFetch("/monitor/targets", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateMonitorTarget(
  id: string,
  patch: Partial<MonitorTargetInput>,
): Promise<MonitorTarget> {
  return apiFetch(`/monitor/targets/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteMonitorTarget(id: string): Promise<void> {
  await apiFetch(`/monitor/targets/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/** 발송하지 않고 지금 시점 리포트를 받아본다. */
export async function previewMonitorTarget(id: string): Promise<MonitorPreview> {
  return apiFetch(`/monitor/targets/${encodeURIComponent(id)}/preview`);
}

/** 수동 발송. force=true 면 변경 0건이어도 보낸다(시연용). */
export async function sendMonitorTarget(
  id: string,
  opts?: { to?: string; force?: boolean },
): Promise<MonitorSendResult> {
  return apiFetch(`/monitor/targets/${encodeURIComponent(id)}/send`, {
    method: "POST",
    body: JSON.stringify({ to: opts?.to, force: opts?.force ?? false }),
  });
}
