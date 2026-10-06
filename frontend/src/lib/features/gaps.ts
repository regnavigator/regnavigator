/**
 * 연계 공백 판정 (2026-10-06) — `Vibe_Coding_Agent_Master_Prompt.docx` 의 "자가치유
 * 라우팅" 을 사용자 정정대로 읽은 것: **사용자가 짠 연계에 빠진 단계가 있으면 채워 제안**.
 *
 * 결정적이다 — 각 기능의 `io.needs`/`io.yields`(`catalog.ts`)만 본다. LLM 도 판단 모델도
 * 쓰지 않는다. 제안일 뿐 자동 삽입하지 않는다(실행 전 사용자가 보고 승인).
 */

import { SLOT_LABEL, type Feature, type Slot } from "@/lib/features/catalog";
import type { CompositionStep } from "@/lib/features/composition";

export type Gap = {
  /** 이 단계 **앞에** 빠진 것 */
  at: number;
  slot: Slot;
  label: string;
  /** 그 슬롯을 내는 기능 — 제안 후보(등록 순) */
  candidates: Feature[];
};

/** 대화·첨부에서 이미 확보된 것 — 첫 단계 앞의 공백을 메운다. */
export type GapContext = {
  hasTurns: boolean;
  hasFormCitations: boolean;
  hasAttachments: boolean;
};

export function contextSlots(ctx: GapContext): Set<Slot> {
  const s = new Set<Slot>();
  // 대화가 있으면 사실관계·쟁점·대상은 거기서 나온다(자동 채움이 그걸 읽는다).
  if (ctx.hasTurns) { s.add("facts"); s.add("issue"); s.add("subject"); }
  if (ctx.hasFormCitations) s.add("form");
  if (ctx.hasAttachments) s.add("doc");
  return s;
}

export function findGaps(
  steps: CompositionStep[],
  byId: Map<string, Feature>,
  ctx: GapContext,
  all: Feature[],
): Gap[] {
  // 단계 1개는 연계가 아니다 — 공백도 없다.
  if (steps.length < 2) return [];
  const have = contextSlots(ctx);
  const out: Gap[] = [];
  steps.forEach((st, i) => {
    const f = byId.get(st.fn);
    if (!f?.io) return;
    if (st.files.length) have.add("doc");
    for (const need of f.io.needs) {
      const alts = Array.isArray(need) ? need : [need];
      if (alts.some((a) => have.has(a))) continue;
      // 첫 단계의 입력은 사용자가 폼에 직접 적는다 — 그 앞엔 끼울 단계가 없다.
      if (i === 0) continue;
      const slot = alts[0]!;
      const candidates = all.filter(
        (c) => c.io?.yields.includes(slot) && c.id !== f.id && !c.triggers,
      );
      if (!candidates.length) continue;
      out.push({ at: i, slot, label: SLOT_LABEL[slot], candidates });
    }
    for (const y of f.io.yields) have.add(y);
  });
  return out;
}
