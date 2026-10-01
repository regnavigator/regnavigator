"use client";

/**
 * FeatureTour — 현 화면 위 앵커형 코치마크(핀) 투어.
 *
 * 별도 가이드 페이지 대신 실제 UI 요소를 스포트라이트로 짚으며 안내(사용자 결정
 * 2026-07-16). 첫 방문 1회 자동 + 사이드바 "이용 안내"로 재실행(window 이벤트).
 * 대상 요소가 화면에 없으면(예: 보고서 버튼은 대화 전 미노출) 그 스텝은 건너뜀.
 */

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

const SEEN_KEY = "medi_feature_tour_v2";
export const OPEN_TOUR_EVENT = "medi-open-tour";

type Step = {
  /** null = 화면 중앙 카드(인트로/아웃트로) */
  selector: string | null;
  title: string;
  desc: string;
};

const STEPS: Step[] = [
  {
    selector: null,
    title: "RegNavigator 이용 안내",
    desc: "법령·별표/서식·판례 근거로 답하는 규제 상담 도구입니다.\n30초만에 핵심 기능을 짚어드릴게요.",
  },
  {
    // 입력 "카드"만 하이라이트 — [data-chat-input] 은 sticky 푸터 전체라
    // 면책 문구·배지까지 통째로 밝아졌다(2026-08-27 지적).
    selector: "[data-tour='input']",
    title: "질문 입력",
    desc: "대화하듯 질문하세요. 규제 질의면 법령 검색이 자동으로 수행되고, 모든 주장에 [1][2] 근거가 붙습니다.",
  },
  {
    selector: "[data-tour='attach']",
    title: "파일 첨부",
    desc: "PDF·DOCX·HWPX 문서를 붙여 질문할 수 있어요. 긴 규정·계약서도 첨부하면 내용을 읽고 답합니다.",
  },
  {
    selector: "[data-tour='report']",
    title: "심층 보고서",
    desc: "목적을 골라 생성하면 백그라운드에서 만들어집니다. 기다릴 필요 없어요 — 채팅을 계속하다 보면 완료 시 사이드바 목록과 이메일로 도착합니다.",
  },
  {
    selector: null,
    title: "서류 작성",
    desc: "답변의 별표·서식 인용에서 [이 서식으로 작성]을 누르면 작성 화면이 열립니다.\n왼쪽 서식 + 오른쪽 도우미와 대화로 채우고, 관보 원본 파일(.hwp) 그대로 내려받아요.",
  },
  {
    selector: null,
    title: "연구 심의 (IRB·DRB)",
    desc: "세 가지 어느 쪽이든 됩니다 — 첫 화면 카드, 입력창의 IRB/DRB 버튼, 또는 그냥 연구 개요를 질문.\n심의면제·신속·정규 예비판정과 절차·서식까지 안내합니다.",
  },
  {
    selector: "[data-tour='bell']",
    title: "개정 알림",
    desc: "저장한 근거의 법령이 폐지·개정예정·시행일 변경되면 여기에 표시됩니다.",
  },
  {
    selector: "[data-tour='bookmarks']",
    title: "저장한 근거",
    desc: "답변 인용에 마우스를 올려 북마크 아이콘으로 저장하고, 폴더로 프로젝트별 정리하세요. 원 대화가 지워져도 근거는 남습니다.",
  },
  {
    selector: null,
    title: "빠르게 쓰기",
    desc: "Ctrl+K 로 대화 검색·새 대화·최근 조문에 바로 이동할 수 있어요. 답변에 마우스를 올리면 복사·Word 내보내기가 나타납니다.\n민감정보(환자 식별 정보 등)는 입력하지 마세요.",
  },
];

type Rect = { top: number; left: number; width: number; height: number };

export function FeatureTour() {
  const [active, setActive] = useState(false);
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);

  // 현재 스텝의 대상 rect 계산 — 없으면 null(중앙 카드).
  const measure = useCallback((i: number): boolean => {
    const step = STEPS[i];
    if (!step) return false;
    if (!step.selector) {
      setRect(null);
      return true;
    }
    const el = document.querySelector(step.selector);
    if (!el) return false; // 대상 없음 — 호출자가 스킵
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    return true;
  }, []);

  const goto = useCallback(
    (from: number, dir: 1 | -1) => {
      let i = from + dir;
      while (i >= 0 && i < STEPS.length) {
        if (measure(i)) {
          setIdx(i);
          return;
        }
        i += dir; // 대상 미존재 스텝 스킵
      }
      // 끝 — 종료
      setActive(false);
      try {
        window.localStorage.setItem(SEEN_KEY, "1");
      } catch { /* 무시 */ }
    },
    [measure],
  );

  const start = useCallback(() => {
    setActive(true);
    if (measure(0)) setIdx(0);
    else goto(0, 1);
  }, [measure, goto]);

  const finish = useCallback(() => {
    setActive(false);
    try {
      window.localStorage.setItem(SEEN_KEY, "1");
    } catch { /* 무시 */ }
  }, []);

  // 첫 방문 자동 실행 + "이용 안내" 재실행 이벤트.
  // ⚠️ 동시 노출 가드(2026-08-28): 공지·동의 등 다른 모달이 열려 있으면
  // 투어 오버레이(z-80)가 그 위를 덮어 버튼 클릭이 막힌다 — 모달이 다
  // 닫힐 때까지 시작을 미룬다(0.5s 폴링, 최대 60s 후 포기).
  useEffect(() => {
    try {
      if (window.localStorage.getItem(SEEN_KEY)) return;
    } catch { return; }
    let tries = 0;
    const iv = window.setInterval(() => {
      tries += 1;
      // Radix 는 닫히면 언마운트, ConsentGate(비-Radix)는 필요할 때만 렌더 —
      // role 존재 자체가 "열려 있음"이다. 투어 자신은 아직 시작 전이라 무매치.
      const dialogOpen = document.querySelector(
        '[role="dialog"], [role="alertdialog"]');
      if (dialogOpen) {
        if (tries > 120) window.clearInterval(iv); // 60s — 오늘은 포기(다음 접속에 재시도)
        return;
      }
      window.clearInterval(iv);
      start();
    }, 500);
    return () => window.clearInterval(iv);
  }, [start]);
  useEffect(() => {
    const onOpen = () => start();
    window.addEventListener(OPEN_TOUR_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_TOUR_EVENT, onOpen);
  }, [start]);

  // 리사이즈/스크롤 시 rect 재계산.
  useEffect(() => {
    if (!active) return;
    const re = () => measure(idx);
    window.addEventListener("resize", re);
    window.addEventListener("scroll", re, true);
    return () => {
      window.removeEventListener("resize", re);
      window.removeEventListener("scroll", re, true);
    };
  }, [active, idx, measure]);

  if (!active) return null;
  const step = STEPS[idx]!;
  const total = STEPS.length;

  // 카드 위치 — 대상 아래(공간 없으면 위), 중앙 스텝은 화면 중앙.
  const CARD_W = 380;
  let cardStyle: React.CSSProperties;
  if (rect) {
    const below = rect.top + rect.height + 12;
    const flip = below + 230 > window.innerHeight;
    cardStyle = {
      position: "fixed",
      top: flip ? Math.max(12, rect.top - 230) : below,
      left: Math.min(Math.max(12, rect.left), window.innerWidth - CARD_W - 12),
      width: CARD_W,
    };
  } else {
    cardStyle = {
      position: "fixed",
      top: "38%",
      left: "50%",
      transform: "translateX(-50%)",
      width: CARD_W,
    };
  }

  return (
    <div className="fixed inset-0 z-[80]" role="dialog" aria-label="이용 안내 투어">
      {/* 딤 배경 — 클릭 시 종료 */}
      <div className="absolute inset-0 bg-black/45" onClick={finish} />
      {/* 스포트라이트 핀 — 대상 주위 링 */}
      {rect ? (
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-lg ring-2 ring-md-primary"
          style={{
            top: rect.top - 6,
            left: rect.left - 6,
            width: rect.width + 12,
            height: rect.height + 12,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.45)",
            background: "transparent",
          }}
        />
      ) : null}
      {/* 카드 */}
      <div
        style={cardStyle}
        className="rounded-card border border-md-outline-variant bg-md-surface px-6 py-5 shadow-xl"
      >
        <p className="text-[11px] font-semibold tracking-[0.12em] text-md-primary">
          {idx + 1} · {total}
        </p>
        <h3 className="mt-2 text-[16px] font-semibold leading-snug text-md-on-surface">{step.title}</h3>
        <p className="mt-2.5 whitespace-pre-line text-[13px] leading-[1.75] text-md-on-surface-variant">
          {step.desc}
        </p>
        <div className="mt-5 flex items-center justify-between">
          <button
            type="button"
            onClick={finish}
            className="text-[12px] text-md-on-surface-variant hover:text-md-on-surface"
          >
            건너뛰기
          </button>
          <div className="flex gap-1.5">
            {idx > 0 ? (
              <Button size="sm" variant="ghost" onClick={() => goto(idx, -1)}>
                이전
              </Button>
            ) : null}
            <Button size="sm" onClick={() => goto(idx, 1)}>
              {idx >= total - 1 ? "완료" : "다음"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
