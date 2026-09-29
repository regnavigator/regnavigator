"use client";

/**
 * 회원가입 — 첫 가입 시 직업/소속 같은 부가 정보 수집.
 *
 * 흐름 (2026-08-11 현행):
 *  1) 폼 제출 → **localStorage**에 profile draft 저장 (email/name/job/organization
 *     + agreed_*). ⚠️ sessionStorage 금지 — 탭 격리라 매직링크를 *다른 탭/메일앱*
 *     에서 열면 draft가 없는 탭에서 인증이 완료돼 부가정보가 유실된다(실사고).
 *  2) NextAuth Email Provider signIn — 인증 메일 발송
 *  3) 로그인 완료 후 ProfileInit(루트 레이아웃)이 draft를 읽어 backend
 *     `PUT /me/profile`로 영속, ConsentGate가 agreed_*를 `POST /me/consent`로 영속.
 */

import { SUPPORT_EMAIL } from "@/lib/site";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signIn, useSession } from "next-auth/react";
import { ThemeLogo } from "@/components/shell/ThemeLogo";
import { saveVerifyRequest } from "@/lib/client/verifyRequest";

const JOBS = ["의사", "약사", "간호사", "교수", "연구원", "기타"];

const ORGS = [
  "전남대학교병원",
  "화순전남대학교병원",
  "전남대학교의생명연구원",
  "화순전남대학교병원의생명연구원",
  "기타(직접입력)",
];

function SignupFormInner() {
  const router = useRouter();
  const { status } = useSession();

  // 이미 로그인된 사용자가 /signup 진입 시 — 가입 폼을 보여줄 이유가 없다.
  // /login 의 동일 가드와 짝. 랜딩 CTA 는 세션을 보고 애초에 "/" 로 보내지만,
  // 메일 CTA·북마크·직접 URL 같은 다른 진입점의 안전망.
  useEffect(() => {
    if (status === "authenticated") router.replace("/");
  }, [status, router]);

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [job, setJob] = useState("");
  const [organization, setOrganization] = useState("");
  const [orgEtc, setOrgEtc] = useState(""); // 소속 '기타(직접입력)' 선택 시
  // 필수 동의 2종(약관·개인정보 / 국외 이전) + 선택(마케팅). 국외 이전은 LLM
  //   해외 위탁 시 PIPA §28의8상 *별도 동의*가 필요해 분리.
  const [agreedTerms, setAgreedTerms] = useState(false);
  const [agreedTransfer, setAgreedTransfer] = useState(false);
  const [agreedMarketing, setAgreedMarketing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allRequiredAgreed = agreedTerms && agreedTransfer;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim()) return;
    if (!allRequiredAgreed) {
      setError("필수 동의 항목(이용약관·개인정보, 국외 이전)에 동의해주세요.");
      return;
    }
    setSubmitting(true);
    try {
      const normalized = email.trim().toLowerCase();
      const trimmedName = name.trim();

      // profile draft — ProfileInit이 로그인 직후 읽어 PUT /me/profile로 영속.
      // agreed_* 는 ConsentGate가 로그인 직후 읽어 서버(POST /me/consent)에
      // 자동 영속한다 — 체크박스를 화면에서만 받고 버리면 동의를 입증할 수 없다.
      // localStorage인 이유: 매직링크가 다른 탭에서 열려도 살아남아야 함(위 주석).
      try {
        localStorage.setItem(
          "medi-front-signup-draft",
          JSON.stringify({
            email: normalized,
            name: trimmedName,
            job,
            organization:
              organization === "기타(직접입력)"
                ? orgEtc.trim()
                : organization,
            agreed_terms: agreedTerms,
            agreed_transfer: agreedTransfer,
            marketing_opt_in: agreedMarketing,
            ts: Date.now(),
          }),
        );
      } catch {
        // private browsing 등 — 무시
      }

      // 1) user 사전 upsert — sendVerificationRequest의 *가입 가드*가 user 존재를
      //    요구하기 때문. signup-init 통과 후에야 매직링크 발송 허용.
      //    베타 게이트 차단도 여기서 명시 에러로 응답.
      const initRes = await fetch("/api/auth/signup-init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: normalized, name: trimmedName }),
      });
      if (!initRes.ok) {
        const body = (await initRes.json().catch(() => null)) as { error?: string } | null;
        setError(
          body?.error ??
            "가입 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        );
        return;
      }

      // 2) 매직링크 발송 — 클릭 시 /auth/set-password 진입(hasPassword=false라 그곳에 머무름)
      const res = await signIn("email", {
        email: normalized,
        callbackUrl: "/auth/set-password",
        redirect: false,
      });
      if (res?.error) {
        setError("메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.");
        return;
      }
      // verify 페이지가 보낸 주소 표시 + 재발송할 수 있게 기록
      saveVerifyRequest(normalized, "/auth/set-password");
      window.location.href = "/auth/verify";
    } catch (err) {
      console.error("[signup] failed", err);
      setError("가입 처리 중 오류가 발생했습니다.");
    } finally {
      setSubmitting(false);
    }
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

      {/* 좌상단 로고 — signup 페이지에선 로그인 화면으로 */}
      <div className="relative z-10 px-8 pt-8 sm:px-16 sm:pt-12">
        <Link
          href="/login"
          aria-label="로그인으로"
          className="inline-flex items-center gap-3 transition-opacity hover:opacity-80"
        >
          <ThemeLogo className="h-9 w-auto" />
          <span className="text-[12.5px] uppercase tracking-[0.1em] text-md-on-surface-variant">
            의료·규제 AI
          </span>
        </Link>
      </div>

      {/* 본문 — 가운데 정렬 + 2-column */}
      <div className="relative z-10 flex flex-1 items-center justify-center px-8 sm:px-16">
        <div className="grid w-full max-w-[1100px] grid-cols-1 items-center gap-12 lg:grid-cols-[1.1fr_1fr] lg:gap-20">
          {/* 좌: 헤딩 + 카피 */}
          <div className="w-full max-w-[560px]">
            <span className="text-[15px] font-semibold uppercase tracking-[0.12em] text-md-primary">
              회원가입
            </span>
            <h1
              className="mt-4 text-[64px] font-bold leading-[1.05] tracking-tight text-md-on-surface sm:text-[88px]"
              style={{
                fontFamily: "'Sora', 'Pretendard Variable', sans-serif",
                letterSpacing: "-0.03em",
              }}
            >
              <span className="theme-grad-text">계정 만들기</span>
            </h1>
            <p className="mt-7 text-[17px] leading-[1.75] text-md-on-surface">
              이메일 인증 후 비밀번호를 설정하면 완료됩니다.
            </p>
            <p className="mt-2 text-[14px] leading-[1.7] text-md-on-surface-variant">
              직업·소속은 선택 입력입니다.
            </p>
          </div>

          {/* 우: 폼 */}
          <div className="w-full max-w-[440px]">
            {/* 클로즈 베타 안내 — 초대된 이메일만 가입 가능 (signup-init의 베타
                게이트 차단 에러는 아래 error 박스에 그대로 노출됨). */}
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
            <form
              onSubmit={(e) => void onSubmit(e)}
              className="flex flex-col gap-4"
            >
              <Field
                label="이메일"
                type="email"
                value={email}
                onChange={setEmail}
                placeholder="you@example.com"
                required
                autoFocus
              />
              <Field
                label="이름"
                type="text"
                value={name}
                onChange={setName}
                placeholder="홍길동"
              />
              <SelectField
                label="직업"
                value={job}
                onChange={setJob}
                options={JOBS}
                placeholder="선택해주세요"
              />
              <SelectField
                label="소속"
                value={organization}
                onChange={setOrganization}
                options={ORGS}
                placeholder="선택해주세요"
              />
              {organization === "기타(직접입력)" ? (
                <Field
                  label="소속 직접 입력"
                  type="text"
                  value={orgEtc}
                  onChange={setOrgEtc}
                  placeholder="소속 기관명"
                />
              ) : null}

              {/* 동의 — 필수 2종(약관·개인정보 / 국외 이전) + 선택(마케팅).
                  필수 미동의 시 가입 버튼 비활성. 민감정보 입력 금지 안내 동반. */}
              <div className="mt-1 flex flex-col gap-2.5 border-t border-md-outline-variant pt-4">
                <label className="flex cursor-pointer items-start gap-2.5 text-[13px] leading-relaxed text-md-on-surface-variant">
                  <input
                    type="checkbox"
                    checked={agreedTerms}
                    onChange={(e) => setAgreedTerms(e.target.checked)}
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

                <label className="flex cursor-pointer items-start gap-2.5 text-[13px] leading-relaxed text-md-on-surface-variant">
                  <input
                    type="checkbox"
                    checked={agreedTransfer}
                    onChange={(e) => setAgreedTransfer(e.target.checked)}
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
                    에 동의합니다. AI 답변 생성을 위해 질의 내용이 국외 사업자에게
                    전송될 수 있습니다.
                  </span>
                </label>

                <label className="flex cursor-pointer items-start gap-2.5 text-[13px] leading-relaxed text-md-on-surface-variant">
                  <input
                    type="checkbox"
                    checked={agreedMarketing}
                    onChange={(e) => setAgreedMarketing(e.target.checked)}
                    className="mt-0.5 size-4 shrink-0 accent-md-primary"
                  />
                  <span>
                    <span className="text-md-on-surface-variant">[선택]</span>{" "}
                    제품 정보·업데이트 등의 수신에 동의합니다.
                  </span>
                </label>

                <p className="mt-0.5 flex items-start gap-1.5 text-[12px] leading-relaxed text-md-on-surface-variant">
                  <span
                    className="material-symbols-outlined mt-px text-[14px]"
                    aria-hidden
                  >
                    info
                  </span>
                  건강정보·진단명·처방 등 민감정보는 입력하지 마세요. 본 서비스는
                  개별 환자 상담을 제공하지 않습니다.
                </p>
              </div>

              <button
                type="submit"
                disabled={submitting || !email.trim() || !allRequiredAgreed}
                className="theme-cta-bg theme-cta-glow group mt-3 inline-flex h-12 items-center justify-center gap-2 rounded-full px-7 text-[15px] font-semibold text-md-on-primary shadow-sm transition-all duration-200 ease-out hover:scale-[1.02] hover:-translate-y-0.5 active:scale-[0.98] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:scale-100 disabled:hover:shadow-sm"
              >
                {submitting ? (
                  <>
                    <span
                      className="material-symbols-outlined animate-spin text-[16px]"
                      aria-hidden
                    >
                      progress_activity
                    </span>
                    발송 중…
                  </>
                ) : (
                  <>
                    <span
                      className="material-symbols-outlined text-[16px]"
                      aria-hidden
                    >
                      mail
                    </span>
                    인증 링크 받기
                  </>
                )}
              </button>
            </form>

            <div className="mt-6 border-t border-md-outline-variant pt-4 text-[13px] text-md-on-surface-variant">
              이미 계정이 있나요?{" "}
              <Link
                href="/login"
                className="font-medium text-md-primary transition-colors hover:text-md-primary-container"
              >
                로그인하기 →
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* 하단 footer */}
      <div className="relative z-10 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-8 pb-8 sm:px-16 sm:pb-10">
        <p className="text-[11.5px] text-md-on-surface-variant">
          © {new Date().getFullYear()} MEDIREG AI · 이메일은 본인 인증·로그인 용으로만 사용됩니다.
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
  required,
  autoFocus,
}: {
  label: string;
  type: "email" | "text";
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  autoFocus?: boolean;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-[12px] font-semibold uppercase tracking-[0.1em] text-md-on-surface-variant">
        {label}
        {required ? "" : <span className="ml-1 normal-case text-md-on-surface-variant opacity-60"> · 선택</span>}
      </span>
      <input
        type={type}
        required={required}
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-12 border-b-2 border-md-outline-variant bg-transparent px-1 py-2 text-[16px] font-medium text-md-on-surface placeholder:font-normal placeholder:text-md-on-surface-variant outline-none transition-colors focus:border-md-primary"
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  placeholder?: string;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-[12px] font-semibold uppercase tracking-[0.1em] text-md-on-surface-variant">
        {label}
        <span className="ml-1 normal-case text-md-on-surface-variant opacity-60"> · 선택</span>
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-12 border-b-2 border-md-outline-variant bg-transparent px-1 py-2 text-[16px] font-medium text-md-on-surface outline-none transition-colors focus:border-md-primary"
      >
        <option value="">{placeholder ?? "선택"}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function SignupPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-md-surface text-md-on-surface">
          <p className="text-body-sm text-md-on-surface-variant">로딩 중…</p>
        </main>
      }
    >
      <SignupFormInner />
    </Suspense>
  );
}
