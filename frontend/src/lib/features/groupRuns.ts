/**
 * 연계 턴 묶기 (2026-10-06) — 연속한 같은 `feature.run.id` 턴들을 **보고서 한 편**으로.
 *
 * 사용자 지적: 연계 결과가 턴 여러 개로 흩어지고 사이사이 프롬프트 말풍선이 끼면 읽을
 * 수 없다. 단계 턴은 보고서의 절(section)이지 대화가 아니다. 순수 함수 — vitest 로 고정.
 *
 * 연속한 턴만 묶는다: 단계 사이에 사용자가 일반 질문을 끼워 넣었다면 run 이 끊긴다 —
 * 그 질문은 그 자리에 그대로 보여야 한다.
 */

import type { Turn } from "@/lib/store/types";

export type TurnBlock =
  | { kind: "turn"; turn: Turn }
  | { kind: "run"; runId: string; name?: string; total: number; turns: Turn[] };

export function groupRuns(turns: Turn[]): TurnBlock[] {
  const out: TurnBlock[] = [];
  for (const t of turns) {
    const run = t.feature?.run;
    const last = out.at(-1);
    if (run && last?.kind === "run" && last.runId === run.id) {
      last.turns.push(t);
      if (run.name && !last.name) last.name = run.name;
      last.total = Math.max(last.total, run.total);
      continue;
    }
    if (run) {
      out.push({ kind: "run", runId: run.id, name: run.name, total: run.total, turns: [t] });
      continue;
    }
    out.push({ kind: "turn", turn: t });
  }
  return out;
}
