import { describe, expect, it } from "vitest";

import { runReportMarkdown } from "@/lib/export/runReport";
import { groupRuns } from "@/lib/features/groupRuns";
import type { Turn } from "@/lib/store/types";

const run = (id: string, index: number, total: number, title: string, name?: string) =>
  ({ id, title, values: {}, run: { id: "run_1", index, total, name } });

const turn = (id: string, feature?: Turn["feature"], content = "답"): Turn =>
  ({ id, user_message: { id, content: "프롬프트 전문" }, status: "done", started_at: 1,
     steps: [], feature,
     answer: { id: `a-${id}`, content, citations: [{ id: "c1", number: 1, title: "의료법 제27조", source_kind: "doc" }] } }) as unknown as Turn;

describe("groupRuns", () => {
  it("연속한 같은 run 턴을 하나로 묶는다", () => {
    const blocks = groupRuns([
      turn("q0"),
      turn("s0", run("a", 0, 3, "사실관계", "사건 초기 검토")),
      turn("s1", run("b", 1, 3, "판례")),
      turn("s2", run("c", 2, 3, "법리")),
      turn("q1"),
    ]);
    expect(blocks.map((b) => b.kind)).toEqual(["turn", "run", "turn"]);
    const r = blocks[1]!;
    if (r.kind !== "run") throw new Error();
    expect(r.turns.map((t) => t.id)).toEqual(["s0", "s1", "s2"]);
    expect(r.name).toBe("사건 초기 검토");
    expect(r.total).toBe(3);
  });
  it("단계 사이에 일반 질문이 끼면 run 이 끊긴다", () => {
    const blocks = groupRuns([
      turn("s0", run("a", 0, 2, "A")), turn("q"), turn("s1", run("b", 1, 2, "B")),
    ]);
    expect(blocks.map((b) => b.kind)).toEqual(["run", "turn", "run"]);
  });
  it("단일 기능 실행(run 없음)은 보통 턴", () => {
    const blocks = groupRuns([turn("f", { id: "prec_issues", title: "판례", values: { 쟁점: "x" } })]);
    expect(blocks[0]!.kind).toBe("turn");
  });
});

describe("runReportMarkdown", () => {
  it("제목·절·입력·본문·근거를 조립하고 마커를 벗긴다", () => {
    const md = runReportMarkdown({
      name: "상대 서면 대응",
      date: new Date(2026, 9, 6),
      turns: [
        turn("s0", { id: "counter_argument", title: "상대방 주장 분석", values: { "상대 주장": "구두 해지" },
                     run: { id: "r", index: 0, total: 2 } },
             "주장은 세 가지다.\n<next_steps>\n- 다음\n</next_steps>"),
        turn("s1", { id: "legal_memo", title: "쟁점별 법리 검토", values: {}, run: { id: "r", index: 1, total: 2 } }),
      ],
    });
    expect(md.startsWith("# 상대 서면 대응\n\n_2026-10-06 · 2단계_")).toBe(true);
    expect(md).toContain("## 1. 상대방 주장 분석");
    expect(md).toContain("- **상대 주장**: 구두 해지");
    expect(md).toContain("주장은 세 가지다.");
    expect(md).not.toContain("<next_steps>");
    expect(md).toContain("### 근거\n\n- [1] 의료법 제27조");
    expect(md).toContain("## 2. 쟁점별 법리 검토");
    expect(md).not.toContain("프롬프트 전문");
  });
});
