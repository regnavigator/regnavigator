import { describe, expect, it } from "vitest";

import { featuresFor } from "@/lib/features/catalog";
import {
  emptyStep, fromTemplate, stepBlanks, stepMessage, toTemplateSteps, type Composition,
} from "@/lib/features/composition";

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

describe("직무 템플릿 ↔ 조합", () => {
  const all = featuresFor({ mode: "expert", hasTurns: true });
  const byId = new Map(all.map((f) => [f.id, f]));

  it("toTemplateSteps 는 값·파일·done 을 버린다", () => {
    const c: Composition = {
      steps: [{ fn: "case_issues", values: { facts: "비밀" }, files: [{ id: "wff_1", name: "a.pdf", chars: 3 }],
                confidential: true, done: true },
              { fn: "prec_issues", values: {}, files: [], confidential: false, done: true }],
      cursor: 2, mode: "auto", status: "done",
    };
    expect(toTemplateSteps(c)).toEqual([
      { fn: "case_issues", confidential: true }, { fn: "prec_issues", confidential: false }]);
    expect(JSON.stringify(toTemplateSteps(c))).not.toContain("비밀");
  });

  it("fromTemplate 는 없는 id 를 걸러 cursor 0 / draft 로 복원한다", () => {
    const r = fromTemplate(
      [{ fn: "case_issues", confidential: true }, { fn: "gone_feature", confidential: false },
       { fn: "prec_issues", confidential: false }], byId);
    expect(r.dropped).toEqual(["gone_feature"]);
    expect(r.composition?.steps.map((s) => s.fn)).toEqual(["case_issues", "prec_issues"]);
    expect(r.composition?.steps[0]?.confidential).toBe(true);
    expect(r.composition?.cursor).toBe(0);
    expect(r.composition?.status).toBe("draft");
    expect(r.composition?.steps.every((s) => Object.keys(s.values).length === 0 && s.files.length === 0)).toBe(true);
  });

  it("전부 없는 id 면 조합 없음", () => {
    expect(fromTemplate([{ fn: "x", confidential: false }], byId).composition).toBeNull();
  });
});
