/**
 * 404 — 존재하지 않는 경로. login/signup·legal 페이지와 동일 톤(dot grid 배경 +
 * ThemeLogo). 홈(랜딩)·로그인 진입로 제공. 인증 흐름과 무관(Next.js 내부 렌더).
 */

import Link from "next/link";
import { ThemeLogo } from "@/components/shell/ThemeLogo";

export default function NotFound() {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-md-surface px-6 text-center text-md-on-surface">
      {/* 배경 dot grid */}
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
        className="pointer-events-none absolute -top-32 right-0 h-[420px] w-[420px] rounded-full bg-md-primary opacity-[0.08] blur-3xl"
      />

      <div className="relative z-10 flex flex-col items-center">
        <Link
          href="/"
          aria-label="메인으로"
          className="mb-10 inline-flex items-center gap-3 transition-opacity hover:opacity-80"
        >
          <ThemeLogo className="h-8 w-auto" />
          <span className="text-[12px] uppercase tracking-[0.1em] text-md-on-surface-variant">
            규제 내비게이터
          </span>
        </Link>

        <p
          className="text-[88px] font-bold leading-none tracking-tight text-md-primary sm:text-[120px]"
          style={{
            fontFamily: "'Sora', 'Pretendard Variable', sans-serif",
            letterSpacing: "-0.04em",
          }}
        >
          404
        </p>
        <h1 className="mt-6 text-[22px] font-semibold text-md-on-surface sm:text-[26px]">
          페이지를 찾을 수 없어요
        </h1>
        <p className="mt-3 max-w-[420px] text-[14.5px] leading-[1.7] text-md-on-surface-variant">
          요청하신 페이지가 존재하지 않거나, 주소가 변경·삭제되었을 수 있습니다.
        </p>

        <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/"
            className="theme-cta-bg theme-cta-glow inline-flex h-12 items-center justify-center gap-2 rounded-full px-7 text-[15px] font-semibold text-md-on-primary shadow-sm transition-all duration-200 ease-out hover:scale-[1.02] hover:-translate-y-0.5 active:scale-[0.98]"
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden>
              chat
            </span>
            채팅으로 가기
          </Link>
          <Link
            href="/landing"
            className="inline-flex h-12 items-center justify-center gap-1.5 rounded-full border border-md-outline-variant px-6 text-[14px] font-medium text-md-on-surface transition-all duration-150 ease-out hover:-translate-y-px hover:border-md-on-surface hover:bg-md-surface-container-low"
          >
            소개 페이지
          </Link>
        </div>
      </div>

      {/* 하단 footer — 약관·개인정보 일관 노출 */}
      <div className="relative z-10 mt-16 flex items-center gap-4 text-[11.5px] text-md-on-surface-variant">
        <span>© {new Date().getFullYear()} RegNavigator</span>
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
