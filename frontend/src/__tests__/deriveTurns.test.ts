import { describe, expect, it } from "vitest";

import { deriveTurns } from "@/lib/parse/derive";
import type { Message, Step } from "@/lib/store/types";

const human = (id: string, content: string, hidden?: boolean): Message =>
  ({ id, type: "human", content, ...(hidden ? { hidden: true } : {}) }) as Message;
const ai = (id: string, content: string): Message =>
  ({ id, type: "ai", content }) as Message;
const step = (id: string, src: string, n: number): Step =>
  ({ id, ts: 1, label: "s", status: "done", tool_name: "qdrant_search",
     source_message_id: src,
     citations: [{ id: `cite_doc_k${n}`, number: n, title: `t${n}`,
                   source_kind: "doc" }] }) as unknown as Step;

describe("deriveTurns", () => {
  it("human 마다 턴 하나, 답변·인용이 그 턴에 묶인다", () => {
    const turns = deriveTurns(
      [human("h1", "q1"), ai("a1", "답 [1]"), human("h2", "q2"), ai("a2", "답2 [2]")],
      {},
      [step("s1", "h1", 1), step("s2", "h2", 2)],
    );
    expect(turns).toHaveLength(2);
    expect(turns[0]!.answer?.content).toBe("답 [1]");
    expect(turns[0]!.answer?.citations.map((c) => c.number)).toEqual([1]);
    expect(turns[1]!.answer?.citations.map((c) => c.number)).toEqual([2]);
    expect(turns.every((t) => t.status === "done")).toBe(true);
  });

  it("숨은 턴(hidden)은 턴에 표시가 붙는다 — 조합 중간 단계", () => {
    const turns = deriveTurns([human("h1", "단계", true), ai("a1", "산출")], {}, []);
    expect(turns[0]!.hidden).toBe(true);
  });

  it("마지막 human 에 답변이 없으면 running", () => {
    const turns = deriveTurns([human("h1", "q")], {}, []);
    expect(turns[0]!.status).toBe("running");
    expect(turns[0]!.answer).toBeUndefined();
  });

  it("step 이 다른 턴으로 새지 않는다(source_message_id 기준)", () => {
    const turns = deriveTurns(
      [human("h1", "q1"), ai("a1", "a"), human("h2", "q2"), ai("a2", "b")],
      {},
      [step("s2", "h2", 2)],
    );
    expect(turns[0]!.steps).toHaveLength(0);
    expect(turns[1]!.steps).toHaveLength(1);
  });
});

describe("deriveTurns — feature 메타(2026-10-06)", () => {
  it("human 메시지의 feature 가 턴에 그대로 실린다", () => {
    const feature = { id: "prec_issues", title: "판례", values: { 쟁점: "x" },
                      run: { id: "run_1", index: 0, total: 2 } };
    const h = { id: "h1", type: "human", content: "프롬프트", feature } as unknown as Message;
    const turns = deriveTurns([h, ai("a1", "답")], {}, []);
    expect(turns[0]!.feature).toEqual(feature);
    expect(turns[0]!.user_message.content).toBe("프롬프트");
  });
});
