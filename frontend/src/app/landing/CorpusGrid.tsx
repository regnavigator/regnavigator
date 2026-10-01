"use client";

/**
 * 랜딩 05(Coverage) — 규제 코퍼스 구성을 종별·건수로 구체화 + 클릭 시 목록 모달.
 *
 * 2026-10-01 RegNavigator 전환: 종전엔 의료 도메인 필터 기준 수치(법령 442·
 * 행정규칙 1,283 등)를 보여줬으나, 코퍼스 자체가 처음부터 전국을 담고 있고
 * RAG 경로에 도메인 편향이 없음을 실측으로 확인해 **전국 수치**로 바꿨다
 * (비의료 질의가 소관부처까지 정확히 검색된다).
 *
 * 수치 출처 — 2026-09-02 openlaw PG 실측 + 검색 API health:
 *   법령 6,368 · 행정규칙 22,868 · 자치법규 163,251 · 판례 124,715 · 해석례 8,823
 *   전체 인덱스 3,887,116 청크(가이드라인 153,466 청크 포함). 갱신은 ETL 새벽 배치.
 *
 * ⚠️ 수치를 바꿀 때는 `scratchpad/corpus_stats.py` 류로 재실측할 것 — 덱·랜딩
 * 수치는 코드/실측 검증 후 사용(메모리 규칙).
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

type Group = {
  icon: string;
  title: string;
  count: string;
  unit: string;
  desc: string;
  /** 모달 — 이 종별에 무엇이 들어 있는지 */
  lead: string;
  /** 개요 — 무엇을 다루고, 언제 쓰이고, 어디서 오는지(2026-09-02: 전체 목록 대신) */
  overview: { label: string; text: string }[];
  sections: { heading: string; items: string[] }[];
  note?: string;
};

const GROUPS: Group[] = [
  {
    icon: "menu_book",
    title: "법령 (법률·시행령·시행규칙)",
    count: "6,368",
    unit: "건",
    desc: "전국 현행 법령 전체. 현행 조문과 시행 예정 조문을 함께 안내.",
    lead: "법률과 그 시행령·시행규칙이 세트로 들어 있습니다. 분야를 가리지 않습니다.",
    overview: [
      { label: "범위", text: "전국 현행 법령 6,368건의 조문 전체. 현행 조문에 더해 시행 예정 개정 조문을 함께 보관해, 개정을 앞둔 규정은 두 버전을 나란히 안내합니다." },
      { label: "쓰임", text: "허가·신고 요건, 의무와 금지, 처벌·행정처분처럼 '근거 조문이 무엇인가'를 묻는 질문의 1차 근거. 답변의 [n] 인용이 조문 단위로 붙고, 클릭하면 원문 전문을 앱 안에서 봅니다." },
      { label: "출처·갱신", text: "국가법령정보센터 원문을 ETL 이 매일 새벽 갱신합니다." },
    ],
    sections: [
      { heading: "산업·영업", items: ["식품위생법", "건축법", "주류 면허 등에 관한 법률", "옥외광고물 등의 관리와 옥외광고산업 진흥에 관한 법률", "유통산업발전법"] },
      { heading: "노동·안전", items: ["근로기준법", "산업안전보건법", "중대재해 처벌 등에 관한 법률", "최저임금법", "산업재해보상보험법"] },
      { heading: "데이터·정보", items: ["개인정보 보호법", "정보통신망 이용촉진 및 정보보호 등에 관한 법률", "신용정보의 이용 및 보호에 관한 법률"] },
      { heading: "생활·계약", items: ["주택임대차보호법", "상가건물 임대차보호법", "소비자기본법", "전자상거래 등에서의 소비자보호에 관한 법률"] },
      { heading: "보건·의료", items: ["의료법", "약사법", "의료기기법", "생명윤리 및 안전에 관한 법률"] },
      { heading: "환경·에너지", items: ["환경영향평가법", "폐기물관리법", "대기환경보전법", "전기사업법"] },
    ],
    note: "위는 예시입니다. 분야를 미리 좁히지 않고 전 분야를 색인합니다.",
  },
  {
    icon: "gavel",
    title: "행정규칙 (고시·훈령·예규)",
    count: "22,868",
    unit: "건",
    desc: "법률·시행령에 없는 세부 기준이 실제로 있는 곳. 별표·첨부 본문까지 색인.",
    lead: "\"...는 고시로 정한다\" 로 위임된 수치·서식·심사 기준이 여기 있습니다.",
    overview: [
      { label: "범위", text: "각 부처 고시·훈령·예규 22,868건. 본문뿐 아니라 **별표·별지 서식의 본문**까지 색인해, 법률에는 없고 별표에만 있는 세부 기준을 찾아냅니다." },
      { label: "쓰임", text: "\"기준이 법에는 안 보인다\" 는 질문의 답이 대부분 여기 있습니다. 실무 사고도 이 층위에서 납니다." },
      { label: "출처·갱신", text: "국가법령정보센터 행정규칙 원문. 개정이 잦아 시행일과 개정예정 여부를 함께 표시합니다." },
    ],
    sections: [
      { heading: "무엇이 들어 있나", items: ["수치 기준(규격·한도·기간)", "심사·평가 기준", "별지 서식과 작성 요령", "처분 양정 기준", "업무 처리 지침"] },
    ],
  },
  {
    icon: "location_city",
    title: "자치법규 (조례·규칙)",
    count: "163,251",
    unit: "건",
    desc: "같은 사안도 지자체마다 달라지는 요건. 다루는 서비스가 드뭅니다.",
    lead: "인허가·영업·입지 규제는 조례에서 갈립니다.",
    overview: [
      { label: "범위", text: "전국 지방자치단체의 조례·규칙 163,251건." },
      { label: "쓰임", text: "\"우리 지역은 어떤가\" 를 확인할 때. 같은 업종이라도 시설 기준·거리 제한·수수료가 관할에 따라 다릅니다." },
      { label: "주의", text: "조례는 개정 주기가 제각각입니다. 최종 확인은 관할 지자체에 하셔야 합니다." },
    ],
    sections: [
      { heading: "자주 갈리는 것", items: ["영업 시설 기준", "입지·거리 제한", "옥외광고물 규격", "수수료·과태료 액수", "지원·보조금 요건"] },
    ],
  },
  {
    icon: "balance",
    title: "판례",
    count: "124,715",
    unit: "건",
    desc: "법원이 실제로 어떻게 판단했는지. 법원·심급 정보 포함.",
    lead: "조문만으로 판단이 서지 않을 때 쓰는 보조 근거입니다.",
    overview: [
      { label: "범위", text: "대법원·고등법원·지방법원 판결 124,715건." },
      { label: "쓰임", text: "요건의 해석이 다투어진 사안, 처분의 적법성, 양정 수준을 볼 때." },
      { label: "한계", text: "판례 검색 전문 서비스만큼의 양은 아닙니다. RegNavigator 의 축은 규제 준수이고 판례는 보조입니다." },
    ],
    sections: [
      { heading: "함께 표시", items: ["법원·심급", "선고일", "사건 유형", "관련 조문"] },
    ],
  },
  {
    icon: "quiz",
    title: "법령해석례 (유권해석)",
    count: "8,823",
    unit: "건",
    desc: "소관 부처가 조문을 어떻게 읽는지. 판례보다 실무에 가깝습니다.",
    lead: "\"이 경우도 해당되나\" 에 대한 행정청의 답입니다.",
    overview: [
      { label: "범위", text: "법제처·각 부처 법령해석 8,823건." },
      { label: "쓰임", text: "적용 대상에 포함되는지, 예외에 해당하는지를 다툴 때. 행정해석과 판례가 갈리는 지점도 함께 보여줍니다." },
      { label: "주의", text: "유권해석은 법원을 구속하지 않습니다. 참고 근거로 제시합니다." },
    ],
    sections: [
      { heading: "자주 쓰이는 질문", items: ["적용 대상 해당 여부", "예외·면제 요건", "용어의 범위", "경과규정 적용"] },
    ],
  },
];

export function CorpusGrid() {
  const [open, setOpen] = useState<number | null>(null);
  const g = open === null ? null : GROUPS[open];

  return (
    <>
      <ul className="mt-16 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {GROUPS.map((d, i) => (
          <li key={d.title}>
            <button
              type="button"
              onClick={() => setOpen(i)}
              aria-haspopup="dialog"
              className="group flex h-full w-full flex-col gap-3 rounded-card border border-md-outline-variant bg-md-surface-container-low p-6 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-md-primary/50 hover:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.25)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary/50"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="material-symbols-outlined text-[22px] text-md-primary" aria-hidden>
                  {d.icon}
                </span>
                <span className="material-symbols-outlined text-[18px] text-md-outline opacity-0 transition-opacity group-hover:opacity-100" aria-hidden>
                  open_in_full
                </span>
              </div>
              <h3 className="text-[16px] font-semibold tracking-tight text-md-on-surface">{d.title}</h3>
              <p className="flex items-baseline gap-1.5">
                <span className="text-[22px] font-bold tabular-nums leading-none text-md-on-surface" style={{ fontFamily: "var(--font-mono)" }}>
                  {d.count}
                </span>
                <span className="text-[11.5px] text-md-on-surface-variant">{d.unit}</span>
              </p>
              <p className="text-[15px] leading-[1.7] text-md-on-surface-variant">{d.desc}</p>
              <span className="mt-auto inline-flex items-center gap-1 pt-1 text-[12px] font-semibold text-md-primary">
                목록 보기
                <span className="material-symbols-outlined text-[15px] transition-transform group-hover:translate-x-0.5" aria-hidden>
                  arrow_forward
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <p className="mx-auto mt-10 max-w-[720px] text-center text-[13px] leading-[1.7] text-md-on-surface-variant/80">
        2026-09 기준 실측. 전체 색인 388만 구절(전국 법령·행정규칙·자치법규·판례·해석례) 중 보건·의료·식약
        도메인을 우선 검색하며, 새벽 배치로 매일 갱신됩니다.
      </p>

      <Dialog open={g !== null} onOpenChange={(v) => !v && setOpen(null)}>
        {g ? (
          <DialogContent
            className="w-[min(92vw,900px)] max-w-none gap-6 p-10 shadow-[0_40px_120px_rgba(0,0,0,0.45),0_4px_16px_rgba(0,0,0,0.12)] ring-1 ring-black/10"
            overlayClassName="bg-black/55 backdrop-blur-lg"
          >
            <DialogHeader className="border-b border-md-outline-variant pb-4">
              <DialogTitle className="flex items-center gap-2.5">
                <span className="material-symbols-outlined text-[22px] text-md-primary" aria-hidden>
                  {g.icon}
                </span>
                {g.title}
                <span className="ml-1 rounded-full bg-md-primary-container px-2.5 py-0.5 font-mono text-[12px] font-semibold text-md-on-primary-container">
                  {g.count} {g.unit}
                </span>
              </DialogTitle>
              <DialogDescription className="text-[15.5px]">
                {g.lead}
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="max-h-[68vh] overflow-y-auto pr-2">
              {/* 개요 — 범위·쓰임·출처를 먼저. 예시 목록은 "그것만 있다"로 읽히므로 보조로 내림 */}
              <dl className="mb-5 grid grid-cols-1 gap-x-6 gap-y-3 rounded-[12px] bg-md-surface-container-low px-5 py-4 sm:grid-cols-[auto_1fr]">
                {g.overview.map((o) => (
                  <div key={o.label} className="contents">
                    <dt className="text-[13px] font-semibold text-md-primary sm:pt-[3px]">{o.label}</dt>
                    <dd className="text-[15px] leading-[1.7] text-md-on-surface">{o.text}</dd>
                  </div>
                ))}
              </dl>
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 [&>*:last-child:nth-child(odd)]:sm:col-span-2">
                {g.sections.map((s) => (
                  <section key={s.heading} className="rounded-[12px] border border-md-outline-variant bg-md-surface-container-lowest p-5">
                    <h4 className="mb-3.5 flex items-baseline gap-2 text-[13px] font-semibold uppercase tracking-[0.08em] text-md-primary">
                      {s.heading}
                      <span className="text-[11px] font-medium normal-case tracking-normal text-md-on-surface-variant">대표 예시</span>
                    </h4>
                    <ul className="flex flex-col gap-2.5">
                      {s.items.map((it) => (
                        <li key={it} className="flex gap-2.5 text-[15px] leading-[1.7] text-md-on-surface">
                          <span aria-hidden className="mt-[0.55em] h-1 w-1 shrink-0 rounded-full bg-md-outline" />
                          <span className="min-w-0 break-keep [overflow-wrap:anywhere]">{it}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
              {g.note ? <p className="mt-5 text-[13.5px] leading-[1.7] text-md-on-surface-variant/80">{g.note}</p> : null}
            </DialogBody>
            <DialogFooter className="justify-between border-t border-md-outline-variant pt-4">
              <button
                type="button"
                onClick={() => setOpen(((open ?? 0) + 1) % GROUPS.length)}
                className="inline-flex h-9 items-center gap-1 rounded-[10px] px-3 text-[13px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container-high hover:text-md-on-surface"
              >
                다음 종별
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  chevron_right
                </span>
              </button>
              <DialogAction variant="secondary" onClick={() => setOpen(null)}>
                닫기
              </DialogAction>
            </DialogFooter>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}
