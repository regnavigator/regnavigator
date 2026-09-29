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

const SAMPLE_PROMPTS: SamplePrompt[] = [
  {
    category: "허가·서식",
    title: "의료기기 품목허가 절차와 제출 서식",
    subtitle: "단계별 절차 · 별표/서식 · 필요 서류",
    expects: [
      "허가·인증·신고 중 어디에 해당하는지와 단계별 절차",
      "제출해야 하는 별표·서식과 첨부 서류 목록(원본 서식 바로 작성 가능)",
      "근거 조문(의료기기법·시행규칙)과 시행일",
    ],
    form: {
      intro: "제품 정보를 입력하면 더 정확한 절차·서식 안내를 받을 수 있습니다.",
      fields: [
        { key: "product", label: "제품명/품목 (선택)", placeholder: "예: 혈당측정기" },
        { key: "grade", label: "등급 (알면)", placeholder: "예: 2등급" },
        { key: "kind", label: "구분", placeholder: "예: 제조 / 수입" },
      ],
      build: (v) =>
        v.product
          ? `${v.product}${v.grade ? ` (${v.grade})` : ""}${v.kind ? ` ${v.kind}` : ""} 품목허가 절차를 단계별로 알려줘. 제출해야 하는 서식·별표와 필요 서류도 함께 정리해줘.`
          : "의료기기 품목허가 절차를 단계별로 알려줘. 제출해야 하는 서식·별표와 필요 서류도 함께 정리해줘.",
    },
  },
  {
    category: "광고·심의",
    title: "의료기기 광고 심의 기준",
    subtitle: "심의 대상 · 신청 절차 · 금지 표현",
    expects: [
      "사전심의 대상 여부와 신청 절차·처리 기간",
      "금지 표현과 위반 시 처벌 조항",
      "관련 판례·해석례가 있으면 함께 인용",
    ],
  },
  {
    category: "임상시험",
    title: "임상시험 IND 승인 절차",
    subtitle: "단계별 제출 서류 · 심사 기간",
    expects: [
      "IND 승인 단계와 제출 서류",
      "심사 기간과 변경 승인 요건",
      "근거 고시·가이드라인 원문 위치",
    ],
  },
  {
    category: "판례·해석",
    title: "비대면 진료 관련 판례·유권해석",
    subtitle: "쟁점 판례 · 행정해석 · 적용 범위",
    expects: [
      "쟁점별 판례 요지와 선고일",
      "행정해석(유권해석)의 결론과 적용 범위",
      "현행 법령 조문과의 연결",
    ],
  },
  // IRB/DRB 명시 진입점(2026-08-21) — AI 키워드 감지와 별개의 이중 접근.
  // 조립 프롬프트에 'IRB' 키워드가 들어가 백엔드 프리게이트도 확실히 걸린다.
  {
    category: "연구 심의 (IRB·DRB)",
    title: "연구 심의 대상인지 확인하기",
    subtitle: "심의면제·신속·정규 판정 · 절차·서식 안내 — 화순전남대병원 기준",
    expects: [
      "IRB 심의 대상 여부와 종류(면제·신속·정규) 예비 판정",
      "DRB(자료 반출) 필요 여부와 IRB 와의 선후",
      "절차·제출 서류 목록(서류 초안 작성으로 이어짐)",
    ],
    featured: true,
    form: {
      intro:
        "연구 개요를 입력하면 IRB(연구윤리)·DRB(의료데이터) 심의 대상 여부와 절차를 안내합니다. (화순전남대학교병원 지침 기준 예비판단)",
      fields: [
        {
          key: "outline",
          label: "연구 개요 (선택)",
          placeholder: "예: 후향적 의무기록 연구, 당뇨 환자 300명 EMR 데이터 분석",
        },
        { key: "data", label: "사용 데이터 (알면)", placeholder: "예: 진료기록, 검사결과, 잔여검체" },
      ],
      build: (v) =>
        `다음 연구가 IRB 심의 대상인지, 심의면제·신속·정규 중 어디에 해당하는지 판정해줘. 병원 의료데이터를 쓰면 DRB 심의도 함께 확인해줘.\n연구 개요: ${v.outline}${v.data ? `\n사용 데이터: ${v.data}` : ""}`,
    },
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
          궁금한 의료 규제를 물어보세요.
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
