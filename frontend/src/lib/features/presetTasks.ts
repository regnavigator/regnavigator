/**
 * 추천 직무(2026-10-06) — 코드 동봉. 사용자 저장분(`/task-templates`)과 섞지 않고 "추천"
 * 라벨로 따로 보인다. 저장분이 없을 때 첫 화면에도 선다. 모두 `findGaps` 공백 0(테스트).
 */

import type { TaskTemplateStep } from "@/lib/client/taskTemplates";

export type PresetTask = { id: string; name: string; steps: TaskTemplateStep[]; about: string };

const s = (fn: string, confidential = false): TaskTemplateStep => ({ fn, confidential });

export const PRESET_TASKS: PresetTask[] = [
  {
    id: "preset_case_intake",
    name: "사건 초기 검토",
    about: "수임 직후 · 첫 상담 회신",
    steps: [
      s("facts_timeline", true), s("question_list"), s("case_issues", true),
      s("prec_issues"), s("precedent_compare"), s("legal_memo"), s("client_brief"),
    ],
  },
  {
    id: "preset_regulatory",
    name: "인허가·컴플라이언스 자문",
    about: "규제 자문",
    steps: [s("pathway"), s("duty_matrix"), s("deadline_calendar"), s("form_find")],
  },
  {
    id: "preset_rebuttal",
    name: "상대 서면 대응",
    about: "소송·분쟁",
    steps: [
      s("counter_argument", true), s("cite_verify"), s("prec_issues"),
      s("evidence_map", true), s("legal_memo"), s("brief"),
    ],
  },
];
