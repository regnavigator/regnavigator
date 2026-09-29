"use client";

/**
 * MaintenanceGate — 백엔드 **런타임** 점검 모드를 반영하는 클라이언트 게이트.
 *
 * 백엔드(admin 토글 또는 4시 크론 `scripts/maintenance.py`)가 점검을 켜면
 * `GET /load` 의 `maintenance.active` 가 true 가 되고 비관리자 API 는 503 을
 * 받는다. 이 컴포넌트는 /load 를 폴링해:
 *   - 비관리자 → 앱을 **점검 화면**으로 덮어 차단(백엔드 503 과 일치).
 *   - 관리자   → 상단 배너로 알리되 정상 사용(점검 해제·확인 가능).
 *
 * env `MAINTENANCE_MODE`(middleware 리다이렉트)와는 별개 — 그건 재배포가 필요한
 * 하드 스위치, 이건 재배포 없이 켜고 끄는 운영 토글이다. 둘은 공존한다.
 */

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { apiFetch } from "@/lib/api/client";
import { ThemeLogo } from "@/components/shell/ThemeLogo";
import { useUsage } from "@/lib/store/useUsage";

type MaintenanceInfo = { active: boolean; message?: string; since?: string | null };
type LoadStatus = { maintenance?: MaintenanceInfo };

const POLL_MS = 15_000;
/** 백엔드 무응답일 때는 빠르게 재시도 — 배포 재기동은 보통 10~30초. */
const POLL_MS_DEGRADED = 3_000;
/** 이 횟수만큼 연속 실패해야 점검 화면 — 사용자 쪽 일시적 네트워크 끊김 오탐 방지. */
const FAIL_THRESHOLD = 2;

export function MaintenanceGate({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession();
  // 관리자 판정은 세션(프런트 ADMIN_EMAILS) **또는** 백엔드(/me/usage is_admin).
  // 운영 compose 가 프런트에 ADMIN_EMAILS 를 안 넘겨 session.isAdmin 이 항상 false 였고,
  // 점검 중 관리자까지 점검 화면에 갇혀 해제하러 갈 수 없었다(2026-09-07 신고).
  // 백엔드는 점검 중 비관리자 /me/usage 를 503 으로 막으므로 usage 가 오면 그 자체가 관리자 증거.
  const { usage } = useUsage();
  const isAdmin =
    !!(session?.user as { isAdmin?: boolean } | undefined)?.isAdmin || !!usage?.is_admin;
  const [info, setInfo] = useState<MaintenanceInfo | null>(null);
  // 백엔드 무응답(배포 재기동·장애) — 연속 실패 횟수. 종전엔 실패를 그냥 삼켜
  // "점검 아님"으로 처리했고, 그 결과 **배포 중 사용자는 점검 화면 대신 모든
  // 동작이 에러 나는 앱**을 봤다(2026-08-03).
  const [failures, setFailures] = useState(0);

  useEffect(() => {
    let timer: number | null = null;
    let cancelled = false;

    async function poll() {
      try {
        const res = await apiFetch<LoadStatus>("/load");
        if (!cancelled) {
          setInfo(res.maintenance ?? { active: false });
          setFailures(0);
        }
      } catch {
        if (!cancelled) setFailures((n) => n + 1);
      }
    }

    void poll();
    // 무응답 구간에선 짧은 주기로 — 복구되면 화면이 저절로 걷힌다.
    const interval = failures >= FAIL_THRESHOLD ? POLL_MS_DEGRADED : POLL_MS;
    timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void poll();
    }, interval);
    const onVis = () => {
      if (document.visibilityState === "visible") void poll();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [failures >= FAIL_THRESHOLD]);   // 주기 전환 시에만 재구독

  const unreachable = failures >= FAIL_THRESHOLD;
  const active = !!info?.active || unreachable;

  // 관리자 — 배너로 알리되 정상 사용(해제하러 /admin/settings 로 이동 가능)
  if (active && isAdmin) {
    return (
      <>
        <div
          role="status"
          className="flex items-center justify-center gap-2 bg-md-tertiary-fixed px-4 py-1.5 text-center text-[12px] font-medium text-md-on-tertiary-fixed-variant"
        >
          <span className="material-symbols-outlined text-[14px]" aria-hidden>
            engineering
          </span>
          {unreachable && !info?.active
            ? "백엔드 무응답 — 재기동 중이거나 장애입니다. 복구되면 자동 해제됩니다."
            : "점검 모드 ON — 일반 사용자 차단 중(관리자만 접근). 해제는 설정 > 서버 점검."}
        </div>
        {children}
      </>
    );
  }

  // 비관리자 — 점검 화면으로 앱 차단. 무응답이면 자동 재연결 안내로.
  if (active && !isAdmin) {
    return (
      <MaintenanceScreen
        message={
          unreachable && !info?.active
            ? "서비스를 업데이트하고 있습니다. 완료되면 자동으로 다시 연결됩니다."
            : info?.message
        }
      />
    );
  }

  return <>{children}</>;
}

function MaintenanceScreen({ message }: { message?: string }) {
  const text =
    (message && message.trim()) ||
    "더 나은 서비스를 위해 시스템 점검을 진행하고 있습니다. 잠시 후 다시 이용해주세요.";

  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-md-surface px-6 text-center text-md-on-surface">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.4]"
        style={{
          backgroundImage:
            "radial-gradient(circle, var(--md-outline-variant) 1px, transparent 1px)",
          backgroundSize: "26px 26px",
          maskImage:
            "radial-gradient(ellipse 60% 50% at 50% 45%, rgba(0,0,0,0.5) 0%, transparent 75%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 60% 50% at 50% 45%, rgba(0,0,0,0.5) 0%, transparent 75%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 right-0 h-[420px] w-[420px] rounded-full bg-md-tertiary opacity-[0.08] blur-3xl"
      />
      <div className="relative z-10 flex flex-col items-center">
        <span className="mb-10 inline-flex items-center gap-3">
          <ThemeLogo className="h-8 w-auto" />
          <span className="text-[12px] text-md-on-surface-variant">
            의료·규제 AI
          </span>
        </span>
        <span
          className="material-symbols-outlined text-[72px] text-md-primary"
          aria-hidden
        >
          engineering
        </span>
        <h1 className="mt-6 text-[22px] font-semibold text-md-on-surface sm:text-[26px]">
          지금은 점검 중이에요
        </h1>
        <p className="mt-4 max-w-[440px] text-[15px] leading-relaxed text-md-on-surface-variant">
          {text}
        </p>
        {/* 관리자 탈출구 — 관리자 판정이 어긋나도(세션 플래그 미설정 등) 설정 화면으로
            갈 수 있게. /admin 레이아웃은 이 게이트 밖이고 백엔드가 관리자만 통과시킨다. */}
        <Link
          href="/admin/settings"
          className="mt-8 text-[12px] text-md-on-surface-variant/70 underline-offset-2 hover:text-md-on-surface hover:underline"
        >
          관리자이신가요? 점검 설정으로 이동
        </Link>
      </div>
    </main>
  );
}
