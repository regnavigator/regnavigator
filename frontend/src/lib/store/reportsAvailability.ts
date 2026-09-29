"use client";

/**
 * 보고서 가용성 단일 진실원 — `GET /load` 의 `reports.*`.
 *
 * ## 왜 store 로 뺐나 (2026-09-10)
 *
 * 종전엔 `useReportsAvailability` 훅 안에서만 폴링하고, 훅 밖(`triggerReport`)은
 * 모듈 전역 변수 `latest` 를 읽었다. 그 변수는 **훅이 마운트돼야만** 채워진다 —
 * 즉 가용성 판정이 "ChatInput 이 화면에 떠 있는가"에 딸려 있었다. 마운트 전이나
 * 훅을 쓰지 않는 진입점에서는 조용히 기본값(정상)으로 통과한다.
 *
 * 원래 문제(2026-09-09): 보고서 버튼은 비활성인데 답변 아래 next_steps 칩은
 * 그대로 `POST /reports` 를 쏴서 503 → 빨간 배너가 떴다. 게이팅이 컴포넌트와
 * 스토어 두 곳에 흩어져 있던 결과다. 그때는 스냅샷으로 급히 막았고, 이제 양쪽이
 * **같은 store** 를 본다.
 *
 * - 구독자가 있는 동안만 폴링(탭이 보일 때만) — 유휴 탭이 서버를 두드리지 않게.
 * - `ensureFresh()`: 트리거 직전 호출. 값이 낡았거나 한 번도 못 받았으면 즉시
 *   1회 조회. 마운트 여부와 무관하게 정확한 판정을 보장한다.
 * - 조회 실패는 **정상으로 간주**한다 — 네트워크 오탐으로 기능을 막지 않는다.
 */

import { apiFetch } from "@/lib/api/client";

export type ReportsAvailability = {
  /** 운영자 토글(기능 단위 일시 중단). POST /reports 는 503. */
  paused: boolean;
  message: string | null;
  /** writer(DGX vLLM) 프로브. null = 로컬 writer 미설정(폴백 모델이라 항상 가능). */
  writerUp: boolean | null;
};

type LoadStatus = {
  reports?: {
    active?: number;
    paused?: boolean;
    message?: string | null;
    writer_up?: boolean | null;
  };
};

const OK: ReportsAvailability = { paused: false, message: null, writerUp: null };
const POLL_MS = 15_000;
/** 이 시간이 지난 값은 트리거 판정에 쓰기엔 낡았다고 본다. */
const STALE_MS = 20_000;

let state: ReportsAvailability = OK;
let fetchedAt = 0;
let inflight: Promise<void> | null = null;
let timer: number | null = null;
const listeners = new Set<() => void>();

async function poll(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await apiFetch<LoadStatus>("/load");
      const r = res.reports ?? {};
      const next: ReportsAvailability = {
        paused: !!r.paused,
        message: r.message ?? null,
        writerUp: r.writer_up === undefined ? null : r.writer_up,
      };
      if (
        next.paused !== state.paused ||
        next.message !== state.message ||
        next.writerUp !== state.writerUp
      ) {
        state = next;
        listeners.forEach((l) => l());
      }
      fetchedAt = Date.now();
    } catch {
      // 조회 실패로 기능을 막지 않는다. 다만 fetchedAt 은 갱신하지 않아
      // 다음 ensureFresh 가 다시 시도한다.
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

function startTimer() {
  if (timer !== null || typeof window === "undefined") return;
  timer = window.setInterval(() => {
    if (document.visibilityState === "visible") void poll();
  }, POLL_MS);
}

function stopTimer() {
  if (timer === null || typeof window === "undefined") return;
  window.clearInterval(timer);
  timer = null;
}

/** useSyncExternalStore 용. 구독자가 생기면 폴링 시작, 없어지면 중단. */
export function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  if (listeners.size === 1) {
    startTimer();
    void poll();
  }
  return () => {
    listeners.delete(cb);
    if (listeners.size === 0) stopTimer();
  };
}

export function getSnapshot(): ReportsAvailability {
  return state;
}

/** SSR 용 — 서버에서는 항상 "정상"으로 렌더한다(점검 배너는 클라이언트에서). */
export function getServerSnapshot(): ReportsAvailability {
  return OK;
}

/**
 * 트리거 직전 판정용 — 값이 낡았으면 즉시 1회 조회하고 최신값을 돌려준다.
 * 훅 마운트 여부와 무관하게 정확하다.
 */
export async function ensureFresh(): Promise<ReportsAvailability> {
  if (Date.now() - fetchedAt > STALE_MS) {
    await poll();
  }
  return state;
}
