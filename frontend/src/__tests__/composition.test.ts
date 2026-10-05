import { describe, expect, it } from "vitest";

import { featuresFor } from "@/lib/features/catalog";
import { emptyStep, stepBlanks, stepMessage } from "@/lib/features/composition";

const pathway = featuresFor({ mode: "expert", hasTurns: true }).find((f) => f.id === "pathway")!;

describe("stepBlanks", () => {
  it("빈 칸이 남아 있으면 true, 채우면 false", () => {
    const st = emptyStep(pathway);
    expect(stepBlanks(pathway, st)).toBe(true);
    expect(stepBlanks(pathway, { ...st, values: { subject: "체외진단 의료기기 수입" } })).toBe(false);
  });
  it("폼이 없는 기능은 빈 칸이 없다", () => {
    const f = { ...pathway, form: undefined };
    expect(stepBlanks(f, emptyStep(f))).toBe(false);
  });
});

describe("stepMessage", () => {
  it("첫 단계의 빈 칸은 템플릿 표식 그대로", () => {
    expect(stepMessage(pathway, emptyStep(pathway), 0)).toContain("___(대상)");
  });
  it("문장형 힌트는 명사만 남겨 치환한다", () => {
    const prec = featuresFor({ mode: "expert", hasTurns: true }).find((f) => f.id === "prec_issues")!;
    const m = stepMessage(prec, emptyStep(prec), 0, { fromConversation: true });
    expect(m).toContain("(앞 대화에서 정리한 쟁점)");
    expect(m).not.toContain("적어 주세요)");
    expect(m.startsWith("지금까지의 대화 내용과 근거를")).toBe(true);
  });
  it("2단계부터 빈 칸은 앞 단계 결과를 가리킨다", () => {
    const m = stepMessage(pathway, emptyStep(pathway), 1);
    expect(m).not.toContain("___(");
    expect(m).toContain("(앞 단계에서 정리한 대상)");
    expect(m.startsWith("앞 단계에서 정리한 내용과 근거를")).toBe(true);
  });
});
