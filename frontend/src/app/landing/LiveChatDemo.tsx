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
    question: "전세 보증금을 안 돌려주는데 어떻게 하나요?",
    answer:
      "계약이 끝났는데 보증금을 안 주면 **임차권등기명령**을 먼저 신청할 수 있습니다 [1]. 등기가 되면 이사를 가도 대항력과 우선변제권이 유지됩니다 [1]. 이후 보증금반환청구 소송이나 지급명령으로 회수합니다 [2]. 계약 종료 전이라면 갱신 거절 통지를 **만료 6개월~2개월 전**에 해야 합니다 [3].",
    cites: [
      { n: 1, kind: "법령", title: "주택임대차보호법 제3조의3(임차권등기명령)" },
      { n: 2, kind: "법령", title: "민사집행법 제56조(지급명령)" },
      { n: 3, kind: "법령", title: "주택임대차보호법 제6조(계약의 갱신)" },
    ],
  },
  {
    question: "중대재해가 발생하면 언제까지 보고해야 하나요?",
    answer:
      "중대재해 발생 사실을 알게 된 때 **지체 없이** 관할 지방고용노동관서에 전화·팩스 등으로 보고해야 합니다 [1]. 보고 항목은 발생 개요와 피해 상황, 조치 및 전망 등입니다 [2]. 산업재해조사표는 발생일로부터 **1개월 이내** 제출합니다 [2]. 보고를 누락하면 과태료가 부과됩니다 [1].",
    cites: [
      { n: 1, kind: "법령", title: "산업안전보건법 제54조(중대재해 발생 시 사업주의 조치)" },
      { n: 2, kind: "법령", title: "산업안전보건법 시행규칙 제73조(산업재해 보고)" },
    ],
  },
  {
    question: "옥외광고물 설치에 허가가 필요한가요?",
    answer:
      "종류·규격·장소에 따라 **허가 대상**과 **신고 대상**이 갈립니다 [1]. 다만 구체적인 크기 제한과 금지 구역은 **지자체 조례**가 정하므로 같은 간판이라도 관할에 따라 달라집니다 [2]. 허가 없이 설치하면 이행강제금 대상입니다 [1]. 관할 시·군·구에 사전 확인을 권합니다.",
    cites: [
      { n: 1, kind: "법령", title: "옥외광고물 등의 관리와 옥외광고산업 진흥에 관한 법률 제3조" },
      { n: 2, kind: "자치법규", title: "시·군·구 옥외광고물 등 관리 조례" },
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
        <span className="font-semibold tracking-[0.06em]">RegNavigator</span>
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
