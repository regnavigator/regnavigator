/**
 * Next.js middleware — 인증 + 비번 미설정 redirect.
 *
 * 1) dev bypass: NEXT_PUBLIC_AUTH_BYPASS=true 또는 NEXT_PUBLIC_DUMMY_MODE=true → 모두 통과 (production은 강제 OFF)
 * 2) withAuth 본체: 미인증이면 /login으로
 * 3) hasPassword=false면 /auth/set-password 강제 (set-password 페이지 자체는 통과 — 루프 방지)
 */

import { withAuth, type NextRequestWithAuth } from "next-auth/middleware";
import type { NextFetchEvent, NextRequest } from "next/server";
import { NextResponse } from "next/server";

/**
 * dev 전용 인증 bypass — production에선 강제로 OFF.
 *  - NEXT_PUBLIC_AUTH_BYPASS=true : 명시 우회 (테스트용 마스터)
 *  - NEXT_PUBLIC_DUMMY_MODE=true  : 더미 모드(backend 호출 자체 X)면 인증 의미 없음
 */
function isDevAuthBypass(): boolean {
  if (process.env.NODE_ENV === "production") return false;
  return (
    process.env.NEXT_PUBLIC_AUTH_BYPASS === "true" ||
    process.env.NEXT_PUBLIC_DUMMY_MODE === "true"
  );
}

const authMiddleware = withAuth(
  function inner(req) {
    const token = req.nextauth.token as { hasPassword?: boolean } | null;
    const { pathname } = req.nextUrl;

    const isSetPasswordRoute =
      pathname.startsWith("/auth/set-password") ||
      pathname.startsWith("/api/auth/set-password");
    if (token && !token.hasPassword && !isSetPasswordRoute) {
      const url = req.nextUrl.clone();
      url.pathname = "/auth/set-password";
      url.searchParams.set("next", pathname);
      return NextResponse.redirect(url);
    }

    // ※ FE 미들웨어 admin 게이트 제거(2026-05-19 회귀 핫픽스): admin 판정이
    //   medi-front의 `ADMIN_EMAILS`(NextAuth jwt 콜백) 단독이라, 이 env가
    //   배포에서 미설정/백엔드와 불일치면 *실제 admin도 token.isAdmin=false*
    //   → /admin 하드 락아웃. admin 권한의 권위 경계는 **백엔드 require_admin**
    //   (별도 ADMIN_EMAILS, 서버 JWT 검증)이며 그대로 유효. FE에서 라우트
    //   하드블록은 env 이중관리로 락아웃 리스크가 커 제거. (메뉴 비노출은
    //   ThreadList의 session.user.isAdmin로 유지 — UX 레벨.)
    return NextResponse.next();
  },
  {
    pages: { signIn: "/login" },
  },
);

export default async function middleware(req: NextRequest, event: NextFetchEvent) {
  const { pathname, searchParams } = req.nextUrl;

  // ── 점검 모드 — `MAINTENANCE_MODE=true`(서버 env) 시 앱 영역 전체를
  //    /maintenance 로. 공개 페이지(landing·login·terms·privacy — matcher 제외)는
  //    유지되고, 점검 해제 후 /maintenance 직접 진입은 홈으로 돌려보냄.
  const maintenance = process.env.MAINTENANCE_MODE === "true";
  if (pathname === "/maintenance") {
    if (!maintenance) {
      const url = req.nextUrl.clone();
      url.pathname = "/";
      return NextResponse.redirect(url);
    }
    return NextResponse.next(); // 점검 페이지 자체는 인증 없이 표시
  }
  if (maintenance) {
    const url = req.nextUrl.clone();
    url.pathname = "/maintenance";
    return NextResponse.redirect(url);
  }

  // `/` = 랜딩 **전용**(2026-08-27 확정). 종전엔 `/?threadId=` 가 채팅을
  // 겸해서, 랜딩 리다이렉트와 한 경로를 나눠 쓰다 클라이언트 라우터 캐시가
  // 꼬이면 기존 대화 클릭이 랜딩으로 튀었다(실사용 사고). 스레드 URL 은
  // 전부 /new?threadId= 로 이관 — 구 딥링크(북마크·메일)는 여기서 이관.
  if (pathname === "/") {
    const url = req.nextUrl.clone();
    const tid = searchParams.get("threadId");
    if (tid) {
      url.pathname = "/new";  // 쿼리는 그대로 유지됨
    } else {
      url.pathname = "/landing";
    }
    return NextResponse.redirect(url);
  }

  // production에서 dev preview 페이지 차단 — 404 redirect.
  if (
    process.env.NODE_ENV === "production" &&
    (pathname.startsWith("/auth/email-preview") ||
      pathname.startsWith("/auth/dialog-preview"))
  ) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  if (isDevAuthBypass()) return NextResponse.next();
  return authMiddleware(req as unknown as NextRequestWithAuth, event);
}

// matcher 화이트리스트 (인증 우회 — 공개 페이지):
//  - `api/auth`         : NextAuth 자체 라우트 (콜백·session 등)
//  - `_next/*`/`favicon`: Next.js static assets
//  - `login`/`signup`   : 인증 진입점
//  - `auth/verify`      : 매직 링크 클릭 (인증 전 필수 통과)
//  - `landing`          : 마케팅 페이지 (공개)
//  - `terms`/`privacy`  : 약관·개인정보처리방침 (공개 — 가입 전 열람·동의)
//  - `guide`            : 이용 매뉴얼 (공개 — 가입 전에도 무엇을 하는지 확인 가능)
//  - `updates`          : 업데이트 내역 게시판 (공개 — 랜딩에서 연결, 2026-09-02)
//  - `api/announcements`: 게시판 프록시(서버 사이드 backend 호출, 공개)
//  - `.*\..*`           : public/ 정적 자산 (logo.png 등). 확장자 있는 경로 전부 우회.
//  - `auth/dialog-preview`: dev dialog 레이아웃 미리보기. production은 위 NODE_ENV 가드로 redirect.
// dev에서만 통과시키고 production은 인증 필요한 경로:
//  - `auth/email-preview`: dev preview 전용. production은 위 NODE_ENV 가드로 redirect.
// 그 외(/admin/*·/, /new, /auth/set-password 등)는 모두 인증 필수.
export const config = {
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico|login|signup|auth/verify|auth/dialog-preview|api/announcements|landing|guide|updates|terms|privacy|.*\\..*).*)"],
};
