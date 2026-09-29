"use client";

/**
 * 랜딩 03(사용법) — 실시간 채팅처럼 움직이는 데모(2026-09-02 요청).
 *
 * 정적 말풍선 2개였던 자리를, 실제 /chat 흐름 그대로 재생한다:
 * 질문 타이핑 → 진행 단계 칩(개인정보 확인 → 근거 문서 검색 → 답변 작성) →
 * 답변 스트리밍(글자 단위) → 인용 [n] 마커가 근거 카드로 붙음 → 검증 배지.
 * 화면에 보일 때만 돌고(IntersectionObserver), 끝나면 잠시 멈췄다 다음 예시로
 * 순환한다. prefers-reduced-motion 이면 애니메이션 없이 완성 상태만 보여준다.
 *
 * 문안·근거는 2026-09-02 실제 파이프라인 답변(bench_chatloop)에서 검증된(✓) 근거만
 * 발췌한 것 — 지어낸 판단·문서 제목이 없다. HeroExamples 와 같은 실측에서 나왔다.
 */

import { useEffect, useRef, useState } from "react";

type Demo = {
  question: string;
  answer: string;
  cites: { n: number; kind: string; title: string }[];
};

const DEMOS: Demo[] = [
  {
    question: "의료기기 광고, 사전 심의를 꼭 받아야 하나요?",
    answer:
      "네. 의료기기를 광고하려는 자는 미리 자율심의기구의 심의를 받아야 합니다 [1]. 거짓·오해 우려가 있거나 허가 내용과 다른 성능·효능 표시는 금지되고 [2], 심의 대상 매체는 인터넷뉴스·일 평균 이용자 10만 명 이상 SNS 등입니다 [3].",
    cites: [
      { n: 1, kind: "법령", title: "의료기기법 제25조(광고의 심의)" },
      { n: 2, kind: "법령", title: "의료기기법 제24조(기재 및 광고의 금지 등)" },
      { n: 3, kind: "법령", title: "의료기기법 시행령 제10조의3" },
    ],
  },
  {
    question: "의료기기 임상시험계획 승인은 얼마나 걸리나요?",
    answer:
      "처리기간은 근무일 기준 30일입니다 [1]. 임상시험계획서와 임상시험용 의료기기 GMP 자료 등을 제출하며 [2], 보완이 있으면 회차마다 30일이 더 걸립니다 [3]. 사전상담으로 초안을 검토받으면 반려를 줄일 수 있습니다.",
    cites: [
      { n: 1, kind: "법령", title: "의료기기법 제10조(임상시험계획의 승인 등)" },
      { n: 2, kind: "가이드라인", title: "의료기기 임상시험 안내서 — 2.2 임상시험계획(변경)승인" },
      { n: 3, kind: "가이드라인", title: "디지털의료기기 임상시험등 관련 가이드라인(민원인안내서)" },
    ],
  },
  {
    question: "치료재료 비용은 어떻게 산정하나요?",
    answer:
      "고시된 급여상한금액 범위 안에서 요양기관의 실구입가로 산정합니다 [1]. 수술료에 포함되는지 별도 산정인지는 재료·시술별로 심사지침이 정합니다 [2]. 예를 들어 Drill Bit 는 수술료에 포함되어 별도 산정이 안 됩니다 [2].",
    cites: [
      { n: 1, kind: "고시", title: "치료재료 급여·비급여 목록 및 급여상한금액표" },
      { n: 2, kind: "급여기준", title: "요양급여의 적용기준 및 방법에 관한 세부사항과 심사지침" },
    ],
  },
];

const STEPS = ["개인정보 확인", "근거 문서 검색 중", "답변 작성"];

type Phase = "idle" | "typing" | "steps" | "streaming" | "done";

export function LiveChatDemo() {
  const rootRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [typed, setTyped] = useState("");
  const [step, setStep] = useState(0);
  const [streamed, setStreamed] = useState("");

  const demo = DEMOS[idx] ?? DEMOS[0]!;

  useEffect(() => {
    try {
      setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch { /* 무시 */ }
    const el = rootRef.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => setVisible(entries.some((e) => e.isIntersecting)), { threshold: 0.4 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  // 상태 기계 — 보일 때만 진행. 안 보이면 현재 상태에서 정지.
  useEffect(() => {
    if (!visible) return;
    if (reduced) {
      setTyped(demo.question);
      setStreamed(demo.answer);
      setPhase("done");
      return;
    }
    let t: number | undefined;
    if (phase === "idle") {
      setTyped("");
      setStreamed("");
      setStep(0);
      t = window.setTimeout(() => setPhase("typing"), 600);
    } else if (phase === "typing") {
      if (typed.length < demo.question.length) {
        t = window.setTimeout(() => setTyped(demo.question.slice(0, typed.length + 1)), 38);
      } else {
        t = window.setTimeout(() => setPhase("steps"), 500);
      }
    } else if (phase === "steps") {
      if (step < STEPS.length - 1) {
        t = window.setTimeout(() => setStep(step + 1), step === 1 ? 1100 : 650);
      } else {
        t = window.setTimeout(() => setPhase("streaming"), 500);
      }
    } else if (phase === "streaming") {
      if (streamed.length < demo.answer.length) {
        // 문장부호 뒤는 살짝 쉼 — 스트리밍 느낌
        const ch = demo.answer[streamed.length];
        const delay = ch === "." || ch === "," ? 120 : 14;
        t = window.setTimeout(() => setStreamed(demo.answer.slice(0, streamed.length + 2)), delay);
      } else {
        setPhase("done");
      }
    } else if (phase === "done") {
      t = window.setTimeout(() => {
        setIdx((i) => (i + 1) % DEMOS.length);
        setPhase("idle");
      }, 9000);
    }
    return () => {
      if (t) window.clearTimeout(t);
    };
  }, [visible, reduced, phase, typed, step, streamed, demo]);

  const showSteps = phase === "steps";
  const showAnswer = phase === "streaming" || phase === "done";
  const done = phase === "done";

  return (
    <div
      ref={rootRef}
      className="rounded-card border border-md-outline-variant bg-md-surface-container-lowest p-7 shadow-[var(--shadow-popover)]"
      aria-live="polite"
    >
      <div className="mb-4 flex items-center gap-2 border-b border-md-outline-variant pb-3 text-[12px] text-md-on-surface-variant">
        <span className="size-2 rounded-full bg-md-primary-fixed-dim" aria-hidden />
        <span className="font-semibold tracking-[0.06em]">MEDIREG AI</span>
        <span className="ml-auto flex items-center gap-1.5">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-md-primary/60" />
            <span className="relative inline-flex size-2 rounded-full bg-md-primary" />
          </span>
          실시간 데모
        </span>
      </div>

      {/* 대화 영역 — 높이를 고정해 순환 중 레이아웃 점프 방지 */}
      <div className="flex min-h-[300px] flex-col gap-4">
        {typed ? (
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-2xl bg-md-primary px-5 py-3.5 text-[15.5px] leading-[1.7] text-md-on-primary">
              {typed}
              {phase === "typing" ? <span className="ml-0.5 inline-block w-[2px] animate-pulse bg-md-on-primary/80">&nbsp;</span> : null}
            </div>
          </div>
        ) : null}

        {showSteps ? (
          <ol className="flex flex-wrap items-center gap-2 pl-1 text-[13px] text-md-on-surface-variant">
            {STEPS.map((s, i) => (
              <li
                key={s}
                className={
                  "flex items-center gap-1 rounded-full border px-2.5 py-1 transition-colors " +
                  (i < step
                    ? "border-md-primary/30 bg-md-primary-container/60 text-md-on-primary-container"
                    : i === step
                      ? "border-md-primary/50 bg-md-primary-container text-md-on-primary-container"
                      : "border-md-outline-variant")
                }
              >
                <span className="material-symbols-outlined text-[14px]" aria-hidden>
                  {i < step ? "check" : i === step ? "progress_activity" : "radio_button_unchecked"}
                </span>
                <span className={i === step ? "font-medium" : ""}>{s}</span>
              </li>
            ))}
          </ol>
        ) : null}

        {showAnswer ? (
          <div className="flex justify-start">
            <div className="max-w-[92%] rounded-2xl bg-md-surface-container-low px-5 py-4 text-[15.5px] leading-[1.8] text-md-on-surface">
              <Cited text={streamed} />
              {!done ? <span className="ml-0.5 inline-block w-[2px] animate-pulse bg-md-on-surface/70">&nbsp;</span> : null}
            </div>
          </div>
        ) : null}

        {done ? (
          <div className="mt-1 flex flex-col gap-1.5 pl-1 animate-in fade-in slide-in-from-bottom-1 duration-500">
            <div className="flex items-center gap-2 text-[11.5px] text-md-on-surface-variant">
              <span className="material-symbols-outlined text-[15px] text-md-primary" aria-hidden>
                verified
              </span>
              근거 {demo.cites.length}건 · 원문 대조 검증됨
            </div>
            <ul className="flex flex-wrap gap-1.5">
              {demo.cites.map((c) => (
                <li
                  key={c.n}
                  className="flex items-center gap-1.5 rounded-lg border border-md-outline-variant bg-md-surface px-3 py-1.5 text-[13px] text-md-on-surface"
                >
                  <span className="font-mono text-[11px] font-semibold text-md-primary">[{c.n}]</span>
                  <span className="rounded bg-md-surface-container-high px-1.5 py-px text-[10.5px] text-md-on-surface-variant">
                    {c.kind}
                  </span>
                  <span className="max-w-[260px] truncate">{c.title}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** "[n]" 마커를 강조 — 실제 답변 화면의 인용 마커와 같은 모양 */
function Cited({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\[\d+\]$/.test(p) ? (
          <span key={i} className="mx-0.5 rounded bg-md-primary-container px-1 font-mono text-[11px] font-semibold text-md-on-primary-container">
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}
