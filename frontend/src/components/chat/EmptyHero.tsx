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
import { FeatureCards } from "@/components/feature/FeatureCards";
import { FeatureDialog } from "@/components/feature/FeatureDialog";
import { featuresFor, type Feature } from "@/lib/features/catalog";
import { useRunFeature } from "@/lib/features/useRunFeature";

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
  onPickPrompt?: (text: string, hint?: { docKinds?: string[] }) => void;
};

export function EmptyHero({ configured, onPickPrompt }: Props) {
  const { data: session } = useSession();
  // 고른 카드 — 공용 템플릿 모달이 받는다(2026-10-02 레지스트리 분리).
  const [picked, setPicked] = useState<Feature | null>(null);
  const userName = useMemo(() => {
    const name = (session?.user as { name?: string | null } | undefined)?.name;
    const email = (session?.user as { email?: string | null } | undefined)?.email;
    if (name && name.trim()) return name.trim();
    if (email) return email.split("@")[0] ?? null;
    return null;
  }, [session]);

  const { mode, showPro } = useMode();
  // 카드 정의는 레지스트리가 단일 출처 — 스레드 내 피커와 같은 목록을 쓴다.
  const features = useMemo(
    () => featuresFor({ mode, hasTurns: false }), [mode]);
  // 첫 화면은 스레드가 아직 없다 → 전역 키. 첫 전송 때 adoptConfidential 이 옮긴다.
  const run = useRunFeature({ mode, onPrefill: onPickPrompt, threadId: null });
  const subtitle =
    mode === "monitor"
      ? "무엇을 모니터링할지 물어보세요. 찾은 규제를 담아 두면 개정을 추적합니다."
      : showPro
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
        <FeatureCards
          features={features}
          layout="tiles"
          onPick={(f) => setPicked(f)}
        />
      ) : null}


      <FeatureDialog
        feature={picked}
        onClose={() => setPicked(null)}
        onRun={run}
      />
    </div>
  );
}
