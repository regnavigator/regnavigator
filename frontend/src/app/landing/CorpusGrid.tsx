"use client";

/**
 * 랜딩 05(Coverage) — 규제 코퍼스 구성을 종별·건수로 구체화 + 클릭 시 목록 모달
 * (2026-09-02 요청: "의료법·약사법·의료기기법만 넣은 것처럼 보인다").
 *
 * 수치(제목 기준 distinct: 법령 442·행정규칙 1,283·해석례 322·자치법규 2,861)는
 * 2026-09-02 openlaw PG(의료 도메인 필터: 식약처·복지부 소관 + 의료·약사·
 * 의약품·의료기기·생명윤리·식품·화장품·건강기능식품 제목) 실측과 검색 API
 * health(전체 인덱스 3,887,116 청크·가이드라인 153,466 청크)에서 가져왔다.
 * 코퍼스 자체는 전체 법령(6,368)·행정규칙(22,868)·자치법규(163,251)·판례(124,715)·
 * 해석례(8,823)를 담고, 의료 도메인 문서를 우선 검색한다. 갱신은 ETL 새벽 배치.
 *
 * ⚠️ 수치를 바꿀 때는 medi-back `scratchpad/corpus_stats.py` 류로 재실측할 것 — 덱·랜딩
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
    count: "442",
    unit: "종 · 19,097 조문",
    desc: "보건·의료·식약 소관 법령 전체. 현행 조문과 시행 예정 조문을 함께 안내.",
    lead: "보건복지부·식약처 소관과 제목에 의료·약사·의약품·의료기기·생명윤리·식품·화장품이 들어가는 법령. 본법과 시행령·시행규칙이 세트로 들어 있습니다.",
    overview: [
      { label: "범위", text: "보건·의료·약사·의약품·의료기기·생명윤리·식품·화장품 관련 법률과 그 시행령·시행규칙 442종. 현행 조문에 더해 시행 예정 개정 조문을 함께 보관해, 개정을 앞둔 규정은 두 버전을 나란히 안내합니다." },
      { label: "쓰임", text: "허가·신고 요건, 의무와 금지, 처벌·행정처분처럼 '근거 조문이 무엇인가'를 묻는 질문의 1차 근거. 답변의 [n] 인용이 조문 단위로 붙고, 클릭하면 원문 전문을 앱 안에서 봅니다." },
      { label: "출처·갱신", text: "국가법령정보센터 원문을 ETL 이 매일 새벽 갱신. 전국 법령 6,368건이 전부 색인돼 있어 개인정보보호법·산업안전보건법 같은 인접 법령도 검색됩니다." },
    ],
    sections: [
      {
        heading: "의료·의료기관",
        items: ["의료법·시행령·시행규칙", "응급의료에 관한 법률", "의료기사 등에 관한 법률", "간호법", "보건의료기본법", "의료사고 피해구제 및 의료분쟁 조정 등에 관한 법률", "호스피스·완화의료 및 연명의료결정에 관한 법률", "농어촌 등 보건의료를 위한 특별조치법"],
      },
      {
        heading: "의약품·마약류",
        items: ["약사법·시행령·시행규칙", "의약품 등의 안전에 관한 규칙", "마약류 관리에 관한 법률", "첨단재생의료 및 첨단바이오의약품 안전 및 지원에 관한 법률", "첨단바이오의약품 안전 및 지원에 관한 규칙", "공중보건 위기대응 의료제품의 개발 촉진 및 긴급 공급을 위한 특별법", "혈액관리법"],
      },
      {
        heading: "의료기기·디지털의료제품",
        items: ["의료기기법·시행규칙", "체외진단의료기기법·시행규칙", "디지털의료제품법·시행규칙", "식품·의약품분야 시험·검사 등에 관한 법률"],
      },
      {
        heading: "연구·생명윤리·데이터",
        items: ["생명윤리 및 안전에 관한 법률·시행규칙", "인체조직안전 및 관리 등에 관한 법률", "장기등 이식에 관한 법률", "제대혈 관리 및 연구에 관한 법률", "실험동물에 관한 법률", "보건의료기술 진흥법"],
      },
      {
        heading: "건강보험·급여",
        items: ["국민건강보험법·시행령·시행규칙", "국민건강보험 요양급여의 기준에 관한 규칙", "의료급여법", "노인장기요양보험법"],
      },
      {
        heading: "식품·화장품·위생",
        items: ["식품위생법", "건강기능식품에 관한 법률", "화장품법", "수입식품안전관리 특별법", "위생용품 관리법", "공중위생관리법"],
      },
    ],
    note: "보건·의료·식약 도메인 442종(현행+시행예정본 521건) 외에도 전국 법령 6,368건이 전부 색인돼 있어 개인정보보호법·산업안전보건법 같은 관련 법령도 검색됩니다.",
  },
  {
    icon: "policy",
    title: "행정규칙 (고시·훈령·예규)",
    count: "1,283",
    unit: "종 · 19,404 조문",
    desc: "보건복지부 462 · 식약처 391 등. 허가·심사·표시·광고·기준규격.",
    lead: "법령 아래에서 실제 실무를 규정하는 고시·훈령·예규. 보건복지부 462건, 식품의약품안전처 391건, 식약평가원·지방식약청·농식품부 소관이 이어집니다.",
    overview: [
      { label: "범위", text: "보건복지부 462·식약처 391건을 중심으로 한 고시·훈령·예규 1,283종. 허가·심사 규정, 기준규격, 급여 기준, 임상시험 규정, 표시·광고 기준이 여기 있습니다." },
      { label: "쓰임", text: "법령이 '무엇을 해야 한다'면 고시는 '어떻게·얼마나'를 정합니다. 제출 서류 목록, 심사 기준, 급여 상한처럼 실무 판단은 대부분 이 층에서 나옵니다." },
      { label: "출처·갱신", text: "행정규칙 전체 22,868건 색인, 보건·의료 소관을 우선 검색. 개정 고시는 시행일과 함께 표시됩니다." },
    ],
    sections: [
      {
        heading: "의료기기·체외진단",
        items: ["의료기기 기준규격", "의료기기 허가·신고·심사 등에 관한 규정", "의료기기 임상시험계획 승인에 관한 규정", "체외진단의료기기 허가·신고·심사 등에 관한 규정", "체외진단의료기기 임상적 성능시험 계획 승인에 관한 규정", "디지털의료기기 임상시험등 계획 승인 및 실시·관리에 관한 규정", "의료기기 제조 및 품질관리 기준"],
      },
      {
        heading: "의약품",
        items: ["의약품의 품목허가·신고·심사 규정", "의약품 임상시험 계획 승인에 관한 규정", "첨단바이오의약품의 품목허가·심사 규정", "의약품 분류 기준에 관한 규정", "한약(생약)제제 등의 품목허가·신고에 관한 규정", "비임상시험관리기준", "의약외품에 관한 기준 및 시험방법", "의료제품 사전 검토 운영에 관한 규정"],
      },
      {
        heading: "건강보험·급여",
        items: ["요양급여의 적용기준 및 방법에 관한 세부사항(보험급여·약제)", "치료재료 급여·비급여 목록 및 급여상한금액표", "건강보험 행위 급여·비급여 목록표 및 급여 상대가치점수", "임상연구의 요양급여 적용에 관한 기준", "장기요양 본인부담금 감경에 관한 고시", "1인실 입원료 일부 지원 대상 등의 요건에 관한 고시"],
      },
      {
        heading: "의료기관·데이터",
        items: ["보건의료 분야 개인정보 전송에 관한 고시", "의료기관 조제실 제제 제조 의료기관 지정", "의약품 거래대금 지연 지급 시의 지연이율 고시", "의료기기 임상시험기관 지정에 관한 규정"],
      },
    ],
  },
  {
    icon: "attach_file",
    title: "별표·서식 (행정규칙 첨부)",
    count: "40만+",
    unit: "건 첨부 파일",
    desc: "고시 본문에 없고 첨부에만 있는 세부 기준·신청 서식. 원본 .hwp 그대로.",
    lead: "고시·규칙의 별표(기준표·작성방법)와 별지 서식(신청서·신고서). 본문 검색으로는 안 잡히던 '첨부에만 있는 기준'을 따로 색인했고, 검색된 서식은 그 자리에서 채워 관보 원본 파일로 내려받습니다.",
    overview: [
      { label: "범위", text: "고시·규칙에 붙은 별표(기준표·작성방법)와 별지 서식(신청서·신고서) 40만 건 이상. 본문에는 '별표 3에 따른다'로만 적혀 있어 본문 검색으로는 잡히지 않던 세부 기준입니다." },
      { label: "쓰임", text: "구체 수치·항목·양식이 필요할 때. 검색된 서식은 [이 서식으로 작성]으로 그 자리에서 채우고, 관보 원본(.hwp)을 바이트 그대로 내려받습니다." },
      { label: "출처·갱신", text: "국가법령정보센터 첨부 파일을 별도 색인. 기준표·작성방법류는 기입형 추출이 어려워 원본 참고를 안내합니다." },
    ],
    sections: [
      {
        heading: "무엇이 들어 있나",
        items: ["의료기기 품목허가 신청서·변경허가 신청서 서식", "의약품 품목허가 신청서 별지", "임상시험계획 승인 신청서", "요양급여 세부사항 별표(급여 기준표)", "의료기기 국제표준화기술문서 작성방법 별표", "IRB·DRB 기관 서식(화순전남대학교병원)"],
      },
      {
        heading: "할 수 있는 것",
        items: ["검색 결과 서식 카드 → [이 서식으로 작성]", "대화·직접 입력·AI 자동 작성 3경로로 채우기", "관보 원본(.hwp) 바이트 보존 내보내기", "기준표류는 원본 참고 안내(빈 서식을 내밀지 않음)"],
      },
    ],
  },
  {
    icon: "auto_stories",
    title: "가이드라인·안내서",
    count: "1,555",
    unit: "문서 · 153,466 구절",
    desc: "식약처 민원인 안내서·허가심사 가이드라인·해설서. 법령 본문에 없는 실무 기준.",
    lead: "식품의약품안전처와 산하기관이 낸 가이드라인·민원인 안내서·해설서·심사 기준. 규제 질문에는 법령과 별도 레인으로 항상 함께 검색되어 '실무에서 실제 어떻게 보는지'를 보강합니다.",
    overview: [
      { label: "범위", text: "식약처·식약평가원·지방식약청의 가이드라인, 민원인 안내서, 해설서, 자주하는 질문집 1,555문서(153,466 구절). 의료기기·의약품·바이오·식품·화장품 전 분야." },
      { label: "쓰임", text: "법령·고시가 정한 요건을 실무에서 어떻게 해석하고 무엇을 제출하는지. 규제 질문에는 법령 검색과 별도 레인으로 항상 함께 검색되어 답변에 같이 인용됩니다." },
      { label: "출처·갱신", text: "식약처 공개 자료를 수집·색인. 문서 제목과 장·절 위치까지 인용에 표시됩니다." },
    ],
    sections: [
      {
        heading: "의료기기",
        items: ["의료기기 소프트웨어 허가심사 가이드라인", "인공지능기술이 적용된 디지털의료기기의 허가·심사 가이드라인", "의료기기 임상시험 안내서 · 임상시험 길라잡이", "디지털치료기기 안전성·성능 평가 및 임상시험계획서 작성 가이드라인(질환별)", "인공지능 기반 조직병리 체외진단의료기기(소프트웨어) 허가심사 가이드라인", "혁신의료기기 단계별 심사 가이드라인", "의료기기 사후관리 제도개선 해설서", "자주하는 질문집(의료기기분야)"],
      },
      {
        heading: "의약품·바이오",
        items: ["의약품 임상시험계획(변경)승인 민원 심사 절차 · 보완사례집", "의약품동등성시험 가이드라인", "첨단바이오의약품 품목허가 등 민원 접수·검토·처리 업무절차", "의약품 허가특허연계제도 안내서", "생물학적제제등 제조 및 품질관리기준 해설서", "의료제품 개발 상담 사례집"],
      },
      {
        heading: "식품·화장품",
        items: ["건강기능식품 기능성 원료 새로운 기능성 사전검토 안내서", "건강기능식품 품목제조신고 해설서", "화장품·의료기기·의약외품 허위과대광고 질의응답집", "자주하는 질문집(식품분야)"],
      },
    ],
  },
  {
    icon: "location_city",
    title: "자치법규 (조례·규칙)",
    count: "2,861",
    unit: "건 · 35,285 조문",
    desc: "시·도·시군구 보건의료·의료급여·공공의료 조례.",
    lead: "지방자치단체의 조례와 규칙 중 보건·의료·식품 관련. 지역보건의료기관 운영, 의료급여기금, 공공의료 지원처럼 지자체별로 다른 기준을 확인할 때 씁니다.",
    overview: [
      { label: "범위", text: "시·도와 시·군·구의 조례·규칙 중 보건·의료·식품 관련 2,861건. 지역보건의료기관 운영, 의료급여기금, 공공의료 지원, 의약품 오남용 예방 등." },
      { label: "쓰임", text: "지자체별로 다른 기준(지원 요건·운영 규정)을 확인할 때. 어느 지역 조례인지 함께 표시됩니다." },
      { label: "출처·갱신", text: "전국 자치법규 163,251건 색인, 보건·의료 관련을 우선 검색." },
    ],
    sections: [
      {
        heading: "예시",
        items: ["○○시 지역보건의료기관 운영에 관한 조례", "○○시 의료급여기금 특별회계 설치 및 운용 조례", "○○시 의약품 오남용 예방 및 교육에 관한 조례", "○○시 불용의약품 등 관리에 관한 조례", "○○도 공공보건의료 지원 조례", "○○시 식품등 기부 활성화 및 지원에 관한 조례"],
      },
    ],
    note: "전국 자치법규 163,251건이 색인돼 있고 그중 보건·의료 관련 2,861건이 우선 검색됩니다.",
  },
  {
    icon: "description",
    title: "법령해석례",
    count: "322",
    unit: "건 (의료·식약)",
    desc: "법제처 유권해석·부처 질의회신. 조문이 애매할 때 정부가 어떻게 읽는지.",
    lead: "법제처 법령해석과 보건복지부·식약처 질의회신. 조문 문언만으로 갈리지 않는 쟁점에서 정부의 공식 해석을 근거로 붙입니다.",
    overview: [
      { label: "범위", text: "법제처 법령해석례와 보건복지부·식약처 질의회신 중 의료·식약 관련 322건." },
      { label: "쓰임", text: "조문 문언만으로 갈리지 않는 쟁점에서 정부의 공식 해석을 근거로 붙입니다. '이 경우도 해당하나요' 류 질문에 특히 유용합니다." },
      { label: "출처·갱신", text: "전체 해석례 8,823건 색인. 안건번호·회신 부처가 함께 표시됩니다." },
    ],
    sections: [
      {
        heading: "예시",
        items: ["비영리법인이 의료기관을 개설하기 위한 요건 (의료법 시행령 제16조)", "법률 시행일 이전 의료사고의 감정 여부 (의료분쟁조정법 제25조)", "약사법 시행규칙 별표 3 '위반사항을 적발한 날'의 의미", "식품 용기의 형태가 '광고'에 포함되는지 (식품위생법 제13조)", "보건교사의 의료행위 대상에 교직원이 포함되는지 (학교보건법 시행령)"],
      },
    ],
    note: "전체 해석례 8,823건 색인, 의료·식약 관련 322건 우선.",
  },
  {
    icon: "gavel",
    title: "판례",
    count: "953",
    unit: "건 (의료·약사·식품)",
    desc: "대법원·고등·행정법원. 의료법·약사법 위반, 행정처분 취소 소송.",
    lead: "의료법·약사법·식품위생법 위반 형사판결과 업무정지·허가취소 등 행정처분 취소 소송. 선고일과 법원이 함께 표시됩니다.",
    overview: [
      { label: "범위", text: "대법원·고등·행정법원 판례 중 의료·약사·식품 관련 953건. 의료법·약사법 위반 형사판결, 업무정지·허가취소 등 행정처분 취소 소송." },
      { label: "쓰임", text: "규정 위반 시 실제 처분·판단 기준이 어떻게 적용됐는지. 선고일·법원·사건명이 인용에 표시됩니다." },
      { label: "출처·갱신", text: "전체 판례 124,715건 색인, 의료 관련을 우선 검색. 법률 자문이 아닌 참고 정보로 안내합니다." },
    ],
    sections: [
      {
        heading: "사건 유형",
        items: ["의료법 위반 · 보건범죄단속법 위반(부정의료업자)", "의료업무정지처분 취소", "약사법 위반 · 마약류관리법 위반", "식품위생법 위반 · 영업정지처분 취소", "요양급여비용 환수처분 취소", "의료비 등 손해배상"],
      },
    ],
    note: "전체 판례 124,715건 색인, 의료 관련 953건 우선.",
  },
  {
    icon: "public",
    title: "웹·공식 창구",
    count: "실시간",
    unit: "보강 검색",
    desc: "최신 개정 고시·보도자료·정부 포털. 등록된 공식 주소로만 링크.",
    lead: "코퍼스에 아직 반영되지 않은 최신 개정·입법예고·보도자료는 웹 검색으로 보강합니다. 답변에 실리는 기관 링크는 등록된 공식 창구 주소만 허용해 잘못된 URL 을 막습니다.",
    overview: [
      { label: "범위", text: "코퍼스 갱신 전의 최신 개정·입법예고·보도자료와 정부 포털 안내. 규제 질문에는 웹 레인이 함께 돌아갑니다." },
      { label: "쓰임", text: "'최근에 바뀐 것', '지금 접수 중인 것'처럼 시점이 중요한 질문의 보강. 웹 인용은 발행처가 정부·공공기관일 때만 검증됨으로 표시됩니다." },
      { label: "출처·갱신", text: "답변에 실리는 기관 링크는 등록된 공식 창구 주소만 허용해 잘못된 URL 을 막고, 커뮤니티·블로그·영상은 인용에서 제외합니다." },
    ],
    sections: [
      {
        heading: "주요 출처",
        items: ["국가법령정보센터(law.go.kr)", "식품의약품안전처·의료기기전자민원창구", "보건복지부·건강보험심사평가원", "한국의료기기안전정보원", "법제처 국가법령해석"],
      },
      {
        heading: "제외",
        items: ["커뮤니티·블로그·영상 등 이용자 생성 콘텐츠는 인용에서 제외"],
      },
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
