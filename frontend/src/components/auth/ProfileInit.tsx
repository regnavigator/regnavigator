"use client";

/**
 * ProfileInit — 가입 폼에서 받은 부가 정보(이름/직군/소속)를 backend 에 영속.
 *
 * 가입 흐름: signup 폼이 sessionStorage draft(medi-front-signup-draft)에
 * name/job/organization 을 저장 → 매직링크 인증으로 로그인 완료 → 이 컴포넌트가
 * `GET /me/profile` 로 미입력(completed=false)을 확인하고 draft 를
 * `PUT /me/profile` 로 자동 제출한다. (signup/page.tsx 의 "backend 협조 필요"
 * TODO 였던 구간 — 2026-08-10 backend /me/profile 신설로 연결.)
 *
 * - 이미 프로필이 있으면(completed) 건드리지 않는다 — 재로그인 덮어쓰기 방지.
 * - draft 가 없으면(기존 회원) 아무것도 안 함 — 조용한 best-effort.
 * - draft 는 **localStorage**에서 읽는다(+구버전 sessionStorage 폴백) —
 *   매직링크가 다른 탭/메일앱에서 열리면 sessionStorage(탭 격리)는 빈 상태라
 *   부가정보가 유실되던 잔존 경로(2026-08-11 발견) 대응.
 * - draft.email ≠ 로그인 계정이면 제출하지 않는다 — 공용 브라우저에서 남의
 *   draft 가 내 프로필로 저장되는 오염 방지. TTL 7일 초과 draft 도 무시.
 * - fail-open: 실패해도 앱 사용을 막지 않는다(ConsentGate 와 동일 철학).
 */

import { useSession } from "next-auth/react";
import { useEffect, useRef } from "react";
import { getMyProfile, putMyProfile } from "@/lib/client/profile";
import { isConfigured, isDummyMode } from "@/lib/store/settings";

const SIGNUP_DRAFT_KEY = "medi-front-signup-draft";
const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000;

type SignupDraft = {
  email?: string;
  name?: string;
  job?: string;
  organization?: string;
  ts?: number;
};

function readDraft(): SignupDraft | null {
  try {
    // localStorage 우선(현행), sessionStorage 는 마이그레이션 폴백(구버전이
    // 저장해 둔 in-flight 가입 흐름이 배포를 걸쳐도 이어지게).
    const raw =
      localStorage.getItem(SIGNUP_DRAFT_KEY) ??
      sessionStorage.getItem(SIGNUP_DRAFT_KEY);
    return raw ? (JSON.parse(raw) as SignupDraft) : null;
  } catch {
    return null;
  }
}

export function ProfileInit() {
  const { data: session, status } = useSession();
  const doneFor = useRef<string | null>(null);
  const userKey =
    (session?.user as { email?: string | null } | undefined)?.email ?? null;

  useEffect(() => {
    if (isDummyMode() || status !== "authenticated" || !userKey) return;
    if (doneFor.current === userKey) return;
    if (!isConfigured()) return;

    const draft = readDraft();
    if (!draft || !(draft.name || draft.job || draft.organization)) {
      doneFor.current = userKey; // draft 없음 — 이 계정은 더 검사 안 함
      return;
    }
    // 계정 불일치(남의 draft) 또는 만료 draft — 제출하지 않음.
    if (
      (draft.email && draft.email.toLowerCase() !== userKey.toLowerCase()) ||
      (draft.ts && Date.now() - draft.ts > DRAFT_TTL_MS)
    ) {
      doneFor.current = userKey;
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const cur = await getMyProfile();
        if (cancelled) return;
        if (!cur.completed) {
          await putMyProfile({
            display_name: draft.name || null,
            affiliation: draft.organization || null,
            job_role: draft.job || null,
          });
        }
        if (!cancelled) doneFor.current = userKey;
      } catch (err) {
        // fail-open — 프로필 저장 실패가 앱 사용을 막으면 안 된다.
        if (!cancelled) doneFor.current = userKey;
        console.warn("[profile] draft 자동 저장 실패 — 생략", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, userKey]);

  return null;
}
