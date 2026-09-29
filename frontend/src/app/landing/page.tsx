/**
 * /landing — MEDIREG AI 통합 랜딩.
 *
 * 7 section + 1 footer를 scroll-snap-y mandatory로 페이지처럼 넘김.
 *   1. Hero        — 무엇을 하는 서비스인지 + 예시 질문
 *   2. IRB·DRB     — 연구 심의 예비판정 (메인 컨텐츠, 2026-08-27 승격)
 *   3. 사용법       — 채팅하듯 (단일 AI 에이전트 강조)
 *   3. 작동 방식    — 4단계 (질문 → 검색 강제 → 답변+인용 → grounding 검증)
 *   4. 포함 규제문서 — 8개 카테고리 그리드
 *   5. 핵심 기능    — 4개 카드 (법령 벡터 검색·웹/판례 통합·심층 보고서·인용 검증)
 *   6. 신뢰도       — 인용 검증 기준(법령 원문 대조·웹 발행처)
 *   8. 최근 업데이트 — 최신 3건 카드 + /updates (2026-09-02, Hero 에도 최신 1건 티커)
 *   F. 제약사항      — 다루지 않는 범위 disclaimer
 *
 * theme 토큰만 사용(raw hex X) — Quiet Forest 자동 적용.
 * 헤드라인 강조는 .theme-grad-text utility.
 */

import Link from "next/link";
import { HashScroll } from "./HashScroll";
import { StartCta } from "./StartCta";
import { SiteNav } from "@/components/shell/SiteNav";
import { IrbExampleCards } from "./IrbExampleCards";
import { HeroExamples } from "./HeroExamples";
import { LiveChatDemo } from "./LiveChatDemo";
import { CorpusGrid } from "./CorpusGrid";
import { RecentUpdates } from "./RecentUpdates";

export const metadata = {
  title: "MEDIREG AI · 의료규제 AI 에이전트",
  description: "법령·고시·해석·판례를 벡터 DB와 웹 검색으로 통합 조회하는 의료·규제 전문 AI 에이전트.",
};

/* ─────────────────── 데이터 ─────────────────── */


const PIPELINE = [
  { num: "01", title: "질문 입력", desc: "자연어로 자유롭게. PII 마스킹·의도 판정 후 검색으로 넘어갑니다." },
  { num: "02", title: "법령 검색 (강제)", desc: "규제 질의는 항상 법령·고시·판례 코퍼스와 웹을 의미 기반으로 검색." },
  { num: "03", title: "답변 + 인용", desc: "확보한 근거로 스트리밍. 문장마다 [n] 인용 마커를 붙입니다." },
  { num: "04", title: "grounding 검증", desc: "인용을 원문과 대조해 신뢰도 배지로 표시. 지어낸 근거를 차단." },
];


const FEATURES = [
  {
    icon: "search",
    title: "법령 벡터 검색",
    desc: "키워드 일치를 넘어 의미 기반. 법조문 표현 몰라도 찾음. 개정·폐지된 조문은 배지로 알려줌.",
  },
  {
    icon: "public",
    title: "웹·판례 통합",
    desc: "최신 고시 개정·판례·해석례를 실시간 보강. 출처와 시행일·선고일 명시.",
  },
  {
    icon: "edit_document",
    title: "서류 작성",
    desc: "검색으로 찾은 관보 서식을 그 자리에서 작성 — 도우미와 대화하면 칸이 채워지고, 원본 서식 파일(.hwp) 그대로 받습니다. 개인정보는 외부 AI 없이 원내 AI만 처리.",
  },
  {
    icon: "summarize",
    title: "심층 보고서",
    desc: "섹션별로 나눠 작성해 실무에 쓸 깊이로. 채팅과 병렬 실행이라 기다리지 않아도 되고, 완료되면 이메일로 Word 첨부.",
  },
  {
    icon: "verified",
    title: "인용 검증",
    desc: "모든 답변은 [n] 마커로 출처 매핑. 법령 인용은 원문 대조로 자동 검증 — 뒷받침 문장을 하이라이트로 확인.",
  },
  {
    icon: "article",
    title: "원문 바로보기",
    desc: "인용을 클릭하면 조문 전문·별표/서식을 앱 안에서 바로. 서식은 HWP 원본을 그대로 내려받습니다.",
  },
  {
    icon: "bookmarks",
    title: "근거 라이브러리",
    desc: "쓸 만한 근거는 저장해 폴더로 정리. 저장한 조문이 개정되면 감지해 표시.",
  },
];

/* ─────────────────── Page ─────────────────── */

export default function LandingPage() {
  return (
    <main className="h-screen snap-y snap-mandatory overflow-y-scroll bg-md-surface text-md-on-surface">
      <HashScroll />
      {/* 고정 nav — 모든 section 위 sticky. 메뉴 정의는 SiteNav 한 곳(공개 페이지 공통) */}
      <SiteNav variant="overlay" />

      {/* ───────── 1. Hero ───────── */}
      <section className="flex min-h-screen snap-start flex-col items-center justify-center px-8 sm:px-16">
        <div className="mx-auto flex w-full max-w-[1100px] flex-col items-center">
          <span className="text-[12px] font-semibold uppercase tracking-[0.16em] text-md-on-surface-variant">
            MEDIREG · Medical Regulation AI
          </span>
          <h1
            className="mt-5 text-center text-[44px] font-bold leading-[1.12] sm:text-[64px]"
            style={{ letterSpacing: "-0.025em" }}
          >
            <span className="theme-grad-text">의료규제,</span>
            <br />
            <span>무엇이든 물어보세요.</span>
          </h1>
          <p className="mt-8 max-w-[600px] text-center text-[17px] leading-[1.8] text-md-on-surface-variant sm:text-[18px]">
            법령·고시·해석례·판례를 벡터 DB와 최신 웹 검색으로 동시에 조회하는
            의료·규제 전문 AI 에이전트.
          </p>

          {/* 예시 카드 — 누르면 실제 답변 예시 모달(2026-09-02). 데이터·모달은 HeroExamples. */}
          <HeroExamples />

          <StartCta
            className="theme-cta-bg theme-cta-glow mt-12 inline-flex h-12 items-center gap-2 rounded-full px-7 text-[15px] font-semibold text-md-on-primary transition-all hover:-translate-y-0.5"
            authedLabel={
              <>
                채팅으로
                <span className="material-symbols-outlined text-[18px]" aria-hidden>
                  arrow_forward
                </span>
              </>
            }
          >
            지금 시작하기
            <span className="material-symbols-outlined text-[18px]" aria-hidden>
              arrow_forward
            </span>
          </StartCta>
          {/* 최신 업데이트 한 줄(2026-09-02) — 랜딩에서 업데이트를 바로 보게. 0건이면 숨김 */}
          <RecentUpdates variant="ticker" />
        </div>
        <ScrollHint />
      </section>

      {/* ───────── 2. IRB·DRB — 메인 컨텐츠(2026-08-27 승격) ───────── */}
      <section className="flex min-h-screen snap-start flex-col items-center justify-center px-8 py-16 sm:px-16">
        <div className="mx-auto w-full max-w-[1100px]">
          <div className="text-center">
            <SectionEyebrow>02 · IRB · DRB</SectionEyebrow>
            <SectionTitle>
              <span>연구 심의, 시작 전에 </span>
              <span className="theme-grad-text">먼저 확인.</span>
            </SectionTitle>
            <p className="mx-auto mt-8 max-w-[640px] text-[17px] leading-[1.8] text-md-on-surface-variant">
              내 연구가 IRB 심의 대상인지, 면제·신속·정규 중 어디인지 —
              기관 지침 기준으로 예비판정하고, 의료데이터 연구의 DRB 심의까지 함께 확인합니다.
            </p>
          </div>

          {/* 단계 카드 — 누르면 실제 사용 예시 모달(2026-09-02 피드백). 데이터·모달은 IrbExampleCards. */}
          <IrbExampleCards />
          <p className="mx-auto mt-10 max-w-[640px] text-center text-[13px] leading-[1.7] text-md-on-surface-variant/80">
            판정 기준: 화순전남대학교병원 IRB·DRB 지침 — AI의 예비판단이며, 최종 판단은
            소속 기관 심의 사무국을 따릅니다.
          </p>
        </div>
      </section>

      {/* ───────── 3. 사용법 ───────── */}
      <section className="flex min-h-screen snap-start flex-col items-center justify-center px-8 sm:px-16">
        <div className="mx-auto grid w-full max-w-[1100px] grid-cols-1 items-center gap-12 lg:grid-cols-[1fr_1.1fr]">
          <div>
            <SectionEyebrow>03 · How to use</SectionEyebrow>
            <SectionTitle>
              그냥 <span className="theme-grad-text">채팅하듯</span> 물어보세요.
            </SectionTitle>
            <p className="mt-8 max-w-[480px] text-[17px] leading-[1.8] text-md-on-surface-variant">
              한 명의 AI 에이전트가 응답합니다. 내부적으로 여러 단계를 거치지만,
              사용자는 *한 화면에서* 한 명과 대화하는 경험.
              질문이 모호해도 의도를 묻고, 출처를 함께 보여줍니다.
            </p>
            <ul className="mt-10 flex flex-col gap-4 text-[15.5px] leading-[1.7]">
              <UsageBullet>법조문 키워드 몰라도 자연어로 OK</UsageBullet>
              <UsageBullet>답변마다 [n] 인용 마커로 출처 명시</UsageBullet>
              <UsageBullet>모호한 질문엔 추가 정보를 먼저 요청</UsageBullet>
              <UsageBullet>심층 보고서는 백그라운드로 — 채팅은 계속, 완료되면 이메일로도</UsageBullet>
            </ul>
          </div>

          {/* 실시간 채팅 데모 — 질문 타이핑→검색 단계→스트리밍→근거 카드 순환(2026-09-02) */}
          <LiveChatDemo />
        </div>
      </section>

      {/* ───────── 3. 작동 방식 ───────── */}
      <section className="flex min-h-screen snap-start flex-col items-center justify-center px-8 py-16 sm:px-16">
        <div className="mx-auto w-full max-w-[1100px]">
          <div className="text-center">
            <SectionEyebrow>04 · How it works</SectionEyebrow>
            <SectionTitle>
              <span>한 번의 질문, </span>
              <span className="theme-grad-text">네 단계 검색.</span>
            </SectionTitle>
            <p className="mx-auto mt-8 max-w-[600px] text-[17px] leading-[1.8] text-md-on-surface-variant">
              사용자는 한 번만 물어봅니다. 내부는 다음 4단계로 작동합니다.
            </p>
          </div>

          <ol className="mt-16 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {PIPELINE.map((p, i) => (
              <li
                key={p.num}
                className="relative flex flex-col gap-4 rounded-card border border-md-outline-variant bg-md-surface-container-low p-8"
              >
                <span
                  className="text-[12px] font-semibold tracking-[0.12em] text-md-primary"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {p.num}
                </span>
                <h3 className="text-[18px] font-semibold tracking-tight text-md-on-surface">
                  {p.title}
                </h3>
                <p className="text-[15.5px] leading-[1.75] text-md-on-surface-variant">
                  {p.desc}
                </p>
                {i < PIPELINE.length - 1 ? (
                  <span
                    className="material-symbols-outlined absolute -right-3 top-1/2 hidden -translate-y-1/2 text-[20px] text-md-outline lg:block"
                    aria-hidden
                  >
                    arrow_forward
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ───────── 4. 포함 규제문서 ───────── */}
      <section className="flex min-h-screen snap-start flex-col items-center justify-center px-8 py-16 sm:px-16">
        <div className="mx-auto w-full max-w-[1100px]">
          <div className="text-center">
            <SectionEyebrow>05 · Coverage</SectionEyebrow>
            <SectionTitle>
              <span>의료 규제 코퍼스를 </span>
              <span className="theme-grad-text">통합 색인.</span>
            </SectionTitle>
            <p className="mx-auto mt-8 max-w-[640px] text-[17px] leading-[1.8] text-md-on-surface-variant">
              법령·고시·별표 서식·가이드라인·자치법규·해석례·판례를 한 인덱스에. 종별을 누르면 무엇이 들어 있는지
              볼 수 있고, 검색 결과에는 출처 유형과 시행일·선고일이 함께 표시됩니다.
            </p>
          </div>

          {/* 종별·건수 카드 — 누르면 목록 모달(2026-09-02 실측 수치). CorpusGrid. */}
          <CorpusGrid />
        </div>
      </section>

      {/* ───────── 5. 핵심 기능 ───────── */}
      <section className="flex min-h-screen snap-start flex-col items-center justify-center px-8 py-16 sm:px-16">
        <div className="mx-auto w-full max-w-[1100px]">
          <div className="text-center">
            <SectionEyebrow>06 · Features</SectionEyebrow>
            <SectionTitle>
              <span>이런 것까지 </span>
              <span className="theme-grad-text">됩니다.</span>
            </SectionTitle>
            <p className="mx-auto mt-8 max-w-[600px] text-[17px] leading-[1.8] text-md-on-surface-variant">
              검색의 정확성, 인용의 투명성, 보고서의 깊이.
            </p>
          </div>

          <ul className="mt-16 grid grid-cols-1 gap-6 sm:grid-cols-2">
            {FEATURES.map((f) => (
              <li
                key={f.title}
                className="theme-card-lift flex items-start gap-5 rounded-card border border-md-outline-variant bg-md-surface-container-low p-8"
              >
                <span
                  className="material-symbols-outlined mt-1 text-[28px] text-md-primary"
                  aria-hidden
                >
                  {f.icon}
                </span>
                <div className="flex flex-col gap-3">
                  <h3 className="text-[18px] font-semibold tracking-tight text-md-on-surface">
                    {f.title}
                  </h3>
                  <p className="text-[15.5px] leading-[1.75] text-md-on-surface-variant">
                    {f.desc}
                  </p>
                </div>
              </li>
            ))}
          </ul>

          <div className="mt-14 flex justify-center">
            <StartCta
              className="theme-cta-bg theme-cta-glow inline-flex h-12 items-center gap-2 rounded-full px-7 text-[15px] font-semibold text-md-on-primary transition-all hover:-translate-y-0.5"
              authedLabel={
                <>
                  채팅으로 돌아가기
                  <span className="material-symbols-outlined text-[18px]" aria-hidden>
                    arrow_forward
                  </span>
                </>
              }
            >
              MEDIREG AI 시작하기
              <span className="material-symbols-outlined text-[18px]" aria-hidden>
                arrow_forward
              </span>
            </StartCta>
          </div>
        </div>
      </section>

      {/* ───────── 6. 신뢰도 판단 기준 (가이드 통합) ───────── */}
      <section
        id="trust"
        className="flex min-h-screen snap-start scroll-mt-20 flex-col items-center justify-center px-8 py-16 sm:px-16"
      >
        <div className="mx-auto w-full max-w-[900px]">
          <div className="text-center">
            <SectionEyebrow>07 · Trust</SectionEyebrow>
            <SectionTitle>
              <span>신뢰도는 </span>
              <span className="theme-grad-text">원문 대조로.</span>
            </SectionTitle>
            <p className="mx-auto mt-8 max-w-[640px] text-[17px] leading-[1.8] text-md-on-surface-variant">
              답변의 모든 인용 <code className="text-md-primary">[n]</code> 은 2단계로
              검증됩니다. 답변 위 신뢰도 배지는 그 검증 비율입니다.
            </p>
          </div>

          {/* 2단계 검증 표 */}
          <div className="mt-12 overflow-hidden rounded-card border border-md-outline-variant">
            <table className="w-full text-left text-[14.5px] leading-[1.7]">
              <thead className="bg-md-surface-container-low text-md-on-surface-variant">
                <tr>
                  <th className="px-6 py-4 font-medium">인용 유형</th>
                  <th className="px-6 py-4 font-medium">검증 방법</th>
                  <th className="px-6 py-4 font-medium">결과</th>
                </tr>
              </thead>
              <tbody className="text-md-on-surface">
                <tr className="border-t border-md-outline-variant/60">
                  <td className="px-6 py-4 align-top font-semibold">법령 인용</td>
                  <td className="px-6 py-4 align-top text-md-on-surface-variant">
                    답변 후 시스템이 그 문장의 주장을 법령 원문과 문장 단위로 대조.
                    뒷받침 문장을 뽑아 원문에 실제로 존재하는지 확인합니다.
                  </td>
                  <td className="px-6 py-4 align-top text-md-on-surface-variant">
                    확인되면 <b className="text-md-primary">✓ 검증됨</b>, 원문에서 못
                    찾거나 지어낸 경우 <b>미검증</b>.
                  </td>
                </tr>
                <tr className="border-t border-md-outline-variant/60">
                  <td className="px-6 py-4 align-top font-semibold">웹 인용</td>
                  <td className="px-6 py-4 align-top text-md-on-surface-variant">
                    원문 대조가 불가하므로 발행처로 판단. 정부·공공기관(law.go.kr,
                    mfds.go.kr 등)이면 검증으로 간주합니다.
                  </td>
                  <td className="px-6 py-4 align-top text-md-on-surface-variant">
                    공공기관이면 <b className="text-md-primary">검증됨</b>, 아니면{" "}
                    <b>미검증</b>.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 배지 등급 */}
          <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-3">
            {[
              { dot: "bg-md-primary", label: "신뢰도 높음", ratio: "≥ 80%" },
              { dot: "bg-md-tertiary", label: "신뢰도 보통", ratio: "30 ~ 79%" },
              { dot: "bg-md-error", label: "신뢰도 낮음", ratio: "< 30%" },
            ].map((t) => (
              <div
                key={t.label}
                className="flex items-center justify-between rounded-card border border-md-outline-variant bg-md-surface-container-low px-6 py-4"
              >
                <span className="flex items-center gap-2 text-[14px] text-md-on-surface">
                  <span className={`h-2 w-2 rounded-full ${t.dot}`} aria-hidden />
                  {t.label}
                </span>
                <span className="text-[13px] text-md-on-surface-variant">{t.ratio}</span>
              </div>
            ))}
          </div>

          <p className="mx-auto mt-8 max-w-[720px] rounded-card border border-md-outline-variant bg-md-surface-container-low px-7 py-5 text-[14.5px] leading-[1.75] text-md-on-surface-variant">
            <b className="text-md-on-surface">‘미검증’은 “틀렸다”는 뜻이 아닙니다</b> —
            “원문에서 직접 뒷받침 문장을 못 찾았다”는 의미입니다. 환각(없는 근거를
            지어냄) 차단을 우선하기 위해 신뢰도는 보수적으로 낮게 잡도록 설계돼
            있습니다.
          </p>
        </div>
      </section>

      {/* ───────── Footer · 제약사항 ───────── */}
      {/* ───────── 8. 최근 업데이트 (2026-09-02) — 데이터·카드는 RecentUpdates ───────── */}
      <RecentUpdates variant="section" />

      <footer className="flex snap-start flex-col items-center justify-center border-t border-md-outline-variant bg-md-surface-container-low px-8 py-16 sm:px-16">
        <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-6">
          <span
            className="text-[11px] font-semibold uppercase tracking-[0.16em] text-md-warning"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            제약 사항 · Limitations
          </span>
          <h2
            className="text-[24px] font-bold tracking-tight text-md-on-surface sm:text-[28px]"
            style={{ letterSpacing: "-0.02em" }}
          >
            다음 영역은 다루지 않습니다.
          </h2>
          <ul className="grid grid-cols-1 gap-4 text-[15px] leading-[1.75] text-md-on-surface-variant sm:grid-cols-2">
            <LimitBullet>일상 잡담·코드 작성·번역 같은 범용 질문</LimitBullet>
            <LimitBullet>개별 환자의 진단·치료 권고 (의료 행위 대체 X)</LimitBullet>
            <LimitBullet>법적 자문 — 답변은 참고용, 최종 판단은 전문가 검토 권장</LimitBullet>
            <LimitBullet>실시간 환자 데이터·전자의무기록(EMR) 접근</LimitBullet>
          </ul>

          <div className="mt-10 flex flex-col items-start justify-between gap-3 border-t border-md-outline-variant pt-6 text-[12px] text-md-on-surface-variant sm:flex-row sm:items-center">
            <span>© {new Date().getFullYear()} MEDIREG AI · 의료·규제 도메인 AI</span>
            <nav className="flex items-center gap-4">
              <Link href="/guide" className="hover:text-md-on-surface">
                이용 안내
              </Link>
              <Link href="/updates" className="hover:text-md-on-surface">
                업데이트 내역
              </Link>
              <Link href="/terms" className="hover:text-md-on-surface">
                이용약관
              </Link>
              <Link href="/privacy" className="hover:text-md-on-surface">
                개인정보처리방침
              </Link>
              <Link href="/login" className="hover:text-md-on-surface">
                로그인 →
              </Link>
            </nav>
          </div>
        </div>
      </footer>
    </main>
  );
}

/* ─────────────────── 보조 컴포넌트 ─────────────────── */

function SectionEyebrow({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="text-[11px] font-semibold uppercase tracking-[0.16em] text-md-primary"
      style={{ fontFamily: "var(--font-mono)" }}
    >
      {children}
    </span>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="mt-5 text-[34px] font-bold leading-[1.15] tracking-tight text-md-on-surface sm:text-[44px]"
      style={{ letterSpacing: "-0.025em" }}
    >
      {children}
    </h2>
  );
}

function UsageBullet({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-3 text-md-on-surface-variant">
      <span
        className="material-symbols-outlined mt-0.5 text-[18px] text-md-primary"
        aria-hidden
      >
        check_circle
      </span>
      <span>{children}</span>
    </li>
  );
}

function LimitBullet({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5">
      <span
        className="material-symbols-outlined mt-0.5 shrink-0 text-[18px] text-md-warning"
        aria-hidden
      >
        block
      </span>
      <span>{children}</span>
    </li>
  );
}


function ScrollHint() {
  return (
    <div className="mt-16 flex flex-col items-center gap-1 text-md-on-surface-variant">
      <span
        className="material-symbols-outlined animate-bounce text-[18px]"
        aria-hidden
      >
        keyboard_arrow_down
      </span>
      <span className="text-[10px] font-semibold uppercase tracking-[0.16em]">
        scroll
      </span>
    </div>
  );
}
