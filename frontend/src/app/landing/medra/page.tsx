/**
 * Medra Landing — design_guide.md 그대로 구현.
 * 기존 chat UI(--md-* 토큰)와는 완전히 분리된 namespace (--medra-*).
 * 비인증·인증 무관하게 접근 가능 (middleware 화이트리스트).
 */

import Link from "next/link";
import { ThemeLogo } from "@/components/shell/ThemeLogo";

export const metadata = {
  title: "의료규제ai · Medra",
  description: "의료규제, 놓치는 것 없이 파악하세요.",
};

const FEATURES = [
  {
    num: "01",
    icon: "menu_book",
    title: "법령 벡터 검색",
    desc: "의료법·약사법·의료기기법 등 의료 규제 코퍼스를 임베딩으로 의미 검색. 키워드가 달라도 동일 조항 도달.",
  },
  {
    num: "02",
    icon: "public",
    title: "웹·판례 통합",
    desc: "최신 판례·고시 변경·해석례를 실시간 웹 검색으로 보강. 출처와 시행일을 인용에 명시.",
  },
  {
    num: "03",
    icon: "summarize",
    title: "심층 보고서 자동 생성",
    desc: "단발 답변에 그치지 않고, 백그라운드에서 법령·웹·종합 3편의 심층 보고서를 자동 작성.",
  },
  {
    num: "04",
    icon: "verified",
    title: "인용 검증",
    desc: "모든 답변은 [n] 마커로 출처 매핑. RAG 기반은 자동 verify, 웹은 화이트리스트 매칭.",
  },
];

const WORKFLOW = [
  { tag: "Step 01", title: "질문 입력", desc: "조항·사건 번호도 함께 알려주면 더 정확합니다." },
  { tag: "Step 02", title: "벡터·웹 검색", desc: "qdrant + tavily로 동시에 검색. 인용 후보 수집." },
  { tag: "Step 03", title: "답변 생성", desc: "[n] 마커가 박힌 본문이 스트리밍." },
  { tag: "Step 04", title: "심층 보고서", desc: "백그라운드에서 3편의 .md 보고서 생성." },
];

export default function LandingPage() {
  return (
    <div data-theme="medra" className="medra-root min-h-screen">
      {/* fixed glass nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 flex h-[60px] items-center justify-between border-b border-[var(--medra-border)] px-10 backdrop-blur-md sm:px-10" style={{ background: "rgba(244,242,237,0.88)" }}>
        <Link href="/landing" className="inline-flex items-center transition-opacity hover:opacity-80">
          <ThemeLogo className="h-7 w-auto" />
        </Link>
        <div className="flex items-center gap-7">
          <a href="#features" className="text-[13.5px] text-[var(--medra-ink2)] transition-colors hover:text-[var(--medra-ink)]">
            기능
          </a>
          <a href="#workflow" className="text-[13.5px] text-[var(--medra-ink2)] transition-colors hover:text-[var(--medra-ink)]">
            작동 방식
          </a>
          <a href="#beta" className="text-[13.5px] text-[var(--medra-ink2)] transition-colors hover:text-[var(--medra-ink)]">
            베타
          </a>
          <Link
            href="/login"
            className="rounded-[var(--medra-r)] bg-[var(--medra-accent)] px-[18px] py-2 text-[13.5px] font-medium text-white transition-all hover:-translate-y-px hover:bg-[var(--medra-accent-light)]"
          >
            베타 시작하기 →
          </Link>
        </div>
      </nav>

      {/* hero */}
      <section className="mx-auto grid max-w-[1100px] grid-cols-1 items-center gap-[60px] px-10 pb-[100px] pt-[160px] lg:grid-cols-[1fr_420px]">
        <div>
          <div
            className="medra-fade-up medra-mono inline-flex items-center gap-2 border border-[var(--medra-accent-mid)] bg-[var(--medra-accent-pale)] px-[14px] py-1.5 text-[12px] font-medium uppercase tracking-[0.08em] text-[var(--medra-accent)]"
            style={{ borderRadius: "2px" }}
          >
            <span className="medra-blink inline-block h-1.5 w-1.5 rounded-full bg-[var(--medra-accent)]" />
            Closed Beta · 2026
          </div>
          <h1
            className="medra-fade-up mt-6 font-bold leading-[1.1] tracking-[-0.02em] text-[var(--medra-ink)]"
            style={{ animationDelay: "0.1s", fontSize: "clamp(36px, 4.5vw, 52px)" }}
          >
            의료규제,
            <br />
            <em className="font-extrabold not-italic text-[var(--medra-accent)]">
              놓치는 것 없이
            </em>
            <br />
            파악하세요
          </h1>
          <p
            className="medra-fade-up mt-7 max-w-[480px] text-[17px] leading-[1.7] text-[var(--medra-ink2)]"
            style={{ animationDelay: "0.2s" }}
          >
            법령·고시·해석·판례를 벡터 DB와 웹 검색으로 통합 조회하고, 인용을 명시한 답변과
            심층 보고서를 자동으로 작성합니다.
          </p>
          <div
            className="medra-fade-up mt-10 flex items-center gap-4"
            style={{ animationDelay: "0.3s" }}
          >
            <Link
              href="/login"
              className="inline-block rounded-[var(--medra-r)] bg-[var(--medra-accent)] px-7 py-3.5 text-[15px] font-medium text-white transition-all hover:-translate-y-0.5 hover:bg-[var(--medra-accent-light)] hover:shadow-[0_8px_24px_rgba(29,77,58,0.25)]"
            >
              베타 시작하기 →
            </Link>
            <a
              href="#features"
              className="inline-block rounded-[var(--medra-r)] border border-[var(--medra-border-strong)] px-[26px] py-[13px] text-[15px] text-[var(--medra-ink)] transition-colors hover:border-[var(--medra-ink2)] hover:bg-[var(--medra-bg2)]"
            >
              기능 살펴보기
            </a>
          </div>
        </div>

        {/* 우측 터미널 mockup */}
        <div
          className="medra-fade-up overflow-hidden rounded-[var(--medra-r-lg)] shadow-[0_24px_60px_rgba(0,0,0,0.18)]"
          style={{ background: "var(--medra-ink)", animationDelay: "0.2s" }}
        >
          <div
            className="flex items-center gap-2 px-4 py-3"
            style={{ background: "#2C2C2A" }}
          >
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: "#E24B4A" }} />
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: "#EF9F27" }} />
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: "#1D9E75" }} />
            <span
              className="medra-mono mx-auto text-[11px] tracking-[0.05em]"
              style={{ color: "#5A5850" }}
            >
              user@medra ~ %
            </span>
          </div>
          <div className="medra-mono p-6 text-[12px] leading-[1.8]">
            <div style={{ color: "var(--medra-accent-mid)" }}>$ medra query</div>
            <div style={{ color: "#E8E4DA" }}>의료기기 광고 심의 기준 알려줘</div>
            <div style={{ color: "var(--medra-gold)", opacity: 0.8, fontSize: 11 }}>
              ▸ 벡터 검색 (의료기기법 §13, 광고심의 고시)
            </div>
            <div style={{ color: "var(--medra-gold)", opacity: 0.8, fontSize: 11 }}>
              ▸ 웹·판례 통합 검색 (식약처 가이드라인 2024-12)
            </div>
            <div style={{ color: "var(--medra-gold)", opacity: 0.8, fontSize: 11 }}>
              ▸ 답변 생성 + 인용 매핑
            </div>
            <div className="mt-3" style={{ color: "#B4B2A9" }}>
              심의 대상은 의료기기법 §13에 따라 모든 광고 매체에 적용됩니다
              <span style={{ color: "#5DCAA5" }}> [1]</span>
              <span style={{ color: "#5DCAA5" }}> [2]</span>.
            </div>
            <div className="mt-3" style={{ color: "#5A5850", fontSize: 11 }}>
              ✓ 1.2k tokens · 2 sources · 18.4s
              <span
                className="medra-cursor-blink ml-1 inline-block h-3 w-1.5 align-middle"
                style={{ background: "var(--medra-accent-mid)" }}
              />
            </div>
          </div>
        </div>
      </section>

      {/* divider */}
      <div className="mx-auto max-w-[1100px] border-t border-[var(--medra-border)] px-10" />

      {/* features */}
      <section id="features" className="mx-auto max-w-[1100px] px-10 py-[100px]">
        <div className="medra-mono text-[11px] uppercase tracking-[0.12em] text-[var(--medra-accent)]">
          Core Features
        </div>
        <h2 className="mt-4 text-[clamp(26px,3vw,36px)] font-bold leading-[1.15] tracking-[-0.02em] text-[var(--medra-ink)]">
          네 가지 핵심 기능
        </h2>
        <p className="mt-3 max-w-[520px] text-[16px] text-[var(--medra-ink2)]">
          복잡한 의료규제 문제를 다각도로 검토합니다.
        </p>

        <div
          className="mt-[60px] grid grid-cols-1 gap-[2px] overflow-hidden rounded-[var(--medra-r-lg)] sm:grid-cols-2"
          style={{ background: "var(--medra-border)" }}
        >
          {FEATURES.map((f) => (
            <article
              key={f.num}
              className="px-9 py-10 transition-colors hover:bg-[var(--medra-bg2)]"
              style={{ background: "var(--medra-bg)" }}
            >
              <div className="medra-mono text-[11px] tracking-[0.08em] text-[var(--medra-ink3)]">
                {f.num}
              </div>
              <div
                className="mt-5 flex h-10 w-10 items-center justify-center rounded-[var(--medra-r)] border border-[var(--medra-accent-mid)] bg-[var(--medra-accent-pale)]"
              >
                <span
                  className="material-symbols-outlined text-[20px] text-[var(--medra-accent)]"
                  aria-hidden
                >
                  {f.icon}
                </span>
              </div>
              <h3 className="mt-5 text-[20px] font-bold leading-[1.2] tracking-[-0.01em] text-[var(--medra-ink)]">
                {f.title}
              </h3>
              <p className="mt-3 text-[14.5px] leading-[1.65] text-[var(--medra-ink2)]">
                {f.desc}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* divider */}
      <div className="mx-auto max-w-[1100px] border-t border-[var(--medra-border)] px-10" />

      {/* workflow */}
      <section
        id="workflow"
        className="mx-auto max-w-[1100px] px-10 py-[80px]"
        style={{ background: "var(--medra-bg)" }}
      >
        <div className="medra-mono text-[11px] uppercase tracking-[0.12em] text-[var(--medra-accent)]">
          How It Works
        </div>
        <h2 className="mt-4 text-[clamp(26px,3vw,36px)] font-bold leading-[1.15] tracking-[-0.02em] text-[var(--medra-ink)]">
          질문 한 번,
          <br />
          <em className="font-extrabold not-italic text-[var(--medra-accent)]">
            네 단계로 답변
          </em>
        </h2>
        <p className="mt-3 max-w-[520px] text-[16px] text-[var(--medra-ink2)]">
          벡터 검색부터 심층 보고서까지 모든 단계가 자동.
        </p>

        <div className="relative mt-12 flex flex-col gap-5 sm:flex-row sm:gap-0">
          {/* 가운데 관통 라인 (desktop only) */}
          <div
            aria-hidden
            className="absolute hidden sm:block"
            style={{
              top: 28,
              left: 28,
              right: 28,
              height: 1,
              background: "var(--medra-border-strong)",
            }}
          />
          {WORKFLOW.map((w, i) => (
            <div
              key={w.tag}
              className="group relative flex-1 px-5 text-center"
            >
              <div
                className="medra-mono mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full border-2 border-[var(--medra-accent)] text-[13px] font-medium text-[var(--medra-accent)] transition-colors group-hover:bg-[var(--medra-accent)] group-hover:text-white"
                style={{ background: "var(--medra-bg)", position: "relative", zIndex: 1 }}
              >
                {String(i + 1).padStart(2, "0")}
              </div>
              <span
                className="medra-mono mb-3 inline-block border border-[var(--medra-accent-mid)] bg-[var(--medra-accent-pale)] px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-[var(--medra-accent)]"
                style={{ borderRadius: "2px" }}
              >
                {w.tag}
              </span>
              <h4 className="text-[14px] font-medium text-[var(--medra-ink)]">
                {w.title}
              </h4>
              <p className="mt-1.5 text-[13px] leading-[1.55] text-[var(--medra-ink2)]">
                {w.desc}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* beta banner — 다크 그린 */}
      <section
        id="beta"
        className="relative overflow-hidden px-10 py-16"
        style={{ background: "var(--medra-accent)" }}
      >
        <span
          aria-hidden
          className="pointer-events-none absolute"
          style={{
            right: -20,
            top: "50%",
            transform: "translateY(-50%) rotate(90deg)",
            fontFamily: "Sora, sans-serif",
            fontSize: 120,
            color: "rgba(255,255,255,0.04)",
            letterSpacing: "-0.05em",
          }}
        >
          BETA
        </span>
        <div className="mx-auto grid max-w-[1100px] grid-cols-1 items-center gap-10 lg:grid-cols-[1fr_auto]">
          <div>
            <div
              className="medra-mono mb-4 inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.1em]"
              style={{ color: "rgba(255,255,255,0.5)" }}
            >
              <span
                className="medra-blink inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: "var(--medra-accent-mid)" }}
              />
              Closed Beta · 한정 모집
            </div>
            <h2 className="text-[34px] font-bold leading-[1.15] tracking-[-0.02em] text-white">
              지금,{" "}
              <em
                className="italic"
                style={{ color: "var(--medra-accent-mid)" }}
              >
                베타에 참여하세요
              </em>
            </h2>
            <p className="mt-5 max-w-[480px] text-[15.5px] leading-[1.7]" style={{ color: "rgba(255,255,255,0.7)" }}>
              초기 사용자에겐 무제한 토큰 + 직접 피드백 채널. 의료법무·약무팀·임상 매니저 우선.
            </p>
          </div>
          <div
            className="rounded-[var(--medra-r)] border px-4 py-3"
            style={{
              background: "rgba(255,255,255,0.07)",
              borderColor: "rgba(255,255,255,0.12)",
            }}
          >
            <div
              className="medra-mono mb-1 text-[10px] uppercase tracking-[0.1em]"
              style={{ color: "var(--medra-accent-mid)" }}
            >
              Beta Period
            </div>
            <div className="text-[14px] font-medium text-white">2026년 5월 ~ 8월</div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-[700px] px-10 py-[120px] text-center">
        <h2 className="text-[clamp(30px,3.5vw,44px)] font-bold leading-[1.15] tracking-[-0.02em] text-[var(--medra-ink)]">
          규정과 관련된 사안,{" "}
          <em className="italic text-[var(--medra-accent)]">함께 풀어드릴게요</em>
        </h2>
        <p className="mt-5 text-[16px] leading-[1.7] text-[var(--medra-ink2)]">
          이메일 한 줄로 시작. 비밀번호도, 카드 정보도 필요 없습니다.
        </p>
        <Link
          href="/login"
          className="mt-10 inline-block rounded-[var(--medra-r)] bg-[var(--medra-accent)] px-7 py-3.5 text-[15px] font-medium text-white transition-all hover:-translate-y-0.5 hover:bg-[var(--medra-accent-light)] hover:shadow-[0_8px_24px_rgba(29,77,58,0.25)]"
        >
          Medra 베타 이용하기 →
        </Link>
      </section>

      {/* footer */}
      <footer className="mx-auto flex max-w-[1100px] items-center justify-between border-t border-[var(--medra-border)] px-10 py-10">
        <ThemeLogo className="h-6 w-auto" />
        <p className="medra-mono text-[12px] text-[var(--medra-ink3)]">
          © {new Date().getFullYear()} 의료규제ai · all rights reserved
        </p>
      </footer>
    </div>
  );
}
