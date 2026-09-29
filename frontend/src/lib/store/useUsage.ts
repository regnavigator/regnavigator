"use client";

/**
 * useUsage — /me/usage 폴링.
 *
 * - 30초 주기 (탭 inactive 시 일시 중단)
 * - jwt 미설정·미구성 dev에서는 호출 안 함
 * - 호출 실패는 silent (사용자 노출 X — Header 뱃지가 그냥 안 뜸)
 */

import { useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { getUsage, type Usage } from "@/lib/client/quota";
import { isConfigured } from "@/lib/store/settings";

const POLL_INTERVAL_MS = 30_000;

/** 토스트 1회 발화 보장 — sessionStorage 기준. 탭 닫혔다 다시 켜면 리셋. */
function maybeWarnQuota(usage: Usage): void {
  if (typeof window === "undefined") return;
  const dailyPct =
    usage.effective_daily_limit > 0
      ? usage.usage.daily_total_tokens / usage.effective_daily_limit
      : 0;
  const monthlyPct =
    usage.effective_monthly_limit > 0
      ? usage.usage.monthly_total_tokens / usage.effective_monthly_limit
      : 0;
  // 100%(초과)를 *맨 앞*에 둬서 최우선 노출 — 사용자가 질문(전송) 시도해
  // 429 받기 *전에* 폴링(30s/visible)만으로 바로 알린다.
  const checks: Array<{ key: string; pct: number; period: string; threshold: number }> = [
    { key: "daily-100", pct: dailyPct, period: "오늘", threshold: 1 },
    { key: "monthly-100", pct: monthlyPct, period: "이번 달", threshold: 1 },
    { key: "daily-95", pct: dailyPct, period: "오늘", threshold: 0.95 },
    { key: "daily-80", pct: dailyPct, period: "오늘", threshold: 0.8 },
    { key: "monthly-95", pct: monthlyPct, period: "이번 달", threshold: 0.95 },
    { key: "monthly-80", pct: monthlyPct, period: "이번 달", threshold: 0.8 },
  ];
  for (const c of checks) {
    if (c.pct < c.threshold) continue;
    const sessionKey = `quota-warned-${c.key}`;
    if (window.sessionStorage.getItem(sessionKey)) continue;
    window.sessionStorage.setItem(sessionKey, "1");
    void import("sonner").then(({ toast }) => {
      const pctNum = Math.round(c.pct * 100);
      if (c.threshold >= 1) {
        toast.error(`${c.period} 사용량 한도 초과 (${pctNum}%)`, {
          description:
            "추가 요청이 차단됩니다. 한도가 초기화되거나 관리자 한도 상향이 필요합니다.",
          duration: 10000,
        });
      } else if (c.threshold >= 0.95) {
        toast.error(`${c.period} 사용량 ${pctNum}%`, {
          description: "한도 초과 임박 — 곧 차단될 수 있습니다.",
          duration: 6000,
        });
      } else {
        toast(`${c.period} 사용량 ${pctNum}%`, {
          description: "한도의 80% 도달.",
        });
      }
    });
    break; // 한 번에 하나만 노출 (초과가 최우선)
  }
}

export function useUsage(): {
  usage: Usage | null;
  refetch: () => void;
} {
  const { status } = useSession();
  const [usage, setUsage] = useState<Usage | null>(null);
  const acRef = useRef<AbortController | null>(null);

  const refetch = () => {
    if (status !== "authenticated" || !isConfigured()) return;
    acRef.current?.abort();
    const ac = new AbortController();
    acRef.current = ac;
    void getUsage(ac.signal)
      .then((u) => {
        setUsage(u);
        maybeWarnQuota(u);
      })
      .catch((e) => {
        if ((e as { name?: string }).name === "AbortError") return;
        console.debug("[useUsage] fetch failed", e);
      });
  };

  useEffect(() => {
    if (status !== "authenticated") return;
    refetch();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") refetch();
    }, POLL_INTERVAL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") refetch();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
      acRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  return { usage, refetch };
}
