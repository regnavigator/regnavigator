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
    category: "광고·심의",
    title: "의료기기 광고 심의 기준",
    question: "의료기기 광고 심의 기준이 어떻게 되나요?",
    answer:
      "의료기기 광고는 **사전 심의 의무**가 있으며, 심의 기준은 법령에서 정한 금지 사항을 중심으로 합니다.\n\n" +
      "**심의 대상 및 의무** — 의료기기를 광고하려는 자는 미리 자율심의기구(한국의료기기산업협회)의 심의를 받아야 합니다 [1]. 심의 대상 매체는 인터넷뉴스서비스, 방송사업자 인터넷홈페이지, 일일 평균 이용자 10만 명 이상의 SNS 등입니다 [2].\n\n" +
      "**금지 사항** [3] — 거짓이거나 오해할 염려가 있는 사항, 허가·인증을 받지 않았거나 신고한 사항과 다른 성능·효능, 객관적 근거 없는 안전성·효능 주장, 의료기기로 오인하게 하는 표현.\n\n" +
      "**심의 기구** — 자율심의기구는 의료기기광고심의위원회를 설치·운영하며 10~20명의 위원으로 구성됩니다 [4]. 심의받은 광고는 심의 내용 그대로 광고해야 하고, 내용이 바뀌면 재심의 대상입니다 [5].",
    cites: [
      { n: 1, kind: "법령", title: "의료기기법 제25조(광고의 심의)" },
      { n: 2, kind: "법령", title: "의료기기법 시행령 제10조의3" },
      { n: 3, kind: "법령", title: "의료기기법 제24조(기재 및 광고의 금지 등)" },
      { n: 4, kind: "법령", title: "의료기기법 제25조의3" },
      { n: 5, kind: "가이드라인", title: "의료기기 사후관리 제도개선 해설서 — 6. 광고의 심의" },
    ],
    next: ["의료기기 광고에서 구체적으로 어떤 표현이 금지되나요?", "심의 신청부터 승인까지 절차와 기간은?", "심의 규정을 위반하면 어떤 처벌을 받나요?"],
    timing: "첫 글자 22초 · 전체 42초 · 근거 40건(검증 35)",
  },
  {
    category: "서류 작성",
    title: "IRB 심의 의뢰서 초안 작성",
    question: "IRB 심의 의뢰서 초안을 작성하려면 어떤 항목이 필요한가요?",
    answer:
      "IRB 심의 의뢰서 초안 작성에 필요한 항목은 **연구의 유형과 기관의 표준운영지침에 따라 달라집니다** [1]. 일반적으로 다음 항목이 포함됩니다.\n\n" +
      "**기본 항목** — 연구계획명(국문·영문), 책임연구자 정보(성명·부서·직위), 공동연구자, 연구 예정 기간, 연구 종류 및 심의 구분(신규/지속/변경).\n\n" +
      "**연구 내용** — 연구 목적 및 의의, 연구 설계(방법·대상자 수·군 정보), 예상 부작용, 수행 기관(단일/다기관).\n\n" +
      "**제출 서류** — 연구계획서, 대상자 동의서 및 설명문 [2], 이해상충 서식, 필요 시 증빙자료.\n\n" +
      "각 기관 IRB 는 자체 표준운영지침을 운영하므로 정확한 항목과 제출 방식은 해당 기관 IRB 에 사전 확인이 필요합니다 [1]. 기관 서식이 검색되면 [서류 초안 작성] 버튼으로 그 자리에서 채울 수 있습니다.",
    cites: [
      { n: 1, kind: "가이드라인", title: "건강기능식품 개발자를 위한 인체적용시험 설계 가이드 — 심의의 구분" },
      { n: 2, kind: "가이드라인", title: "임상시험 대상자 동의설명서 및 피해보상 가이드라인 해설서" },
    ],
    next: ["IRB 심의 신청부터 승인까지 전체 절차와 기한을 알려줘", "IRB 심의용 연구계획서에 포함되어야 할 핵심 내용은?", "임상시험 대상자 동의서 및 설명문의 필수 항목은?"],
    timing: "첫 글자 19초 · 전체 30초 · 근거 37건(검증 32)",
  },
  {
    category: "임상시험",
    title: "임상시험 IND 승인 절차",
    question: "임상시험 IND 승인 절차를 알려주세요",
    answer:
      "IND(임상시험계획 승인) 절차는 **의료기기와 의약품이 다릅니다.**\n\n" +
      "**의료기기** — 품목허가용 안전성·유효성 자료 수집, 연구용·성능비교·가교시험이 신청 대상이며 처리기간은 근무일 기준 30일입니다 [1]. 제출 서류는 임상시험계획 승인신청서(시행규칙 별지 제19호), 임상시험계획서, 임상시험용 의료기기 GMP 자료, 비임상시험 자료 등입니다 [1][2].\n" +
      "절차: 신청 접수 → 심사(30일) → 1차 보완(필요시 30일) → 2차 보완(필요시 30일) → 식약처장 승인 [3]. 사전상담으로 계획서 초안을 미리 검토받으면 반려를 줄일 수 있습니다 [4].\n\n" +
      "**의약품** — 처리기간 근무일 30일, 핵심 제출 자료는 임상시험계획서·개발계획·임상시험용 의약품의 안전성 자료(비임상·품질)입니다 [5]. 의료기기보다 비임상 자료 요구 수준이 높은 경향이 있습니다.",
    cites: [
      { n: 1, kind: "법령", title: "의료기기법 제10조(임상시험계획의 승인 등)" },
      { n: 2, kind: "가이드라인", title: "의료기기 임상시험 안내서 — 2.2 임상시험계획(변경)승인" },
      { n: 3, kind: "가이드라인", title: "디지털의료기기 임상시험등 관련 가이드라인(민원인안내서) — 4 임상시험등 계획 승인" },
      { n: 4, kind: "고시", title: "디지털의료기기 임상시험등 계획 승인 및 실시·관리에 관한 규정" },
      { n: 5, kind: "고시", title: "의약품 임상시험 계획 승인에 관한 규정 제3조" },
    ],
    next: ["의료기기 임상시험계획 승인 신청 시 필요한 비임상시험 자료 요건을 자세히 알려줘", "의약품 임상시험계획 승인 신청 시 필요한 비임상·품질 자료 요건", "의료기기 임상시험 사전상담 신청 방법과 절차"],
    timing: "첫 글자 21초 · 전체 40초 · 근거 47건(검증 42)",
  },
  {
    category: "급여기준",
    title: "치료재료 산정 기준과 심사지침",
    question: "치료재료 산정 기준과 심사지침은 어떻게 되나요?",
    answer:
      "치료재료의 산정 기준과 심사지침은 건강보험심사평가원의 **「요양급여의 적용기준 및 방법에 관한 세부사항과 심사지침」**에 규정되어 있습니다 [1].\n\n" +
      "**상한금액 기준** — 치료재료는 「치료재료 급여·비급여목록 및 급여상한금액표」에 고시된 상한금액 범위 내에서 요양기관의 실구입가로 산정됩니다 [2].\n\n" +
      "**별도 산정 여부** — 수술료·시술료에 포함되는지, 별도 산정인지는 시술·재료 종류별로 심사지침이 정합니다. 예를 들어 Drill Bit 는 체내 고정용 나사 삽입 시 쓰는 내구성 제제로 수술료에 포함되어 별도 산정 불가 [3], 특정 카테터·가이드와이어는 별도 산정 가능 [2].\n\n" +
      "**심사 기준** — 재료별 인정 기준·산정 코드·상한금액이 세부 지침에 명시되어 있고 심평원이 이를 기준으로 심사합니다 [1]. 불명확하면 심평원에 유권해석을 요청할 수 있습니다.",
    cites: [
      { n: 1, kind: "급여기준", title: "요양급여의 적용기준 및 방법에 관한 세부사항과 심사지침" },
      { n: 2, kind: "급여기준", title: "요양급여의 적용기준 및 방법에 관한 세부사항과 심사지침 — 치료재료 산정" },
      { n: 3, kind: "급여기준", title: "요양급여의 적용기준 및 방법에 관한 세부사항과 심사지침 — 별도 산정 불가 재료" },
    ],
    next: ["특정 치료재료의 별도 산정 가능 여부는 어떻게 확인하나요?", "치료재료 상한금액표는 어디서 보나요?", "치료재료 산정 기준에 대해 심평원에 문의하는 방법은?"],
    timing: "첫 글자 13초 · 전체 30초 · 근거 13건(검증 8)",
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
                  <span className="font-semibold tracking-[0.06em]">MEDIREG AI</span>
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
