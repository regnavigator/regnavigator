"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { Suspense } from "react";
import Link from "next/link";
import { ThemeLogo } from "@/components/shell/ThemeLogo";
import {
  MIN_LENGTH,
  POLICY_HINT,
  validatePassword,
} from "@/lib/password-policy";

function SetPasswordInner() {
  const { data: session, status, update } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionAny = session as { hasPassword?: boolean } | null;
  // reset=1 query는 비밀번호 재설정 매직링크 흐름에서 박힌다(기존 비밀번호는 유지된 채
  // 진입 — 로그인된 세션에서 새 비밀번호로 덮어쓴다).
  const isReset =
    params.get("reset") === "1" || sessionAny?.hasPassword === true;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const policyError = validatePassword(password);
    if (policyError) {
      setError(policyError);
      return;
    }
    if (password !== confirm) {
      setError("두 비밀번호가 일치하지 않습니다.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/auth/set-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as
          | { error?: string }
          | null;
        setError(body?.error ?? "설정에 실패했습니다. 잠시 후 다시 시도해주세요.");
        return;
      }
      await update();
      router.replace(next);
    } catch (err) {
      console.error("[set-password]", err);
      setError("네트워크 오류가 발생했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-md-surface">
        <p className="text-body-sm text-md-on-surface-variant">로딩 중…</p>
      </main>
    );
  }

  return (
    <main className="relative flex min-h-screen flex-col overflow-hidden bg-md-surface text-md-on-surface">
      {/* 배경 dot grid + blob — login/signup/verify와 동일 */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.5]"
        style={{
          backgroundImage:
            "radial-gradient(circle, var(--md-outline-variant) 1px, transparent 1px)",
          backgroundSize: "26px 26px",
          maskImage:
            "radial-gradient(ellipse 80% 60% at 50% 50%, rgba(0,0,0,0.6) 0%, transparent 75%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 80% 60% at 50% 50%, rgba(0,0,0,0.6) 0%, transparent 75%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 -right-32 h-[520px] w-[520px] rounded-full bg-md-primary opacity-[0.09] blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 -left-32 h-[460px] w-[460px] rounded-full bg-md-secondary opacity-[0.06] blur-3xl"
      />

      {/* 좌상단 로고 */}
      <div className="relative z-10 px-8 pt-8 sm:px-16 sm:pt-12">
        <Link
          href="/new"
          aria-label="메인으로"
          className="inline-flex items-center gap-3 transition-opacity hover:opacity-80"
        >
          <ThemeLogo className="h-9 w-auto" />
          <span className="text-[12.5px] uppercase tracking-[0.1em] text-md-on-surface-variant">
            의료·규제 AI
          </span>
        </Link>
      </div>

      {/* 본문 — 2-column */}
      <div className="relative z-10 flex flex-1 items-center justify-center px-8 sm:px-16">
        <div className="grid w-full max-w-[1100px] grid-cols-1 items-center gap-12 lg:grid-cols-[1.1fr_1fr] lg:gap-20">
          {/* 좌: 헤딩 + 카피 */}
          <div className="w-full max-w-[560px]">
            <span className="text-[15px] font-semibold uppercase tracking-[0.12em] text-md-primary">
              {isReset ? "비밀번호 변경" : "비밀번호 설정"}
            </span>
            <h1
              className="mt-4 text-[64px] font-bold leading-[1.05] tracking-tight text-md-on-surface sm:text-[88px]"
              style={{
                fontFamily: "'Sora', 'Pretendard Variable', sans-serif",
                letterSpacing: "-0.03em",
              }}
            >
              <span className="theme-grad-text">
                {isReset ? "새 비밀번호" : "비밀번호를 설정하세요"}
              </span>
            </h1>
            <p className="mt-7 text-[17px] leading-[1.75] text-md-on-surface">
              {isReset
                ? "보안을 위해 새 비밀번호를 입력해주세요."
                : "다음 로그인부터 비밀번호로 접속할 수 있습니다."}
            </p>
            <p className="mt-2 text-[14px] leading-[1.7] text-md-on-surface-variant">
              {POLICY_HINT}. 추측이 어려운 조합을 권장합니다.
            </p>
          </div>

          {/* 우: 폼 */}
          <div className="w-full max-w-[440px]">
            {session?.user?.email ? (
              <div className="mb-5 flex items-center gap-3 rounded-card border border-md-outline-variant bg-md-surface-container-low px-4 py-3">
                <span
                  className="material-symbols-outlined text-[18px] text-md-on-surface-variant"
                  aria-hidden
                >
                  account_circle
                </span>
                <div className="flex flex-col gap-0.5 text-[13px]">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-md-on-surface-variant">
                    계정
                  </span>
                  <span className="font-medium text-md-on-surface">
                    {session.user.email}
                  </span>
                </div>
              </div>
            ) : null}

            {error ? (
              <div className="mb-4 flex items-start gap-2 border-l-2 border-md-error bg-md-error-container/40 px-3 py-2 text-[13px] text-md-on-error-container">
                <span
                  className="material-symbols-outlined text-[16px]"
                  aria-hidden
                >
                  error
                </span>
                <span>{error}</span>
              </div>
            ) : null}

            <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-4">
              <Field
                label={`새 비밀번호 (${POLICY_HINT})`}
                value={password}
                onChange={setPassword}
                autoFocus
              />
              <Field
                label="비밀번호 확인"
                value={confirm}
                onChange={setConfirm}
              />
              {/* 실시간 일치 피드백 — 이전엔 제출 후에야 불일치를 알 수 있었다 */}
              {confirm.length > 0 ? (
                password === confirm ? (
                  <p className="flex items-center gap-1.5 text-[12.5px] text-md-primary">
                    <span className="material-symbols-outlined text-[15px]" aria-hidden>
                      check_circle
                    </span>
                    비밀번호가 일치합니다
                  </p>
                ) : (
                  <p className="flex items-center gap-1.5 text-[12.5px] text-md-error">
                    <span className="material-symbols-outlined text-[15px]" aria-hidden>
                      error
                    </span>
                    두 비밀번호가 일치하지 않습니다
                  </p>
                )
              ) : null}
              <button
                type="submit"
                disabled={submitting || !password || !confirm || password !== confirm}
                className="theme-cta-bg theme-cta-glow group mt-3 inline-flex h-12 items-center justify-center gap-2 rounded-full px-7 text-[15px] font-semibold text-md-on-primary shadow-sm transition-all duration-200 ease-out hover:scale-[1.02] hover:-translate-y-0.5 active:scale-[0.98] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:scale-100"
              >
                {submitting ? (
                  <>
                    <span
                      className="material-symbols-outlined animate-spin text-[16px]"
                      aria-hidden
                    >
                      progress_activity
                    </span>
                    저장 중…
                  </>
                ) : (
                  "저장"
                )}
              </button>
            </form>
          </div>
        </div>
      </div>

      {/* 하단 footer */}
      <div className="relative z-10 flex items-center justify-between gap-4 px-8 pb-8 sm:px-16 sm:pb-10">
        <p className="text-[11.5px] text-md-on-surface-variant">
          © {new Date().getFullYear()} MEDIREG AI
        </p>
        <p className="text-[11.5px] text-md-on-surface-variant">
          비밀번호는 암호화되어 저장됩니다.
        </p>
      </div>
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoFocus?: boolean;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-[12px] font-semibold uppercase tracking-[0.1em] text-md-on-surface-variant">
        {label}
      </span>
      <input
        type="password"
        required
        autoFocus={autoFocus}
        minLength={MIN_LENGTH}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-12 border-b-2 border-md-outline-variant bg-transparent px-1 py-2 text-[16px] font-medium text-md-on-surface placeholder:font-normal placeholder:text-md-on-surface-variant outline-none transition-colors focus:border-md-primary"
      />
    </label>
  );
}

export default function SetPasswordPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-md-surface">
          <p className="text-body-sm text-md-on-surface-variant">로딩 중…</p>
        </main>
      }
    >
      <SetPasswordInner />
    </Suspense>
  );
}
