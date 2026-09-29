/**
 * 점검중 페이지 — `MAINTENANCE_MODE=true`(서버 env) 시 middleware가 앱 영역
 * 전체를 이 페이지로 보낸다. 공개 페이지(landing·terms·privacy·login)는 유지.
 *
 * 안내 문구는 `NEXT_PUBLIC_MAINTENANCE_MESSAGE`로 덮어쓸 수 있음(예상 복구
 * 시각 등). 톤은 404/legal 페이지와 동일(dot grid + ThemeLogo).
 */

import type { Metadata } from "next";
import Link from "next/link";
import { ThemeLogo } from "@/components/shell/ThemeLogo";

export const metadata: Metadata = {
  title: "점검 중 · MEDIREG AI",
  robots: { index: false },
};

export default function MaintenancePage() {
  const message =
    process.env.NEXT_PUBLIC_MAINTENANCE_MESSAGE ||
    "더 나은 서비스를 위해 시스템 점검을 진행하고 있습니다. 잠시 후 다시 이용해주세요.";

  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-md-surface px-6 text-center text-md-on-surface">
      {/* 배경 dot grid — 404와 동일 톤 */}
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
          <span className="text-[12px] uppercase tracking-[0.1em] text-md-on-surface-variant">
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
        <p className="mt-3 max-w-[440px] text-[14.5px] leading-[1.7] text-md-on-surface-variant">
          {message}
        </p>
        <p className="mt-2 text-[12.5px] text-md-on-surface-variant">
          진행 중이던 대화와 보고서는 안전하게 보관됩니다.
        </p>

        <div className="mt-9">
          <Link
            href="/landing"
            className="inline-flex h-12 items-center justify-center gap-1.5 rounded-full border border-md-outline-variant px-6 text-[14px] font-medium text-md-on-surface transition-all duration-150 ease-out hover:-translate-y-px hover:border-md-on-surface hover:bg-md-surface-container-low"
          >
            서비스 소개 보기
          </Link>
        </div>
      </div>

      <div className="relative z-10 mt-16 flex items-center gap-4 text-[11.5px] text-md-on-surface-variant">
        <span>© {new Date().getFullYear()} MEDIREG AI</span>
        <Link href="/terms" className="hover:text-md-on-surface">
          이용약관
        </Link>
        <Link href="/privacy" className="hover:text-md-on-surface">
          개인정보처리방침
        </Link>
      </div>
    </main>
  );
}
