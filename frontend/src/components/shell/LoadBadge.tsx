"use client";

/**
 * LoadBadge — 서버 혼잡 표시 (`GET /load` 폴링, 인증 X).
 *
 * 검색 백프레셔(동시 2)·보고서 큐(동시 1)가 차 있으면 `status:"busy"` — 사용자가
 * "왜 느리지"를 이해하고 기다릴 수 있게 배지로 알린다(frontend_legal_handoff.md §4).
 *
 * - ~5초 폴링. 인터벌은 유지하되 탭이 백그라운드면 poll 스킵(요청 없음),
 *   visible 복귀 시 즉시 1회 poll(visibilitychange).
 * - `busy`일 때만 렌더 — ok/조회실패는 아무것도 안 보임(오탐으로 불안 조성 금지).
 */

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api/client";

type LoadStatus = {
  status: "ok" | "busy";
  search?: { active: number; waiting: number; limit: number };
  reports?: { active: number };
};

const POLL_MS = 5_000;

export function LoadBadge() {
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let timer: number | null = null;
    let cancelled = false;

    async function poll() {
      try {
        const res = await apiFetch<LoadStatus>("/load");
        if (!cancelled) setBusy(res.status === "busy");
      } catch {
        if (!cancelled) setBusy(false); // 조회 실패 = 표시 안 함
      }
    }

    function schedule() {
      if (timer !== null) return;
      void poll();
      timer = window.setInterval(() => {
        if (document.visibilityState === "visible") void poll();
      }, POLL_MS);
    }

    function onVisibility() {
      if (document.visibilityState === "visible") void poll();
    }

    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  if (!busy) return null;

  return (
    <div
      role="status"
      className="mx-auto mb-2 flex w-fit items-center gap-1.5 rounded-full border border-md-tertiary bg-md-tertiary-fixed px-3 py-1 text-[12px] font-medium text-md-on-tertiary-fixed-variant"
    >
      <span className="material-symbols-outlined text-[14px]" aria-hidden>
        hourglass_top
      </span>
      지금 이용자가 많아 응답이 느릴 수 있어요
    </div>
  );
}
