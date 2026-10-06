/**
 * 연계 보고서 → Markdown (2026-10-06). 프런트에서 조립 — 백엔드 호출 없음.
 * 심층 보고서(`/reports`)와 무관: 화면에 보이는 절·답변·인용을 그대로 파일로.
 */

import { parseNextStepsMarker } from "@/lib/parse/nextSteps";
import { stripPathwayMarker } from "@/lib/parse/pathwayMarker";
import { stripVerdictMarker } from "@/lib/parse/verdict";
import type { Turn } from "@/lib/store/types";

export function cleanAnswer(content: string): string {
  return stripVerdictMarker(parseNextStepsMarker(stripPathwayMarker(content)).clean).trim();
}

export function runReportMarkdown(opts: {
  name?: string;
  turns: Turn[];
  date?: Date;
}): string {
  const d = opts.date ?? new Date();
  const ymd = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const out: string[] = [`# ${opts.name?.trim() || "기능연계 보고서"}`, "", `_${ymd} · ${opts.turns.length}단계_`, ""];
  opts.turns.forEach((t, i) => {
    const f = t.feature;
    out.push(`## ${i + 1}. ${f?.title ?? "질문"}`, "");
    const vals = Object.entries(f?.values ?? {}).filter(([, v]) => (v ?? "").trim());
    if (vals.length) {
      out.push(...vals.map(([k, v]) => `- **${k}**: ${v.trim()}`), "");
    }
    if (t.answer?.content) {
      out.push(cleanAnswer(t.answer.content), "");
      const cites = t.answer.citations ?? [];
      if (cites.length) {
        out.push("### 근거", "");
        for (const c of cites) {
          const title = (c.title ?? "").trim() || "(제목 없음)";
          const url = (c as { url?: string }).url;
          out.push(`- [${c.number}] ${title}${url ? ` — ${url}` : ""}`);
        }
        out.push("");
      }
    } else if (t.status === "error") {
      out.push("_（이 단계는 오류로 끝났습니다）_", "");
    } else {
      out.push("_（답변 없음）_", "");
    }
  });
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trimEnd() + "\n";
}
