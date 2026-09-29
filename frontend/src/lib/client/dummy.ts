/**
 * Dummy LangGraph client — 00 §4 비목표("dev/QA 전용 dummy 모드 허용"), 05 §3.1.
 *
 * `NEXT_PUBLIC_DUMMY_MODE=true`일 때 진짜 SDK Client 대신 본 모듈의 fake 객체를
 * 반환. 사용자 흐름(질문 → StepCard 진행 → 답변·인용) UX 검증용.
 *
 * **압축 규칙**: 한 파일 안에 thread store + stream 시나리오 모두. helper 분산 X.
 *
 * **호환 인터페이스**: `useChatState` / `threads.ts`가 호출하는 메서드만 모방.
 *   - threads.search / create / update / delete / getState
 *   - runs.stream (AsyncIterable<{event,data}>) / cancel
 *
 * back v0.4 정합:
 *   - 모든 emit chunk가 snake_case
 *   - state.steps 단일 소스 (custom 이벤트 X)
 *   - `streamMode: ["values", "messages-tuple"]` event 이름 그대로
 *   - 시간 = ms epoch int
 *   - id 발행 = "백엔드(=더미)"가 — `step_*`, `cite_*`, file path
 *   - step.label은 사용자 향 한국어 한 줄 (내부 노드 이름 X)
 *
 * 본 파일은 *production 빌드에 끼지 않게* env로만 켜진다 (00 §4).
 */

// ADR-0001 Phase 4: SDK 타입 의존 제거 — 필요한 표면만 지역 타입으로.
// fixture(JSONL)는 구 계약 포맷 그대로 유지 — `runDummyStream` 어댑터가
// 구 이벤트(values/messages-tuple/...)를 기존 리듀서 핸들러에 직접 연결한다.
import type { StreamHandlers } from "@/lib/store/turns";

/* ─────────────────── 메모리 thread store ─────────────────── */

type DummyThreadMeta = {
  metadata: Record<string, unknown>;
  created_at: number;
  updated_at: number;
  has_interrupt: boolean;
};

const threads = new Map<string, DummyThreadMeta>();

function makeId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}_${Date.now().toString(36)}`;
}

function nowMs(): number {
  return Date.now();
}

/** `threads.search`가 반환하는 raw 객체 모양 — `threads.ts adaptThread`가 소비. */
function toRawThread(id: string, meta: DummyThreadMeta) {
  return {
    thread_id: id,
    created_at: new Date(meta.created_at).toISOString(),
    updated_at: new Date(meta.updated_at).toISOString(),
    state_updated_at: new Date(meta.updated_at).toISOString(),
    metadata: meta.metadata,
    status: meta.has_interrupt ? "interrupted" : "idle",
    values: {},
    interrupts: {},
  };
}

/* ─────────────────── delay helper ─────────────────── */

/** delay helper — abort 신호로 정지 가능 */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    const t = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

type StreamChunk = { event: string; data: unknown; run_id?: string };

/* ─────────────────── v9 fixture-based scenarios ─────────────────── */

/**
 * v9 fixture 시나리오 — `/public/mocks/fast_stream.jsonl` 또는 `deep_stream.jsonl`의
 * 라인을 차례로 yield. medi-back v9 출력과 정합:
 *   - tool_progress custom event (qdrant/tavily/read_report progress)
 *   - <next_steps> 인라인 마커 (답변 본문 끝)
 *   - read_report·request_deep_report 도구 step
 *
 * source of truth는 medi-back/mocks/*.jsonl. medi-front는 public/mocks/로 복사된 사본.
 * 백엔드 변경 시 두 곳 모두 갱신해야 함 (medi-back/mocks/README.md 참조).
 */
const FIXTURE_LINE_DELAY_MS = 150;  // 자연스러운 스트리밍 진행 (백엔드 실측치 근사)

/** /mocks/*.jsonl 캐시 — 첫 호출 시 fetch, 이후 동일 시나리오 재사용. */
const fixtureCache: Record<string, StreamChunk[]> = {};

async function loadFixture(name: "fast_stream" | "deep_stream"): Promise<StreamChunk[]> {
  if (fixtureCache[name]) return fixtureCache[name];
  const res = await fetch(`/mocks/${name}.jsonl`);
  if (!res.ok) {
    console.warn(`[dummy] fixture ${name}.jsonl load failed (status=${res.status})`);
    return [];
  }
  const text = await res.text();
  const lines = text.trim().split("\n").filter(Boolean);
  const chunks: StreamChunk[] = [];
  for (const line of lines) {
    try {
      chunks.push(JSON.parse(line) as StreamChunk);
    } catch {
      // 파싱 실패 라인은 skip (corrupted JSONL 방어)
    }
  }
  fixtureCache[name] = chunks;
  return chunks;
}

/**
 * fixture를 로드해 yield. 매 stream마다 fixture id에 unique 접미사를 박아 두 번째 이후
 * send가 동일 id로 중복되지 않도록 함. user message는 useChatState의 localId로 매핑(사용자
 * 입력 한 번만 노출). content도 실제 입력으로 patch.
 */
async function* scenarioFromFixture(
  fixtureName: "fast_stream" | "deep_stream",
  userMsgId: string,
  userContent: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamChunk> {
  const chunks = await loadFixture(fixtureName);
  if (chunks.length === 0) {
    yield {
      event: "values",
      data: {
        messages: [
          { id: userMsgId || makeId("msg_user"), type: "human", content: userContent },
          { id: makeId("msg_ai"), type: "ai", content: "(fixture 로드 실패 — /mocks/ 확인 필요)" },
        ],
      },
    };
    return;
  }

  // 매 stream session마다 unique 접미사 — fixture의 고정 id가 충돌하지 않게.
  const sessionSuffix = `_${Math.random().toString(36).slice(2, 8)}_${Date.now().toString(36)}`;
  const idMap = new Map<string, string>();

  function remapId(id: string): string {
    if (!id) return id;
    const cached = idMap.get(id);
    if (cached) return cached;
    // user message id는 frontend의 localId로 매핑 — 중복 노출 방지
    if (id === "msg_user_001" || /^msg_user_/.test(id)) {
      idMap.set(id, userMsgId || `${id}${sessionSuffix}`);
    } else {
      idMap.set(id, `${id}${sessionSuffix}`);
    }
    return idMap.get(id)!;
  }

  // 객체 깊이 순회하며 id-like 필드를 remap. 새 객체 반환 (원본 fixture 캐시는 그대로 보존).
  function rewriteIds(obj: unknown): unknown {
    if (Array.isArray(obj)) return obj.map(rewriteIds);
    if (obj && typeof obj === "object") {
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(obj)) {
        if (
          (k === "id" ||
            k === "source_message_id" ||
            k === "step_id" ||
            k === "tool_call_id" ||
            k === "generated_by_step_id") &&
          typeof v === "string"
        ) {
          out[k] = remapId(v);
        } else {
          out[k] = rewriteIds(v);
        }
      }
      return out;
    }
    return obj;
  }

  let firstUserPatched = false;
  for (const raw of chunks) {
    if (signal?.aborted) {
      throw new DOMException("aborted", "AbortError");
    }
    let chunk: StreamChunk = {
      ...raw,
      data: rewriteIds(raw.data),
    };
    // 첫 values 이벤트의 user message content를 실제 사용자 입력으로 patch
    if (!firstUserPatched && chunk.event === "values") {
      const data = chunk.data as {
        messages?: Array<{ type?: string; content?: string; id?: string }>;
      };
      if (Array.isArray(data?.messages) && data.messages.some((m) => m?.type === "human")) {
        chunk = {
          ...chunk,
          data: {
            ...data,
            messages: data.messages.map((m) =>
              m?.type === "human" ? { ...m, content: userContent } : m,
            ),
          },
        };
        firstUserPatched = true;
      }
    }
    yield chunk;
    await sleep(FIXTURE_LINE_DELAY_MS, signal);
  }

  // fast_stream 후처리 — 사용자 입력에 명시적 deep 키워드가 있을 때만 request_deep_report
  // step을 emit (자동 dispatch 트리거). 일반 채팅(예: "ㅎㅇ")엔 deep 안 발화.
  if (fixtureName === "fast_stream" && /보고서|심층|deep/i.test(userContent)) {
    yield {
      event: "values",
      data: rewriteIds({
        steps: [
          {
            id: "step_deep_req",
            ts: Date.now(),
            ended_at: Date.now() + 100,
            label: "심층 보고서 작성 요청",
            status: "done",
            tool_name: "request_deep_report",
            input_preview: userContent.slice(0, 60),
            output_preview: "deep dispatch 트리거",
            source_message_id: "msg_user_001", // remap → userMsgId
            turn_idx: 0,
          },
        ],
      }),
    };
  }
}

/* ─────────────────── stream helper — runs.stream return value ─────────────────── */

/** deep dispatch 트리거 메시지 id prefix — backend·frontend 약속 (R8). */
const DEEP_TRIGGER_ID_PREFIX = "synthetic-deep-trigger-";

/**
 * `client.runs.stream`은 AsyncIterable + Promise (run 메타) 양쪽이 필요한 SDK 타입이지만,
 * `useChatState`는 `for await (const chunk of stream)` 루프만 돌리므로
 * `Symbol.asyncIterator`만 구현해 그대로 흡수된다 (turns.ts §runStream §301).
 */
function buildStream(
  threadId: string,
  payload: {
    input?: {
      messages: Array<{ id?: string; type: "human"; content: string }>;
    };
    command?: { resume: unknown };
    signal?: AbortSignal;
  },
  assistantId: string,
): AsyncIterable<StreamChunk> {
  const userMsg = payload.input?.messages?.[payload.input.messages.length - 1];
  const userContent = userMsg?.content ?? "";
  const userMsgId = userMsg?.id ?? "";

  // deep 감지: (a) assistantId 매칭, (b) trigger msg id prefix 매칭
  const firstMsgId = payload.input?.messages?.[0]?.id ?? "";
  const isDeep =
    /agent[_-]?deep/i.test(assistantId) ||
    firstMsgId.startsWith(DEEP_TRIGGER_ID_PREFIX);

  return {
    [Symbol.asyncIterator]() {
      const gen = isDeep
        ? scenarioFromFixture("deep_stream", userMsgId, userContent, payload.signal)
        : scenarioFromFixture("fast_stream", userMsgId, userContent, payload.signal);
      void threadId;
      return {
        async next() {
          try {
            const r = await gen.next();
            return r.done
              ? { value: undefined as unknown as StreamChunk, done: true }
              : { value: r.value, done: false };
          } catch (err) {
            // abort는 useChatState catch가 흡수
            throw err;
          }
        },
        async return() {
          await gen.return(undefined);
          return { value: undefined as unknown as StreamChunk, done: true };
        },
      };
    },
  };
}

/* ─────────────────── public — 신 runStream용 어댑터 (Phase 4) ─────────────────── */

/**
 * 더미 스트림을 기존 리듀서 핸들러(StreamHandlers)에 직접 연결.
 * 구 fixture 이벤트(values/messages-tuple/interrupt/error/custom)를 그대로 소비 —
 * fixture 파일 무변경. `onAlive`는 inactivity 타이머 리셋용.
 */
export async function runDummyStream(
  threadId: string,
  opts: { message: string; localId?: string; signal?: AbortSignal; onAlive?: () => void },
  handlers: StreamHandlers,
): Promise<void> {
  // 메타 갱신 (사이드바 정렬·자동 제목) — 구 fake runs.stream 과 동일 side effect.
  const meta = threads.get(threadId);
  if (meta) {
    meta.updated_at = nowMs();
    const currentTitle =
      typeof meta.metadata.title === "string" ? meta.metadata.title : "";
    if (currentTitle === "" || currentTitle === "새 대화") {
      meta.metadata.title = opts.message.slice(0, 40);
    }
  }

  const stream = buildStream(
    threadId,
    {
      input: { messages: [{ id: opts.localId, type: "human", content: opts.message }] },
      signal: opts.signal,
    },
    "agent",
  );
  for await (const c of stream) {
    opts.onAlive?.();
    switch (c.event) {
      case "values":
        handlers.onValues((c.data ?? {}) as Parameters<StreamHandlers["onValues"]>[0]);
        break;
      case "messages-tuple":
      case "messages/partial":
      case "messages":
        handlers.onMessageChunk(c.data);
        break;
      case "interrupt": {
        const d = c.data as { value?: unknown } | undefined;
        const value = (d && "value" in d ? d.value : c.data) as Parameters<
          StreamHandlers["onInterrupt"]
        >[0];
        if (value && typeof value === "object") handlers.onInterrupt(value);
        break;
      }
      case "error":
        handlers.onError(c.data);
        break;
      case "custom": {
        const d = c.data as { type?: string } | null | undefined;
        if (d && d.type === "tool_progress" && handlers.onToolProgress) {
          handlers.onToolProgress(d as Parameters<NonNullable<StreamHandlers["onToolProgress"]>>[0]);
        }
        break;
      }
      default:
        break;
    }
  }
}

/* ─────────────────── public — fake backend (threads 표면) ─────────────────── */

/**
 * threads.ts 더미 분기가 쓰는 표면 — 구 fake Client 에서 SDK 타입만 벗겨냄.
 */
export function getDummyBackend() {
  return dummyBackend;
}

const dummyBackend = {
    threads: {
      async search(_opts: {
        limit?: number;
        offset?: number;
        sortBy?: string;
        sortOrder?: string;
        signal?: AbortSignal;
      }) {
        // 메모리 store에 들어있는 thread만 반환. 처음엔 빈 배열 — 사용자가 [+ 새 대화]로 채움.
        const list = Array.from(threads.entries())
          .map(([id, meta]) => toRawThread(id, meta))
          .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
        const offset = _opts.offset ?? 0;
        const limit = _opts.limit ?? 50;
        return list.slice(offset, offset + limit);
      },
      async create() {
        const id = makeId("thread");
        const t = nowMs();
        const meta: DummyThreadMeta = {
          metadata: { title: "새 대화" },
          created_at: t,
          updated_at: t,
          has_interrupt: false,
        };
        threads.set(id, meta);
        return toRawThread(id, meta);
      },
      async update(threadId: string, body: { metadata?: Record<string, unknown> }) {
        const meta = threads.get(threadId);
        if (!meta) throw new Error(`thread_not_found: ${threadId}`);
        if (body.metadata) {
          meta.metadata = { ...meta.metadata, ...body.metadata };
        }
        meta.updated_at = nowMs();
        return toRawThread(threadId, meta);
      },
      async delete(threadId: string) {
        threads.delete(threadId);
      },
      async getState(threadId: string) {
        // 더미는 thread별 누적 state를 들고 있지 않음 — 빈 state 반환.
        // useChatState는 실패 시 빈 상태로 fallback하므로 안전.
        void threadId;
        return {
          values: { messages: [], files: {}, steps: [] },
          next: [],
          checkpoint: null,
          metadata: null,
          created_at: null,
          parent_checkpoint: null,
          tasks: [],
        };
      },
      async patch(threadId: string, body: { metadata?: Record<string, unknown> }) {
        // 일부 SDK 버전 표기 호환 — update 동일 동작.
        return this.update(threadId, body);
      },
    },
};
