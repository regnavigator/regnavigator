/**
 * Stream 소비 + Turn store — P5.1~P5.13.
 *
 * `client.runs.stream(...)`이 발행하는 chunk를 4 채널(`values` / `messages-tuple` /
 * `interrupt` / `error`)로 분기해 ChatState를 incremental update.
 *
 * **단일 소스**: 진행 상태는 `state.steps`에서만. custom 이벤트 X (back §11 I1).
 *
 * 본 모듈은 React 의존성 X — 순수 reducer + run 함수. UI는 `useStreamRun` 훅(`./useStreamRun`)
 * 이 host에서 상태 결합.
 *
 * P5 DoD 매핑:
 *  - P5.1 stream chunk를 event 키로 분기
 *  - P5.2 values 핸들러 = state 3채널 분배
 *  - P5.3 state.steps id-merge reducer
 *  - P5.4 state.files dict union
 *  - P5.5 state.messages add_messages
 *  - P5.6 messages-tuple AI partial → answer.content live
 *  - P5.7 Turn incremental derive (전체 재계산 X)
 *  - P5.8 interrupt → active turn에 set + status=interrupted
 *  - P5.9 error → ChatState.error
 *  - P5.10 재연결 시 idempotent — getState 후 deriveTurns로 전체 재파생
 *  - P5.11 id 기반 dedupe (mergeSteps + mergeMessages, file은 path)
 */

import { toast } from "sonner";
import { getConfidential, getMode, styleForMode } from "@/lib/store/mode";
import { streamChatEvents, type ChatSseEvent } from "@/lib/client/chatApi";
import { isDummyMode } from "@/lib/store/settings";

// PII 카테고리 코드 → 한국어 라벨(토스트 표기용). 미매핑은 코드 그대로.
const PII_LABELS: Record<string, string> = {
  phone: "전화번호", rrn: "주민번호", email: "이메일", card: "카드번호",
  ip: "IP주소", passport: "여권번호", biznum: "사업자번호",
  vehicle: "차량번호", wallet: "지갑주소",
  이름: "이름", 주소: "주소", 생년월일: "생년월일", 나이: "나이",
};

// 마스킹 placeholder 전체(정렬용) — backend pii.py + gate.py 의 치환 토큰.
const PII_PLACEHOLDER_RE =
  /\[(이름|주소|생년월일|나이|이메일|지갑주소|주민등록번호|사업자번호|카드번호|전화번호|여권번호|IP주소|차량번호)\]/g;
// 오탐 신고 가능한 placeholder — NER 판정분(이름·주소류)만. 전화번호·주민번호
// 등 regex 확정분은 신고 대상이 아니다(서버도 422 로 거부).
const PII_REPORTABLE = new Set(["[이름]", "[주소]", "[생년월일]", "[나이]"]);

/**
 * 원문 ↔ 마스킹본 대조 — 어떤 단어가 placeholder 로 치환됐는지 추출.
 *
 * masked 를 placeholder 로 쪼개 사이 리터럴을 original 에서 순서대로 찾아가며
 * 치환 구간을 복원한다. 정렬 실패(연속 placeholder 등 모호 케이스)는 그 지점에서
 * 중단하고 부분 결과만 — 신고 UX 는 best-effort, 실패해도 일반 고지 토스트로 폴백.
 */
export function extractMaskedTerms(
  original: string,
  masked: string,
): { term: string; placeholder: string }[] {
  // masked 를 [placeholder | 리터럴] 토큰 열로 분해
  const tokens: { lit: string; ph: string | null }[] = [];
  const re = new RegExp(PII_PLACEHOLDER_RE.source, "g");
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(masked))) {
    tokens.push({ lit: masked.slice(last, m.index), ph: m[0] });
    last = m.index + m[0].length;
  }
  tokens.push({ lit: masked.slice(last), ph: null });

  const out: { term: string; placeholder: string }[] = [];
  let oi = 0; // original 커서
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (!t) continue;
    if (t.lit) {
      const idx = original.indexOf(t.lit, oi);
      if (idx < 0) return out; // 정렬 실패 — 부분 결과 반환
      oi = idx + t.lit.length;
    }
    if (!t.ph) continue;
    const next = tokens[i + 1];
    let end: number;
    if (next?.lit) {
      end = original.indexOf(next.lit, oi);
      if (end < 0) return out;
    } else if (next?.ph) {
      return out; // 연속 placeholder — 경계 모호, 중단(부분 결과)
    } else {
      end = original.length;
    }
    const term = original.slice(oi, end).trim();
    if (term.length >= 2 && term.length <= 30) {
      out.push({ term, placeholder: t.ph });
    }
    oi = end;
  }
  return out;
}
import {
  aiMessageText,
  deriveCitations,
  deriveTurns,
  isGroundingArtifact,
  mergeFiles,
  mergeMessages,
  mergeSteps,
  toArtifact,
} from "@/lib/parse/derive";
import type {
  Artifact,
  ChatState,
  FileEntry,
  InterruptValue,
  Message,
  Step,
  ToolProgressEvent,
  Turn,
} from "@/lib/store/types";

/* ─────────────────── ChatState helpers ─────────────────── */

export function emptyChatState(): ChatState {
  return { messages: [], files: {}, steps: [], turns: [], error: null };
}

/**
 * `values` 핸들러 — 백엔드가 보낸 raw state로 3 채널 분배 + Turn incremental derive.
 *
 * Turn 파생 incremental 규칙(05 §2.1):
 *  - 새 human 메시지가 생겼으면 새 Turn append
 *  - state.steps에 새 id가 생겼으면 마지막 turn에 push, 기존 id면 그 id를 patch merge
 *  - 마지막 ai message content 갱신 시 active turn answer.content 갱신
 *
 * 단순화: 본 함수는 *전체 재파생*을 호출하지 않고, *마지막 turn만* 갱신한다.
 * 첫 turn 생성 또는 turn 경계 변화 시점만 derive 호출.
 */
export function applyValues(
  prev: ChatState,
  values: {
    messages?: Message[];
    files?: Record<string, FileEntry>;
    steps?: Step[];
  },
): ChatState {
  // 1) 3 채널 reducer 적용
  const nextMessages = values.messages
    ? mergeMessages(prev.messages, values.messages)
    : prev.messages;
  const nextFiles = mergeFiles(prev.files, values.files);
  const nextSteps = values.steps ? mergeSteps(prev.steps, values.steps) : prev.steps;
  // 라이브 결과 카드는 여기서 클리어하지 **않는다** — steps 이벤트는 검색 완료
  // 직후(답변 토큰 전) 도착해서 여기서 지우면 노출이 밀리초로 끝난다(QA 실측).
  // 의도한 노출 구간 = "검색 결과 도착 ~ 답변 첫 토큰" → 클리어는
  // applyMessageChunk(첫 토큰)·settleAfterStream 이 담당.
  // 단, 최종 ai 메시지가 함께 오는 values(done 정합)는 답변 확정 → 클리어.
  const hasAiMessage = (values.messages ?? []).some((m) => m.type === "ai");
  const nextLiveResults = hasAiMessage ? null : prev.live_results;

  // 2) Turn[] incremental derive
  //    human 메시지 수가 늘었으면 turn 경계 변화 — 전체 재파생.
  //    그 외엔 마지막 turn에 step·answer만 patch.
  //    (단일 thread 전환으로 합성 deep-trigger 메시지 없음 — human=실 메시지.)
  const prevHumanCount = prev.messages.filter(
    (m) => m.type === "human",
  ).length;
  const nextHumanCount = nextMessages.filter(
    (m) => m.type === "human",
  ).length;

  let nextTurns: Turn[];
  if (nextHumanCount !== prevHumanCount || prev.turns.length === 0) {
    nextTurns = deriveTurns(nextMessages, nextFiles, nextSteps);
  } else {
    nextTurns = patchLastTurn(prev.turns, nextMessages, nextFiles, nextSteps);
  }

  return {
    ...prev,
    messages: nextMessages,
    files: nextFiles,
    steps: nextSteps,
    turns: nextTurns,
    live_results: nextLiveResults,
    error: prev.error,
  };
}

/**
 * 마지막 Turn에 step·answer·artifact를 incremental patch.
 * (turn 경계는 변하지 않은 경우만 사용 — 새 human message가 생기면 deriveTurns 전체 호출)
 */
function patchLastTurn(
  prevTurns: Turn[],
  messages: Message[],
  files: Record<string, FileEntry>,
  steps: Step[],
): Turn[] {
  if (prevTurns.length === 0) return prevTurns;
  const last = prevTurns[prevTurns.length - 1]!;
  const lastTurnIdx = prevTurns.length - 1;

  // 마지막 turn에 속하는 step — backend canonical:
  //   1) source_message_id === last.id (= human msg id)
  //   2) turn_idx === lastTurnIdx
  //   3) 둘 다 없으면 ts >= last.started_at (legacy fallback)
  const byMsgId = steps.filter((s) => s.source_message_id === last.id);
  const byTurnIdx = byMsgId.length > 0 ? byMsgId : steps.filter((s) => s.turn_idx === lastTurnIdx);
  const turnSteps =
    byTurnIdx.length > 0
      ? byTurnIdx
      : steps.filter(
          (s) =>
            s.source_message_id === undefined &&
            s.turn_idx === undefined &&
            s.ts >= last.started_at,
        );

  // ★ lastAi는 *마지막 turn 범위 내*에서만 찾아야 함.
  //   전체 messages에서 찾으면 이전 turn의 ai 답변이 새 turn answer로 박혀
  //   "기존 답변이 떴다가 ai 스트리밍 시작 시 사라지는" 현상 발생.
  let lastHumanIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]!;
    if (m.type === "human") {
      lastHumanIdx = i;
      break;
    }
  }
  const turnMsgs = lastHumanIdx >= 0 ? messages.slice(lastHumanIdx) : messages;
  // *최종 답변 본문*만 lastAi로 잡음 — text 있고 + tool_calls 없는 ai 메시지.
  //   - 빈 content (tool_calls only) → 제외 (suggest_next_steps 같은 wrapper)
  //   - text + tool_calls 함께 있는 preamble ("검색하겠습니다" + tool_use) → 제외
  // 이래야 streaming 중에도 답변 영역에 intermediate 텍스트 안 새어듦.
  // grounding 검증 산출물(`[{"n":..,"quote":..}]`)도 답변 아님 — 제외.
  const aiTextMsgs = turnMsgs.filter(
    (m) =>
      m.type === "ai" &&
      m.kind !== "report_overview" && // 개요는 전용 턴 — 일반 턴 answer 흡수 금지
      aiMessageText(m).length > 0 &&
      !(m.tool_calls && m.tool_calls.length > 0) &&
      !isGroundingArtifact(aiMessageText(m)),
  );
  const lastAi = aiTextMsgs[aiTextMsgs.length - 1];
  const content = lastAi ? aiMessageText(lastAi) : "";
  // process_content — preamble (text + tool_calls 동반) 텍스트들을 합침.
  // final answer와 분리되어 UI 토글에 별도 노출. lastAi 필터에 의해 aiTextMsgs에 포함 안 되므로
  // 별도로 turnMsgs에서 직접 추출.
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
  const stepCitations = turnSteps.flatMap((s) => s.citations ?? []);

  // turn 동안 변경된 file만 — R3 generated_by_step_id 우선, fallback은 modified_at 윈도우
  const turnStepIds = new Set(turnSteps.map((s) => s.id));
  const artifacts: Artifact[] = Object.entries(files)
    .filter(([, entry]) => {
      if (entry.generated_by_step_id) {
        return turnStepIds.has(entry.generated_by_step_id);
      }
      const t = entry.modified_at ?? entry.created_at;
      return t >= last.started_at;
    })
    .map(([path, entry]) => toArtifact(path, entry));

  // status 추론: error > running > done (interrupt는 별도 핸들러가 이미 set)
  let status: Turn["status"] = last.status;
  if (last.status !== "interrupted") {
    const hasError = turnSteps.some((s) => s.status === "error");
    const hasRunning = turnSteps.some((s) => s.status === "running");
    status = hasError ? "error" : hasRunning ? "running" : lastAi ? "done" : "running";
  }

  const updated: Turn = {
    ...last,
    status,
    steps: turnSteps,
    answer: lastAi
      ? {
          id: lastAi.id,
          content,
          citations: deriveCitations(content, stepCitations),
          artifacts,
        }
      : last.answer,
    truncated: lastAi?.truncated || undefined,
    process_content: process_content || last.process_content,
  };
  const out = prevTurns.slice(0, -1);
  out.push(updated);
  return out;
}

/**
 * `messages-tuple` 핸들러 — AI 메시지 토큰 partial로 라이브 갱신 (P5.6).
 *
 * SDK는 `[message, metadata]` 튜플을 `chunk.data`로 보냄. partial AIMessageChunk의
 * content를 active turn의 answer.content에 그대로 set (turn.answer.citations·artifacts는
 * 다음 values chunk에서 정합).
 *
 * **주의**: messages 채널 자체는 *건드리지 않음* — values chunk가 add_messages reducer로
 * 정합 보장.
 */
export function applyMessageChunk(
  prev: ChatState,
  data: unknown,
): ChatState {
  if (prev.turns.length === 0) return prev;
  // SDK 튜플: [{ type, content, ... }, { metadata }]
  type ChunkShape = {
    id?: string;
    type?: string;
    content?: unknown;
    tool_calls?: unknown[];
    tool_call_chunks?: unknown[];
  };
  let chunk: ChunkShape | null = null;
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === "object") {
    chunk = data[0] as ChunkShape;
  } else if (typeof data === "object" && data !== null) {
    chunk = data as ChunkShape;
  }
  if (!chunk) return prev;

  // preamble chunk("검색하겠습니다" + tool_use) — patchLastTurn 필터와 동일하게 답변
  // 영역에 박지 않음. values 단계에서 process_content로 분리됨.
  // 이 필터 없으면 streaming 중 preamble 텍스트가 답변에 노출됐다가 완료 시 사라지는
  // 깜빡임 발생.
  const hasToolCalls =
    (Array.isArray(chunk.tool_calls) && chunk.tool_calls.length > 0) ||
    (Array.isArray(chunk.tool_call_chunks) && chunk.tool_call_chunks.length > 0);
  if (hasToolCalls) return prev;

  // 라이브 답변 = AI 메시지만. tool(RAG 전문)/human/system은 제외 — 없으면 RAG
  // ToolMessage 전문이 답변 영역에 깜빡였다 사라짐. 단 messages-tuple 스트리밍
  // partial의 type은 "ai"가 아니라 "AIMessageChunk" — allowlist(=="ai")로 막으면
  // 토큰 스트리밍이 통째로 사라지고 마지막에 한 번에 튀어나옴(회귀). 따라서
  // *비-AI 타입만 골라 제외*(denylist) — ai/AIMessageChunk/미지정은 통과.
  const chunkType = (chunk.type ?? "").toLowerCase();
  if (
    chunkType === "tool" ||
    chunkType === "toolmessagechunk" ||
    chunkType === "human" ||
    chunkType === "system" ||
    chunkType === "function"
  ) {
    return prev;
  }

  // Note: We now allow report streams to accumulate in `turn.answer.content` during streaming.
  // This is safe because `Turn.tsx` will only render the progressive headings in `ReportInProgressCard`
  // and will not render the full `TurnAnswer` for report turns.


  // Anthropic·OpenAI 양식 모두 string | array 가능
  const text = aiMessageText({
    id: chunk.id ?? "_partial",
    type: "ai",
    content: (chunk.content ?? "") as string | unknown[],
  });
  if (!text) return prev;

  // 보고서 grounding LLM(`_ground_citations`)의 검증 산출물 `[{"n":..,"quote":..}]`
  //   이 messages-tuple로 새어나와 답변창에 박스로 뜨는 회귀 차단(사용자 보고).
  //   report_turn_ids 매칭에 의존하지 않고 내용 패턴으로 — 누적분(answer)에 이미
  //   grounding 시작 조각이 있거나 이번 chunk가 grounding이면 통째로 무시.
  const lastAnswer = prev.turns[prev.turns.length - 1]!.answer?.content ?? "";
  if (isGroundingArtifact(text) || isGroundingArtifact(lastAnswer + text)) {
    // 이미 grounding 조각이 answer에 박혀 있으면 비워서 박스 제거.
    if (isGroundingArtifact(lastAnswer)) {
      const lastT = prev.turns[prev.turns.length - 1]!;
      const cleared: Turn = { ...lastT, answer: undefined };
      return { ...prev, turns: [...prev.turns.slice(0, -1), cleared] };
    }
    return prev;
  }

  const last = prev.turns[prev.turns.length - 1]!;
  const stepCitations = last.steps.flatMap((s) => s.citations ?? []);

  // partial이 *다른 message의 token*일 수 있음 (preamble → 답변 전환 직전 잔여 partial).
  // chunk.id ≠ last.answer.id 이면 이전 누적을 버리고 새로 시작.
  const chunkId = chunk.id ?? "";
  const prevId = last.answer?.id ?? "";
  const isNewMessage = chunkId !== "" && prevId !== "" && chunkId !== prevId;
  const baseContent = isNewMessage ? "" : (last.answer?.content ?? "");
  const newContent = baseContent + text;

  const updated: Turn = {
    ...last,
    answer: {
      // partial 동안 id 모르면 ""로 두고 다음 values chunk가 박아줌
      id: chunkId || last.answer?.id || "",
      content: newContent,
      citations: deriveCitations(newContent, stepCitations),
      artifacts: last.answer?.artifacts ?? [],
    },
  };
  return {
    ...prev,
    // 답변 본문이 시작되면 대기 인디케이터(live_progress)·라이브 검색 결과
    // 카드(live_results)를 클리어 — 답변 영역과 겹치지 않게.
    live_progress: null,
    live_results: null,
    turns: [...prev.turns.slice(0, -1), updated],
  };
}

/**
 * `meta` 핸들러 (자체 SSE) — 로컬 낙관 human id를 서버 발급 id로 치환.
 *
 * 서버 steps 의 `source_message_id` 는 서버 human id 를 가리키므로, 치환해야
 * patchLastTurn 의 step↔turn 매칭이 id 로 정확히 붙는다(리로드 시에도 서버 id
 * 기준이라 정합). localId 메시지가 없으면 no-op.
 */
export function applyMeta(
  prev: ChatState,
  serverHumanId: string,
  localId: string,
  hidden = false,
): ChatState {
  if (!serverHumanId || serverHumanId === localId) {
    // id 는 그대로여도 hidden 은 반영해야 한다 — 안 하면 조합 단계가 화면에
    // 쏟아졌다가 새로고침 후에야 사라진다.
    if (!hidden) return prev;
    return {
      ...prev,
      messages: prev.messages.map((m) =>
        m.id === localId ? { ...m, hidden: true } : m,
      ),
      turns: prev.turns.map((t) => (t.id === localId ? { ...t, hidden: true } : t)),
    };
  }
  const idx = prev.messages.findIndex((m) => m.id === localId);
  if (idx < 0) return prev;
  const messages = prev.messages.slice();
  messages[idx] = {
    ...messages[idx]!,
    id: serverHumanId,
    ...(hidden ? { hidden: true } : {}),
  };
  const turns = prev.turns.map((t) =>
    t.id === localId
      ? {
          ...t,
          id: serverHumanId,
          user_message: { ...t.user_message, id: serverHumanId },
          ...(hidden ? { hidden: true } : {}),
        }
      : t,
  );
  return { ...prev, messages, turns };
}

/**
 * `interrupt` 핸들러 — active turn에 interrupt set (P5.8).
 */
export function applyInterrupt(prev: ChatState, value: InterruptValue): ChatState {
  if (prev.turns.length === 0) return prev;
  const last = prev.turns[prev.turns.length - 1]!;
  const updated: Turn = { ...last, interrupt: value, status: "interrupted" };
  return { ...prev, turns: [...prev.turns.slice(0, -1), updated] };
}

/**
 * `custom` 채널의 tool_progress 이벤트 핸들러 (back v4).
 *
 * - 마지막 turn에서 같은 tool_name을 가진 running step을 찾아 progress_message 갱신.
 * - 없으면 무시 (state.steps 자체를 만들지 않음 — values 채널이 step lifecycle 담당).
 * - phase는 message에 이미 반영되어 별도 저장 안 함 (단일 라이브 라인이면 충분).
 */
export function applyToolProgress(
  prev: ChatState,
  event: {
    tool: string;
    message: string;
    phase?: string;
    index?: number;
    title?: string;
    subtitle?: string;
    url?: string;
  },
): ChatState {
  if (prev.turns.length === 0) return prev;

  // phase="result" — 검색 결과 1건 라이브 카드로 누적 (backend `_emit_result`).
  // (tool, index)로 dedupe. 새 turn 시작·steps 이벤트 도착 시 클리어.
  if (
    event.phase === "result" &&
    typeof event.index === "number" &&
    typeof event.title === "string" &&
    event.title.length > 0
  ) {
    const entry = {
      tool: event.tool,
      index: event.index,
      title: event.title,
      ...(event.subtitle ? { subtitle: event.subtitle } : {}),
      ...(event.url ? { url: event.url } : {}),
    };
    const current = prev.live_results ?? [];
    const pos = current.findIndex(
      (r) => r.tool === entry.tool && r.index === entry.index,
    );
    const nextResults =
      pos >= 0
        ? current.map((r, i) => (i === pos ? entry : r))
        : [...current, entry];
    return { ...prev, live_results: nextResults };
  }

  const lastTurnIdx = prev.turns.length - 1;
  const last = prev.turns[lastTurnIdx]!;
  // running step 중 같은 tool_name 매칭 — 가장 최근 것
  const targetIdx = (() => {
    for (let i = last.steps.length - 1; i >= 0; i--) {
      const s = last.steps[i]!;
      if (s.status === "running" && s.tool_name === event.tool) return i;
    }
    return -1;
  })();
  // 매칭 running step이 없으면(=backend가 검색 시작 시 running step을 안 박는 동안:
  //   첫 chunk 대기 구간) progress 메시지를 *버리지 말고* live_progress에 보관 →
  //   대기 인디케이터에 라이브 노출(정적 대기 체감 완화). step이 생기면 아래
  //   분기가 그 step의 progress_message로 갱신.
  if (targetIdx < 0) {
    return prev.live_progress === event.message
      ? prev
      : { ...prev, live_progress: event.message };
  }

  const targetStep = last.steps[targetIdx]!;
  if (targetStep.progress_message === event.message) return prev; // no-op
  const updatedStep: Step = { ...targetStep, progress_message: event.message };
  const updatedSteps = last.steps.slice();
  updatedSteps[targetIdx] = updatedStep;
  // state.steps에서도 갱신 (turn 재파생 시 정합)
  const globalSteps = prev.steps.map((s) => (s.id === updatedStep.id ? updatedStep : s));
  const updatedTurn: Turn = { ...last, steps: updatedSteps };
  return {
    ...prev,
    steps: globalSteps,
    turns: [...prev.turns.slice(0, -1), updatedTurn],
  };
}

// ※ Deep 보고서 라이브 진행 reducers(applyDeepStep·applyDeepToolProgress)는
//   단일 thread 전환(2026-05-19)으로 폐기 — 어디에서도 호출되지 않는 dead code였다.
//   진행 표시는 report_turn_ids + ReportInProgressCard + reports 폴링으로 대체됨.

/**
 * 스트림 종료 후 잔여 "running" 표시 확정 — 정지(Stop)·에러·inactivity timeout으로
 * 스트림이 끊기면 터미널 values chunk가 오지 않아 마지막 turn.status가 "running"에
 * 고착된다 → typing dots("답변을 준비하고 있어요")·caret이 영구 반복(에러 배너와
 * 동시에 떠 "에러인데 로딩 중" 모순 UI). 스트림이 실제로 끝난 시점(finally)에
 * 호출해 마지막 turn을 done으로 확정하고 live_progress를 클리어한다.
 * (interrupted 상태는 applyInterrupt가 이미 확정 — 건드리지 않음.)
 */
export function settleAfterStream(prev: ChatState): ChatState {
  const last = prev.turns[prev.turns.length - 1];
  if (!last || last.status !== "running") {
    return prev.live_progress || prev.live_results
      ? { ...prev, live_progress: null, live_results: null }
      : prev;
  }
  const settled: Turn = { ...last, status: "done" };
  return {
    ...prev,
    live_progress: null,
    live_results: null,
    turns: [...prev.turns.slice(0, -1), settled],
  };
}

/**
 * `error` 핸들러 — ChatState.error에 set (P5.9).
 *
 * back에서 보낸 user-facing 메시지만 노출 (`details`/stack은 표시 X — skill data-contract §11).
 */
export function applyError(
  prev: ChatState,
  data: unknown,
): ChatState {
  let message = "스트림 오류가 발생했습니다.";
  let retriable = true;
  if (data && typeof data === "object") {
    const obj = data as { message?: unknown; retriable?: unknown };
    if (typeof obj.message === "string" && obj.message.length > 0) message = obj.message;
    if (typeof obj.retriable === "boolean") retriable = obj.retriable;
  }
  return { ...prev, error: { message, retriable } };
}

/* ─────────────────── 재연결 idempotent (P5.10) ─────────────────── */

/**
 * Thread state에서 ChatState 전체 재파생 (P5.10).
 *
 * `client.threads.getState(threadId).values`를 그대로 받아 deriveTurns 호출.
 * 중복 표시 X — id-merge reducer가 자체 dedupe.
 */
export function rebuildFromThreadState(
  values:
    | {
        messages?: Message[];
        files?: Record<string, FileEntry>;
        steps?: Step[];
      }
    | undefined,
): ChatState {
  if (!values) return emptyChatState();
  const messages = values.messages ?? [];
  const files = values.files ?? {};
  const sortedSteps = [...(values.steps ?? [])].sort((a, b) => a.ts - b.ts);
  // backend가 step에 source_message_id를 박아 turn 분배가 정확 → ts 추정 휴리스틱 불필요.
  return {
    messages,
    files,
    steps: sortedSteps,
    turns: deriveTurns(messages, files, sortedSteps),
    error: null,
  };
}

/* ─────────────────── 스트림 진입 함수 (P5.1) ─────────────────── */

export type StreamHandlers = {
  onValues: (values: {
    messages?: Message[];
    files?: Record<string, FileEntry>;
    steps?: Step[];
  }) => void;
  onMessageChunk: (data: unknown) => void;
  onInterrupt: (value: InterruptValue) => void;
  onError: (data: unknown) => void;
  /** 자체 SSE `meta` — 서버 발급 human message id (localId 치환용) */
  onMeta?: (humanMessageId: string, hidden?: boolean) => void;
  /** custom 채널의 tool_progress 이벤트 — running step에 라이브 메시지 갱신 (back v4) */
  onToolProgress?: (event: ToolProgressEvent) => void;
  /** `done` 이벤트 수신 — 텍스트 확정. 이후 grounding(trailing steps)이 와도 턴은
   *  이미 settle 됨(인용/태그 즉시 노출·"생성중" 해제). 스트림은 grounding 위해 잠깐 더 열려 있음. */
  onStreamDone?: () => void;
  /** done 뒤 trailing `document_update` — 서류 초안에 이번 발화로 채워진 항목. */
  onDocumentUpdate?: (ev: DocumentUpdateEvent) => void;
};

export type DocumentUpdateEvent = Extract<ChatSseEvent, { type: "document_update" }>;

/** SSE `document_update` → ChatState.document 병합 리듀서. */
export function applyDocumentUpdate(
  prev: ChatState,
  ev: DocumentUpdateEvent,
): ChatState {
  const cur =
    prev.document && prev.document.report_id === ev.report_id
      ? prev.document
      : null;
  const filled = { ...(cur?.filled ?? {}) };
  for (const f of ev.filled) filled[f.field] = f.value;
  // fields(전체 목록)는 복원 응답에만 있음 — 없으면 filled∪remaining 으로 구성.
  const fields = cur?.fields?.length
    ? cur.fields
    : [...Object.keys(filled), ...ev.remaining];
  return {
    ...prev,
    document: {
      report_id: ev.report_id,
      fields,
      filled,
      remaining: ev.remaining,
      last_filled: ev.filled.map((f) => f.field),
      last_corrected: ev.corrected ?? [],
      rev: (cur?.rev ?? 0) + 1,
    },
  };
}

/**
 * 스트림 chunk 무수신 임계 — 이 시간 동안 어떤 event도 도착하지 않으면 스스로 abort.
 * 백엔드 dead/네트워크 단절/proxy idle drop 등 케이스에서 자동 종료 + 사용자 알림.
 * LLM thinking은 보통 10~20s 내 첫 chunk가 도착함 → 60s면 충분히 여유 있고,
 * 사용자 입장에서 "에러 같은데 무한 대기"라고 느끼는 임계 한참 안 넘김.
 * 정지 버튼으로 사용자에게 책임 떠넘기지 말고, timeout 도달 즉시 자동 abort.
 */
const STREAM_INACTIVITY_TIMEOUT_MS = 60_000;

/**
 * Inactivity timeout으로 abort된 스트림임을 식별하기 위한 sentinel error.
 * useChatState의 catch가 AbortError(사용자 stop)와 구분해 retriable 메시지를 박는다.
 */
export class StreamInactivityTimeoutError extends Error {
  readonly retriable = true;
  constructor(timeoutMs: number) {
    super(
      `백엔드 응답이 ${Math.round(timeoutMs / 1000)}초간 오지 않아 연결을 끊었습니다. 다시 시도해주세요.`,
    );
    this.name = "StreamInactivityTimeoutError";
  }
}

/**
 * 자체 SSE `POST /chat` 스트림 소비 — ADR-0001 Phase 4 (구 `client.runs.stream` 대체).
 *
 * 이벤트 → 기존 리듀서 매핑 (계약: medi-back `docs/contracts/frontend_chat_v2.md` §2):
 *  - meta            → onMeta (로컬 human id → 서버 id 치환)
 *  - token           → onMessageChunk({id: message_id, type:"ai", content: text})
 *                      (message_id 로 모델 호출 경계 식별 — preamble 누적 리셋)
 *  - tool_progress   → onToolProgress (구 custom 채널과 동일 payload)
 *  - step_lifecycle  → 무시 — 구 경로에서도 steps 는 완료 시 values 로만 반영
 *                      (running 라이브는 tool_progress → live_progress 가 담당)
 *  - steps           → onValues({steps}) (id-merge, grounding verified 갱신 포함)
 *  - clarify         → onInterrupt (턴 종료형 — 답변은 다음 send 로, resume 아님)
 *  - error           → onError
 *  - done            → 최종 ai message + steps 를 onValues 로 정합
 *
 * **inactivity timeout**: 이벤트가 timeoutMs 동안 안 오면 자체 abort +
 * StreamInactivityTimeoutError throw. 사용자 stop(AbortError)과 구분.
 */
/** 답변 설명 수준 프리셋 — ChatInput 토글이 저장(localStorage). null=기본.
 *
 * **모드가 우선한다**(2026-10-01). 일반 상담 모드에서는 토글을 감추므로,
 * 전문가 모드에서 켜 둔 값이 남아 있어도 `simple` 로 고정한다. 토글을 숨겨
 * 놓고 이전 설정이 계속 먹으면 모드를 바꾼 의미가 없다.
 */
export function getAnswerStyle(): "expert" | "simple" | null {
  if (typeof window === "undefined") return null;
  const forced = styleForMode(getMode());
  if (forced) return forced;
  const v = window.localStorage.getItem("medi_answer_style");
  return v === "expert" || v === "simple" ? v : null;
}

export function setAnswerStyle(v: "expert" | "simple" | null): void {
  try {
    if (v) window.localStorage.setItem("medi_answer_style", v);
    else window.localStorage.removeItem("medi_answer_style");
  } catch { /* 무시 */ }
}

/** 첨부 문서 payload — POST /chat attachments (파일 업로드 v1). */
export type ChatAttachmentPayload = { name: string; text: string };

/** 낙관 human 메시지용 합성 — **백엔드 `_compose_message` 와 동일 형식**이어야
 *  reload 후 서버 저장본과 표시가 일치한다(UserMessage 가 이 태그를 접어 렌더). */
export function composeWithAttachments(
  text: string,
  attachments?: ChatAttachmentPayload[] | null,
): string {
  if (!attachments?.length) return text;
  return (
    text +
    attachments
      .map((a) => `\n\n<attachment name="${a.name}">\n${a.text.trim()}\n</attachment>`)
      .join("")
  );
}

/** 원내 모델 고지를 이미 띄운 스레드 — 턴마다 토스트가 쌓이지 않게. */
const _localNotified = new Set<string>();

export async function runStream(
  threadId: string,
  options: {
    /** 사용자 메시지 (clarify 답변 포함 — 신계약은 전부 일반 메시지) */
    message: string;
    /** 낙관 표시한 로컬 human message id — 더미 모드 fixture id 매핑용 */
    localId?: string;
    signal?: AbortSignal;
    /** 법률그래프 ④ 선택 조문 — null/미지정=미변경, []=해제 */
    selectedLawKeys?: string[] | null;
    /** 첨부 문서 — 서버가 message 와 합성 후 PII 게이트 통과 */
    attachments?: ChatAttachmentPayload[] | null;
    /** 스킬 명시 진입 — "irb_drb": IRB/DRB 버튼(이중 접근) */
    skillHint?: string | null;
    /** 조합 중간 단계 — 렌더 제외 */
    hidden?: boolean;
    /** 단계별 기밀(2026-10-02) — 주면 전역 토글 대신 이 값을 쓴다 */
    confidential?: boolean;
    /** 조합 첨부 id — 서버가 본문을 꺼내 합친다 */
    workflowFileIds?: string[];
    inactivityTimeoutMs?: number;
  },
  handlers: StreamHandlers,
): Promise<void> {
  // 내부 abort controller — 외부 signal(사용자 stop)과 inactivity timer 통합.
  const innerAc = new AbortController();
  const timeoutMs = options.inactivityTimeoutMs ?? STREAM_INACTIVITY_TIMEOUT_MS;
  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const resetTimer = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timedOut = true;
      innerAc.abort();
    }, timeoutMs);
  };
  const externalSignal = options.signal;
  const onExternalAbort = () => innerAc.abort();
  if (externalSignal) {
    if (externalSignal.aborted) innerAc.abort();
    else externalSignal.addEventListener("abort", onExternalAbort);
  }

  const onEvent = (ev: ChatSseEvent) => {
    resetTimer();
    if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
      console.debug("[stream]", ev.type, ev);
    }
    switch (ev.type) {
      case "meta":
        handlers.onMeta?.(ev.human_message_id, ev.hidden);
        break;
      case "pii_notice": {
        // 입력에서 개인정보 자동 제거됨 — 토스트 고지 + 오탐 신고(2026-08-13).
        // masked_text(서버 저장본)와 원문을 대조해 치환 단어를 짚고, NER 판정분
        // (이름·주소류)이면 [오류 신고] 버튼을 단다. 신고는 선보고 후조치 —
        // 즉시 마스킹 제외되고 관리자가 사후 라벨링한다.
        const original = composeWithAttachments(
          options.message,
          options.attachments,
        );
        const reportable = ev.masked_text
          ? extractMaskedTerms(original, ev.masked_text).filter((t) =>
              PII_REPORTABLE.has(t.placeholder),
            )
          : [];
        if (reportable.length) {
          const names = reportable.map((t) => `'${t.term}'`).join(", ");
          toast.warning(
            `${names}이(가) 개인정보로 감지되어 검색에서 제외됐어요.`,
            {
              duration: 12000,
              description: "용어·제품명인데 잘못 걸렸다면 신고해 주세요.",
              action: {
                label: "오류 신고",
                onClick: () => {
                  void (async () => {
                    try {
                      const { reportPiiTerm } = await import(
                        "@/lib/client/quota"
                      );
                      const results = await Promise.all(
                        reportable.map((t) =>
                          reportPiiTerm(ev.thread_id, {
                            term: t.term,
                            placeholder: t.placeholder,
                            messageId: ev.human_message_id,
                          }),
                        ),
                      );
                      if (results.some((r) => r.unmasked)) {
                        toast.success(
                          "신고했어요. 다음 질문부터 바로 반영됩니다.",
                        );
                      } else {
                        toast.info(
                          "신고를 접수했어요. 검토 결과 개인정보로 확인된 단어는 계속 보호돼요.",
                        );
                      }
                    } catch {
                      toast.error("신고 전송에 실패했어요. 잠시 후 다시 시도해 주세요.");
                    }
                  })();
                },
              },
            },
          );
          break;
        }
        const labels = (ev.categories ?? [])
          .map((c) => PII_LABELS[c] ?? c)
          .filter((v, i, a) => a.indexOf(v) === i);
        const detail = labels.length ? ` (${labels.join(", ")})` : "";
        toast.info(`입력에 포함된 개인정보를 자동으로 제거했어요${detail}. 특정 개인·주소는 조회할 수 없어요.`);
        break;
      }
      case "processing_mode": {
        // 서버가 확정한 처리 경로 고지(2026-10-01). 입력창 배너는 **클라이언트의
        // 설정값**을 보여 줄 뿐이라 "정말 그렇게 처리됐는가"는 알려주지 못한다.
        // 이 이벤트가 서버 쪽 확인이다. 턴마다 띄우면 소음이라 스레드당 한 번만.
        if (ev.local && !_localNotified.has(ev.thread_id)) {
          _localNotified.add(ev.thread_id);
          toast.info(
            ev.confidential
              ? "이 대화는 원내(온프레미스) 모델에서 처리됩니다 — 외부 전송·웹 검색 없음."
              : "이 질문은 원내(온프레미스) 모델에서 처리됩니다.",
            { duration: 8000 },
          );
        }
        break;
      }
      case "token":
        handlers.onMessageChunk({
          id: ev.message_id ?? "",
          type: "ai",
          content: ev.text,
        });
        break;
      case "tool_progress":
        handlers.onToolProgress?.(ev as ToolProgressEvent);
        break;
      case "steps":
        handlers.onValues({ steps: ev.steps });
        break;
      case "clarify":
        handlers.onInterrupt(ev as InterruptValue);
        break;
      case "document_update":
        handlers.onDocumentUpdate?.(ev);
        break;
      case "error":
        handlers.onError(ev);
        break;
      case "done": {
        const values: {
          messages?: Message[];
          steps?: Step[];
        } = { steps: ev.steps ?? [] };
        if (ev.text) {
          values.messages = [
            {
              id: ev.message_id ?? `ai-${Date.now()}`,
              type: "ai",
              content: ev.text,
              truncated: ev.truncated || undefined,
            },
          ];
        }
        handlers.onValues(values);
        handlers.onStreamDone?.();
        break;
      }
      default:
        break; // step_lifecycle 등 — 무시
    }
  };

  resetTimer();
  try {
    if (isDummyMode()) {
      const { runDummyStream } = await import("@/lib/client/dummy");
      await runDummyStream(
        threadId,
        {
          message: options.message,
          localId: options.localId,
          signal: innerAc.signal,
          onAlive: resetTimer,
        },
        handlers,
      );
    } else {
      await streamChatEvents(
        {
          thread_id: threadId,
          message: options.message,
          selected_law_keys: options.selectedLawKeys ?? null,
          style: getAnswerStyle(),
          attachments: options.attachments ?? null,
          skill_hint: options.skillHint ?? null,
          // 조합은 단계마다 기밀이 다를 수 있다 — 명시값이 있으면 그걸 쓰고,
          // 없으면 전역 토글(일반 채팅)을 쓴다.
          confidential: options.confidential ?? getConfidential(threadId),
          hidden: options.hidden ?? false,
          workflow_file_ids: options.workflowFileIds ?? null,
        },
        { signal: innerAc.signal },
        onEvent,
      );
    }
  } catch (err) {
    if (timedOut) throw new StreamInactivityTimeoutError(timeoutMs);
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
  }
}
