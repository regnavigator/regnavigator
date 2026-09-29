"use client";

import { SUPPORT_EMAIL } from "@/lib/site";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { ThemeLogo } from "@/components/shell/ThemeLogo";
import { saveVerifyRequest } from "@/lib/client/verifyRequest";

type Mode = "password" | "email" | "forgot";

const COPY: Record<Mode, { eyebrow: string; heading: string; sub: string; hint: string }> = {
  password: {
    eyebrow: "로그인",
    heading: "다시 오셨네요",
    sub: "이메일과 비밀번호로 접속하세요.",
    hint: "비밀번호를 잊으셨다면 우측에서 재설정할 수 있어요.",
  },
  email: {
    eyebrow: "메일 인증",
    heading: "이메일로 로그인",
    sub: "입력한 주소로 인증 링크를 보냅니다.",
    hint: "링크는 발송 후 10분간 유효합니다.",
  },
  forgot: {
    eyebrow: "비밀번호 재설정",
    heading: "비밀번호 재설정",
    sub: "이메일을 입력하면 재설정 링크를 보냅니다.",
    hint: "요청 즉시 기존 비밀번호는 무효화됩니다. 새 비밀번호는 링크 클릭 후 설정하세요.",
  },
};

function LoginFormInner() {
  const router = useRouter();
  const params = useSearchParams();
  const callbackUrl = params.get("callbackUrl") ?? "/";
  const urlError = params.get("error");
  const { status } = useSession();

  // 이미 로그인된 사용자가 /login 진입 시(landing "시작하기" 등) — 로그인 폼을
  // 보여줄 필요 없이 바로 채팅으로. callbackUrl 있으면 그쪽, 없으면 채팅 홈("/").
  // 사용자 회신 "login 되어있으면 바로 채팅창가야지 왜 로긴창으로 이동시킴".
  useEffect(() => {
    if (status === "authenticated") {
      router.replace(callbackUrl && callbackUrl !== "/" ? callbackUrl : "/");
    }
  }, [status, callbackUrl, router]);

  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSignupCta, setShowSignupCta] = useState(false);

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setShowSignupCta(false);
  }

  async function onSubmitPassword(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setShowSignupCta(false);
    if (!email.trim() || !password) return;
    setSubmitting(true);
    try {
      const res = await signIn("credentials", {
        email: email.trim().toLowerCase(),
        password,
        redirect: false,
        callbackUrl,
      });
      if (res?.error) {
        if (res.error === "LOCKED") {
          setError(
            "비밀번호를 여러 번 잘못 입력해 로그인이 10분간 제한되었습니다. " +
              "잠시 후 다시 시도하거나, 아래 '비밀번호를 잊으셨나요?'에서 재설정해주세요.",
          );
        } else if (res.error === "AccessDenied") {
          // 비밀번호는 맞았는데 signIn 콜백(베타 게이트)이 막은 경우 — 비밀번호 오류로
          // 보이면 사용자가 재설정만 반복한다(2026-09-23). 비밀번호를 아는 본인에게만
          // 보이는 분기라 가입 여부 노출 우려는 없다.
          setError(
            `클로즈 베타 대상이 아닌 이메일입니다. 참여를 원하시면 운영팀(${SUPPORT_EMAIL})에 문의해주세요.`,
          );
        } else {
          setError("이메일 또는 비밀번호가 일치하지 않습니다.");
        }
        return;
      }
      router.replace(res?.url ?? callbackUrl);
    } finally {
      setSubmitting(false);
    }
  }

  async function onSubmitEmail(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setShowSignupCta(false);
    if (!email.trim()) return;
    setSubmitting(true);
    try {
      const normalizedEmail = email.trim().toLowerCase();
      const res = await signIn("email", {
        email: normalizedEmail,
        callbackUrl,
        redirect: false,
      });
      if (res?.error) {
        setError("등록되지 않은 이메일이거나 발송에 실패했습니다.");
        setShowSignupCta(true);
        return;
      }
      // verify 페이지가 보낸 주소 표시 + 재발송할 수 있게 기록
      saveVerifyRequest(normalizedEmail, callbackUrl);
      router.push(res?.url ?? "/auth/verify");
    } finally {
      setSubmitting(false);
    }
  }

  async function onSubmitForgot(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setShowSignupCta(false);
    const normalized = email.trim().toLowerCase();
    if (!normalized) return;
    setSubmitting(true);
    try {
      // 매직링크만 보낸다 — 링크를 눌러 본인임이 확인된 세션에서 새 비밀번호를 정한다.
      // 종전엔 요청 즉시 기존 비밀번호를 지워(/api/auth/forgot-password), 이메일만 알면
      // 누구든 남의 비밀번호를 무효화할 수 있었다(2026-09-23 제거). 기존 비밀번호는
      // 새 비밀번호를 정할 때까지 그대로 유효하다.
      //    가입 안 된 이메일이면 sendVerificationRequest 가드가 throw → res.error 반환.
      const signInRes = await signIn("email", {
        email: normalized,
        callbackUrl: "/auth/set-password?reset=1",
        redirect: false,
      });
      if (signInRes?.error) {
        setError("등록되지 않은 이메일이거나 발송에 실패했습니다.");
        setShowSignupCta(true);
        return;
      }
      saveVerifyRequest(normalized, "/auth/set-password?reset=1");
      router.push(signInRes?.url ?? "/auth/verify");
    } finally {
      setSubmitting(false);
    }
  }

  const errorMessage =
    error ??
    (urlError === "EmailSignin"
      ? "메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요."
      : urlError === "Verification"
        ? "링크가 만료되었거나 이미 사용되었습니다. 다시 요청해주세요."
        : urlError === "CredentialsSignin"
          ? "이메일 또는 비밀번호가 일치하지 않습니다."
          : urlError
            ? "로그인 중 오류가 발생했습니다."
            : null);

  const copy = COPY[mode];

  // 인증 확정 → 위 effect가 redirect 중. 로그인 폼 대신 짧은 로딩(깜빡임 차단).
  if (status === "authenticated") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-md-surface text-md-on-surface">
        <p className="flex items-center gap-2 text-body-sm text-md-on-surface-variant">
          <span
            className="material-symbols-outlined animate-spin text-[18px]"
            aria-hidden
          >
            progress_activity
          </span>
          채팅으로 이동 중…
        </p>
      </main>
    );
  }

  return (
    <main className="relative flex min-h-screen flex-col overflow-hidden bg-md-surface text-md-on-surface">
      {/* 배경 dot grid + blob */}
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

      {/* 좌상단 로고 — 비로그인 사용자라 회원가입으로 */}
      <div className="relative z-10 px-8 pt-8 sm:px-16 sm:pt-12">
        <Link
          href="/signup"
          aria-label="회원가입으로"
          className="inline-flex items-center gap-3 transition-opacity hover:opacity-80"
        >
          <ThemeLogo className="h-9 w-auto" />
          <span className="text-[12.5px] uppercase tracking-[0.1em] text-md-on-surface-variant">
            의료·규제 AI
          </span>
        </Link>
      </div>

      {/* 본문 — 가운데 정렬 + 2-column (lg 이상) */}
      <div className="relative z-10 flex flex-1 items-center justify-center px-8 sm:px-16">
        <div className="grid w-full max-w-[1100px] grid-cols-1 items-center gap-12 lg:grid-cols-[1.1fr_1fr] lg:gap-20">
          {/* 좌: 헤딩 + 카피 */}
          <div className="w-full max-w-[560px]">
            <span className="text-[15px] font-semibold uppercase tracking-[0.12em] text-md-primary">
              {copy.eyebrow}
            </span>
            <h1
              className="mt-4 text-[64px] font-bold leading-[1.05] tracking-tight text-md-on-surface sm:text-[88px]"
              style={{
                fontFamily: "'Sora', 'Pretendard Variable', sans-serif",
                letterSpacing: "-0.03em",
              }}
            >
              <span className="theme-grad-text">{copy.heading}</span>
            </h1>
            <p className="mt-7 text-[17px] leading-[1.75] text-md-on-surface">
              {copy.sub}
            </p>
            <p className="mt-2 text-[14px] leading-[1.7] text-md-on-surface-variant">
              {copy.hint}
            </p>
          </div>

          {/* 우: 폼 */}
          <div className="w-full max-w-[420px]">
            {/* 클로즈 베타 안내 — 초대된 이메일만 이용 가능 (백엔드 403 detail도
                로그인 실패 시 그대로 노출됨). */}
            <div className="mb-4 flex items-start gap-2 border-l-2 border-md-primary bg-md-surface-container-low px-3 py-2.5 text-[13px] leading-relaxed text-md-on-surface-variant">
              <span
                className="material-symbols-outlined text-[16px] text-md-primary"
                aria-hidden
              >
                campaign
              </span>
              <span>
                지금은{" "}
                <span className="font-semibold text-md-on-surface">
                  클로즈 베타
                </span>{" "}
                기간입니다. 초대된 이메일만 이용할 수 있어요. 참여·계정 문의는{" "}
                <a
                  href={`mailto:${SUPPORT_EMAIL}`}
                  className="font-medium text-md-primary hover:underline"
                >
                  {SUPPORT_EMAIL}
                </a>
                으로 보내주세요.
              </span>
            </div>
            {errorMessage ? (
              <div className="mb-4 flex flex-col gap-2 border-l-2 border-md-error bg-md-error-container/40 px-3 py-2 text-[13px] text-md-on-error-container">
                <div className="flex items-start gap-2">
                  <span
                    className="material-symbols-outlined text-[16px]"
                    aria-hidden
                  >
                    error
                  </span>
                  <span>{errorMessage}</span>
                </div>
                {showSignupCta ? (
                  <Link
                    href="/signup"
                    className="ml-6 inline-flex w-fit items-center gap-1 text-[12.5px] font-medium text-md-primary hover:underline"
                  >
                    회원가입하기
                    <span
                      className="material-symbols-outlined text-[14px]"
                      aria-hidden
                    >
                      arrow_forward
                    </span>
                  </Link>
                ) : null}
              </div>
            ) : null}

            {mode === "password" ? (
              <form
                onSubmit={(e) => void onSubmitPassword(e)}
                className="flex flex-col gap-4"
              >
                <Field
                  label="이메일"
                  type="email"
                  value={email}
                  onChange={setEmail}
                  placeholder="you@example.com"
                  autoFocus
                />
                <Field
                  label="비밀번호"
                  type="password"
                  value={password}
                  onChange={setPassword}
                />
                <PrimaryButton
                  type="submit"
                  loading={submitting}
                  loadingLabel="로그인 중…"
                  disabled={!email.trim() || !password}
                >
                  로그인
                </PrimaryButton>
              </form>
            ) : mode === "email" ? (
              <form
                onSubmit={(e) => void onSubmitEmail(e)}
                className="flex flex-col gap-4"
              >
                <Field
                  label="이메일"
                  type="email"
                  value={email}
                  onChange={setEmail}
                  placeholder="you@example.com"
                  autoFocus
                />
                <PrimaryButton
                  type="submit"
                  loading={submitting}
                  loadingLabel="발송 중…"
                  disabled={!email.trim()}
                  icon="mail"
                >
                  인증 링크 받기
                </PrimaryButton>
              </form>
            ) : (
              <form
                onSubmit={(e) => void onSubmitForgot(e)}
                className="flex flex-col gap-4"
              >
                <Field
                  label="이메일"
                  type="email"
                  value={email}
                  onChange={setEmail}
                  placeholder="you@example.com"
                  autoFocus
                />
                <PrimaryButton
                  type="submit"
                  loading={submitting}
                  loadingLabel="재설정 중…"
                  disabled={!email.trim()}
                  icon="lock_reset"
                >
                  비밀번호 재설정 메일 받기
                </PrimaryButton>
              </form>
            )}

            {/* 모드 전환 링크 */}
            <div className="mt-6 flex flex-col gap-3 border-t border-md-outline-variant pt-4 text-[13px] text-md-on-surface-variant">
              {mode === "password" ? (
                <>
                  <button
                    type="button"
                    onClick={() => switchMode("forgot")}
                    className="group inline-flex items-center gap-1.5 transition-all hover:gap-2 hover:text-md-primary"
                  >
                    <span>비밀번호를 잊으셨나요?</span>
                    <span
                      className="material-symbols-outlined text-[14px] transition-transform group-hover:translate-x-0.5"
                      aria-hidden
                    >
                      arrow_forward
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => switchMode("email")}
                    className="group inline-flex items-center gap-1.5 transition-all hover:gap-2 hover:text-md-primary"
                  >
                    <span>비밀번호 없이 이메일로 로그인</span>
                    <span
                      className="material-symbols-outlined text-[14px] transition-transform group-hover:translate-x-0.5"
                      aria-hidden
                    >
                      arrow_forward
                    </span>
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => switchMode("password")}
                  className="group inline-flex items-center gap-1.5 transition-all hover:gap-2 hover:text-md-primary"
                >
                  <span
                    className="material-symbols-outlined text-[14px] transition-transform group-hover:-translate-x-0.5"
                    aria-hidden
                  >
                    arrow_back
                  </span>
                  <span>비밀번호로 로그인</span>
                </button>
              )}
              <Link
                href="/signup"
                className="group inline-flex items-center gap-1.5 transition-all hover:gap-2 hover:text-md-primary"
              >
                <span>처음이신가요? 회원가입</span>
                <span
                  className="material-symbols-outlined text-[14px] transition-transform group-hover:translate-x-0.5"
                  aria-hidden
                >
                  arrow_forward
                </span>
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* 하단 footer */}
      <div className="relative z-10 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-8 pb-8 sm:px-16 sm:pb-10">
        <p className="text-[11.5px] text-md-on-surface-variant">
          © {new Date().getFullYear()} MEDIREG AI · 답변은 참고용, 적용 전 전문가 검토를 권장합니다.
        </p>
        <nav className="flex items-center gap-4 text-[11.5px] text-md-on-surface-variant">
          <Link href="/terms" className="hover:text-md-on-surface">
            이용약관
          </Link>
          <Link href="/privacy" className="hover:text-md-on-surface">
            개인정보처리방침
          </Link>
          <a
            href={`mailto:${SUPPORT_EMAIL}`}
            className="hover:text-md-on-surface"
          >
            문의
          </a>
        </nav>
      </div>
    </main>
  );
}

function Field({
  label,
  type,
  value,
  onChange,
  placeholder,
  autoFocus,
}: {
  label: string;
  type: "email" | "password";
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-[12px] font-semibold uppercase tracking-[0.1em] text-md-on-surface-variant">
        {label}
      </span>
      <input
        type={type}
        required
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-12 border-b-2 border-md-outline-variant bg-transparent px-1 py-2 text-[16px] font-medium text-md-on-surface placeholder:font-normal placeholder:text-md-on-surface-variant outline-none transition-colors focus:border-md-primary"
      />
    </label>
  );
}

function PrimaryButton({
  type,
  loading,
  loadingLabel,
  disabled,
  icon,
  children,
}: {
  type: "submit" | "button";
  loading?: boolean;
  loadingLabel?: string;
  disabled?: boolean;
  icon?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type={type}
      disabled={loading || disabled}
      className="theme-cta-bg theme-cta-glow group mt-3 inline-flex h-12 items-center justify-center gap-2 rounded-full px-7 text-[15px] font-semibold text-md-on-primary shadow-sm transition-all duration-200 ease-out hover:scale-[1.02] hover:-translate-y-0.5 active:scale-[0.98] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:scale-100 disabled:hover:shadow-sm"
    >
      {loading ? (
        <>
          <span
            className="material-symbols-outlined animate-spin text-[16px]"
            aria-hidden
          >
            progress_activity
          </span>
          {loadingLabel ?? "처리 중…"}
        </>
      ) : (
        <>
          {icon ? (
            <span
              className="material-symbols-outlined text-[16px]"
              aria-hidden
            >
              {icon}
            </span>
          ) : null}
          {children}
        </>
      )}
    </button>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-md-surface text-md-on-surface">
          <p className="text-body-sm text-md-on-surface-variant">로딩 중…</p>
        </main>
      }
    >
      <LoginFormInner />
    </Suspense>
  );
}
