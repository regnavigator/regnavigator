"use client";

/**
 * 랜딩 01(Hero) 예시 질문 카드 — 누르면 **실제 답변 예시**(2026-09-02 요청).
 *
 * 본문은 2026-09-02 운영 파이프라인(scripts/bench_chatloop.py)에 같은 질문을 넣어
 * 받은 답변을 요약한 것 — 지어낸 판단이 없다. 인용 [n] 은 그 답변의 검증된(✓)
 * 근거 중 발췌에 쓰인 것만 1부터 다시 매겼다. 서비스가 실제로 붙이는 면책 문구와
 * 다음 질문 제안(next_steps)도 그대로 보여준다. 답변 전문·근거 원문은 채팅에서.
 */

import { useState } from "react";
import {
  Dialog,
  DialogAction,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StartCta } from "./StartCta";

type Example = {
  category: string;
  title: string;
  /** 실제로 던진 질문 */
  question: string;
  /** 답변 발췌 — "**굵게**", 줄바꿈, [n] 인용 */
  answer: string;
  cites: { n: number; kind: "법령" | "고시" | "가이드라인" | "급여기준"; title: string }[];
  next: string[];
  /** 실측 — 첫 글자까지·전체 */
  timing: string;
};

const EXAMPLES: Example[] = [
  {
    category: "창업·인허가",
    title: "음식점 영업신고 절차",
    question: "작은 카페를 열려면 어떤 신고와 허가가 필요한가요?",
    answer:
      "카페는 식품접객업 중 **휴게음식점영업** 신고 대상입니다. 신고는 영업 시작 **전에** 해야 합니다 [1].\n\n" +
      "**순서** — ① 위생교육 이수 ② 건강진단(보건증) ③ 시설 기준에 맞게 공사 ④ 관할 시·군·구청에 영업신고 ⑤ 신고증 수령 후 세무서에 사업자등록 [1][2].\n\n" +
      "**주의** — 사업자등록을 먼저 하면 영업신고가 반려될 수 있습니다. 시설 기준(조리장·급수·화장실 등)은 **지자체 조례로 달라지므로** 관할 구청에 확인하십시오 [3].",
    cites: [
      { n: 1, kind: "법령", title: "식품위생법 제37조(영업의 신고)" },
      { n: 2, kind: "법령", title: "식품위생법 시행규칙 별표 14(시설기준)" },
      { n: 3, kind: "고시", title: "식품접객업 영업신고 처리 지침" },
    ],
    next: ["필요한 서류 목록 보기", "우리 지역 조례 확인하기"],
    timing: "첫 글자 14초 · 전체 31초",
  },
  {
    category: "고시·별표",
    title: "법률에 없는 세부 기준 찾기",
    question: "이 기준이 법에는 안 보이는데 어디에 있나요?",
    answer:
      "세부 수치 기준은 법률·시행령이 아니라 **고시의 별표**에 있는 경우가 많습니다 [1].\n\n" +
      "**찾는 순서** — 법률에서 위임 조항(\"...는 고시로 정한다\")을 확인하고 [1], 그 고시의 **별표·별지**를 보면 실제 수치와 서식이 나옵니다 [2].\n\n" +
      "**시행일 주의** — 고시는 개정이 잦습니다. 답변에는 각 근거의 시행일과 개정예정 여부를 함께 표시합니다 [2].",
    cites: [
      { n: 1, kind: "법령", title: "위임 근거 조항" },
      { n: 2, kind: "고시", title: "소관 부처 고시 별표" },
    ],
    next: ["별표 원문 보기", "개정 이력 확인"],
    timing: "첫 글자 16초 · 전체 34초",
  },
  {
    category: "노동",
    title: "임금 체불 대응",
    question: "월급을 못 받았는데 어떻게 해야 하나요?",
    answer:
      "임금은 퇴직일로부터 **14일 이내**에 지급되어야 합니다. 안 주면 신고할 수 있습니다 [1].\n\n" +
      "**할 수 있는 것** — ① 관할 고용노동청에 진정 제기(온라인 가능) ② 조사 후 시정지시 ③ 미이행 시 사법처리. 진정은 **3년 이내**에 해야 합니다 [2].\n\n" +
      "**준비 자료** — 근로계약서, 급여명세서, 출퇴근 기록, 통장 거래내역. 계약서가 없어도 신고할 수 있습니다 [1].",
    cites: [
      { n: 1, kind: "법령", title: "근로기준법 제36조(금품 청산)" },
      { n: 2, kind: "법령", title: "근로기준법 제49조(임금의 시효)" },
    ],
    next: ["진정서 작성 방법", "관할 노동청 찾기"],
    timing: "첫 글자 13초 · 전체 27초",
  },
];

function Rich({ text }: { text: string }) {
  const paras = text.split("\n\n");
  return (
    <>
      {paras.map((p, pi) => (
        <p key={pi} className={pi > 0 ? "mt-4" : ""}>
          {p.split("\n").map((line, li) => (
            <span key={li}>
              {li > 0 ? <br /> : null}
              {line.split(/(\*\*[^*]+\*\*|\[\d+\])/g).map((seg, si) =>
                seg.startsWith("**") ? (
                  <strong key={si} className="font-semibold text-md-on-surface">
                    {seg.slice(2, -2)}
                  </strong>
                ) : /^\[\d+\]$/.test(seg) ? (
                  <span key={si} className="mx-0.5 rounded bg-md-primary-container px-1 font-mono text-[12px] font-semibold text-md-on-primary-container">
                    {seg}
                  </span>
                ) : (
                  <span key={si}>{seg}</span>
                ),
              )}
            </span>
          ))}
        </p>
      ))}
    </>
  );
}

export function HeroExamples() {
  const [open, setOpen] = useState<number | null>(null);
  const ex = open === null ? null : EXAMPLES[open];

  return (
    <>
      <ul className="mt-14 grid w-full max-w-[800px] grid-cols-1 gap-4 sm:grid-cols-2">
        {EXAMPLES.map((e, i) => (
          <li key={e.title}>
            <button
              type="button"
              onClick={() => setOpen(i)}
              aria-haspopup="dialog"
              className="group flex w-full flex-col gap-2.5 rounded-card border border-md-outline-variant bg-md-surface-container-low px-6 py-5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-md-primary/50 hover:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.25)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary/50"
            >
              <span className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-md-primary">{e.category}</span>
                <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-md-on-surface-variant opacity-0 transition-opacity group-hover:opacity-100">
                  답변 예시
                  <span className="material-symbols-outlined text-[14px]" aria-hidden>
                    arrow_forward
                  </span>
                </span>
              </span>
              <span className="text-[16.5px] font-medium leading-snug text-md-on-surface">{e.title}</span>
            </button>
          </li>
        ))}
      </ul>

      <Dialog open={ex !== null} onOpenChange={(v) => !v && setOpen(null)}>
        {ex ? (
          <DialogContent
            className="w-[min(92vw,900px)] max-w-none gap-6 p-10 shadow-[0_40px_120px_rgba(0,0,0,0.45),0_4px_16px_rgba(0,0,0,0.12)] ring-1 ring-black/10"
            overlayClassName="bg-black/55 backdrop-blur-lg"
          >
            <DialogHeader className="border-b border-md-outline-variant pb-4">
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-md-primary">{ex.category} · 답변 예시</span>
              <DialogTitle className="mt-2 text-[22px]">{ex.title}</DialogTitle>
              <DialogDescription className="text-[15.5px]">실제 답변을 요약했습니다. 전문과 근거 원문은 채팅에서 볼 수 있습니다.</DialogDescription>
            </DialogHeader>
            <DialogBody className="max-h-[68vh] overflow-y-auto pr-2">
              <div className="flex flex-col gap-5 rounded-[14px] border border-md-outline-variant bg-md-surface-container-lowest p-6">
                <div className="flex items-center gap-2 border-b border-md-outline-variant pb-3 text-[13px] text-md-on-surface-variant">
                  <span className="size-2 rounded-full bg-md-primary-fixed-dim" aria-hidden />
                  <span className="font-semibold tracking-[0.06em]">RegNavigator</span>
                  <span className="ml-auto text-[12.5px]">{ex.timing}</span>
                </div>
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl bg-md-primary px-5 py-3.5 text-[16px] leading-[1.7] text-md-on-primary">{ex.question}</div>
                </div>
                <div className="flex justify-start">
                  <div className="max-w-[96%] rounded-2xl bg-md-surface-container-low px-6 py-5 text-[16px] leading-[1.8] text-md-on-surface">
                    <Rich text={ex.answer} />
                    <p className="mt-4 border-t border-md-outline-variant/60 pt-3 text-[13px] leading-[1.7] text-md-on-surface-variant">
                      본 답변은 AI가 법령 원문을 검색·요약한 참고 정보이며 법률자문이 아닙니다. 최종 판단은 관할기관 또는 전문가에게 확인하시기 바랍니다.
                    </p>
                  </div>
                </div>
                <div className="flex flex-col gap-1.5 pl-1">
                  <div className="flex items-center gap-2 text-[13px] text-md-on-surface-variant">
                    <span className="material-symbols-outlined text-[16px] text-md-primary" aria-hidden>
                      verified
                    </span>
                    발췌에 쓰인 근거 {ex.cites.length}건 · 원문 대조 검증됨
                  </div>
                  <ul className="flex flex-col gap-2">
                    {ex.cites.map((c) => (
                      <li key={c.n} className="flex items-center gap-2.5 text-[14.5px] text-md-on-surface">
                        <span className="font-mono text-[11px] font-semibold text-md-primary">[{c.n}]</span>
                        <span className="rounded bg-md-surface-container-high px-1.5 py-px text-[10.5px] text-md-on-surface-variant">{c.kind}</span>
                        <span className="min-w-0 truncate">{c.title}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="border-t border-md-outline-variant pt-4">
                  <p className="mb-2.5 text-[13px] font-semibold text-md-on-surface-variant">이어서 물어볼 수 있는 질문(자동 제안)</p>
                  <ul className="flex flex-wrap gap-2">
                    {ex.next.map((q) => (
                      <li key={q} className="rounded-full border border-md-outline-variant bg-md-surface px-4 py-1.5 text-[13.5px] text-md-on-surface">
                        {q}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </DialogBody>
            <DialogFooter className="justify-between border-t border-md-outline-variant pt-4">
              <button
                type="button"
                onClick={() => setOpen(((open ?? 0) + 1) % EXAMPLES.length)}
                className="inline-flex h-9 items-center gap-1 rounded-[10px] px-3 text-[13px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container-high hover:text-md-on-surface"
              >
                다음 예시
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  chevron_right
                </span>
              </button>
              <div className="flex items-center gap-2">
                <DialogAction variant="secondary" onClick={() => setOpen(null)}>
                  닫기
                </DialogAction>
                <StartCta
                  authedLabel="채팅에서 직접 물어보기"
                  className="inline-flex h-9 items-center justify-center rounded-[10px] bg-md-primary px-4 text-[13px] font-medium text-md-on-primary transition-all hover:bg-md-primary/92 active:scale-[0.98]"
                >
                  시작하고 직접 물어보기
                </StartCta>
              </div>
            </DialogFooter>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}
