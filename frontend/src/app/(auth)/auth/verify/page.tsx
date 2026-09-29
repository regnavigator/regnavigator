"use client";

/**
 * /auth/verify — 매직링크 발송 완료 안내.
 *
 * 발송 지점(signup·login·forgot)이 sessionStorage `medi-front-verify-request`에
 * `{email, callbackUrl}`을 남긴다 → 본 페이지가 (1) **어느 주소로 보냈는지 표시**
 * (오타 확인 가능), (2) **실제 재발송 버튼**(30초 쿨다운) 제공.
 * 이전엔 "다른 주소로 다시 보내기" 버튼이 재발송이 아니라 /login 이동이라
 * 레이블과 동작이 어긋났고, 보낸 주소도 표시되지 않았다.
 *
 * draft가 없으면(새 탭·직접 진입) 재발송 대신 로그인으로 안내.
 */

import { MAIL_FROM_DEFAULT, SUPPORT_EMAIL } from "@/lib/site";
import { useEffect, useState } from "react";
import Link from "next/link";
import { signIn } from "next-auth/react";
import { ThemeLogo } from "@/components/shell/ThemeLogo";
import {
  readVerifyRequest,
  type VerifyRequest,
} from "@/lib/client/verifyRequest";

const RESEND_COOLDOWN_SEC = 30;

export default function VerifyRequestPage() {
  const [req, setReq] = useState<VerifyRequest | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    setReq(readVerifyRequest());
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = window.setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => window.clearTimeout(t);
  }, [cooldown]);

  async function resend() {
    if (!req?.email || sending || cooldown > 0) return;
    setSending(true);
    setNotice(null);
    try {
      const res = await signIn("email", {
        email: req.email,
        callbackUrl: req.callbackUrl ?? "/",
        redirect: false,
      });
      if (res?.error) {
        setNotice("재발송에 실패했습니다. 잠시 후 다시 시도해주세요.");
      } else {
        setNotice("인증 메일을 다시 보냈습니다. 메일함을 확인해주세요.");
        setCooldown(RESEND_COOLDOWN_SEC);
      }
    } catch {
      setNotice("재발송에 실패했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="relative flex min-h-screen flex-col overflow-hidden bg-md-surface text-md-on-surface">
      {/* 배경 dot grid (radial mask로 중앙 강조 가장자리 페이드) */}
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

      {/* 그라데이션 blob */}
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
          className="inline-flex items-center gap-3 text-md-on-surface transition-opacity hover:opacity-80"
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
          {/* 좌: 헤딩 + 카피 + CTA */}
          <div className="w-full max-w-[600px]">
            <span className="text-[15px] font-semibold uppercase tracking-[0.12em] text-md-primary">
              메일 발송 완료
            </span>

            <h1
              className="mt-4 text-[52px] font-bold leading-[1.05] tracking-tight text-md-on-surface sm:text-[80px]"
              style={{
                fontFamily: "'Sora', 'Pretendard Variable', sans-serif",
                letterSpacing: "-0.03em",
              }}
            >
              <span className="theme-grad-text">메일함을 확인하세요</span>
            </h1>

            <p className="mt-7 text-[17px] leading-[1.75] text-md-on-surface">
              {req?.email ? (
                <>
                  <strong className="font-semibold">{req.email}</strong> 주소로
                  로그인 링크를 보냈습니다. 링크를 클릭하면 자동으로 로그인됩니다.
                </>
              ) : (
                <>입력한 주소로 로그인 링크를 보냈습니다. 링크를 클릭하면 자동으로 로그인됩니다.</>
              )}
            </p>
            <p className="mt-2 text-[14px] leading-[1.7] text-md-on-surface-variant">
              메일이 보이지 않으면 스팸함을 확인하거나, 아래에서 다시 발송하세요.
              링크는 발송 후 10분간 유효하며 한 번만 사용할 수 있습니다. 계속
              문제가 있으면{" "}
              <a
                href={`mailto:${SUPPORT_EMAIL}`}
                className="font-medium text-md-primary hover:underline"
              >
                {SUPPORT_EMAIL}
              </a>
              으로 문의해주세요.
            </p>

            {notice ? (
              <p
                role="status"
                className="mt-4 border-l-2 border-md-primary bg-md-surface-container-low px-3 py-2 text-[13px] text-md-on-surface"
              >
                {notice}
              </p>
            ) : null}

            <div className="mt-8 flex flex-wrap items-center gap-4">
              {req?.email ? (
                <button
                  type="button"
                  onClick={() => void resend()}
                  disabled={sending || cooldown > 0}
                  className="theme-cta-bg theme-cta-glow inline-flex h-12 items-center justify-center gap-2 rounded-full px-7 text-[15px] font-semibold text-md-on-primary shadow-sm transition-all duration-200 ease-out hover:scale-[1.02] hover:-translate-y-0.5 active:scale-[0.98] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:scale-100"
                >
                  <span
                    className={
                      "material-symbols-outlined text-[16px] " +
                      (sending ? "animate-spin" : "")
                    }
                    aria-hidden
                  >
                    {sending ? "progress_activity" : "forward_to_inbox"}
                  </span>
                  {cooldown > 0 ? `다시 보내기 (${cooldown}초)` : "메일 다시 보내기"}
                </button>
              ) : null}
              <Link
                href="/login"
                className="inline-flex h-12 items-center justify-center gap-2 rounded-full border border-md-outline-variant px-6 text-[14px] font-medium text-md-on-surface transition-colors hover:bg-md-surface-container-low"
              >
                다른 주소로 로그인하기
              </Link>
            </div>
          </div>

          {/* 우: 정보 카드 stack — 모바일에서도 노출(축약형은 위 본문에 포함돼
              있으나, 발신 주소·문의처는 여기서만 확인 가능). */}
          <aside className="flex flex-col gap-7">
            <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-md-on-surface-variant">
              링크 정보
            </span>
            <InfoRow
              icon="schedule"
              label="유효 시간"
              value="10분"
              hint="발송 후 10분 안에 클릭"
            />
            <InfoRow
              icon="lock"
              label="보안"
              value="일회용 링크"
              hint="한 번 사용하면 만료"
            />
            <InfoRow
              icon="alternate_email"
              label="발신 주소"
              value={MAIL_FROM_DEFAULT}
              hint={`문의는 ${SUPPORT_EMAIL}`}
            />
          </aside>
        </div>
      </div>

      {/* 하단 footer */}
      <div className="relative z-10 flex items-center justify-between gap-4 px-8 pb-8 sm:px-16 sm:pb-10">
        <p className="text-[11.5px] text-md-on-surface-variant">
          © {new Date().getFullYear()} MEDIREG AI
        </p>
        <p className="text-[11.5px] text-md-on-surface-variant">
          이메일은 본인 인증·로그인 용으로만 사용됩니다.
        </p>
      </div>
    </main>
  );
}

function InfoRow({
  icon,
  label,
  value,
  hint,
}: {
  icon: string;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="group flex items-start gap-4 border-l-2 border-md-outline-variant pl-5 transition-all hover:border-md-primary hover:pl-6">
      <span
        className="material-symbols-outlined mt-0.5 text-[22px] text-md-on-surface-variant transition-colors group-hover:text-md-primary"
        aria-hidden
      >
        {icon}
      </span>
      <div className="flex flex-col gap-1">
        <span className="text-[11.5px] font-semibold uppercase tracking-[0.1em] text-md-on-surface-variant">
          {label}
        </span>
        <span className="text-[16px] font-semibold leading-tight text-md-on-surface">
          {value}
        </span>
        <span className="text-[12.5px] leading-relaxed text-md-on-surface-variant">{hint}</span>
      </div>
    </div>
  );
}
