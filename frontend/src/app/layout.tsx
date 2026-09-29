import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { Toaster } from "sonner";
import { AuthProvider } from "@/components/providers/AuthProvider";
import { ConsentGate } from "@/components/legal/ConsentGate";
import { ProfileInit } from "@/components/auth/ProfileInit";
import { ThemeToggleSlot } from "@/components/shell/ThemeToggleSlot";
import "@/styles/globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

/**
 * 모바일 뷰포트(2026-07-26). Next.js 가 기본
 * `width=device-width, initial-scale=1` 은 자동 삽입하므로 여기선 themeColor 만.
 *
 * ⚠️ `viewportFit: "cover"` 는 **의도적으로 넣지 않는다** — cover 는 콘텐츠를
 *    노치/홈 인디케이터 아래까지 확장시키므로 모든 고정 요소에 정확한
 *    `env(safe-area-inset-*)` 보정이 뒤따라야 하고, 실기기 없이는 그 결과를
 *    검증할 수 없다. 기본값(auto)은 브라우저가 안전영역을 알아서 피해준다.
 * ⚠️ `maximumScale`·`userScalable:false` 도 넣지 않는다 — 확대 봉쇄는 접근성
 *    위반이며, iOS 입력 자동확대는 globals.css 의 16px 규칙으로 이미 해결.
 */
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#101418" },
  ],
};

export const metadata: Metadata = {
  manifest: "/manifest.webmanifest",
  title: "MEDIREG AI",
  description: "법령·고시·해석·판례를 벡터 DB와 웹 검색으로 통합 조회하는 의료·규제 전문 AI 에이전트.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      {/* eslint-disable @next/next/no-page-custom-font */}
      <head>
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css"
        />
        {/* Material Symbols Outlined — globals.css 에서 @import … layer(base) 로 로드(2026-09-08).
            여기 <link> 로 두면 레이어 밖 규칙이 Tailwind 유틸리티를 덮어 아이콘 정렬·크기가 깨진다. */}
        {/* Sora + JetBrains Mono — design_guide.md (medra) 전용 폰트. landing 페이지에서만 사용 */}
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap"
        />
      </head>
      {/* eslint-enable @next/next/no-page-custom-font */}
      {/* suppressHydrationWarning — 아래 인라인 스크립트가 hydration 전에 body
          data-theme 을 박아 서버 HTML(속성 없음)과 불일치. 테마 flash 방지의
          의도된 동작이라 React 표준대로 이 요소만 경고 억제(단일 속성 한정). */}
      <body
        suppressHydrationWarning
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased`}
      >
        {/* 테마 flash 방지 — hydration 전에 body data-theme 박음 */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('medi-front-theme');if(t==='basic'){document.body.removeAttribute('data-theme');}else if(t==='regia'||t==='dark'){document.body.setAttribute('data-theme',t);}else{document.body.setAttribute('data-theme','medra');}}catch(e){}})();`,
          }}
        />
        <AuthProvider>
          <NuqsAdapter>{children}</NuqsAdapter>
          {/* 동의 기록 게이트 — needs_consent면 모달, signup draft 있으면 자동 제출 */}
          <ConsentGate />
          {/* 가입 폼 부가정보(이름/직군/소속) draft → backend /me/profile 자동 영속 */}
          <ProfileInit />
          {/* fixed 우상단 테마 토글 — landing path에선 자동 숨김 (URL 단위 theme) */}
          <ThemeToggleSlot />
          <Toaster
            position="bottom-center"
            theme="light"
            duration={3500}
            offset={120}
            icons={{
              // success/info는 보더 색 + 텍스트로 구분 충분 → hide 유지.
              // error/warning은 색만으론 약함(색맹 사용자) → Material 아이콘 노출.
              success: <span className="hidden" />,
              info: <span className="hidden" />,
              error: (
                <span
                  className="material-symbols-outlined shrink-0 text-[18px] text-md-error"
                  aria-hidden
                >
                  error
                </span>
              ),
              warning: (
                <span
                  className="material-symbols-outlined shrink-0 text-[18px] text-md-tertiary"
                  aria-hidden
                >
                  warning
                </span>
              ),
            }}
            toastOptions={{
              classNames: {
                // 배경·텍스트·보더 모두 theme token (var()) — basic/medra/regia 자동 매칭.
                // 보더는 --md-primary로 박아 테마별 시그니처 색이 자연스럽게 노출.
                // shadow는 Tailwind utility(shadow-lg)로 — raw rgba 직접 작성 회피(R1).
                toast:
                  "!bg-md-surface !text-md-on-surface !border !border-md-primary !rounded-card !shadow-lg !px-4 !py-3 !text-[13.5px] !font-medium !gap-2",
                title: "!text-md-on-surface !font-semibold !text-[14px]",
                description: "!text-md-on-surface-variant !text-[12.5px]",
                error: "!border-md-error",
                actionButton:
                  "!bg-md-primary !text-md-on-primary !rounded-pill !px-3 !text-[12px] !font-semibold",
                cancelButton:
                  "!bg-md-surface-container !text-md-on-surface-variant !rounded-pill !px-3 !text-[12px]",
              },
            }}
          />
        </AuthProvider>
      </body>
    </html>
  );
}
