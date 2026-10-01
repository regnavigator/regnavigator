"use client";

/**
 * AuthProvider — NextAuth SessionProvider + accessToken을 in-memory authToken store로 동기.
 * localStorage 저장은 XSS 위험으로 안 함. 매 새로고침마다 NextAuth session에서 다시 받음.
 *
 * **session loading 게이팅**: useSession()이 status='loading'(브라우저가 /api/auth/session
 * 호출 중) 동안 children 렌더 보류 → 첫 backend fetch가 token sync된 후에만 발사.
 * 이거 없으면 PageShell이 mount하자마자 useChatState→getClient가 token=null 상태로
 * Authorization 헤더 없이 호출 → backend 401. (사용자가 다른 페이지 갔다 오면 session
 * 캐시되어 풀리는 race condition.)
 */

import { SessionProvider, useSession } from "next-auth/react";
import { useEffect, useState, type ReactNode } from "react";
import { setAuthToken } from "@/lib/client/authToken";

function TokenGate({ children }: { children: ReactNode }) {
  const { data: session, status } = useSession();
  // children 렌더는 *token이 in-memory store에 박힌 후*에만. status만 체크하면
  // useEffect ordering(자식 effect → 부모 effect) 때문에 자식 fetch가 먼저
  // 발사돼 401. tokenReady 게이트로 명시 동기화.
  const [tokenReady, setTokenReady] = useState(false);
  useEffect(() => {
    if (status === "loading") return;
    const token = (session as { accessToken?: string } | null)?.accessToken ?? null;
    setAuthToken(token);
    setTokenReady(true);
  }, [session, status]);

  if (status === "loading" || !tokenReady) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-md-surface">
        <div className="flex flex-col items-center gap-3 text-md-on-surface-variant">
          <span
            className="material-symbols-outlined animate-md-spin text-[28px] text-md-primary"
            aria-hidden
          >
            progress_activity
          </span>
          <p className="text-body-sm">불러오는 중…</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}

/**
 * dev 우회 — `NEXT_PUBLIC_AUTH_BYPASS`/`NEXT_PUBLIC_DUMMY_MODE` 면 SessionProvider 를
 * 아예 마운트하지 않는다. 인증 DB 없이 띄울 때 `/api/auth/session` 이 500 을 내고
 * 콘솔이 에러로 뒤덮여 실제 문제를 가리기 때문(2026-10-01). production 빌드에서는
 * 두 플래그가 강제로 꺼지므로 운영 경로에는 영향이 없다.
 */
const AUTH_BYPASS =
  process.env.NODE_ENV !== "production" &&
  (process.env.NEXT_PUBLIC_AUTH_BYPASS === "true" ||
    process.env.NEXT_PUBLIC_DUMMY_MODE === "true");

export function AuthProvider({ children }: { children: ReactNode }) {
  // dev 우회: SessionProvider 는 **유지**한다 — ConsentGate 등 여러 컴포넌트가
  // useSession() 을 쓰므로 빼면 트리가 깨진다. 대신 `session={null}` 을 넘겨
  // 초기 조회를 생략하고 재조회를 끈다(next-auth v4: session prop 이 주어지면
  // _getSession 이 네트워크를 타지 않는다). TokenGate 도 건너뛴다 — 받을 토큰이 없다.
  if (AUTH_BYPASS) {
    return (
      <SessionProvider session={null} refetchInterval={0} refetchOnWindowFocus={false}>
        {children}
      </SessionProvider>
    );
  }
  return (
    <SessionProvider>
      <TokenGate>{children}</TokenGate>
    </SessionProvider>
  );
}
