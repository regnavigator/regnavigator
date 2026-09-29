/**
 * Turn 파생 — back §8, 05 §2.1, P5.7.
 *
 * raw `state.{messages, files, steps}`로부터 UI가 소비할 `Turn[]`을 만든다.
 *
 * **핵심 규칙**:
 * - 새 `human` 메시지 = 새 Turn 시작 (turn.id = human.id)
 * - 다음 `human` 메시지 또는 stream 종료 = Turn 끝
 * - Turn 안의 step = `state.steps`에서 `ts`가 turn 범위에 포함되는 것
 *   - 마지막 turn은 `ts >= turn.started_at` (끝나지 않은 step도 포함)
 * - Turn 안의 마지막 ai message text → `answer.content`
 * - `answer.citations` = 본문 [n] + step.citations 합집합 (id dedupe, number 순)
 * - `answer.artifacts` = 이 turn 동안 변경/생성된 file path
 *
 * 본 모듈은 *재연결 시 전체 재파생*에 사용 (back §9). 매 chunk마다 호출하지 말 것 —
 * incremental update는 `lib/store/turns.ts`가 담당.
 *
 * 모든 필드 네이밍은 snake_case (back §10 I11).
 */

import type {
  Artifact,
  Citation,
  FileEntry,
  Message,
  Step,
  Turn,
} from "@/lib/store/types";
import { parseCitationTokens } from "@/lib/parse/citation";

const MD_HEADING_RE = /^#\s+(.+)$/m;

function basename(path: string): string {
  const idx = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return idx >= 0 ? path.slice(idx + 1) : path;
}

function extractTitle(text: string): string | undefined {
  const m = text.match(MD_HEADING_RE);
  return m ? m[1]!.trim() : undefined;
}

function mimeFromExt(ext: string | undefined): string | undefined {
  if (!ext) return undefined;
  switch (ext.toLowerCase()) {
    case "md":
      return "text/markdown";
    case "txt":
      return "text/plain";
    case "json":
      return "application/json";
    case "csv":
      return "text/csv";
    case "html":
      return "text/html";
    case "pdf":
      return "application/pdf";
    default:
      return undefined;
  }
}

/**
 * `state.files[path]` → `Artifact` view (05 §2.4 그대로).
 * bytes는 content를 join한 텍스트의 UTF-8 바이트 길이.
 */
export function toArtifact(path: string, entry: FileEntry): Artifact {
  const text = (entry.content ?? []).join("\n");
  const ext = path.split(".").pop();
  const enc = typeof TextEncoder !== "undefined" ? new TextEncoder() : null;
  const bytes = enc ? enc.encode(text).length : text.length;
  return {
    path,
    bytes,
    modified_at: entry.modified_at,
    is_streaming: entry.is_streaming ?? false,
    title: extractTitle(text) ?? basename(path),
    mime_type: mimeFromExt(ext),
  };
}

/**
 * AI 메시지 content를 평문 string으로 정규화 — Anthropic block / list / string 모두 흡수.
 */
export function aiMessageText(msg: Message): string {
  const c = msg.content as unknown;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c
      .map((block) => {
        if (typeof block === "string") return block;
        if (block && typeof block === "object") {
          const obj = block as { text?: unknown; type?: unknown };
          if (typeof obj.text === "string") return obj.text;
        }
        return "";
      })
      .join("");
  }
  return "";
}

/**
 * backend 보고서 grounding LLM(`_ground_citations`)의 *내부 검증 산출물*인지 판별.
 * 형식: `[{"n":1,"quote":"..."}, ...]` (또는 partial로 잘린 `[{"n":1,"quote":`).
 *
 * 이 JSON은 답변·UI에 노출돼선 안 되는 backend 내부 처리물인데, LLM 호출이
 * `streamSubgraphs`+`messages-tuple`로 스트림에 새어나와 답변창에 박스로 뜨는
 * 회귀가 있음(사용자 보고). `report_turn_ids` 매칭에 의존하지 않고 *내용 패턴*으로
 * 차단 — 어느 turn이든, 스트리밍 partial이든 values message든 답변에서 제외.
 * 근본 해결은 backend가 grounding LLM을 스트림에서 제외(RFC).
 */
export function isGroundingArtifact(text: string): boolean {
  const t = text.trimStart();
  // 1. Direct JSON prefix check
  if (/^\[?\s*\{\s*"n"\s*:\s*\d+\s*,\s*"quote"\s*:/.test(t)) {
    return true;
  }
  // 2. Fenced code block wrapping grounding JSON check (e.g. ```json \n [ \n { "n": 1 ... })
  if (/^```(?:json)?\s*\[?\s*\{\s*"n"\s*:\s*\d+/.test(t)) {
    return true;
  }
  // 3. General fallback: if the content contains a high density of grounding-specific JSON keys
  // and starts with markdown code fencing, or is primarily grounding JSON.
  if (t.includes('"n":') && t.includes('"quote":') && (t.startsWith('`') || t.startsWith('['))) {
    return true;
  }
  return false;
}

/**
 * `answer.content` 안의 `[n]` 마커가 가리키는 step.citations + *모든 web citation* 을
 * References로 노출.
 *
 * **신뢰성 원칙**: 답변에 *실제 인용된 출처*만 references로 남김. 검색 과정에서 발견했지만
 * 답변에 안 쓴 출처는 *답변 근거가 아니므로* 노출 X — 무관 출처 섞이면 신뢰성 떨어짐.
 *
 * - doc citation: 본문 인용된 것만.
 * - web citation(`source_kind === "web"`): 본문 인용 여부 무관하게 *항상* 포함 —
 *   backend가 web 결과엔 `[N]` 마킹을 안 박는 케이스가 있어 이걸 안 하면 web 결과가
 *   통째로 빠짐.
 * - escape `\[n\]`은 마커로 보지 않음.
 * - **number 기준 dedupe**(id 기준 X) — 같은 number의 다른 id가 두 개 들어오면 *마지막*
 *   (= 시간순으로 더 최근 step) 만 살아남음. id로 dedupe하면 본문 [1]이 *오래된* citation에
 *   매칭되어 "새 레퍼런스가 추가됐는데 기존 거로 참조되는" 버그 발생.
 * - number 오름차순 정렬.
 */
export function deriveCitations(
  content: string,
  stepCitations: Citation[],
): Citation[] {
  // 1) 본문에 등장하는 number 모음 (숫자 마커 + 텍스트 ref 매칭 후 number 도출)
  const referencedNumbers = new Set<number>();
  for (const tok of parseCitationTokens(content, stepCitations)) {
    if (tok.kind === "citation") referencedNumbers.add(tok.number);
  }

  // 2) number 기준 dedupe + 정렬.
  //    포함 조건: 본문 인용됐거나 OR web citation.
  const byNumber = new Map<number, Citation>();
  for (const c of stepCitations) {
    if (referencedNumbers.has(c.number) || c.source_kind === "web") {
      byNumber.set(c.number, c);
    }
  }
  return Array.from(byNumber.values()).sort((a, b) => a.number - b.number);
}

/**
 * 전체 state로부터 Turn[] 재파생 (재연결 시).
 *
 * messages는 `add_messages` reducer가 적용된 결과 — id-merge·append 후의 시간순 배열로 가정.
 * messages가 비어있으면 `[]` 반환.
 */
/** 보고서 파이프라인 step(report_decompose·gather·writer) — 채팅 턴 소속 아님. */
const isReportStep = (s: Step) => !!s.tool_name?.startsWith("report_");

/**
 * turn에 속하는 step만 골라냄. backend canonical:
 *  - step.source_message_id === human.id 매칭 우선
 *  - 없으면 step.turn_idx === t 매칭
 *  - 둘 다 없는 step만 ts fallback (legacy)
 *
 * ★ report_* step 은 **항상 제외**(채팅↔보고서 완전 분리, 2026-07-25).
 * 백엔드가 보고서 step 을 채팅 턴에 바인딩하지 않도록 고쳤지만(source_message_id
 * 없음), 그러면 ③ ts fallback 이 "마지막 human 이후 = hi 가 Infinity" 라 오히려
 * 보고서 진행 step 을 마지막 채팅 턴으로 빨아들인다. 여기서 원천 배제해야
 * 채팅 턴 타임라인에 '자료 수집 중'·'보고서 작성 중' 이 끼지 않는다.
 * (보고서 진행 표시는 useChatState 의 report_progress + 우측 패널 담당.)
 */
function filterTurnSteps(
  sortedSteps: Step[],
  humanId: string,
  turnIdx: number,
  messages: Message[],
  humanIdxArr: number[],
): Step[] {
  const chatSteps = sortedSteps.filter((s) => !isReportStep(s));
  // 1) source_message_id 매칭 — 정확
  const byMsgId = chatSteps.filter((s) => s.source_message_id === humanId);
  if (byMsgId.length > 0) return byMsgId;
  // 2) turn_idx 매칭
  const byTurnIdx = chatSteps.filter((s) => s.turn_idx === turnIdx);
  if (byTurnIdx.length > 0) return byTurnIdx;
  // 3) ts fallback — backend 미구현 step만 해당. human 사이 ts 범위로
  const human = messages[humanIdxArr[turnIdx]!] as { ts?: number } | undefined;
  const nextHuman =
    turnIdx + 1 < humanIdxArr.length
      ? (messages[humanIdxArr[turnIdx + 1]!] as { ts?: number })
      : undefined;
  const lo = human?.ts ?? -Infinity;
  const hi = nextHuman?.ts ?? Infinity;
  return chatSteps.filter(
    (s) =>
      s.source_message_id === undefined &&
      s.turn_idx === undefined &&
      s.ts >= lo &&
      s.ts < hi,
  );
}

export function deriveTurns(
  messages: Message[],
  files: Record<string, FileEntry>,
  steps: Step[],
): Turn[] {
  if (!messages || messages.length === 0) return [];

  // 1) turn 경계 = human 메시지 + report_overview 메시지(파이프라인 재설계
  //    2026-07-24 — 보고서 완료 개요는 선행 human 없는 단독 AI 메시지로 오며,
  //    일반 턴의 answer 를 덮지 않도록 *전용 턴*으로 분리 렌더).
  type Boundary = { idx: number; overview?: Message };
  const boundaries: Boundary[] = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i]!;
    if (m.type === "human") boundaries.push({ idx: i });
    else if (m.type === "ai" && m.kind === "report_overview")
      boundaries.push({ idx: i, overview: m });
  }
  if (boundaries.length === 0) return [];
  // step turn_idx 매칭용 — human 서수는 종전과 동일해야 함(overview 미포함).
  const humanIdx = boundaries.filter((b) => !b.overview).map((b) => b.idx);

  // step ts 정렬 (안전하게)
  const sortedSteps = [...steps].sort((a, b) => a.ts - b.ts);
  // overview 턴의 [n] 인용 원천 — 보고서 합성 step(report_*)의 citations.
  const reportStepCites: Citation[] = sortedSteps
    .filter((s) => s.tool_name?.startsWith("report_"))
    .flatMap((s) => s.citations ?? []);

  const turns: Turn[] = [];
  let t = -1; // human 서수(overview 제외) — filterTurnSteps turn_idx 와 정합.
  for (let b = 0; b < boundaries.length; b++) {
    const cur = boundaries[b]!;
    if (cur.overview) {
      const om = cur.overview;
      const oContent = aiMessageText(om);
      const oTs =
        (om as { ts?: number }).ts ??
        turns[turns.length - 1]?.ended_at ??
        sortedSteps[sortedSteps.length - 1]?.ts ??
        0;
      turns.push({
        id: om.id,
        kind: "report_overview",
        user_message: { id: om.id, content: "" },
        status: "done",
        started_at: oTs,
        steps: [],
        answer: {
          id: om.id,
          content: oContent,
          citations: deriveCitations(oContent, reportStepCites),
          artifacts: [],
        },
      });
      continue;
    }
    t++;
    const startIdx = cur.idx;
    const endIdx =
      b + 1 < boundaries.length ? boundaries[b + 1]!.idx : messages.length;
    const human = messages[startIdx]! as Message & { type: "human" };
    const turnMsgs = messages.slice(startIdx, endIdx);

    // turn 분배 — backend가 step에 박은 source_message_id 또는 turn_idx로 정확 매칭.
    // 둘 다 없는 step은 ts fallback (legacy backend 호환).
    const turnSteps = filterTurnSteps(sortedSteps, human.id, t, messages, humanIdx);

    // 시작 시각 — turn 첫 step.ts 우선 → human.ts → fallback.
    const humanTs = (human as { ts?: number }).ts;
    const startedAt =
      turnSteps[0]?.ts ?? humanTs ?? sortedSteps[0]?.ts ?? Date.now();

    let ended_at_value: number | undefined;
    if (b + 1 < boundaries.length) {
      const next = messages[boundaries[b + 1]!.idx]!;
      const nextTs = (next as { ts?: number }).ts;
      if (typeof nextTs === "number") ended_at_value = nextTs;
    }

    // *최종 답변* 본문 — text 있고 + tool_calls 없는 ai 메시지만 lastAi.
    // grounding 검증 산출물(`[{"n":..,"quote":..}]`)은 답변 아님 — 제외.
    // report_overview 는 전용 턴이 담당 — 일반 턴 answer 로 흡수 금지.
    const aiTextMsgs = turnMsgs.filter(
      (m) =>
        m.type === "ai" &&
        m.kind !== "report_overview" &&
        aiMessageText(m).length > 0 &&
        !(m.tool_calls && m.tool_calls.length > 0) &&
        !isGroundingArtifact(aiMessageText(m)),
    );
    const lastAi = aiTextMsgs[aiTextMsgs.length - 1];
    const content = lastAi ? aiMessageText(lastAi) : "";
    // process_content — preamble (text + tool_calls 동반) 별도 추출.
    const processMsgs = turnMsgs.filter(
      (m) =>
        m.type === "ai" &&
        aiMessageText(m).length > 0 &&
        m.tool_calls &&
        m.tool_calls.length > 0,
    );
    const process_content = processMsgs
      .map((m) => aiMessageText(m))
      .filter((t) => t.length > 0)
      .join("\n\n---\n\n");

    // step.citations 모두 모음
    const stepCitations: Citation[] = turnSteps.flatMap((s) => s.citations ?? []);

    // turn 동안 변경된 file만 필터:
    //   1) R3 — file.generated_by_step_id가 이 turn의 step.id에 속함
    //   2) fallback — modified_at이 turn 시간 윈도우 안
    const turnStepIds = new Set(turnSteps.map((s) => s.id));
    const turnEnd = ended_at_value ?? Number.MAX_SAFE_INTEGER;
    const artifacts: Artifact[] = Object.entries(files)
      .filter(([, entry]) => {
        if (entry.generated_by_step_id) {
          return turnStepIds.has(entry.generated_by_step_id);
        }
        const t = entry.modified_at ?? entry.created_at;
        return t >= startedAt && t <= turnEnd;
      })
      .map(([path, entry]) => toArtifact(path, entry));

    // turn status 추론
    const hasError = turnSteps.some((s) => s.status === "error");
    const hasRunning = turnSteps.some((s) => s.status === "running");
    const status: Turn["status"] = hasError
      ? "error"
      : hasRunning
        ? "running"
        : b + 1 < boundaries.length || lastAi
          ? "done"
          : "running";

    turns.push({
      id: human.id,
      user_message: { id: human.id, content: aiMessageText(human) },
      status,
      started_at: startedAt,
      ended_at: ended_at_value,
      steps: turnSteps,
      answer: lastAi
        ? {
            id: lastAi.id,
            content,
            citations: deriveCitations(content, stepCitations),
            artifacts,
          }
        : undefined,
      process_content: process_content || undefined,
    });
  }
  return turns;
}

/* ─────────────────── reducers ─────────────────── */

/**
 * `state.steps` reducer = id 기준 patch merge (back §11 I2, P5.3, P5.11).
 * 같은 id로 두 번 와도 안전 — 두 번째가 첫 번째에 *patch 병합* (전체 교체 X).
 * 반환은 ts 시간순.
 */
export function mergeSteps(prev: Step[], incoming: Step[]): Step[] {
  if (!incoming || incoming.length === 0) return prev;
  const map = new Map<string, Step>();
  for (const s of prev) map.set(s.id, s);
  for (const s of incoming) {
    const existing = map.get(s.id);
    map.set(s.id, existing ? { ...existing, ...s } : s);
  }
  return Array.from(map.values()).sort((a, b) => a.ts - b.ts);
}

/**
 * `state.messages` reducer — LangChain `add_messages` 표준 (P5.5).
 * id 일치 시 병합(나중 게 우선), 없는 id는 끝에 append.
 * 백엔드가 `add_messages` reducer를 이미 적용한 결과를 보내므로 — 본 함수는
 * 단절·재연결 시 incremental 누적을 다시 박을 때만 사용.
 */
export function mergeMessages(prev: Message[], incoming: Message[]): Message[] {
  if (!incoming || incoming.length === 0) return prev;
  const map = new Map<string, number>();
  prev.forEach((m, i) => map.set(m.id, i));
  const out = [...prev];
  for (const m of incoming) {
    const idx = map.get(m.id);
    if (idx !== undefined) {
      out[idx] = { ...out[idx]!, ...m };
    } else {
      map.set(m.id, out.length);
      out.push(m);
    }
  }
  return out;
}

/**
 * `state.files` reducer — path 단위 dict union (P5.4).
 * `is_streaming: true`인 동안엔 `content` 라인 배열에 *append* (replace X).
 * 단순화: 백엔드가 보낸 entry로 path를 덮어쓴다 (LangGraph dict union).
 */
export function mergeFiles(
  prev: Record<string, FileEntry>,
  incoming: Record<string, FileEntry> | undefined,
): Record<string, FileEntry> {
  if (!incoming) return prev;
  return { ...prev, ...incoming };
}
