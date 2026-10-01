"use client";

/**
 * EmptyHero — 03 §10. Claude 톤 (기존 디자인 유지).
 *
 * - 시간대 + 사용자 이름 동적 인사 (그라데이션 텍스트)
 * - 1줄 invitation 카피
 * - 4개 빠른 프롬프트 카드 (gap-px divider 트릭, 평면)
 * - 하단 disclaimer
 *
 * medra 테마 swap 시 색·폰트는 token으로 자동 적용.
 */

import { useMemo, useState } from "react";
import { useMode } from "@/components/providers/ModeProvider";
import { useSession } from "next-auth/react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

type FormField = {
  key: string;
  label: string;
  placeholder: string;
  required?: boolean;
};

type SamplePrompt = {
  category: string;
  title: string;
  subtitle: string;
  /** 구조화 입력 폼 — 있으면 클릭 시 필드 폼으로 프롬프트 조립(질문 품질↑). */
  form?: { intro: string; fields: FormField[]; build: (v: Record<string, string>) => string };
  /** 2열 전체 폭 카드 (IRB/DRB 같은 대표 진입점) */
  featured?: boolean;
  /** 이 질문으로 답변에서 얻는 것 — 예시 모달의 안내(2026-09-08). 2~3개 */
  expects: string[];
};

// 역할(RA/QA·인허가 컨설턴트·의사) 실무를 겨냥. 소스 다양성(법령·별표/서식·판례)
// 을 발견하도록 구성 — 허가·서식(별표), 판례/해석, 광고심의, 임상시험.
/** 카테고리별 아이콘 — 목록 행 좌측. */
const CATEGORY_ICON: Record<string, string> = {
  "허가·서식": "description",
  "광고·심의": "campaign",
  "임상시험": "science",
  "판례·해석": "gavel",
  "연구 심의 (IRB·DRB)": "fact_check",
};

const EXPERT_PROMPTS: SamplePrompt[] = [
  {
    category: "인허가·서식",
    title: "인허가 절차와 제출 서식 찾기",
    subtitle: "단계별 절차 · 별표/서식 · 필요 서류",
    expects: [
      "허가·등록·신고 중 어디에 해당하는지와 단계별 절차",
      "제출할 별표·서식과 첨부 서류 목록(원본 서식 바로 작성 가능)",
      "근거 조문과 시행일",
    ],
    form: {
      intro: "대상을 적으면 더 정확한 절차·서식 안내를 받을 수 있습니다.",
      fields: [
        { key: "subject", label: "대상 (사업·제품·행위)", placeholder: "예: 체외진단 의료기기 / 일반음식점" },
        { key: "detail", label: "추가 조건 (선택)", placeholder: "예: 2등급, 수입" },
      ],
      build: (v) =>
        v.subject
          ? `${v.subject}${v.detail ? ` (${v.detail})` : ""} 인허가 절차를 단계별로 알려줘. 제출해야 하는 서식·별표와 필요 서류도 함께 정리해줘.`
          : "인허가 절차를 단계별로 알려줘. 제출 서식·별표와 필요 서류도 정리해줘.",
    },
  },
  {
    category: "고시·별표",
    title: "고시·행정규칙의 세부 기준 확인",
    subtitle: "별표 본문 · 적용 범위 · 개정 이력",
    expects: [
      "법률·시행령에 없고 고시 별표에만 있는 세부 기준",
      "적용 대상과 예외",
      "최근 개정 여부와 시행일",
    ],
  },
  {
    category: "자치법규",
    title: "지자체 조례로 달라지는 요건",
    subtitle: "관할별 편차 · 입지·시설 기준",
    expects: [
      "같은 사안에서 지자체별로 갈리는 요건",
      "조례·규칙 근거 조문",
      "관할 기관에 확인해야 할 항목",
    ],
  },
  {
    category: "판례·해석",
    title: "쟁점에 대한 판례·유권해석",
    subtitle: "쟁점 판례 · 행정해석 · 적용 범위",
    expects: [
      "법원이 어떻게 판단했는지(법원·심급 포함)",
      "행정해석과 판례가 갈리는 지점",
      "내 사안에 적용되는 범위",
    ],
  },
];

const PUBLIC_PROMPTS: SamplePrompt[] = [
  {
    category: "생활·계약",
    title: "임대차 보증금·계약 문제",
    subtitle: "보증금 반환 · 계약 해지 · 수리 책임",
    expects: [
      "지금 할 수 있는 조치를 순서대로",
      "근거가 되는 법 조문",
      "전문가 상담이 필요한 시점",
    ],
  },
  {
    category: "일터",
    title: "임금·해고·휴가 문제",
    subtitle: "체불 임금 · 해고 절차 · 연차",
    expects: [
      "어디에 어떻게 신고하는지",
      "근거 조문과 기한",
      "준비해야 할 자료",
    ],
  },
  {
    category: "창업·영업",
    title: "업종별 인허가와 영업신고",
    subtitle: "필요한 허가 · 순서 · 제출 서류",
    expects: [
      "무엇을 → 어디에 → 어떤 서류로 내는지",
      "인허가와 사업자등록의 선후",
      "관할 지자체에 확인할 항목",
    ],
    form: {
      intro: "업종을 적으면 더 정확한 절차를 안내받을 수 있습니다.",
      fields: [
        { key: "biz", label: "업종", placeholder: "예: 카페 / 온라인 쇼핑몰" },
        { key: "region", label: "지역 (선택)", placeholder: "예: 서울 마포구" },
      ],
      build: (v) =>
        v.biz
          ? `${v.biz}${v.region ? ` (${v.region})` : ""} 창업에 필요한 인허가와 영업신고 절차를 순서대로 알려줘. 어디에 어떤 서류를 내야 하는지도 알려줘.`
          : "창업에 필요한 인허가와 영업신고 절차를 순서대로 알려줘.",
    },
  },
  {
    category: "행정처분",
    title: "과태료·행정처분을 받았을 때",
    subtitle: "이의신청 · 기한 · 감경 사유",
    expects: [
      "이의신청 방법과 기한",
      "감경·면제 사유가 있는지",
      "근거 조문",
    ],
  },
];

function getTimeGreeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "늦은 시간이네요";
  if (h < 11) return "좋은 아침이에요";
  if (h < 17) return "안녕하세요";
  if (h < 21) return "수고 많으셨어요";
  return "좋은 저녁이에요";
}

type Props = {
  configured: boolean;
  onPickPrompt?: (text: string) => void;
};

export function EmptyHero({ configured, onPickPrompt }: Props) {
  const { data: session } = useSession();
  // 구조화 폼 상태 — form 있는 카드 클릭 시 오픈.
  const [formPrompt, setFormPrompt] = useState<SamplePrompt | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const userName = useMemo(() => {
    const name = (session?.user as { name?: string | null } | undefined)?.name;
    const email = (session?.user as { email?: string | null } | undefined)?.email;
    if (name && name.trim()) return name.trim();
    if (email) return email.split("@")[0] ?? null;
    return null;
  }, [session]);

  const { showPro } = useMode();
  // 진입 경로에 따라 예시와 안내 문구가 갈린다(2026-10-01).
  const SAMPLE_PROMPTS = showPro ? EXPERT_PROMPTS : PUBLIC_PROMPTS;
  const subtitle = showPro
    ? "법령·고시·자치법규·판례를 근거와 함께 찾아드립니다."
    : "궁금한 것을 일상어로 물어보세요. 절차와 근거를 함께 알려드립니다.";

  const greeting = useMemo(() => {
    const time = getTimeGreeting();
    return userName ? `${time}, ${userName}님` : time;
  }, [userName]);

  if (!configured) {
    return (
      <div className="flex flex-col items-center gap-3 px-4 text-center">
        <h1 className="text-h1 text-md-on-surface">설정이 필요합니다</h1>
        <p className="text-body-base text-md-on-surface-variant">
          먼저 설정에서 배포 URL과 Assistant ID를 입력하세요.
        </p>
      </div>
    );
  }

  return (
    <div className="relative flex flex-col items-center gap-8 px-4">
      {/* 2026-09-07 "AI 틱" 정리(OpenAI·토스 톤): 오로라 blob·그라데이션 제목·2×2 카드
          그리드를 걷어냈다. 평문 제목 + 한 줄 안내 + 예시 질문 칩. */}
      <div className="max-w-[560px] text-center">
        <h1
          className="text-[26px] font-semibold leading-[1.2] text-md-on-surface sm:text-[30px]"
          style={{ letterSpacing: "-0.02em" }}
        >
          {greeting}
        </h1>
        <p className="mt-2.5 text-[15px] text-md-on-surface-variant">
          {subtitle}
        </p>
      </div>

      {onPickPrompt ? (
        // 2026-09-07 운영자 요청: pill 보다 "인식하기 쉬운 형태" — 토스식 목록 행.
        // 아이콘 + 제목 + 한 줄 설명, 얇은 구분선. 카드 박스·그림자 없음.
        <ul className="w-full max-w-[560px] divide-y divide-md-outline-variant/70 border-y border-md-outline-variant/70">
          {SAMPLE_PROMPTS.map((p) => (
            <li key={p.title}>
              <button
                type="button"
                onClick={() => {
                  // 2026-09-08: 폼이 없어도 모달 — "무엇을 얻는지"를 보고 시작(가이드).
                  setFormValues({});
                  setFormPrompt(p);
                }}
                className="group flex w-full items-center gap-3.5 px-2 py-3 text-left transition-colors hover:bg-md-surface-container-low active:bg-md-surface-container"
              >
                <span
                  className="material-symbols-outlined inline-flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-md-surface-container text-[20px] text-md-on-surface-variant"
                  aria-hidden
                >
                  {CATEGORY_ICON[p.category] ?? "chat"}
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="truncate text-[14.5px] font-medium text-md-on-surface">
                    {p.title}
                  </span>
                  <span className="truncate text-[12.5px] text-md-on-surface-variant">
                    {p.category} · {p.subtitle}
                  </span>
                </span>
                <span
                  className="material-symbols-outlined shrink-0 text-[18px] text-md-on-surface-variant/50"
                  aria-hidden
                >
                  chevron_right
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {/* 예시 질문 모달(2026-09-08 재설계) — "허접하다" 지적. 구성:
          ① 아이콘 + 제목 + 한 줄 설명 ② 이 질문으로 얻는 것(불릿) ③ (폼 있으면) 입력 칸
          ④ 실제로 보낼 질문 미리보기(입력에 따라 갱신) ⑤ [이 질문으로 시작]. */}
      <Dialog open={!!formPrompt} onOpenChange={(v) => !v && setFormPrompt(null)}>
        <DialogContent className="w-[min(92vw,520px)] max-w-none">
          <DialogHeader>
            <div className="flex items-start gap-3">
              <span
                className="material-symbols-outlined inline-flex size-10 shrink-0 items-center justify-center rounded-[10px] bg-md-surface-container text-[22px] text-md-on-surface-variant"
                aria-hidden
              >
                {formPrompt ? (CATEGORY_ICON[formPrompt.category] ?? "chat") : "chat"}
              </span>
              <div className="min-w-0">
                <DialogTitle>{formPrompt?.title}</DialogTitle>
                <DialogDescription>
                  {formPrompt?.form?.intro ?? `${formPrompt?.category ?? ""} · ${formPrompt?.subtitle ?? ""}`}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          {/* ② 얻는 것 */}
          <section>
            <p className="text-[12px] font-semibold text-md-on-surface-variant">이 질문으로 알 수 있는 것</p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {formPrompt?.expects.map((e) => (
                <li key={e} className="flex items-start gap-2 text-[14px] leading-relaxed text-md-on-surface">
                  <span className="material-symbols-outlined mt-[3px] text-[16px] text-md-primary" aria-hidden>
                    check
                  </span>
                  <span className="break-keep">{e}</span>
                </li>
              ))}
            </ul>
          </section>

          {/* ③ 입력(선택) */}
          {formPrompt?.form ? (
            <section>
              <p className="text-[12px] font-semibold text-md-on-surface-variant">
                더 정확한 답을 위해(선택)
              </p>
              <div className="mt-2 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {formPrompt.form.fields.map((f, i) => (
                  <label
                    key={f.key}
                    className={`flex flex-col gap-1 ${i === 0 ? "sm:col-span-2" : ""}`}
                  >
                    <span className="text-[12px] text-md-on-surface-variant">{f.label}</span>
                    <input
                      value={formValues[f.key] ?? ""}
                      onChange={(e) =>
                        setFormValues((prev) => ({ ...prev, [f.key]: e.target.value }))
                      }
                      placeholder={f.placeholder}
                      className="h-10 rounded-[10px] border border-md-outline-variant bg-md-surface px-3 text-[14px] text-md-on-surface placeholder:text-md-on-surface-variant/60 focus:border-md-primary focus:outline-none"
                    />
                  </label>
                ))}
              </div>
            </section>
          ) : null}

          {/* ④ 보낼 질문 미리보기 */}
          <section className="rounded-[12px] bg-md-surface-container-low px-4 py-3">
            <p className="text-[12px] font-semibold text-md-on-surface-variant">이렇게 물어봅니다</p>
            <p className="mt-1 break-keep text-[14px] leading-relaxed text-md-on-surface">
              {formPrompt
                ? formPrompt.form
                  ? formPrompt.form.build(
                      Object.fromEntries(
                        Object.entries(formValues).map(([k, v]) => [k, v.trim()]),
                      ),
                    )
                  : formPrompt.title
                : ""}
            </p>
            <p className="mt-1.5 text-[12px] text-md-on-surface-variant">
              보낸 뒤에도 입력창에서 이어서 물어볼 수 있습니다.
            </p>
          </section>

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setFormPrompt(null)}>
              취소
            </Button>
            <Button
              onClick={() => {
                if (!formPrompt) return;
                if (formPrompt.form) {
                  const cleaned: Record<string, string> = {};
                  for (const [k, v] of Object.entries(formValues)) cleaned[k] = v.trim();
                  onPickPrompt?.(formPrompt.form.build(cleaned));
                } else {
                  onPickPrompt?.(formPrompt.title);
                }
                setFormPrompt(null);
              }}
            >
              이 질문으로 시작
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
