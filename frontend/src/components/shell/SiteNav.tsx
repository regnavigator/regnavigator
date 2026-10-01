"use client";

/**
 * SiteNav — 공개 페이지(랜딩·이용 안내·업데이트·약관·개인정보) 공통 상단 nav.
 *
 * 2026-09-07 요청: "메인 nav 메뉴를 한쪽으로 몰아넣고, 페이지마다 빠진 메뉴가
 * 없게". 그전엔 페이지별로 헤더를 따로 그려서 /guide 엔 '업데이트'가, /updates 엔
 * '로그인'이, 약관 페이지엔 '이용 안내'가 없었다. 여기 한 곳에서 메뉴를 정의하고
 * 모든 공개 페이지가 같은 컴포넌트를 쓴다.
 *
 * 구조: [로고 · 소개 · 이용 안내 · 업데이트 · (로그인 | 시작하기) / (채팅으로)]
 *  - 2026-09-08: 타이틀(로고)까지 포함해 전부 왼쪽 한 그룹(운영자: "한곳으로 모으라니깐 타이틀도 포함").
 *  - 현재 경로는 aria-current + 진한 색으로 표시.
 *  - CTA 는 세션 인지(LandingNavCta 와 같은 규칙): 로그인 상태면 [채팅으로] 하나.
 *  - 관리자면 **오른쪽 끝**에 [관리자] 버튼(2026-09-22) — 사용자용 메뉴 묶음과 떨어뜨려
 *    일반 진입(채팅으로)과 구분. 판정: 세션 isAdmin(프런트 ADMIN_EMAILS) 또는 /me/usage 의
 *    is_admin(권한 관리자 포함) 1회 조회 — 폴링 훅(useUsage)은 쓰지 않는다.
 *
 * variant
 *  - "bar"     : sticky, 아래 테두리, h-16(=64px). /guide 의 sticky 목차가 top-16 에
 *                붙으므로 높이를 바꾸면 그쪽도 같이 봐야 한다.
 *  - "overlay" : 랜딩용 fixed + 위→아래 투명 그라데이션(섹션 위에 얹힘).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { getUsage } from "@/lib/client/quota";

const MENU: { href: string; label: string }[] = [
  { href: "/landing", label: "소개" },
  { href: "/guide", label: "이용 안내" },
  { href: "/updates", label: "업데이트" },
];

const LINK =
  "inline-flex h-9 items-center rounded-full px-3 text-[13px] font-semibold transition-colors sm:px-4";
const LINK_IDLE = "text-md-on-surface-variant hover:text-md-on-surface";
const LINK_ACTIVE = "text-md-on-surface";
const CTA =
  "theme-cta-bg theme-cta-glow inline-flex h-9 items-center rounded-full px-5 text-[13px] font-semibold text-md-on-primary transition-all";

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return pathname === href || pathname.startsWith(href + "/");
}

export function SiteNav({
  variant = "bar",
  maxWidth = "max-w-[980px]",
}: {
  variant?: "bar" | "overlay";
  /** bar 변형의 내부 컨테이너 폭(tailwind 클래스). 페이지 본문 폭과 맞춘다. */
  maxWidth?: string;
}) {
  const pathname = usePathname();
  const { data: session, status } = useSession();
  const authed = status === "authenticated";
  const sessionAdmin = !!(session?.user as { isAdmin?: boolean } | undefined)?.isAdmin;
  const [backendAdmin, setBackendAdmin] = useState(false);
  useEffect(() => {
    if (!authed || sessionAdmin) return;
    const ctl = new AbortController();
    getUsage(ctl.signal)
      .then((u) => setBackendAdmin(!!u.is_admin))
      .catch(() => { /* 표시 전용 — 실패하면 버튼만 안 보인다 */ });
    return () => ctl.abort();
  }, [authed, sessionAdmin]);
  const isAdmin = authed && (sessionAdmin || backendAdmin);

  const adminEntry = isAdmin ? (
    <Link
      href="/admin"
      title="관리자 페이지"
      aria-label="관리자 페이지"
      className="ml-auto inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border border-md-outline-variant bg-md-surface-container-lowest px-3 sm:px-4 text-[13px] font-semibold text-md-on-surface transition-colors hover:border-md-primary hover:text-md-primary"
    >
      <span className="material-symbols-outlined text-[17px]" aria-hidden>
        admin_panel_settings
      </span>
      <span className="hidden sm:inline">관리자</span>
    </Link>
  ) : null;

  const logo = (
    <Link
      href="/landing"
      aria-label="RegNavigator 홈"
      className="inline-flex shrink-0 items-center gap-2 text-md-on-surface"
    >
      <span
        className="material-symbols-outlined text-[20px] text-md-primary"
        style={{ fontVariationSettings: "'FILL' 1" }}
        aria-hidden
      >
        gavel
      </span>
      <span className="text-[15px] font-bold tracking-tight" style={{ letterSpacing: "-0.02em" }}>
        RegNavigator
      </span>
    </Link>
  );

  const menu = (
    <nav aria-label="주 메뉴" className="flex items-center gap-1 sm:gap-2">
      {MENU.map((m) => {
        const active = isActive(pathname, m.href);
        return (
          <Link
            key={m.href}
            href={m.href}
            aria-current={active ? "page" : undefined}
            className={`${LINK} ${active ? LINK_ACTIVE : LINK_IDLE}`}
          >
            {m.label}
          </Link>
        );
      })}
      {authed ? (
        <Link href="/new" className={`ml-1 ${CTA}`}>
          채팅으로
        </Link>
      ) : (
        <>
          <Link href="/login" className={`${LINK} ${LINK_IDLE}`}>
            로그인
          </Link>
          <Link href="/signup" className={`ml-1 ${CTA}`}>
            시작하기
          </Link>
        </>
      )}
    </nav>
  );

  if (variant === "overlay") {
    return (
      <div className="pointer-events-none fixed inset-x-0 top-0 z-50 flex items-center gap-6 bg-gradient-to-b from-md-surface/95 to-md-surface/0 px-6 py-5 sm:px-16">
        <div className="pointer-events-auto">{logo}</div>
        <div className="pointer-events-auto">{menu}</div>
        {adminEntry ? <div className="pointer-events-auto ml-auto">{adminEntry}</div> : null}
      </div>
    );
  }

  return (
    <header className="sticky top-0 z-30 border-b border-md-outline-variant bg-md-surface-container-lowest">
      <div className={`mx-auto flex h-16 ${maxWidth} items-center gap-6 px-6`}>
        {logo}
        {menu}
        {adminEntry}
      </div>
    </header>
  );
}
