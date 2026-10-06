import { describe, expect, it } from "vitest";

import { briefKindOf, featuresFor, STAGES } from "@/lib/features/catalog";
import { PRESET_TASKS } from "@/lib/features/presetTasks";
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

  it("fromTemplate 는 직무 이름을 조합에 심는다 (보고서 제목)", () => {
    const r = fromTemplate([{ fn: "prec_issues", confidential: false }], byId, "사건 초기 검토");
    expect(r.composition?.name).toBe("사건 초기 검토");
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

  it("사실관계 → 법리 검토: 쟁점이 빠졌다 (사건 검토·상대 주장 분석이 후보)", () => {
    const gaps = findGaps(steps("facts_timeline", "legal_memo"), byId, none, all);
    expect(gaps.map((g) => [g.at, g.slot])).toEqual([[1, "article"]]);
  });
  it("사실관계 → 판례 비교: 판례가 빠졌다", () => {
    const gaps = findGaps(steps("facts_timeline", "precedent_compare"), byId, none, all);
    expect(gaps.map((g) => [g.at, g.slot])).toEqual([[1, "precedent"]]);
    expect(gaps[0]!.candidates.map((c) => c.id)).toContain("prec_issues");
  });
  it("사건 검토 → 판례 → 법리 검토: 공백 없음", () => {
    expect(findGaps(steps("case_issues", "prec_issues", "legal_memo"), byId, none, all)).toEqual([]);
  });
  it("채울 기능이 없는 슬롯(subject 는 사용자 입력)은 제안하지 않는다", () => {
    const s = steps("prec_issues", "form_find");
    expect(findGaps(s, byId, none, all)).toEqual([]);
    expect(findGaps(s, byId, { ...none, hasTurns: true }, all)).toEqual([]);
  });
  it("첫 단계의 빈 입력은 공백으로 보지 않는다 (폼에 직접 적는다)", () => {
    expect(findGaps(steps("prec_issues", "sanction_level"), byId, none, all)
      .map((g) => [g.at, g.slot])).toEqual([[1, "duty"]]);
  });
  it("단계 1개는 공백 없음", () => {
    expect(findGaps(steps("brief"), byId, none, all)).toEqual([]);
  });
});

describe("기능 카탈로그 20개 · 4단계 (2026-10-06)", () => {
  const all = featuresFor({ mode: "expert", hasTurns: true });
  const byId = new Map(all.map((f) => [f.id, f]));

  it("전문가 기능은 20개, 모두 단계 라벨·아이콘·io 가 있다", () => {
    expect(all).toHaveLength(20);
    for (const f of all) {
      expect(STAGES as string[]).toContain(f.category);
      expect(f.icon, f.id).toBeTruthy();
      expect(f.io, f.id).toBeTruthy();
    }
    expect(all.map((f) => f.category)).toEqual([...all.map((f) => f.category)].sort());
  });
  it("합병·이동된 id 는 레지스트리에 없고 LEGACY_FN 으로 승격된다", () => {
    for (const old of ["pending_watch", "rule_gap", "mon_extract", "impact_graph"]) {
      expect(byId.has(old), old).toBe(false);
    }
    const r = fromTemplate(
      [{ fn: "pending_watch", confidential: false }, { fn: "rule_gap", confidential: true },
       { fn: "mon_extract", confidential: false }], byId);
    expect(r.dropped).toEqual([]);
    expect(r.composition?.steps.map((s) => s.fn)).toEqual(["article_diff", "doc_review", "doc_review"]);
    expect(r.composition?.steps[1]?.confidential).toBe(true);
  });
  it("impact_graph 는 모니터링 모드로 옮겨졌고 doc_review 도 거기 있다", () => {
    const mon = featuresFor({ mode: "monitor", hasTurns: true }).map((f) => f.id);
    expect(mon).toContain("impact_graph");
    expect(mon).toContain("doc_review");
    expect(mon).not.toContain("mon_extract");
  });
  it("추천 직무 3개는 모두 공백 0 이고 8단계 이내", () => {
    const none = { hasTurns: false, hasFormCitations: false, hasAttachments: false };
    for (const t of PRESET_TASKS) {
      const r = fromTemplate(t.steps, byId);
      expect(r.dropped, t.name).toEqual([]);
      expect(r.composition!.steps.length).toBeLessThanOrEqual(8);
      expect(findGaps(r.composition!.steps, byId, none, all), t.name).toEqual([]);
    }
  });
  it("article_diff 의 방향 선택 · doc_review 의 관점 선택이 프롬프트를 바꾼다", () => {
    const ad = byId.get("article_diff")!.form!.build;
    expect(ad({ article: "의료법 제27조", direction: "시행 예정" })).toContain("시행 예정인 개정본");
    expect(ad({ article: "의료법 제27조", direction: "시행 예정" })).not.toContain("개정 주석");
    expect(ad({ article: "의료법 제27조", direction: "과거 개정" })).toContain("개정 주석");
    expect(ad({ article: "의료법 제27조" })).toContain("개정 주석");
    const dr = byId.get("doc_review")!.form!.build;
    expect(dr({ perspective: "내규↔법령 갭" })).toContain("규정 조항 ↔ 근거 법령");
    expect(dr({ perspective: "규제 추출" })).toContain("걸리는 법령");
    expect(dr({})).toContain("규제 적합성");
    const mon = featuresFor({ mode: "monitor", hasTurns: true }).find((f) => f.id === "doc_review")!;
    expect(mon.form!.build({})).toContain("걸리는 법령"); // 모니터링 기본값 = 규제 추출
  });
  it("briefKindOf 는 자유 문자열을 종류 키로", () => {
    expect(briefKindOf("답변서")).toBe("answer");
    expect(briefKindOf("검토 보고")).toBe("review");
    expect(briefKindOf("내용증명")).toBe("demand");
    expect(briefKindOf("질의서")).toBe("inquiry");
    expect(briefKindOf("")).toBe("opinion");
    expect(briefKindOf(undefined)).toBe("opinion");
  });
});
