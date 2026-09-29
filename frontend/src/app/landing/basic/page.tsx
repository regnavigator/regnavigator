/**
 * Basic Landing — 흰 배경 + 한국 brand palette + Pretendard.
 * 의료 표준 톤. 절제된 색·정보 밀도 ↑.
 */

import Link from "next/link";

export const metadata = {
  title: "MEDIREG AI · 의료·규제 AI",
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

export default function BasicLandingPage() {
  return (
    <main className="min-h-screen bg-md-surface text-md-on-surface">
      {/* nav */}
      <nav className="sticky top-0 z-50 flex h-16 items-center justify-between border-b border-md-outline-variant bg-md-surface px-8 sm:px-16">
        <Link
          href="/landing"
          className="inline-flex items-center gap-2 text-md-on-surface"
        >
          <span
            className="material-symbols-outlined text-[20px] text-md-primary"
            style={{ fontVariationSettings: "'FILL' 1" }}
            aria-hidden
          >
            gavel
          </span>
          <span className="text-[16px] font-bold tracking-tight">MEDIREG AI</span>
        </Link>
        <Link
          href="/login"
          className="theme-cta-bg theme-cta-glow inline-flex h-9 items-center rounded-full px-5 text-[13px] font-semibold text-md-on-primary transition-all hover:-translate-y-0.5"
        >
          시작하기
        </Link>
      </nav>

      {/* hero */}
      <section className="mx-auto grid max-w-[1100px] grid-cols-1 items-center gap-12 px-8 py-24 sm:px-16 lg:grid-cols-2">
        <div>
          <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-md-primary">
            의료·규제 AI
          </span>
          <h1
            className="mt-4 text-[44px] font-bold leading-[1.1] tracking-tight sm:text-[60px]"
            style={{ letterSpacing: "-0.025em" }}
          >
            <span className="theme-grad-text">의료규제, 한 번에</span>
          </h1>
          <p className="mt-6 max-w-[480px] text-[16px] leading-relaxed text-md-on-surface-variant">
            법령·고시·판례를 벡터 DB와 웹 검색으로 통합 조회하고,
            인용을 명시한 답변과 심층 보고서를 자동으로 작성합니다.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link
              href="/login"
              className="theme-cta-bg theme-cta-glow inline-flex h-12 items-center rounded-full px-7 text-[15px] font-semibold text-md-on-primary transition-all hover:-translate-y-0.5"
            >
              시작하기 →
            </Link>
            <Link
              href="/landing"
              className="inline-flex h-12 items-center rounded-full border border-md-outline-variant px-7 text-[14px] font-medium text-md-on-surface transition-colors hover:bg-md-surface-container-low"
            >
              테마 갤러리
            </Link>
          </div>
        </div>
        <div className="rounded-card border border-md-outline-variant bg-md-surface-container-low p-6">
          <div className="mb-3 flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-md-error" aria-hidden />
            <span className="size-2 rounded-full bg-md-tertiary" aria-hidden />
            <span className="size-2 rounded-full bg-md-primary" aria-hidden />
          </div>
          <div className="text-[12px] font-mono text-md-on-surface-variant">
            $ medra query
          </div>
          <div className="mt-1 text-[13.5px] text-md-on-surface">
            의료기기 광고 심의 기준 알려줘
          </div>
          <div className="mt-3 text-[12.5px] leading-relaxed text-md-on-surface-variant">
            심의 대상은 의료기기법 §13에 따라{" "}
            <span className="text-md-primary">[1]</span> 모든 광고 매체에 적용됩니다{" "}
            <span className="text-md-primary">[2]</span>.
          </div>
        </div>
      </section>

      {/* features */}
      <section className="mx-auto max-w-[1100px] px-8 py-16 sm:px-16">
        <span className="text-[12px] font-semibold uppercase tracking-[0.12em] text-md-primary">
          Core Features
        </span>
        <h2
          className="mt-3 text-[32px] font-bold leading-tight tracking-tight"
          style={{ letterSpacing: "-0.02em" }}
        >
          네 가지 핵심 기능
        </h2>
        <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <article
              key={f.title}
              className="theme-card-lift rounded-card border border-md-outline-variant bg-md-surface p-6"
            >
              <span
                className="material-symbols-outlined text-[24px] text-md-primary"
                aria-hidden
              >
                {f.icon}
              </span>
              <h3 className="mt-3 text-[18px] font-bold tracking-tight">
                {f.title}
              </h3>
              <p className="mt-2 text-[14px] leading-relaxed text-md-on-surface-variant">
                {f.desc}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* footer */}
      <footer className="mx-auto flex max-w-[1100px] items-center justify-between border-t border-md-outline-variant px-8 py-8 text-[11.5px] text-md-on-surface-variant sm:px-16">
        <span>© {new Date().getFullYear()} MEDIREG AI · 의료·규제 AI</span>
        <Link href="/login" className="hover:text-md-on-surface">
          로그인 →
        </Link>
      </footer>
    </main>
  );
}
