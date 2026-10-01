"use client";

/**
 * EntryPathCards — 랜딩 02 섹션: 세 가지 진입 경로 소개 (2026-10-01).
 *
 * 종전엔 이 자리가 IRB/DRB 섹션이었다. 기관 심의는 RegNavigator 에서
 * 도메인 팩 하나일 뿐이라 랜딩 두 번째 자리에 둘 성격이 아니다.
 * 제품의 실제 구조(`/start` 의 세 경로)와 맞췄다.
 *
 * 카드를 누르면 로그인 뒤 해당 경로로 들어간다 — 모드는 `/start` 가 정하므로
 * 여기서는 선택 화면으로만 보낸다.
 */

import Link from "next/link";

type Path = {
  key: string;
  no: string;
  icon: string;
  title: string;
  who: string;
  lines: string[];
};

const PATHS: Path[] = [
  {
    key: "public",
    no: "01",
    icon: "diversity_3",
    title: "일반 상담",
    who: "시민 · 소상공인",
    lines: [
      "어려운 용어 대신 일상어로 설명",
      "무엇을 · 어디에 · 어떤 서류로 내는지",
      "답변마다 근거 조문 표시",
    ],
  },
  {
    key: "expert",
    no: "02",
    icon: "gavel",
    title: "전문가 업무",
    who: "변호사 · 법무 · 인허가 담당",
    lines: [
      "조문 중심 분석과 인용 검증",
      "고시 별표 · 지자체 조례까지 추적",
      "신청 서식 작성 · 심층 보고서",
    ],
  },
  {
    key: "monitor",
    no: "03",
    icon: "monitoring",
    title: "규제 모니터링",
    who: "로펌 · 기업 법무팀",
    lines: [
      "관심 조문을 고객사별로 묶어 관리",
      "폐지 · 개정예정 · 시행일 변경 감지",
      "정기 리포트 자동 발송",
    ],
  },
];

export function EntryPathCards() {
  return (
    <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-3">
      {PATHS.map((p) => (
        <Link
          key={p.key}
          href="/start?pick=1"
          className="group flex flex-col rounded-[12px] border border-md-outline-variant bg-md-surface-container-lowest p-7 text-left transition-all hover:-translate-y-1 hover:border-md-primary hover:shadow-lg"
        >
          <div className="flex items-center justify-between">
            <span
              className="material-symbols-outlined text-[28px] text-md-primary"
              aria-hidden
            >
              {p.icon}
            </span>
            <span className="text-[11px] font-semibold tracking-[0.16em] text-md-on-surface-variant/60">
              {p.no}
            </span>
          </div>

          <h3 className="mt-5 text-[19px] font-bold">{p.title}</h3>
          <p className="mt-1 text-[12.5px] font-medium text-md-primary">{p.who}</p>

          <ul className="mt-5 flex flex-col gap-2 border-t border-md-outline-variant pt-5">
            {p.lines.map((l) => (
              <li
                key={l}
                className="flex gap-2 text-[13px] leading-[1.6] text-md-on-surface-variant"
              >
                <span
                  className="material-symbols-outlined mt-[2px] text-[15px] text-md-primary"
                  aria-hidden
                >
                  check_small
                </span>
                <span>{l}</span>
              </li>
            ))}
          </ul>

          <span className="mt-6 text-[12.5px] font-bold text-md-primary">
            이 경로로 시작 →
          </span>
        </Link>
      ))}
    </div>
  );
}
