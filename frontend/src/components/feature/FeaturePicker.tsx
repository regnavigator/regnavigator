"use client";

/**
 * FeaturePicker — 스레드 **안에서** 기능을 바꿔 가며 이어 묻는 진입점 (2026-10-02).
 *
 * 사용자 요구: "인허가 질문을 하고 나서 관련 서식을 정리한다든지, 법적 쟁점을
 * 검토한 다음 관련 문서를 첨부해 검토한다든지 — 어떤 모드로든 질문이 시작되고 나면
 * 카드들이 스레드 내에서 자유롭게 선택돼야 한다."
 *
 * 첫 화면 카드는 첫 턴이 생기는 순간 사라진다. 그래서 입력창 툴바에 상시 진입점을
 * 하나 두고, 그 안에서 **격자 + 검색**으로 고르게 한다 — 기능이 늘어나도 버틴다.
 *
 * 여기서 고르는 것은 **앱 모드(일반/전문가/모니터링)가 아니라 그 턴의 기능**이다.
 * 대화 중간에 앱 모드까지 바뀌면 같은 스레드에서 답변 어투가 섞이고 기밀 토글이
 * 사라졌다 나타난다. 모드는 사이드바에서만 바꾼다.
 */

import { useMemo, useState } from "react";

import { FeatureCards } from "@/components/feature/FeatureCards";
import { FeatureDialog } from "@/components/feature/FeatureDialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  featuresFor,
  filterFeatures,
  type Feature,
  type FeatureContext,
} from "@/lib/features/catalog";
import { useRunFeature } from "@/lib/features/useRunFeature";

export function FeaturePicker({
  ctx,
  disabled,
  onPrefill,
  threadId = null,
}: {
  ctx: FeatureContext;
  disabled?: boolean;
  onPrefill?: (text: string) => void;
  /** 기밀 토글 스레드 키(2026-10-03) */
  threadId?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Feature | null>(null);

  const run = useRunFeature({ mode: ctx.mode, onPrefill, threadId });
  const all = useMemo(() => featuresFor(ctx), [ctx]);
  const shown = useMemo(() => filterFeatures(all, q), [all, q]);

  if (!all.length) return null;

  return (
    <>
      <Popover
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setQ("");
        }}
      >
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            data-testid="feature-picker"
            aria-label="기능 선택 — 이 대화에서 이어서 할 수 있는 작업"
            title="이 대화에서 이어서 할 수 있는 작업"
            className="inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low hover:text-md-on-surface disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="material-symbols-outlined text-[16px]" aria-hidden>
              apps
            </span>
            기능
          </button>
        </PopoverTrigger>

        <PopoverContent
          side="top"
          align="start"
          // 420px 고정은 2열 격자가 들어갈 수 없는 폭이었다(실사용 지적).
          // 기능이 늘어날수록 한눈에 들어오는 수가 중요하다.
          className="w-[min(92vw,780px)] p-3"
        >
          <p className="px-1 pb-1.5 text-[11px] leading-snug text-md-on-surface-variant">
            이어서 할 작업을 고르세요. 같은 대화 안에서 진행되며 앞 내용을 그대로
            이어받습니다. 같은 기능을 몇 번이든 다시 쓸 수 있습니다.
          </p>

          {/* 검색은 **항상** 보인다(2026-10-02). 건수에 따라 나타났다 사라지면
              사용자는 그런 기능이 없다고 생각한다(실사용 지적). */}
          <div className="relative mb-2">
            <span
              className="material-symbols-outlined pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[16px] text-md-on-surface-variant"
              aria-hidden
            >
              search
            </span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="기능 찾기 (이름 · 설명 · 분류)"
              data-testid="feature-search"
              className="w-full rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest py-1.5 pl-8 pr-2.5 text-[12.5px] outline-none focus:border-md-primary"
            />
          </div>

          <div className="max-h-[min(58vh,460px)] overflow-y-auto pr-0.5">
            <FeatureCards
              features={shown}
              layout="grid"
              onPick={(f) => {
                setPicked(f);
                setOpen(false);
              }}
            />
          </div>

        </PopoverContent>
      </Popover>

      <FeatureDialog
        feature={picked}
        onClose={() => setPicked(null)}
        onRun={run}
      />
    </>
  );
}
