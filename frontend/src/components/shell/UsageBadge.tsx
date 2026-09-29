"use client";

/**
 * UsageBadge — Header 우측 토큰 사용량 progress.
 *
 * - 일/월 사용량 progress bar 두 개
 * - 80% 이상 warning, 95% 이상 error 색
 * - hover시 절대 수치 + 비용 tooltip
 * - admin은 "ADMIN" 라벨 표시 (한도 적용 X)
 */

import { useUsage } from "@/lib/store/useUsage";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

function fmt(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function pct(used: number, limit: number): number {
  if (!limit || limit <= 0) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}

function barColor(p: number): string {
  if (p >= 95) return "bg-md-error";
  if (p >= 80) return "bg-md-tertiary";
  return "bg-md-primary";
}

export function UsageBadge() {
  const { usage } = useUsage();
  if (!usage) return null;

  if (usage.is_admin) {
    return (
      <span
        title={`admin · ${usage.email}`}
        className="inline-flex h-7 items-center gap-1 rounded-pill bg-md-tertiary-fixed px-2.5 text-[11px] font-semibold text-md-on-tertiary-fixed-variant"
      >
        <span className="material-symbols-outlined text-[14px]" aria-hidden>
          shield_person
        </span>
        Admin
      </span>
    );
  }

  const dailyUsed = usage.usage.daily_total_tokens;
  const dailyLimit = usage.effective_daily_limit;
  const monthlyUsed = usage.usage.monthly_total_tokens;
  const monthlyLimit = usage.effective_monthly_limit;
  const dPct = pct(dailyUsed, dailyLimit);
  const mPct = pct(monthlyUsed, monthlyLimit);

  const tooltip = [
    `오늘  ${fmt(dailyUsed)} / ${fmt(dailyLimit)} 토큰 (${dPct}%)`,
    `이번 달  ${fmt(monthlyUsed)} / ${fmt(monthlyLimit)} 토큰 (${mPct}%)`,
    `누적 비용  $${usage.usage.monthly_cost_usd.toFixed(2)}`,
  ].join("\n");

  // 모바일(<sm): compact 한 줄 — 일 progress + % 만. desktop: 일/월 두 줄.
  const detail = (
    <div className="flex flex-col gap-2 text-[12px]">
      <p className="font-semibold text-md-on-surface">내 사용량</p>
      <div className="flex flex-col gap-1 text-md-on-surface-variant">
        <p>오늘: <b className="text-md-on-surface">{fmt(dailyUsed)}</b> / {fmt(dailyLimit)} 토큰 ({dPct}%)</p>
        <p>이번 달: <b className="text-md-on-surface">{fmt(monthlyUsed)}</b> / {fmt(monthlyLimit)} 토큰 ({mPct}%)</p>
        <p>이번 달 비용: <b className="text-md-on-surface">${usage.usage.monthly_cost_usd.toFixed(2)}</b></p>
      </div>
      <p className="text-[11px] text-md-on-surface-variant/80">
        일 한도는 매일 자정(한국시간), 월 한도는 매월 1일에 초기화됩니다.
      </p>
    </div>
  );

  return (
    <>
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            title={tooltip}
            aria-label="토큰 사용량 — 눌러서 상세"
            className="hidden items-center gap-2 rounded border border-md-outline-variant bg-md-surface-container-low px-2 py-1 text-left text-[11px] text-md-on-surface-variant transition-colors hover:bg-md-surface-container sm:flex"
          >
            <span className="material-symbols-outlined text-[14px]" aria-hidden>
              bolt
            </span>
            <div className="flex flex-col gap-0.5">
              <Bar label="일" pct={dPct} />
              <Bar label="월" pct={mPct} />
            </div>
          </button>
        </PopoverTrigger>
        <PopoverContent side="top" align="start" className="w-[260px] px-3 py-2.5">
          {detail}
        </PopoverContent>
      </Popover>
      <div
        title={tooltip}
        role="status"
        aria-label="토큰 사용량"
        className="flex items-center gap-1 rounded border border-md-outline-variant bg-md-surface-container-low px-2 py-1 text-[11px] text-md-on-surface-variant sm:hidden"
      >
        <span className="material-symbols-outlined text-[14px]" aria-hidden>
          bolt
        </span>
        <span className="tabular-nums">{dPct}%</span>
      </div>
    </>
  );
}

function Bar({ label, pct: p }: { label: string; pct: number }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-3 shrink-0 text-[10px] text-md-on-surface-variant">
        {label}
      </span>
      <span className="relative inline-block h-1 w-20 overflow-hidden rounded bg-md-outline-variant">
        <span
          className={`absolute inset-y-0 left-0 ${barColor(p)} rounded`}
          style={{ width: `${p}%` }}
          aria-hidden
        />
      </span>
      <span className="w-7 text-right text-[10px] tabular-nums text-md-on-surface-variant">
        {p}%
      </span>
    </div>
  );
}
