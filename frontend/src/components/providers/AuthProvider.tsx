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

export function AuthProvider({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <TokenGate>{children}</TokenGate>
    </SessionProvider>
  );
}
