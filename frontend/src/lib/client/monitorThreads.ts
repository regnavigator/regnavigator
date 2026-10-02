/**
 * monitorThreads — 모니터링 스레드 API (2026-10-02).
 *
 * 설계: `backend/docs/spec/monitor-threads-design.md`.
 * 관찰 단위가 북마크 폴더에서 **스레드**로 바뀌었다. 대상 하나 = 스레드 하나.
 */

import { apiFetch } from "@/lib/api/client";
import type { Citation } from "@/lib/store/types";

export type MonitorThread = {
  id: string;
  title: string | null;
  updated_at?: string;
  watch_count: number;
  unread_alerts: number;
};

export type WatchItem = {
  id: string;
  thread_id: string;
  article_key: string;
  title: string;
  citation: Citation;
  added_by: "ai" | "user" | "file";
  reason: string | null;
  added_at: string;
};

export type Suggestion = {
  article_key: string;
  citation: Citation;
  title: string | null;
  doc_category: string | null;
  /** 이미 관찰 중 — '추가'가 아니라 '있음'으로 보여야 한다 */
  already: boolean;
};

export type MonitorAlert = {
  id: string;
  thread_id: string;
  thread_title: string | null;
  article_key: string;
  kind: "repealed" | "pending" | "amended" | "effective_date";
  summary: string;
  detected_at: string;
  unread: boolean;
  payload: Record<string, unknown>;
};

export function createMonitorThread(title?: string) {
  return apiFetch<{ thread_id: string; kind: string; title: string | null }>(
    "/monitor/threads",
    { method: "POST", body: JSON.stringify({ title }) },
  );
}

export function listMonitorThreads() {
  return apiFetch<{ threads: MonitorThread[] }>("/monitor/threads");
}

export function listWatch(threadId: string) {
  return apiFetch<{ thread_id: string; items: WatchItem[] }>(
    `/monitor/threads/${encodeURIComponent(threadId)}/watch`,
  );
}

/** 관찰 목록에 넣는다 — **자동이 아니라 사용자의 승인**이다. */
export function addWatch(
  threadId: string,
  citations: Citation[],
  addedBy: "ai" | "user" | "file" = "user",
) {
  return apiFetch<{ ok: boolean; added: string[]; skipped: string[]; count: number }>(
    `/monitor/threads/${encodeURIComponent(threadId)}/watch`,
    { method: "POST", body: JSON.stringify({ citations, added_by: addedBy }) },
  );
}

export function removeWatch(threadId: string, articleKey: string) {
  return apiFetch<{ ok: boolean; count: number }>(
    `/monitor/threads/${encodeURIComponent(threadId)}/watch/${encodeURIComponent(articleKey)}`,
    { method: "DELETE" },
  );
}

export function suggestWatch(threadId: string) {
  return apiFetch<{ suggestions: Suggestion[]; watching: number }>(
    `/monitor/threads/${encodeURIComponent(threadId)}/watch/suggest`,
    { method: "POST" },
  );
}

export function listAlerts(opts?: { unread?: boolean; kind?: string }) {
  const p = new URLSearchParams();
  if (opts?.unread) p.set("unread", "1");
  if (opts?.kind) p.set("kind", opts.kind);
  const q = p.toString();
  return apiFetch<{ alerts: MonitorAlert[]; unread_total: number }>(
    `/monitor/alerts${q ? `?${q}` : ""}`,
  );
}

export function readAlert(id: string) {
  return apiFetch<{ ok: boolean }>(
    `/monitor/alerts/${encodeURIComponent(id)}/read`, { method: "POST" });
}

export function dismissAlert(id: string) {
  return apiFetch<{ ok: boolean }>(
    `/monitor/alerts/${encodeURIComponent(id)}/dismiss`, { method: "POST" });
}

export function detectNow(threadId: string) {
  return apiFetch<{ checked: number; changed: number; created: number; complete: boolean }>(
    `/monitor/threads/${encodeURIComponent(threadId)}/detect`, { method: "POST" });
}

export function buildThreadReport(threadId: string, since?: string) {
  return apiFetch<{ report_id: string; title: string; alerts: number }>(
    `/monitor/threads/${encodeURIComponent(threadId)}/report`,
    { method: "POST", body: JSON.stringify({ since }) },
  );
}

export function sendThreadReport(
  threadId: string, reportId: string, recipients: string[],
) {
  return apiFetch<{ ok: boolean; recipients: string[] }>(
    `/monitor/threads/${encodeURIComponent(threadId)}/send`,
    { method: "POST", body: JSON.stringify({ report_id: reportId, recipients }) },
  );
}

// ── 주소록 ──────────────────────────────────────────────────────────────────

export type Contact = {
  id: string;
  email: string;
  name: string | null;
  org: string | null;
  display: string;
  last_used_at: string | null;
};

export function searchContacts(q = "") {
  return apiFetch<{ contacts: Contact[] }>(
    `/contacts${q ? `?q=${encodeURIComponent(q)}` : ""}`);
}

export function createContact(c: { email: string; name?: string; org?: string }) {
  return apiFetch<{ ok: boolean; id: string }>("/contacts", {
    method: "POST", body: JSON.stringify(c),
  });
}

/**
 * 스레드 종류 전환 — 대화 ↔ 모니터링 대상 (2026-10-02).
 *
 * 되돌려도 관찰 목록은 남는다. 전환은 분류 변경이지 삭제가 아니다.
 */
export function setThreadKind(threadId: string, kind: "chat" | "monitor") {
  return apiFetch<{ ok: boolean; thread_id: string; kind: string }>(
    `/chat/${encodeURIComponent(threadId)}/kind`,
    { method: "PATCH", body: JSON.stringify({ kind }) },
  );
}

/**
 * 법령 DB 연결 여부 (2026-10-02).
 *
 * 변경 감지는 openlaw PG 가 있어야 **실제로** 동작한다. 없으면 알람이 아예
 * 생성되지 않는데, 그 사실을 토스트로 한 번만 알리면 "버튼이 고장났다"로 보인다.
 * `/readyz` 가 이미 그 상태를 준다 — 새 API 가 필요 없다(공개 엔드포인트라
 * DSN 은 실리지 않는다, 운영 불변식 §8).
 */
export async function lawDbReady(): Promise<boolean | null> {
  // ⚠️ `/readyz` 는 degraded 일 때 **503** 을 돌려준다. 그래서 `apiFetch` 로 부르면
  // 정작 "PG 가 죽었다"는 바로 그 경우가 예외로 떨어져 경고를 못 띄운다
  // (2026-10-02 실측). 본문을 봐야 하므로 상태코드와 무관하게 직접 읽는다.
  try {
    const { getEffectiveSettings } = await import("@/lib/store/settings");
    const base = (getEffectiveSettings().deployment_url ?? "").replace(/\/$/, "");
    if (!base) return null;
    const res = await fetch(`${base}/readyz`);
    const d = (await res.json()) as {
      checks?: Record<string, { status?: string }>;
    };
    const st = d?.checks?.postgres?.status;
    return st ? st === "ok" : null;
  } catch {
    return null;   // 확인 못 함 — 경고를 띄우지 않는다(거짓 경고가 더 나쁘다)
  }
}

/**
 * 관찰 추천 — 담을 만한 후보와 **왜 담아야 하는지** (2026-10-02).
 *
 * 자동으로 담지 않는다. 추천과 사유까지만이고 선택은 사람이 한다.
 * `skipped: "confidential"` 이면 기밀 대화라 추천을 건너뛴 것이다.
 */
export function recommendWatch(threadId: string) {
  return apiFetch<{ picks: Record<string, string>; skipped?: string }>(
    `/monitor/threads/${encodeURIComponent(threadId)}/watch/recommend`,
    { method: "POST" },
  );
}
