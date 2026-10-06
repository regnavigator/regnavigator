import { describe, expect, it } from "vitest";

import { featuresFor } from "@/lib/features/catalog";
import {
  emptyStep, fromTemplate, stepBlanks, stepMessage, toTemplateSteps, type Composition,
} from "@/lib/features/composition";
import { findGaps } from "@/lib/features/gaps";

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

describe("연계 공백 판정 findGaps", () => {
  const all = featuresFor({ mode: "expert", hasTurns: true });
  const byId = new Map(all.map((f) => [f.id, f]));
  const steps = (...ids: string[]) => ids.map((id) => emptyStep(byId.get(id)!));
  const none = { hasTurns: false, hasFormCitations: false, hasAttachments: false };

  it("사건 검토 → 의견서: 판례가 빠졌다", () => {
    const gaps = findGaps(steps("case_issues", "brief"), byId, none, all);
    expect(gaps.map((g) => [g.at, g.slot])).toEqual([[1, "precedent"]]);
    expect(gaps[0]!.candidates.map((c) => c.id)).toContain("prec_issues");
  });
  it("사건 검토 → 판례 → 의견서: 공백 없음", () => {
    expect(findGaps(steps("case_issues", "prec_issues", "brief"), byId, none, all)).toEqual([]);
  });
  it("채울 기능이 없는 슬롯(subject 는 사용자 입력)은 제안하지 않는다", () => {
    // form_find 는 subject 가 필요하지만 subject 를 '내는' 기능은 없다 — 끼울 단계가
    // 없는 공백은 제안이 아니라 폼 빈 칸이다. 대화가 있어도 결과는 같다.
    const s = steps("prec_issues", "form_find");
    expect(findGaps(s, byId, none, all)).toEqual([]);
    expect(findGaps(s, byId, { ...none, hasTurns: true }, all)).toEqual([]);
  });
  it("첨부가 있으면 doc 공백이 아니다", () => {
    const s = steps("prec_issues", "rule_gap");
    expect(findGaps(s, byId, none, all).map((g) => g.slot)).toEqual([]); // doc 을 내는 기능도 없다
    expect(findGaps(s, byId, { ...none, hasAttachments: true }, all)).toEqual([]);
  });
  it("첫 단계의 빈 입력은 공백으로 보지 않는다 (폼에 직접 적는다)", () => {
    expect(findGaps(steps("prec_issues", "sanction_level"), byId, none, all)
      .map((g) => [g.at, g.slot])).toEqual([[1, "duty"]]);
  });
  it("단계 1개는 공백 없음", () => {
    expect(findGaps(steps("brief"), byId, none, all)).toEqual([]);
  });
});
