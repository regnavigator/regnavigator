/**
 * `<pathway>` 마커 파싱 — 규제 경로 단계 (2026-10-01).
 *
 * `<next_steps>` 와 **같은 계약**이다: 모델이 본문 말미에 마커를 붙이고, 본문은
 * 그대로 영속되며, FE 가 파싱해 카드로 렌더하고 본문에서는 가린다.
 *
 * 전용 SSE 이벤트로 받지 않는 이유 — 이벤트는 휘발이라 새로고침·스레드 재방문
 * 때 경로가 사라진다. 메시지 본문에 있으면 저장·복원이 공짜다.
 *
 * 스트리밍 중에는 닫는 태그가 아직 안 왔을 수 있어 세 경우를 처리한다:
 * 닫힌 블록 / 열린 채 진행 중 / 여는 태그가 깨진 꼬리(`<pathw` 등).
 */

import type { PathwayStep } from "@/lib/store/types/state";

const CLOSED_RE = /<pathway>\s*([\s\S]*?)\s*<\/pathway>/i;
const CLOSED_ALL_RE = /<pathway>[\s\S]*?<\/pathway>/gi;
const OPEN_RE = /<pathway>[\s\S]*$/i;
const OPEN_TAG = "<pathway>";
const PARTIAL_OPEN_RE = /<[a-z]{0,8}$/i;
const FENCE_RE = /^```(?:json)?\s*|\s*```$/g;

const MAX_STEPS = 12;
const LIMIT: Record<string, number> = {
  title: 80, what: 300, where: 120, form: 160, when: 80, note: 300,
};

function clip(v: unknown, key: string): string | null {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  return s ? s.slice(0, LIMIT[key] ?? 200) : null;
}

function cites(v: unknown): number[] {
  if (!Array.isArray(v)) return [];
  const out: number[] = [];
  for (const x of v.slice(0, 10)) {
    const n = Number(String(x).trim().replace(/^\[|\]$/g, ""));
    if (Number.isInteger(n) && n >= 1 && n <= 999 && !out.includes(n)) out.push(n);
  }
  return out;
}

/** 본문에서 마커 블록을 걷어낸다(스트리밍 중 꼬리 포함). */
export function stripPathwayMarker(content: string): string {
  if (!content) return content;
  let out = content.replace(CLOSED_ALL_RE, "");
  if (OPEN_RE.test(out)) out = out.replace(OPEN_RE, "");
  const partial = out.match(PARTIAL_OPEN_RE);
  if (partial && OPEN_TAG.startsWith(partial[0].toLowerCase())) {
    out = out.slice(0, out.length - partial[0].length);
  }
  return out.trimEnd();
}

/** 마커에서 단계 목록을 꺼낸다. 없거나 깨졌으면 빈 배열. */
export function parsePathwayMarker(content: string): PathwayStep[] {
  const m = content?.match(CLOSED_RE);
  if (!m?.[1]) return [];

  let data: unknown;
  try {
    data = JSON.parse(m[1].replace(FENCE_RE, ""));
  } catch {
    return [];   // JSON 깨짐 — 마커는 strip 되고 카드만 안 뜬다
  }
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const o = data as Record<string, unknown>;
    data = o.steps ?? o.pathway;
  }
  if (!Array.isArray(data)) return [];

  const steps: PathwayStep[] = [];
  for (const item of data.slice(0, MAX_STEPS)) {
    if (!item || typeof item !== "object") continue;
    const o = item as Record<string, unknown>;
    const title = clip(o.title ?? o.step, "title");
    const what = clip(o.what ?? o.desc, "what");
    if (!title && !what) continue;
    steps.push({
      no: steps.length + 1,
      title: title ?? `${steps.length + 1}단계`,
      what,
      where: clip(o.where, "where"),
      form: clip(o.form, "form"),
      when: clip(o.when ?? o.deadline, "when"),
      note: clip(o.note, "note"),
      cites: cites(o.cites ?? o.citations),
    });
  }
  return steps;
}
