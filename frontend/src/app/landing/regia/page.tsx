/**
 * Regia Landing — Stripe-inspired 모던 SaaS 톤.
 * 흰 배경 + 인디고/블루/시안 그라데이션 + Pretendard.
 * 출처: regia_landing_page.html
 *
 * data-theme="regia" 박혀 토큰 자동 swap.
 */

import Link from "next/link";

export const metadata = {
  title: "Regia · 의료규제 AI 어시스턴트",
};

const FEATURES = [
  {
    icon: "menu_book",
    title: "법령 벡터 검색",
    desc: "의료법·약사법·의료기기법 등 규제 코퍼스를 임베딩으로 의미 검색.",
  },
  {
    icon: "public",
    title: "웹·판례 통합",
    desc: "최신 판례·고시 변경·해석례를 실시간 보강. 출처와 시행일 명시.",
  },
  {
    icon: "summarize",
    title: "심층 보고서",
    desc: "백그라운드에서 법령·웹·종합 3편의 심층 보고서를 자동 작성.",
  },
  {
    icon: "verified",
    title: "인용 검증",
    desc: "모든 답변은 [n] 마커로 출처 매핑. RAG 자동 verify.",
  },
];

const STATS = [
  { num: "42%", lbl: "검색 시간 절감" },
  { num: "3편", lbl: "심층 보고서/세션" },
  { num: "10초", lbl: "평균 응답" },
];

export default function RegiaLandingPage() {
  return (
    <main
      data-theme="regia"
      className="relative min-h-screen bg-md-surface text-md-on-surface"
    >
      {/* hero stripe gradient bg */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-screen"
        style={{
          background:
            "linear-gradient(160deg, #f8f7ff 0%, #eff6ff 50%, #f0fffe 100%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 -right-32 h-[700px] w-[700px] rounded-full"
        style={{
          background:
            "radial-gradient(circle, rgba(99,102,241,0.12) 0%, rgba(59,130,246,0.06) 40%, transparent 70%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-24 -left-20 h-[500px] w-[500px] rounded-full"
        style={{
          background:
            "radial-gradient(circle, rgba(6,182,212,0.10) 0%, rgba(59,130,246,0.05) 40%, transparent 70%)",
        }}
      />

      {/* nav */}
      <nav className="sticky top-0 z-50 flex h-16 items-center justify-between border-b border-md-outline-variant bg-md-surface/80 px-8 backdrop-blur-md sm:px-16">
        <Link
          href="/landing"
          className="inline-flex items-center gap-2 text-md-on-surface"
        >
          <span
            className="material-symbols-outlined text-[22px]"
            style={{
              background: "linear-gradient(135deg, #6366F1, #06B6D4)",
              WebkitBackgroundClip: "text",
              backgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
            aria-hidden
          >
            gavel
          </span>
          <span className="text-[18px] font-black tracking-tight">
            <span className="theme-grad-text">Regia</span>
          </span>
        </Link>
        <Link
          href="/login"
          className="theme-cta-bg theme-cta-glow inline-flex h-9 items-center rounded-[8px] px-5 text-[13.5px] font-bold text-white shadow-[0_2px_12px_rgba(99,102,241,0.35)] transition-all hover:-translate-y-px"
        >
          베타 시작하기
        </Link>
      </nav>

      {/* hero */}
      <section className="relative mx-auto grid max-w-[1180px] grid-cols-1 items-center gap-16 px-10 py-32 lg:grid-cols-2">
        <div>
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-md-primary-fixed-dim bg-md-primary-fixed px-3.5 py-1.5">
            <span
              className="size-1.5 rounded-full animate-md-pulse"
              style={{ background: "#6366F1" }}
              aria-hidden
            />
            <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-md-primary-container">
              Closed Beta · 2026
            </span>
          </div>
          <h1
            className="text-[58px] font-black leading-[1.1]"
            style={{ letterSpacing: "-0.035em" }}
          >
            의료규제,
            <br />
            <em className="not-italic theme-grad-text">놓치는 것 없이</em>
            <br />
            파악하세요
          </h1>
          <p className="mt-6 max-w-[480px] text-[18px] leading-[1.75] text-md-on-surface-variant">
            법령·고시·해석·판례를 <strong className="font-bold text-md-on-surface">벡터 DB</strong>와{" "}
            <strong className="font-bold text-md-on-surface">웹·판례 통합</strong>으로 검색하고,
            인용을 명시한 답변과 심층 보고서를 자동으로 작성합니다.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-4">
            <Link
              href="/login"
              className="theme-cta-bg theme-cta-glow inline-flex h-14 items-center gap-2 rounded-[10px] px-8 text-[16px] font-extrabold text-white transition-all hover:-translate-y-0.5"
            >
              베타 시작하기 →
            </Link>
            <a
              href="#features"
              className="inline-flex h-14 items-center rounded-[10px] border-[1.5px] border-md-outline-variant bg-md-surface/80 px-7 text-[15px] font-semibold text-md-on-surface-variant transition-all hover:border-md-primary-fixed-dim hover:text-md-primary-container"
            >
              기능 살펴보기
            </a>
          </div>
        </div>

        {/* demo card */}
        <div className="rounded-[18px] border border-md-outline-variant bg-md-surface p-7 shadow-[0_8px_40px_rgba(15,23,41,0.11)]">
          <div className="mb-4 flex items-center gap-2 text-[12.5px] text-md-on-surface-variant">
            <span className="size-2.5 rounded-full bg-md-error" aria-hidden />
            <span className="size-2.5 rounded-full bg-md-tertiary" aria-hidden />
            <span className="size-2.5 rounded-full bg-md-primary" aria-hidden />
            <span className="ml-auto font-mono">medra · session</span>
          </div>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {["광고심의", "비대면진료", "임상시험", "신의료기술"].map((t) => (
              <span
                key={t}
                className="rounded-full border border-md-primary-fixed-dim bg-md-primary-fixed px-3 py-1 text-[11.5px] font-semibold text-md-primary-container"
              >
                {t}
              </span>
            ))}
          </div>
          <div
            className="ml-auto inline-block rounded-[10px_10px_2px_10px] px-3.5 py-2.5 text-[13.5px] text-white shadow-[0_2px_10px_rgba(99,102,241,0.25)]"
            style={{
              background:
                "linear-gradient(135deg, #6366F1 0%, #3B82F6 60%, #06B6D4 100%)",
            }}
          >
            의료기기 광고 심의 기준 알려줘
          </div>
          <div className="mt-3 rounded-[2px_10px_10px_10px] border border-md-outline-variant bg-md-surface-container-low px-3.5 py-3 text-[13px] leading-[1.6] text-md-on-surface-variant">
            심의 대상은 <strong className="text-md-primary-container">의료기기법 §13</strong>에 따라
            모든 광고 매체에 적용됩니다.
            <span className="ml-2 inline-block rounded border border-md-primary-fixed-dim bg-md-primary-fixed px-2 py-0.5 text-[10.5px] text-md-on-surface-variant">
              출처 [1] [2]
            </span>
          </div>
        </div>
      </section>

      {/* features */}
      <section id="features" className="relative mx-auto max-w-[1180px] px-10 py-24">
        <div className="mb-14 text-center">
          <span className="theme-grad-text inline-block text-[12px] font-bold uppercase tracking-[0.16em]">
            Core Features
          </span>
          <h2
            className="mt-3 text-[38px] font-extrabold leading-[1.18]"
            style={{ letterSpacing: "-0.02em" }}
          >
            네 가지 핵심 기능
          </h2>
          <p className="mt-3 text-[17px] leading-[1.75] text-md-on-surface-variant">
            복잡한 의료규제 문제를 다각도로 검토합니다.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((f) => (
            <article
              key={f.title}
              className="theme-card-lift rounded-[18px] border-[1.5px] border-md-outline-variant bg-md-surface p-7 shadow-[0_2px_16px_rgba(15,23,41,0.07)]"
            >
              <div
                className="mb-5 inline-flex h-14 w-14 items-center justify-center rounded-[14px] border border-md-primary-fixed-dim"
                style={{ background: "var(--md-primary-fixed)" }}
              >
                <span
                  className="material-symbols-outlined text-[26px] text-md-primary-container"
                  aria-hidden
                >
                  {f.icon}
                </span>
              </div>
              <h3 className="text-[17px] font-extrabold tracking-tight">
                {f.title}
              </h3>
              <p className="mt-2.5 text-[13.5px] leading-[1.65] text-md-on-surface-variant">
                {f.desc}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* beta band — gradient bg */}
      <section
        className="relative px-10 py-12"
        style={{
          background:
            "linear-gradient(135deg, #6366F1 0%, #3B82F6 60%, #06B6D4 100%)",
        }}
      >
        <div className="mx-auto flex max-w-[1180px] items-center justify-between gap-10">
          <div>
            <span className="text-[12px] font-bold uppercase tracking-[0.1em] text-white/70">
              Closed Beta
            </span>
            <h3 className="mt-2 text-[24px] font-extrabold text-white">
              지금, <em className="not-italic">베타에 참여하세요</em>
            </h3>
            <p className="mt-2 max-w-[400px] text-[15px] leading-[1.6] text-white/80">
              초기 사용자에겐 무제한 토큰 + 직접 피드백 채널.
            </p>
          </div>
          <div className="flex shrink-0 gap-12">
            {STATS.map((s) => (
              <div key={s.lbl} className="text-center">
                <div className="text-[32px] font-black text-white">{s.num}</div>
                <div className="mt-1 text-[12px] text-white/65">{s.lbl}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-[700px] px-10 py-32 text-center">
        <h2
          className="text-[40px] font-extrabold leading-[1.15]"
          style={{ letterSpacing: "-0.02em" }}
        >
          규정과 관련된 사안,{" "}
          <em className="not-italic theme-grad-text">함께 풀어드릴게요</em>
        </h2>
        <p className="mt-5 text-[16px] leading-[1.7] text-md-on-surface-variant">
          이메일 한 줄로 시작. 비밀번호도, 카드 정보도 필요 없습니다.
        </p>
        <Link
          href="/login"
          className="theme-cta-bg theme-cta-glow mt-10 inline-flex h-14 items-center gap-2 rounded-[10px] px-8 text-[16px] font-extrabold text-white transition-all hover:-translate-y-0.5"
        >
          Regia 베타 이용하기 →
        </Link>
      </section>

      {/* footer */}
      <footer className="mx-auto flex max-w-[1180px] items-center justify-between border-t border-md-outline-variant px-10 py-10 text-[12px]">
        <span className="font-bold theme-grad-text text-[18px]">Regia</span>
        <span className="font-mono text-md-on-surface-variant">
          © {new Date().getFullYear()} MEDIREG AI · all rights reserved
        </span>
      </footer>
    </main>
  );
}
