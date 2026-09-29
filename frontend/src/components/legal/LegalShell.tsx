"use client";

/**
 * LegalShell — 이용약관(/terms)·개인정보처리방침(/privacy) 공통 레이아웃.
 *
 * login/signup 페이지 톤(dot grid 배경·blob·md 토큰) 재사용하되, *읽기 문서*라
 * 가운데 정렬된 스크롤 본문 + 상단 로고 헤더 + 하단 footer 구조. 콘텐츠는 page가
 * children으로 주입(섹션은 `LegalSection` 헬퍼).
 */

import type { ReactNode } from "react";
import Link from "next/link";
import { SiteNav } from "@/components/shell/SiteNav";

export function LegalShell({
  title,
  subtitle,
  effectiveDate,
  draftNotice = true,
  children,
}: {
  title: string;
  subtitle?: string;
  /** "2026-05-21" 같은 시행일(또는 시행 예정일) */
  effectiveDate?: string;
  /** 법무 검토 전 초안 안내 배너 노출 여부 */
  draftNotice?: boolean;
  children: ReactNode;
}) {
  return (
    <main className="relative min-h-screen overflow-x-hidden bg-md-surface text-md-on-surface">
      {/* 배경 dot grid */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 opacity-[0.4]"
        style={{
          backgroundImage:
            "radial-gradient(circle, var(--md-outline-variant) 1px, transparent 1px)",
          backgroundSize: "26px 26px",
          maskImage:
            "radial-gradient(ellipse 70% 50% at 50% 30%, rgba(0,0,0,0.5) 0%, transparent 75%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 70% 50% at 50% 30%, rgba(0,0,0,0.5) 0%, transparent 75%)",
        }}
      />

      {/* 상단 nav — 공개 페이지 공통(SiteNav). 메뉴 누락·페이지별 편차 제거(2026-09-07) */}
      <SiteNav maxWidth="max-w-[820px]" />

      {/* 본문 */}
      <div className="relative z-10 mx-auto max-w-[820px] px-6 py-10 sm:px-8 sm:py-14">
        <span className="text-[13px] font-semibold text-md-primary">
          {title === "이용약관" ? "Terms of Service" : "Privacy Policy"}
        </span>
        <h1
          className="mt-3 text-[40px] font-bold leading-[1.1] tracking-tight text-md-on-surface sm:text-[52px]"
          style={{
            fontFamily: "'Sora', 'Pretendard Variable', sans-serif",
            letterSpacing: "-0.03em",
          }}
        >
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-4 text-[15px] leading-[1.7] text-md-on-surface-variant">
            {subtitle}
          </p>
        ) : null}
        {effectiveDate ? (
          <p className="mt-2 text-[12.5px] text-md-on-surface-variant">
            시행일 · {effectiveDate}
          </p>
        ) : null}

        {draftNotice ? (
          <div className="mt-6 flex items-start gap-2 rounded-card border border-md-outline-variant bg-md-surface-container-low px-4 py-3">
            <span
              className="material-symbols-outlined mt-px shrink-0 text-[18px] text-md-on-surface-variant"
              aria-hidden
            >
              gavel
            </span>
            <p className="text-[12.5px] leading-relaxed text-md-on-surface-variant">
              본 서비스는 클로즈 베타 단계로 운영됩니다.
            </p>
          </div>
        ) : null}

        <div className="mt-10 flex flex-col gap-8">{children}</div>

        {/* 하단 footer */}
        <footer className="mt-16 flex flex-col items-start justify-between gap-3 border-t border-md-outline-variant pt-6 text-[12px] text-md-on-surface-variant sm:flex-row sm:items-center">
          <span>© {new Date().getFullYear()} MEDIREG AI</span>
          <nav className="flex items-center gap-4">
            <Link href="/terms" className="hover:text-md-on-surface">
              이용약관
            </Link>
            <Link href="/privacy" className="hover:text-md-on-surface">
              개인정보처리방침
            </Link>
          </nav>
        </footer>
      </div>
    </main>
  );
}

/** 약관 섹션 — 번호 제목 + 본문. */
export function LegalSection({
  no,
  heading,
  children,
}: {
  no: number;
  heading: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <h2 className="text-[17px] font-semibold text-md-on-surface">
        제{no}조 · {heading}
      </h2>
      <div className="flex flex-col gap-2 text-[14px] leading-[1.8] text-md-on-surface-variant">
        {children}
      </div>
    </section>
  );
}
