/**
 * 조합(composition) — 타입 · 서버 왕복 · 단계 메시지 조립 (2026-10-02).
 *
 * 조합은 **기능(function) 들의 순서 + 단계별 입력·파일·기밀**이다. 저장 형태는
 * 그대로 장기 목표인 **직무(task)** 의 저장 형태가 된다 — task 는 "이 객체에
 * 이름을 붙여 따로 저장하는 것"으로 끝나야 하므로 단계 하나가 자족적이다.
 *
 * 실행 모델: 각 단계는 **숨은 턴**으로 돌고, 마지막에 종합 1건만 보인다.
 * 단계마다 답을 쏟으면 읽을 수 없는 대화가 된다.
 */

import { apiFetch } from "@/lib/api/client";
import { LEGACY_FN, type Feature } from "@/lib/features/catalog";

export type CompositionFile = { id: string; name: string; chars: number };

export type CompositionStep = {
  /** 기능 id (`Feature.id`) */
  fn: string;
  values: Record<string, string>;
  files: CompositionFile[];
  confidential: boolean;
  done: boolean;
};

export type Composition = {
  steps: CompositionStep[];
  /** 다음에 실행할 단계. `steps.length` 면 완료 */
  cursor: number;
  /** stepwise = 단계마다 멈춰 사람이 검토 · auto = 끝까지 자동 */
  mode: "stepwise" | "auto";
  status: "draft" | "running" | "done";
};

export function emptyStep(f: Feature): CompositionStep {
  return {
    fn: f.id,
    values: {},
    files: [],
    // 기밀이 필요한 기능은 기본값을 켜 둔다 — 끄는 건 의식적 선택이어야 한다.
    confidential: f.triggers === "confidential" || f.triggers === "attach",
    done: false,
  };
}

/** 이 단계가 지금 실행 가능한가. 파일이 필요한데 없으면 못 돈다. */
export function stepReady(f: Feature | undefined, st: CompositionStep): boolean {
  if (!f) return false;
  if (needsFiles(f) && st.files.length === 0) return false;
  return true;
}

/**
 * 채워야 할 빈 칸이 남았는가 (2026-10-05). 폼의 `build` 는 빈 값을 `___(힌트)` 로
 * 남기므로 그 표식이 곧 "아직 못 보낼 문장"이다 — 템플릿 규칙과 같은 진실원을 쓴다.
 */
export function stepBlanks(f: Feature, st: CompositionStep): boolean {
  if (!f.form) return false;
  const cleaned: Record<string, string> = {};
  for (const [k, v] of Object.entries(st.values)) cleaned[k] = (v ?? "").trim();
  return f.form.build(cleaned).includes("___(");
}

/** 파일을 올려야만 의미가 있는 기능인가 — `triggers:"attach"` 가 그 표식이다. */
export function needsFiles(f: Feature): boolean {
  return f.triggers === "attach";
}

/* ─────────────────── 서버 왕복 ─────────────────── */

export async function saveComposition(
  threadId: string,
  c: Composition,
): Promise<{ workflow: Composition | null }> {
  return apiFetch(`/chat/${encodeURIComponent(threadId)}/workflow`, {
    method: "PATCH",
    body: JSON.stringify(c),
  });
}

export async function uploadStepFile(
  threadId: string,
  file: File,
): Promise<CompositionFile & { truncated?: boolean }> {
  const fd = new FormData();
  fd.append("file", file);
  return apiFetch(`/chat/${encodeURIComponent(threadId)}/workflow/files`, {
    method: "POST",
    body: fd,
  });
}

export async function deleteStepFile(
  threadId: string,
  fileId: string,
): Promise<void> {
  await apiFetch(
    `/chat/${encodeURIComponent(threadId)}/workflow/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE" },
  );
}

/** 앞 단계 산출 → 다음 단계 입력 초안. 실패하면 빈 객체(조합을 막지 않는다). */
export async function suggestValues(
  threadId: string,
  title: string,
  fields: { key: string; label?: string; placeholder?: string }[],
): Promise<Record<string, string>> {
  try {
    const r = await apiFetch<{ values: Record<string, string> }>(
      `/chat/${encodeURIComponent(threadId)}/workflow/suggest`,
      { method: "POST", body: JSON.stringify({ title, fields }) },
    );
    return r.values ?? {};
  } catch {
    return {};
  }
}

/* ─────────────────── 직무(task) 템플릿 ↔ 조합 ─────────────────── */

export type TemplateStep = { fn: string; confidential: boolean };

/**
 * 조합 → 템플릿 단계. **값·파일·done 을 버린다** — 값은 사건마다 다르고 저장하면
 * 다음 사건에 지난 사실관계가 섞인다(기밀 격리). 파일은 스레드 소속이라 못 옮긴다.
 */
export function toTemplateSteps(c: Composition): TemplateStep[] {
  return c.steps
    .filter((st) => st.fn.trim())
    .map((st) => ({ fn: st.fn, confidential: st.confidential }));
}

/**
 * 템플릿 → 새 조합(cursor 0, draft). 레지스트리에 없는 기능 id 는 **버리고** 이름을
 * 돌려준다 — 문서의 "끊어진 노드" 검증에 해당. 기능 목록의 진실원은 프런트라 여기서 한다.
 */
export function fromTemplate(
  steps: TemplateStep[],
  byId: Map<string, Feature>,
): { composition: Composition | null; dropped: string[] } {
  const dropped: string[] = [];
  const out: CompositionStep[] = [];
  for (const st of steps) {
    // 합병·이동된 id 는 조용히 승격한다(2026-10-06) — 저장된 직무가 끊기지 않는다.
    const fn = LEGACY_FN[st.fn] ?? st.fn;
    const f = byId.get(fn);
    if (!f) { dropped.push(st.fn); continue; }
    out.push({ ...emptyStep(f), confidential: st.confidential });
  }
  if (!out.length) return { composition: null, dropped };
  return {
    composition: { steps: out, cursor: 0, mode: "stepwise", status: "draft" },
    dropped,
  };
}

/* ─────────────────── 단계 메시지 ─────────────────── */

/**
 * 단계 하나를 보낼 메시지.
 *
 * 첫 단계가 아니면 "앞 단계를 이어받으라"는 한 줄을 덧붙인다. 앞 단계의 산출을
 * 본문에 **옮겨 담지는 않는다** — 같은 스레드의 연속된 턴이라 모델이 이미 본다.
 * 누적분을 직렬화하는 것은 컨텍스트를 터뜨린 이력이 있다.
 */
export function stepMessage(
  f: Feature,
  st: CompositionStep,
  index: number,
  opts?: { fromConversation?: boolean },
): string {
  const lead =
    index > 0
      ? "앞 단계에서 정리한 내용과 근거를 그대로 이어받아서 진행해줘.\n\n"
      : opts?.fromConversation
        ? "지금까지의 대화 내용과 근거를 그대로 이어받아서 진행해줘.\n\n"
        : "";
  if (f.form) {
    const cleaned: Record<string, string> = {};
    for (const [k, v] of Object.entries(st.values)) cleaned[k] = (v ?? "").trim();
    const body = f.form.build(cleaned);
    // 남은 빈 칸은 앞 단계(2단계부터) 또는 앞 대화(대화 중 첫 단계)의 결과를 가리키게
    // 바꾼다(2026-10-05 실측 정정). `___(대상)` 그대로 보내면 모델이 "란이 비어
    // 있습니다"로 멈춘다. 연계는 앞 결과가 다음 입력이므로 따로 적지 않아도 이어진다.
    const ref = index > 0 ? "앞 단계" : opts?.fromConversation ? "앞 대화" : null;
    // 힌트가 "쟁점을 적어 주세요" 같은 문장이면 명사만 남긴다 — 그대로 치환하면
    // "(앞 대화에서 정리한 쟁점을 적어 주세요)" 가 된다(2026-10-05 실측).
    const noun = (h: string) =>
      h.replace(/[을를은는이가]?\s*(적어|붙여 넣어|입력해|써)\s*주세요\.?$/u, "").trim() || h;
    return lead + (ref
      ? body.replace(/___\(([^)]*)\)/g, (_m, h: string) => `(${ref}에서 정리한 ${noun(h)})`)
      : body);
  }
  return lead + f.title;
}

/**
 * 마지막 종합 — 이것만 화면에 보인다.
 *
 * 사용자 말풍선으로 남는 문장이라 읽을 수 있어야 한다. 긴 지시문을 그대로 두면
 * 대화가 지저분해지므로 단계 목록 + 짧은 요구로 쓴다.
 */
export function synthesisMessage(titles: string[]): string {
  const list = titles.map((t, i) => `${i + 1}. ${t}`).join("\n");
  return (
    `다음 단계를 거쳤어.\n${list}\n\n` +
    "각 단계에서 확인한 것을 하나로 종합해서 정리해줘. " +
    "결론과 근거를 먼저 쓰고, 단계별로 무엇이 확인됐는지, " +
    "그리고 아직 확인되지 않은 쟁점이 무엇인지 적어줘. " +
    "앞 단계에서 확인되지 않은 것을 새로 지어내지 마."
  );
}
