"use client";

/**
 * `/start` — 진입 경로 선택 (2026-10-01).
 *
 * 로그인 뒤 첫 화면. 세 경로 중 하나를 고르면 그 모드로 들어간다.
 *
 * 자동 이동은 **`?auto=1` 일 때만** 한다 — 미들웨어가 `/` 를 여기로 보낼 때 붙인다.
 * 주소창에 `/start` 를 직접 치거나 사이드바의 '모드 전환'(`?pick=1`)으로 들어오면
 * 항상 선택 화면을 보여준다. 저장된 모드가 있다고 무조건 튕기면 "안 열린다"로
 * 보인다(2026-10-01 실사용 지적).
 */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useMode } from "@/components/providers/ModeProvider";
import { ALL_MODES, MODE_META, type AppMode } from "@/lib/store/mode";

const DETAIL: Record<AppMode, string[]> = {
  public: [
    "어려운 법률 용어 대신 쉬운 말로 설명",
    "무엇을 · 어디에 · 어떤 서류로 내야 하는지 절차 안내",
    "답변마다 근거 조문 표시",
  ],
  expert: [
    "조문 중심 분석 · 인용 검증 배지",
    "법률 인용 네트워크로 관련 조문 추적",
    "신청 서식 작성 · 심층 보고서",
  ],
  monitor: [
    "대화와 자료로 관찰할 규제를 모읍니다",
    "폐지 · 개정예정 · 시행일 변경을 감지해 알람",
    "변경 보고서를 만들어 선택한 수신자에게 발송",
  ],
};

function StartInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { mode, ready, setMode } = useMode();
  const [picking, setPicking] = useState<AppMode | null>(null);

  // 자동 이동은 `/` 에서 넘어온 경우(auto=1)에만. 주소창에 /start 를 직접 치거나
  // 사이드바로 전환하러 온 경우(pick=1)는 항상 선택 화면을 보여준다.
  const forcePick = params.get("auto") !== "1" || params.get("pick") === "1";

  // 이미 고른 모드가 있으면 바로 넘어간다 (단, 전환하러 온 경우는 제외).
  useEffect(() => {
    if (!ready || forcePick || !mode) return;
    router.replace(MODE_META[mode].href);
  }, [ready, forcePick, mode, router]);

  const choose = (m: AppMode) => {
    // 전문가 모드는 **법률 업무 종사자용**이다(2026-10-03). 자격 확인 절차 없이
    // 누구나 들어와 의견서 초안을 뽑아 제3자에게 주면 서비스가 변호사법 §109
    // 위반의 수단이 된다. 최소 장치: 자기선언 + 기록. 인증은 후속 과제.
    if (m === "expert") {
      const ok = window.confirm(
        "전문가 모드는 변호사·법무 담당자 등 법률 업무 종사자를 위한 도구입니다.\n" +
        "산출물은 참고 자료이며, 제3자에게 법률 자문으로 제공할 수 없습니다.\n\n" +
        "해당 업무 종사자로서 이용하시겠습니까?",
      );
      if (!ok) return;
      try {
        window.localStorage.setItem("regnav_expert_ack", new Date().toISOString());
      } catch {
        /* 무시 */
      }
    }
    setPicking(m);
    setMode(m);
    router.push(MODE_META[m].href);
  };

  // 자동 이동 중엔 카드를 깜빡이지 않게 비워 둔다.
  if (!ready || (!forcePick && mode)) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-md-surface">
        <div className="flex flex-col items-center gap-3 text-md-on-surface-variant">
          <span
            className="material-symbols-outlined animate-md-spin text-[28px] text-md-primary"
            aria-hidden
          >
            progress_activity
          </span>
          <p className="text-[13px]">불러오는 중…</p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-md-surface px-6 py-14">
      <div className="mx-auto w-full max-w-[1000px]">
        <header className="mb-10 text-center">
          <h1 className="text-[26px] font-bold tracking-[-0.3px] text-md-primary">
            무엇을 하시겠습니까?
          </h1>
          <p className="mt-2 text-[14px] text-md-on-surface-variant">
            용도에 맞는 경로를 고르시면 그에 맞게 화면과 기능이 준비됩니다.
            {forcePick ? " 언제든 다시 바꿀 수 있습니다." : ""}
          </p>
        </header>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {ALL_MODES.map((m) => {
            const meta = MODE_META[m];
            const current = mode === m;
            return (
              <button
                key={m}
                type="button"
                data-mode-card={m}
                onClick={() => choose(m)}
                disabled={picking !== null}
                className={[
                  "group flex flex-col rounded-[10px] border bg-md-surface-container-low p-6 text-left transition-all",
                  "hover:-translate-y-0.5 hover:border-md-primary hover:shadow-md",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary",
                  "disabled:pointer-events-none disabled:opacity-60",
                  current ? "border-md-primary ring-1 ring-md-primary" : "border-md-outline-variant",
                ].join(" ")}
              >
                <span
                  className="material-symbols-outlined mb-3 text-[30px] text-md-primary"
                  aria-hidden
                >
                  {meta.icon}
                </span>

                <span className="flex items-center gap-2 text-[16px] font-bold">
                  {meta.label}
                  {current && (
                    <span className="rounded-[4px] bg-md-primary px-1.5 py-0.5 text-[10px] font-medium text-md-on-primary">
                      현재
                    </span>
                  )}
                </span>

                <span className="mt-1.5 text-[13px] text-md-on-surface-variant">
                  {meta.desc}
                </span>

                <ul className="mt-4 flex flex-col gap-1.5 border-t border-md-outline-variant pt-4">
                  {DETAIL[m].map((d) => (
                    <li key={d} className="flex gap-1.5 text-[12px] text-md-on-surface-variant">
                      <span
                        className="material-symbols-outlined mt-[1px] text-[14px] text-md-primary"
                        aria-hidden
                      >
                        check_small
                      </span>
                      <span>{d}</span>
                    </li>
                  ))}
                </ul>

                <span className="mt-5 text-[12px] font-bold text-md-primary">
                  {picking === m ? "여는 중…" : "시작하기 →"}
                </span>
              </button>
            );
          })}
        </div>

        <p className="mt-10 text-center text-[12px] text-md-on-surface-variant">
          법령 안내 서비스이며 법률 자문이 아닙니다. 최종 판단은 담당 전문가에게 확인하십시오.
        </p>
      </div>
    </main>
  );
}

export default function StartPage() {
  return (
    <Suspense fallback={null}>
      <StartInner />
    </Suspense>
  );
}
