"use client";

/**
 * ConsentGate — 동의 기록을 서버에 영속하는 게이트 (개인정보보호법 이행).
 *
 * 로그인 완료(JWT 확보) 후 `GET /me/consent` 로 상태 확인:
 *  - `needs_consent=false` → 아무것도 안 함
 *  - `needs_consent=true`  →
 *     a) signup draft(체크박스 완료 흔적)가 있으면 **자동 제출** — 가입 화면에서
 *        이미 동의했으므로 다시 묻지 않는다
 *     b) 없으면(기존 회원·고지 개정·새 탭 가입) **동의 모달** 표시
 *
 * 배경: 가입 화면 체크박스가 버튼 활성화에만 쓰이고 서버에 기록되지 않아 동의
 * 사실을 입증할 수 없었다(medi-back docs/frontend_legal_handoff.md §1). 이제
 * events(legal_consent)에 누가·언제·어느 버전·어느 항목으로 남는다.
 *
 * fail-open: 상태 조회 실패(백엔드 미기동 등)는 앱 사용을 막지 않는다 — 게이트는
 * 기록 장치이지 기능 차단기가 아니다.
 */

import { signOut, useSession } from "next-auth/react";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  getConsentStatus,
  giveConsent,
  type ConsentScope,
} from "@/lib/client/privacy";
import { isConfigured, isDummyMode } from "@/lib/store/settings";

/** 동의 게이트를 건너뛰는 공개·인증 플로우 경로 — 모달이 가입/열람을 방해하면 안 됨. */
const SKIP_PREFIXES = ["/landing", "/login", "/signup", "/terms", "/privacy", "/auth"];

const SIGNUP_DRAFT_KEY = "medi-front-signup-draft";

type SignupDraft = {
  email?: string;
  ts?: number;
  agreed_terms?: boolean;
  agreed_transfer?: boolean;
  marketing_opt_in?: boolean;
  /** 이 draft 의 동의를 서버에 한 번 기록했음 — 재사용 금지(고지 개정 시 자동 재동의 방지). */
  consent_done?: boolean;
};

const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000;

/** 자동 제출에 쓸 수 있는 draft 인가 — 같은 계정·7일 이내·아직 안 쓴 것만(2026-09-23).
 *  종전엔 조건 없이 재사용해, 고지 버전이 올라가도 같은 브라우저에선 재동의가
 *  사용자 확인 없이 자동 처리됐다. 남의 draft(공용 PC)도 내 동의로 제출될 수 있었다. */
function usableDraft(d: SignupDraft | null, email: string): d is SignupDraft {
  return (
    !!d &&
    !d.consent_done &&
    !!d.email &&
    d.email.toLowerCase() === email.toLowerCase() &&
    typeof d.ts === "number" &&
    Date.now() - d.ts <= DRAFT_TTL_MS
  );
}

function markDraftConsumed(): void {
  try {
    for (const store of [localStorage, sessionStorage]) {
      const raw = store.getItem(SIGNUP_DRAFT_KEY);
      if (!raw) continue;
      // 프로필(ProfileInit)이 아직 읽을 수 있게 draft 는 남기고 동의 재사용만 막는다.
      store.setItem(SIGNUP_DRAFT_KEY, JSON.stringify({ ...JSON.parse(raw), consent_done: true }));
    }
  } catch {
    /* 무시 */
  }
}

function readSignupDraft(): SignupDraft | null {
  try {
    // localStorage 우선 — 가입 폼이 2026-08-11부터 localStorage에 저장(매직링크가
    // 다른 탭에서 열려도 draft 생존). sessionStorage는 구버전 in-flight 폴백.
    const raw =
      localStorage.getItem(SIGNUP_DRAFT_KEY) ??
      sessionStorage.getItem(SIGNUP_DRAFT_KEY);
    return raw ? (JSON.parse(raw) as SignupDraft) : null;
  } catch {
    return null;
  }
}

export function ConsentGate() {
  const { data: session, status } = useSession();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [version, setVersion] = useState<string | null>(null);
  const [terms, setTerms] = useState(false);
  const [transfer, setTransfer] = useState(false);
  const [marketing, setMarketing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 검사 완료한 *계정* 기록 — boolean 이면 (a) in-flight 중 이탈로 결과가
  // 폐기돼도 재검사가 영영 안 되고, (b) client-nav 로 다른 계정 재로그인 시
  // 새 계정 검사가 생략된다(리뷰 발견). 완료 시점에만 계정 키를 기록.
  const checkedFor = useRef<string | null>(null);
  const userKey =
    (session?.user as { email?: string | null } | undefined)?.email ?? null;

  const skip =
    isDummyMode() ||
    SKIP_PREFIXES.some((p) => pathname?.startsWith(p));

  useEffect(() => {
    if (skip || status !== "authenticated" || !userKey) return;
    if (checkedFor.current === userKey) return;
    if (!isConfigured()) return;

    let cancelled = false;
    void (async () => {
      try {
        const st = await getConsentStatus();
        if (cancelled) return; // 폐기 — checkedFor 미기록이라 다음 기회에 재검사
        checkedFor.current = userKey;
        if (!st.needs_consent) return;

        // 방금 가입 화면에서 필수 항목을 모두 체크한 흔적(draft)이 있으면 자동 제출.
        // 같은 계정·7일 이내·처음 쓰는 draft 만 — 고지 개정 때는 반드시 모달로 다시 묻는다.
        const raw = readSignupDraft();
        const draft = usableDraft(raw, userKey) ? raw : null;
        if (draft?.agreed_terms && draft.agreed_transfer) {
          const scopes: ConsentScope[] = [
            "terms",
            "transfer",
            ...(draft.marketing_opt_in ? (["marketing"] as const) : []),
          ];
          try {
            await giveConsent(scopes, st.current_version);
            markDraftConsumed();
            return; // 기록 완료 — 모달 불필요
          } catch {
            // 자동 제출 실패 → 모달로 폴백
          }
        }
        if (cancelled) return;
        setVersion(st.current_version);
        setMarketing(Boolean(draft?.marketing_opt_in));
        setOpen(true);
      } catch (err) {
        // fail-open — 백엔드 미기동/구버전이어도 앱 사용은 막지 않는다.
        // 이 계정은 검사한 것으로 기록(무한 재시도로 백엔드를 두드리지 않게).
        if (!cancelled) checkedFor.current = userKey;
        console.warn("[consent] 상태 조회 실패 — 게이트 생략", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [skip, status, userKey]);

  if (!open) return null;

  const allRequired = terms && transfer;

  async function onSubmit() {
    if (!allRequired || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const scopes: ConsentScope[] = [
        "terms",
        "transfer",
        ...(marketing ? (["marketing"] as const) : []),
      ];
      await giveConsent(scopes, version ?? undefined);
      markDraftConsumed();
      setOpen(false);
    } catch (err) {
      console.error("[consent] 기록 실패", err);
      setError("동의 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 px-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="consent-gate-title"
    >
      <div className="w-full max-w-[480px] rounded-card border border-md-outline-variant bg-md-surface p-6 shadow-xl sm:p-8">
        <h2
          id="consent-gate-title"
          className="text-[19px] font-bold text-md-on-surface"
        >
          서비스 이용 동의
        </h2>
        <p className="mt-2 text-[13.5px] leading-relaxed text-md-on-surface-variant">
          서비스 이용을 위해 아래 항목에 대한 동의가 필요합니다.
          {version ? (
            <span className="ml-1 text-[12px] opacity-70">(고지 버전 {version})</span>
          ) : null}
        </p>

        <div className="mt-5 flex flex-col gap-3">
          <label className="flex cursor-pointer items-start gap-2.5 text-[13.5px] leading-relaxed text-md-on-surface-variant">
            <input
              type="checkbox"
              checked={terms}
              onChange={(e) => setTerms(e.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-md-primary"
            />
            <span>
              <span className="font-semibold text-md-on-surface">[필수]</span>{" "}
              <Link
                href="/terms"
                target="_blank"
                className="font-medium text-md-primary underline-offset-2 hover:underline"
              >
                이용약관
              </Link>
              {" 및 "}
              <Link
                href="/privacy"
                target="_blank"
                className="font-medium text-md-primary underline-offset-2 hover:underline"
              >
                개인정보 수집·이용
              </Link>
              에 동의합니다.
            </span>
          </label>

          <label className="flex cursor-pointer items-start gap-2.5 text-[13.5px] leading-relaxed text-md-on-surface-variant">
            <input
              type="checkbox"
              checked={transfer}
              onChange={(e) => setTransfer(e.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-md-primary"
            />
            <span>
              <span className="font-semibold text-md-on-surface">[필수]</span>{" "}
              개인정보의{" "}
              <Link
                href="/privacy"
                target="_blank"
                className="font-medium text-md-primary underline-offset-2 hover:underline"
              >
                국외 이전
              </Link>
              에 동의합니다. AI 답변 생성을 위해 질의 내용이 국외 사업자
              (Anthropic·OpenAI 등)에게 전송될 수 있습니다.
            </span>
          </label>

          <label className="flex cursor-pointer items-start gap-2.5 text-[13.5px] leading-relaxed text-md-on-surface-variant">
            <input
              type="checkbox"
              checked={marketing}
              onChange={(e) => setMarketing(e.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-md-primary"
            />
            <span>
              <span>[선택]</span> 제품 정보·업데이트 등의 수신에
              동의합니다.
            </span>
          </label>
        </div>

        {error ? (
          <div className="mt-4 flex items-start gap-2 border-l-2 border-md-error bg-md-error-container/40 px-3 py-2 text-[13px] text-md-on-error-container">
            <span className="material-symbols-outlined text-[16px]" aria-hidden>
              error
            </span>
            <span>{error}</span>
          </div>
        ) : null}

        <button
          type="button"
          onClick={() => void onSubmit()}
          disabled={!allRequired || submitting}
          className="theme-cta-bg mt-6 inline-flex h-11 w-full items-center justify-center gap-2 rounded-full text-[14.5px] font-semibold text-md-on-primary transition-all disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? (
            <>
              <span
                className="material-symbols-outlined animate-spin text-[16px]"
                aria-hidden
              >
                progress_activity
              </span>
              처리 중…
            </>
          ) : (
            "동의하고 계속하기"
          )}
        </button>

        <p className="mt-3 text-center text-[11.5px] leading-relaxed text-md-on-surface-variant">
          필수 항목에 동의하지 않으면 서비스를 이용할 수 없습니다.
        </p>
        {/* 탈출구 — 동의를 원치 않는 사용자가 오버레이에 갇히지 않게 */}
        <button
          type="button"
          onClick={() => void signOut({ callbackUrl: "/login" })}
          className="mx-auto mt-2 block text-[11.5px] text-md-on-surface-variant underline-offset-2 hover:text-md-on-surface hover:underline"
        >
          동의하지 않고 로그아웃
        </button>
      </div>
    </div>
  );
}
