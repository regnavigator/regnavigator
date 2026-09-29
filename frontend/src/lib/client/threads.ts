/**
 * Thread 어댑터 — ADR-0001 Phase 4: langgraph SDK → 자체 `/chat/*` REST.
 *
 * 계약: medi-back `docs/contracts/frontend_chat_v2.md` §3. raw 응답을 UI 코드에 노출하지
 * 않는 원칙은 유지 — 본 모듈만 응답 shape 을 보고 snake_case `Thread` 로 반환.
 */

import { apiFetch } from "@/lib/api/client";
import type { ChatThreadRow } from "@/lib/client/chatApi";
import { isDummyMode } from "@/lib/store/settings";
import { randomUUID } from "@/lib/utils";

/** front-derived Thread (back §6.1 그대로) */
export type Thread = {
  id: string;
  title: string;
  created_at: number; // ms
  updated_at: number; // ms
  has_interrupt: boolean;
  pinned?: boolean;
  /** 본문 검색 결과에만 존재 — 검색어 주변 발췌. */
  match_snippet?: string;
};

const FALLBACK_TITLE = "새 대화";

function toMs(s: string | undefined | null): number {
  if (!s) return 0;
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : 0;
}

function adaptRow(row: ChatThreadRow): Thread {
  const title = (row.title ?? "").trim();
  return {
    id: row.thread_id,
    title: title.length > 0 ? title : FALLBACK_TITLE,
    created_at: toMs(row.created_at),
    updated_at: toMs(row.updated_at),
    // 신계약의 clarify 는 턴 종료형(영속 인터럽트 상태 없음) — 항상 false.
    has_interrupt: false,
    pinned: !!row.pinned,
    ...(row.match_snippet ? { match_snippet: row.match_snippet } : {}),
  };
}

/** 대화 *본문* 검색 — 제목만이던 검색을 메시지 내용까지 확장. q 2자 미만 → 빈 결과. */
export async function searchThreadsByContent(
  q: string,
  opts: { signal?: AbortSignal } = {},
): Promise<Thread[]> {
  if (isDummyMode()) return [];
  const query = q.trim();
  if (query.length < 2) return [];
  try {
    const res = await apiFetch<{ threads: ChatThreadRow[] }>(
      `/chat/search?q=${encodeURIComponent(query)}`,
      { signal: opts.signal },
    );
    return res.threads.map(adaptRow);
  } catch (err) {
    console.debug("[searchThreadsByContent] failed", err);
    return [];
  }
}

/** thread 고정/해제 — 사이드바 상단 고정. */
export async function setThreadPinned(id: string, pinned: boolean): Promise<void> {
  const { apiFetch } = await import("@/lib/api/client");
  await apiFetch(`/chat/${encodeURIComponent(id)}/pin`, {
    method: "POST",
    body: JSON.stringify({ pinned }),
  });
}

/* ─────────────────── dummy 분기 헬퍼 ─────────────────── */

type DummyRaw = {
  thread_id: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
  status: string;
};

function adaptDummy(raw: DummyRaw): Thread {
  const titleRaw =
    typeof raw.metadata.title === "string" ? raw.metadata.title.trim() : "";
  return {
    id: raw.thread_id,
    title: titleRaw.length > 0 ? titleRaw : FALLBACK_TITLE,
    created_at: toMs(raw.created_at),
    updated_at: toMs(raw.updated_at),
    has_interrupt: raw.status === "interrupted",
  };
}

async function dummyThreads() {
  const { getDummyBackend } = await import("@/lib/client/dummy");
  return getDummyBackend().threads;
}

/* ─────────────────── public API ─────────────────── */

export type SearchOptions = {
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
};

export async function searchThreads(opts: SearchOptions = {}): Promise<Thread[]> {
  if (isDummyMode()) {
    const t = await dummyThreads();
    const list = await t.search({ limit: opts.limit, offset: opts.offset });
    return (list as DummyRaw[]).map(adaptDummy);
  }
  try {
    const res = await apiFetch<{ threads: ChatThreadRow[] }>(
      `/chat/threads?limit=${opts.limit ?? 50}`,
      { signal: opts.signal },
    );
    return res.threads.map(adaptRow);
  } catch (err) {
    console.debug("[searchThreads] failed", err);
    return [];
  }
}

/**
 * 단일 thread 조회 — ChatColumn 상단 제목 표시용. 실패 시 null.
 * 신경로는 단건 메타 endpoint 가 없어 목록에서 lookup (limit 200).
 */
export async function getThread(id: string): Promise<Thread | null> {
  const list = await searchThreads({ limit: 200 });
  return list.find((t) => t.id === id) ?? null;
}

/**
 * thread 생성 — 신경로는 서버 사전 생성이 없다(첫 `POST /chat` 이 생성).
 * 로컬에서 id 만 발급해 반환 — 첫 메시지 전송 시 서버에 생긴다.
 */
export async function createThread(): Promise<Thread> {
  if (isDummyMode()) {
    const t = await dummyThreads();
    return adaptDummy((await t.create()) as DummyRaw);
  }
  const now = Date.now();
  return {
    id: `t_${randomUUID().replace(/-/g, "")}`,
    title: FALLBACK_TITLE,
    created_at: now,
    updated_at: now,
    has_interrupt: false,
  };
}

export async function renameThread(id: string, title: string): Promise<void> {
  if (isDummyMode()) {
    const t = await dummyThreads();
    await t.update(id, { metadata: { title } });
  } else {
    await apiFetch(`/chat/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
  }
  notifyThreadListChanged();
}

export async function deleteThread(id: string): Promise<void> {
  if (isDummyMode()) {
    const t = await dummyThreads();
    await t.delete(id);
  } else {
    await apiFetch(`/chat/${encodeURIComponent(id)}`, { method: "DELETE" });
  }
  notifyThreadListChanged();
}

/**
 * R7 — backend 자동 제목 생성 trigger. `POST /chat/{tid}/auto-title`
 * (신경로 — loopback 없이 threads_repo.title 직접, 응답 shape 동일).
 * 첫 turn fast 응답 직후 1회 호출 (best-effort — 실패 시 제목은 빈 채로).
 */
export async function autoTitleThread(threadId: string): Promise<void> {
  if (isDummyMode()) return; // 더미는 runDummyStream 이 제목 자동 추출
  try {
    await apiFetch(`/chat/${encodeURIComponent(threadId)}/auto-title`, {
      method: "POST",
      body: "{}",
    });
    notifyThreadListChanged();
  } catch (err) {
    console.warn("[autoTitleThread] failed", err);
  }
}

/**
 * 사용자 첫 질의 텍스트에서 thread 제목 도출.
 * - trim + 공백 정규화, 최대 40자, 단어 중간 절단 회피, 빈 입력 → FALLBACK_TITLE
 */
const TITLE_MAX = 40;

export function deriveTitleFromQuery(text: string): string {
  const cleaned = text.trim().replace(/\s+/g, " ");
  if (!cleaned) return FALLBACK_TITLE;
  if (cleaned.length <= TITLE_MAX) return cleaned;
  const cut = cleaned.slice(0, TITLE_MAX);
  const lastSpace = cut.lastIndexOf(" ");
  const base = lastSpace > TITLE_MAX / 2 ? cut.slice(0, lastSpace) : cut;
  return base + "…";
}

/**
 * 사이드바 ThreadList가 다시 fetch하도록 신호 — settings 변경과 같은 패턴.
 */
export const THREAD_LIST_CHANGED_EVENT = "medi-front-thread-list-changed";

export function notifyThreadListChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(THREAD_LIST_CHANGED_EVENT));
}
