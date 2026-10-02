"use client";

/**
 * 기능 실행기 — "카드를 골랐다" 를 실제 동작으로 옮기는 **단일 경로** (2026-10-02).
 *
 * 종전엔 이 로직이 `EmptyHero` 의 다이얼로그 버튼 안에 인라인으로 있었다. 표면이
 * 늘면(첫 화면 · 스레드 내 피커 · 맥락 제안) 그만큼 복제되고, 복제된 쪽이 부수효과를
 * 빠뜨리면 **"기밀 검토를 골랐는데 기밀이 안 켜진 채 외부 모델로 나가는"** 사고가 난다.
 * 그래서 프리필과 부수효과를 여기 한 곳에 묶는다.
 */

import { useCallback } from "react";
import { toast } from "sonner";

import type { Feature } from "@/lib/features/catalog";
import {
  autoEnableConfidential,
  OPEN_ATTACH_EVENT,
  OPEN_BRIEF_EVENT,
  OPEN_WATCH_EVENT,
  setConfidential,
  type AppMode,
} from "@/lib/store/mode";

export function useRunFeature(opts: {
  mode: AppMode | null;
  /** 조립된 프롬프트를 입력창에 넣는다. 자동 전송하지 않는다 — 편집할 수 있어야 한다. */
  onPrefill?: (text: string, hint?: { docKinds?: string[] }) => void;
  /** 기밀 토글의 스레드 키(2026-10-03). `/new` 면 null → 전역 키 */
  threadId?: string | null;
}) {
  const { mode, onPrefill } = opts;

  return useCallback(
    (
      feature: Feature,
      values: Record<string, string>,
      /**
       * 조합의 두 번째 이후 단계인가 (2026-10-02).
       *
       * 맞으면 프리필 앞에 한 줄을 덧붙여 **앞 단계 결과를 기준으로 삼으라**고
       * 지시한다. 앞 단계의 쟁점·인용을 프롬프트에 옮겨 담지는 않는다 — 같은
       * 스레드의 연속된 턴이라 모델이 이미 대화로 본다. 누적분을 직렬화하는 것은
       * 과거에 컨텍스트를 터뜨린 적이 있다.
       */
      chained?: boolean,
    ) => {
      // 1) 프롬프트 — 패널을 여는 기능(brief)은 프리필할 문장이 없다.
      //
      // 폼이 없는 카드(일반 경로의 상황 카드)는 **제목 자체가 질문**이다. 종전
      // EmptyHero 가 `onPickPrompt(title)` 로 그렇게 동작했는데, 레지스트리로
      // 옮기며 이 분기를 빠뜨려 일반 모드 카드가 눌러도 아무 일도 안 했다
      // (2026-10-02 회귀).
      if (onPrefill && feature.triggers !== "brief" && feature.triggers !== "watch") {
        const lead = chained
          ? "앞 단계에서 정리한 내용과 근거를 그대로 이어받아서 진행해줘.\n\n"
          : "";
        if (feature.form) {
          const cleaned: Record<string, string> = {};
          for (const [k, v] of Object.entries(values)) cleaned[k] = (v ?? "").trim();
          onPrefill(lead + feature.form.build(cleaned), { docKinds: feature.docKinds });
        } else {
          onPrefill(lead + feature.title, { docKinds: feature.docKinds });
        }
      }

      // 2) 부수효과 — 카드가 약속한 기능이 실제로 켜져야 한다.
      switch (feature.triggers) {
        case "confidential":
          if (autoEnableConfidential(mode, opts.threadId)) {
            toast.info("기밀 모드를 켰습니다 — 이 대화는 원내 모델로만 처리됩니다.", {
              duration: 7000,
              action: { label: "끄기", onClick: () => setConfidential(false, opts.threadId) },
            });
          }
          break;
        case "attach":
          // 첨부 시 ChatInput 이 기밀을 자동으로 켠다 — 여기서 중복하지 않는다.
          window.dispatchEvent(new CustomEvent(OPEN_ATTACH_EVENT));
          break;
        case "brief":
          window.dispatchEvent(new CustomEvent(OPEN_BRIEF_EVENT));
          break;
        case "watch":
          window.dispatchEvent(new CustomEvent(OPEN_WATCH_EVENT));
          break;
        default:
          break;
      }
    },
    [mode, onPrefill, opts.threadId],
  );
}
