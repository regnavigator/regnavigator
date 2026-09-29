"use client";

/**
 * 랜딩 CTA — 세션 인지형.
 *
 * 랜딩은 서버 컴포넌트라 세션을 못 본다. 그래서 "시작하기"가 로그인 여부와
 * 무관하게 /signup 으로 갔고, 이미 로그인한 사용자도 회원가입 폼을 봤다.
 * (사용자 회신: "로그인 되어있는데 시작하기 누르면 회원가입으로 감")
 *
 * authenticated → 채팅 홈("/new") — `/` 는 이제 랜딩 고정이라 "/" 로 보내면
 * 랜딩→랜딩 루프가 된다(2026-08-27 실사용 지적). 그 외 → /signup.
 * status === "loading" 동안은 비로그인 취급(=/signup) — 어차피 /signup 쪽에도
 * 로그인 가드가 있어 잘못 눌려도 채팅으로 되돌아간다.
 */

import Link from "next/link";
import { useSession } from "next-auth/react";
import type { ReactNode } from "react";

export function StartCta({
  className,
  children,
  authedLabel,
}: {
  className?: string;
  children: ReactNode;
  /** 로그인 상태에서 대체할 라벨(없으면 children 그대로) */
  authedLabel?: ReactNode;
}) {
  const { status } = useSession();
  const authed = status === "authenticated";
  return (
    <Link href={authed ? "/new" : "/signup"} className={className}>
      {authed ? (authedLabel ?? children) : children}
    </Link>
  );
}

