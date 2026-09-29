"use client";

/**
 * 랜딩 02(IRB·DRB) 단계 카드 — 누르면 **실제 사용 예시**(2026-09-02 피드백).
 *
 * 카드 설명만으로는 "물어보면 어떤 식으로 나오는지"가 안 보였다. 카드마다
 * 대표 대화 한 토막(질문 → 확인 질문 → 예비판정/절차)을 모달로 보여준다.
 * 예시는 irb-triage / drb-triage / irb-procedure 스킬의 실제 동작 규칙을 따른다:
 * 추정 금지(결정적 슬롯은 하나씩 확인), 판정 + 판단 경로 + 근거 조항 위치,
 * 기관 예비판단 고지. 기관 규정 원문은 노출하지 않는다(요지·조항 위치만).
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

type Line =
  | { role: "user"; text: string }
  | { role: "ai"; text: string; verdict?: { label: string; tone: "ok" | "warn" | "info" } }
  | { role: "ui"; text: string };

type Example = {
  icon: string;
  title: string;
  desc: string;
  /** 모달 제목 밑 한 줄 — 이 예시가 보여주는 것 */
  lead: string;
  /** 단계 칩 — 흐름을 한눈에 */
  flow: string[];
  lines: Line[];
};

const EXAMPLES: Example[] = [
  {
    icon: "rule",
    title: "심의 유형 예비판정",
    desc: "연구 설계(후향/전향, 대상, 데이터)를 바탕으로 심의면제·신속·정규를 근거 조항과 함께 판정.",
    lead: "연구를 한 문장으로 말하면, 판정에 필요한 것만 확인하고 판정합니다.",
    flow: ["연구 개요", "확인 질문", "예비판정 + 근거"],
    lines: [
      {
        role: "user",
        text: "2020~2024년 당뇨 환자 500명 의무기록을 후향적으로 분석하려고 합니다. IRB 심의 받아야 하나요?",
      },
      {
        role: "ai",
        text: "후향적 의무기록(차트리뷰) 연구로 이해했습니다. 판정에 결정적인 한 가지만 확인할게요 — 분석 데이터에 성명·등록번호 같은 식별정보가 포함되나요, 아니면 익명·가명 처리된 자료만 쓰시나요?",
      },
      { role: "user", text: "연구용 번호로 바꿔서 가명처리된 자료만 씁니다." },
      {
        role: "ai",
        text:
          "예비판정: 심의면제 대상.\n" +
          "판단 경로: ① 사람 대상 연구 → 심의 대상 ② 기존 자료(의무기록) 이용 ③ 가명처리, 연구자가 식별정보에 접근하지 않음 ④ 취약 대상자·민감 정보 특례 해당 없음 → 심의면제 요건 충족.\n" +
          "단, 면제도 **면제 심의 의뢰서 제출과 전문간사 평가**는 필요합니다. 근거: 기관 IRB SOP 심의면제 조항(면제 유형 '기존 자료·문서 이용 연구').\n" +
          "AI의 예비판단입니다. 최종 판정은 소속 기관 IRB 사무국을 따릅니다.",
      },
    ],
  },
  {
    icon: "database",
    title: "DRB 의료데이터 심의",
    desc: "EMR·검사결과·잔여검체를 쓰는 연구는 IRB와 별도로 DRB 대상 여부를 함께 확인.",
    lead: "같은 대화에서 이어서 물으면, 데이터 반출 여부를 확인하고 DRB 종류와 IRB와의 순서까지 답합니다.",
    flow: ["이어서 질문", "반출 여부 확인", "DRB 판정 + 순서"],
    lines: [
      { role: "user", text: "그럼 병원 EMR 데이터를 쓰는 거라 DRB도 따로 받아야 하나요?" },
      {
        role: "ai",
        text: "네, 병원 의료정보데이터를 연구에 활용하면 IRB와 별도로 DRB(의료정보데이터심의위원회) 심의 대상입니다. 종류를 가르는 한 가지 — 가명처리한 개별 환자 단위 데이터를 병원 밖으로 반출하거나 외부 기관과 결합하나요, 아니면 원내 분석 환경 안에서만 분석하나요?",
      },
      { role: "user", text: "원내 폐쇄형 분석실에서만 분석하고 결과 통계만 가져갑니다." },
      {
        role: "ai",
        text:
          "예비판정: DRB 신속심의 대상.\n" +
          "원시데이터 반출·외부 결합이 없고 원내 분석에 한정되므로 신속심의 요건에 해당합니다(반출·결합이 있으면 정규심의).\n" +
          "순서: IRB 승인(또는 면제 확인) → DRB 신청. DRB 승인 유효기간은 IRB 승인기간에 종속됩니다.\n" +
          "근거: 기관 DRB 표준운영지침 심의 종류 조항. 예비판단이며 최종 확정은 위원회 사무국 검토를 따릅니다.",
      },
    ],
  },
  {
    icon: "edit_document",
    title: "절차·서식까지 연결",
    desc: "판정에 맞는 신청 절차와 제출 서류를 안내하고, 심의 의뢰서 초안까지 만들어 드립니다.",
    lead: "판정이 나면 무엇을 언제 내야 하는지 목록으로 받고, 의뢰서는 초안을 받아 채운 뒤 Word 파일로 내려받습니다.",
    flow: ["제출 서류 목록", "[서류 초안 작성]", "초안 채우기 → Word"],
    lines: [
      { role: "user", text: "면제 심의 의뢰서는 뭘 준비해서 어디에 내면 되나요?" },
      {
        role: "ai",
        text:
          "심의면제 의뢰 시 제출 서류(기관 IRB SOP 「47. 다.(13)」 기준):\n" +
          "1. 심의면제 의뢰서 [서식 1]  2. 연구계획서 요약  3. 연구대상자 동의서 면제 사유서\n" +
          "4. 연구책임자 이력서  5. 연구비내역서 제출 면제 사유서 등\n" +
          "절차: 행정간사 접수 → 전문간사 평가 → 면제 여부 결정 → 검토결과 통보. SOP 다른 조항(「5. 다.(1)」)의 목록과 차이가 있어 제출 전 사무국 확인을 권합니다. 의뢰서는 아래 버튼으로 바로 작성할 수 있습니다.",
      },
      { role: "ui", text: "[서류 초안 작성] 버튼 → 백그라운드에서 의뢰서 초안 작성(수 분 이상)" },
      {
        role: "ai",
        text: "초안이 완성되면 작성 화면에서 이어서 채웁니다. 대화로 \"연구 제목은 ○○, 연구책임자는 ○○\"라고 말하면 해당 칸이 채워지고, 직접 입력도 됩니다. 기관 서식은 원본 파일이 없어 Word 파일로 내려받아 기관 양식에 옮겨 제출합니다. 성명·연락처 같은 개인정보는 외부 AI로 보내지 않습니다.",
      },
    ],
  },
];

function Bubble({ line }: { line: Line }) {
  if (line.role === "ui") {
    return (
      <div className="my-1 flex justify-center">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-md-outline-variant px-3.5 py-1.5 text-[13.5px] text-md-on-surface-variant">
          <span className="material-symbols-outlined text-[15px]" aria-hidden>
            touch_app
          </span>
          {line.text}
        </span>
      </div>
    );
  }
  const isUser = line.role === "user";
  const verdict = line.role === "ai" ? line.verdict : undefined;
  const toneCls =
    verdict?.tone === "ok"
      ? "bg-md-primary-fixed text-md-on-primary-fixed-variant"
      : verdict?.tone === "warn"
        ? "bg-md-error-container text-md-on-error-container"
        : "bg-md-tertiary-container text-md-on-tertiary-container";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={
          "max-w-[88%] whitespace-pre-line break-keep rounded-2xl px-6 py-4 text-[16px] leading-[1.8] [overflow-wrap:anywhere] " +
          (isUser
            ? "bg-md-primary text-md-on-primary"
            : "bg-md-surface-container-low text-md-on-surface")
        }
      >
        {verdict ? (
          <span className={`mb-2.5 flex w-fit rounded-full px-3 py-1 text-[12.5px] font-semibold ${toneCls}`}>
            {verdict.label}
          </span>
        ) : null}
        {renderBold(line.text)}
      </div>
    </div>
  );
}

/** "**굵게**" 최소 마크업만 — 예시 텍스트의 강조용 */
function renderBold(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? (
      <strong key={i} className="font-semibold">
        {p.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{p}</span>
    ),
  );
}

export function IrbExampleCards() {
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const ex = openIdx === null ? null : EXAMPLES[openIdx];

  return (
    <>
      <ul className="mt-16 grid grid-cols-1 gap-5 sm:grid-cols-3">
        {EXAMPLES.map((c, i) => (
          <li key={c.title}>
            <button
              type="button"
              onClick={() => setOpenIdx(i)}
              aria-haspopup="dialog"
              className="group relative flex h-full w-full flex-col gap-4 overflow-hidden rounded-card border border-md-outline-variant bg-md-surface-container-low p-7 text-left transition-all duration-200 hover:-translate-y-1 hover:border-md-primary/50 hover:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.25)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary/50"
            >
              <span
                aria-hidden
                className="absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r from-md-primary to-md-tertiary opacity-70 transition-opacity group-hover:opacity-100"
              />
              <div className="flex items-center justify-between">
                <span
                  aria-hidden
                  className="inline-flex size-11 items-center justify-center rounded-xl bg-md-primary-container text-md-primary transition-transform duration-200 group-hover:scale-105"
                >
                  <span className="material-symbols-outlined text-[24px]">{c.icon}</span>
                </span>
                <span
                  className="text-[22px] font-bold tabular-nums text-md-outline-variant"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
              </div>
              <h3 className="text-[17.5px] font-bold tracking-tight text-md-on-surface">{c.title}</h3>
              <p className="text-[15px] leading-[1.75] text-md-on-surface-variant">{c.desc}</p>
              <span className="mt-auto inline-flex items-center gap-1 pt-1 text-[12.5px] font-semibold text-md-primary">
                실제 사용 예시 보기
                <span className="material-symbols-outlined text-[16px] transition-transform group-hover:translate-x-0.5" aria-hidden>
                  arrow_forward
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      <Dialog open={ex !== null} onOpenChange={(v) => !v && setOpenIdx(null)}>
        {ex ? (
          <DialogContent
            className="w-[min(92vw,900px)] max-w-none gap-6 p-10 shadow-[0_40px_120px_rgba(0,0,0,0.45),0_4px_16px_rgba(0,0,0,0.12)] ring-1 ring-black/10"
            overlayClassName="bg-black/55 backdrop-blur-lg"
          >
            <DialogHeader className="border-b border-md-outline-variant pb-4">
              <DialogTitle>
                {String((openIdx ?? 0) + 1).padStart(2, "0")} · {ex.title} — 실제 사용 예시
              </DialogTitle>
              <DialogDescription className="text-[15.5px]">{ex.lead}</DialogDescription>
            </DialogHeader>
            <DialogBody className="max-h-[68vh] overflow-y-auto pr-2">
              <ol className="mb-5 flex flex-wrap items-center gap-2 text-[13px] text-md-on-surface-variant">
                {ex.flow.map((f, i) => (
                  <li key={f} className="flex items-center gap-1.5">
                    <span className="rounded-full bg-md-surface-container px-2.5 py-0.5 font-medium text-md-on-surface">
                      {f}
                    </span>
                    {i < ex.flow.length - 1 ? (
                      <span className="material-symbols-outlined text-[14px]" aria-hidden>
                        chevron_right
                      </span>
                    ) : null}
                  </li>
                ))}
              </ol>
              <div className="flex flex-col gap-5 rounded-[14px] border border-md-outline-variant bg-md-surface-container-lowest p-6 shadow-[inset_0_1px_0_rgba(255,255,255,0.6)]">
                <div className="flex items-center gap-2 border-b border-md-outline-variant pb-3 text-[13px] text-md-on-surface-variant">
                  <span className="size-2 rounded-full bg-md-primary-fixed-dim" aria-hidden />
                  <span className="font-semibold tracking-[0.06em]">MEDIREG AI</span>
                  <span className="ml-auto">예시 대화 — 실제 답변은 입력한 연구 내용에 따라 달라집니다</span>
                </div>
                {ex.lines.map((l, i) => (
                  <Bubble key={i} line={l} />
                ))}
              </div>
              <p className="mt-5 text-[13.5px] leading-[1.7] text-md-on-surface-variant/80">
                판정 기준: 화순전남대학교병원 IRB·DRB 지침. 기관 규정 원문은 노출하지 않고 조항 위치와
                요지만 안내합니다. AI의 예비판단이며 최종 판단은 소속 기관 심의 사무국을 따릅니다.
              </p>
            </DialogBody>
            <DialogFooter className="justify-between border-t border-md-outline-variant pt-4">
              <button
                type="button"
                onClick={() => setOpenIdx(((openIdx ?? 0) + 1) % EXAMPLES.length)}
                className="inline-flex h-9 items-center gap-1 rounded-[10px] px-3 text-[13px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container-high hover:text-md-on-surface"
              >
                다음 예시
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  chevron_right
                </span>
              </button>
              <div className="flex items-center gap-2">
                <DialogAction variant="secondary" onClick={() => setOpenIdx(null)}>
                  닫기
                </DialogAction>
                <StartCta
                  authedLabel="채팅에서 직접 해보기"
                  className="inline-flex h-9 items-center justify-center rounded-[10px] bg-md-primary px-4 text-[13px] font-medium text-md-on-primary transition-all hover:bg-md-primary/92 active:scale-[0.98]"
                >
                  시작하고 직접 해보기
                </StartCta>
              </div>
            </DialogFooter>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}
