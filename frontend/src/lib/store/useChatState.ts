"use client";

/**
 * useChatState — P5.13 React state + Context.
 *
 * ADR-0001 Phase 4: 전송층을 langgraph SDK → 자체 SSE(`POST /chat`)·REST 로 교체.
 * send/stop/resume/retry 골격·에러 분기·reports 폴링은 유지, 호출부만 치환:
 *  - 리로드: `client.threads.getState` → `GET /chat/{tid}/state`
 *  - 정지:   `runs.cancel` → SSE fetch abort (서버가 턴 워커 취소)
 *  - resume: `Command(resume)` → **일반 메시지 send** (clarify 턴 종료형 신계약)
 *  - 보고서: `runs.stream("agent_report")` → `POST /reports` + 상태 폴링
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  applyDocumentUpdate,
  applyError,
  applyInterrupt,
  applyMessageChunk,
  applyMeta,
  applyToolProgress,
  applyValues,
  emptyChatState,
  composeWithAttachments,
  rebuildFromThreadState,
  runStream,
  settleAfterStream,
  StreamInactivityTimeoutError,
  type ChatAttachmentPayload,
  type DocumentUpdateEvent,
} from "@/lib/store/turns";
import {
  DOCUMENT_DELETED_EVENT,
  DOCUMENTS_CHANGED_EVENT,
  createDocumentFromForm,
  fetchDocumentState,
} from "@/lib/client/documents";
import { toast } from "sonner";
import type {
  ChatState,
  FileEntry,
  Message,
  Report,
  Step,
  ToolProgressEvent,
} from "@/lib/store/types";
import { apiFetch, type ApiError } from "@/lib/api/client";
import type { ChatStateResponse, ReportRunStatus } from "@/lib/client/chatApi";
import { isDummyMode } from "@/lib/store/settings";
import { listReports } from "@/lib/client/reports";
import { autoTitleThread } from "@/lib/client/threads";
import { parse429 } from "@/lib/client/quota";
import { ensureFresh as ensureReportsAvailability } from "@/lib/store/reportsAvailability";
import { randomUUID } from "@/lib/utils";

/* ─────────────────── 신경로 상태 조회 ─────────────────── */

/**
 * `GET /chat/{tid}/state` → rebuildFromThreadState 입력 shape.
 * (구 getState 의 values 대응. files 는 신경로에 없음 — 빈 dict.)
 */
async function fetchThreadValues(
  threadId: string,
  signal?: AbortSignal,
): Promise<{
  messages: Message[];
  files: Record<string, FileEntry>;
  steps: Step[];
  confidential_seen?: boolean;
  kind?: string;
  workflow?: { steps: string[]; cursor: number } | null;
}> {
  if (isDummyMode()) {
    return { messages: [], files: {}, steps: [] }; // 더미는 누적 state 없음(기존 동작)
  }
  const res = await apiFetch<ChatStateResponse>(
    `/chat/${encodeURIComponent(threadId)}/state`,
    { signal },
  );
  const messages: Message[] = res.messages.map((m, i) => ({
    id: m.id ?? `srv-${i}`,
    type: m.type,
    content: m.content,
    ...(m.tool_calls && m.tool_calls.length > 0
      ? { tool_calls: m.tool_calls.map((name) => ({ id: "", name, args: {} })) }
      : {}),
    // report_overview 등 특수 태그 — 전용 턴 렌더(재설계 2026-07-24).
    ...(m.kind ? { kind: m.kind } : {}),
    ...(m.report_id ? { report_id: m.report_id } : {}),
    // 조합 중간 단계(2026-10-02) — 빠뜨리면 새로고침 후 숨김이 풀려
    // 단계 답변이 전부 쏟아진다(실측).
    ...(m.hidden ? { hidden: true } : {}),
  }));
  return {
    messages, files: {}, steps: res.steps ?? [],
    confidential_seen: !!res.confidential_seen,
    kind: res.kind,
    // 진행 중인 기능 조합(2026-10-02) — 새로고침해도 단계가 살아야 한다.
    workflow: res.workflow ?? null,
  };
}

const REPORT_POLL_INTERVAL_MS = 5_000;
// 정책(2026-07-24): writer 는 초장기 허용, 챗 즉각성 우선 — DGX 점유를 챗에
// 양보하면 보고서가 수십 분~시간 단위로 늘 수 있다. 백엔드 stale 임계(3h)와
// 정렬해 3시간. 초과·새로고침해도 잡은 계속 돌고 runs/active 복원이 이어받는다.
const REPORT_POLL_TIMEOUT_MS = 180 * 60_000;

function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    const t = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * 한 thread의 ChatState 관리 훅.
 */
type UseChatStateOptions = {
  /** thread가 backend에 없음 (404) — 호스트가 URL `?threadId` 클리어하도록 callback */
  onInvalidThread?: () => void;
};

export function useChatState(
  threadId: string | null,
  options: UseChatStateOptions = {},
): {
  state: ChatState;
  /** 채팅 스트리밍 중 여부 — 입력 잠금은 *이것만* 본다(보고서와 분리). */
  isRunning: boolean;
  /** `done`(텍스트 확정) 수신됨 — grounding 위해 스트림은 아직 열려 있어도 턴은 settle. */
  streamComplete: boolean;
  /** 심층 보고서 폴링 중 여부 — 입력을 잠그지 않는다(보고서 중 병렬 대화 허용). */
  reportRunning: boolean;
  /** thread 전환 시 서버 상태 fetch 진행 중 — 로딩 화면 게이트(실제 fetch 수명). */
  threadLoading: boolean;
  send: (
    text: string,
    opts?: {
      reuseId?: string;
      attachments?: ChatAttachmentPayload[];
      skillHint?: string | null;
      /** 조합 중간 단계 — 채팅에 렌더하지 않는다 */
      hidden?: boolean;
      /** 단계별 기밀 — 주면 전역 토글 대신 이 값 */
      confidential?: boolean;
      /** 조합 첨부 — 서버가 본문을 꺼내 합친다(텍스트를 다시 올리지 않는다) */
      workflowFileIds?: string[];
    },
  ) => Promise<void>;
  /** 보고서 트리거(next_steps `kind:"report"` 클릭) — `POST /reports` + 폴링. */
  triggerReport: (
    prompt: string,
    opts?: {
      reuseId?: string;
      reuseKey?: string;
      purpose?: string | null;
      /** 사용자가 고른 별표·서식(article_key) — 그 서식으로 작성(2026-08-26) */
      formArticleKey?: string | null;
    },
  ) => Promise<void>;
  /**
   * [이 서식으로 작성] — 선택한 별표·서식으로 기입 문서를 즉시 연다
   * (2026-08-27). 보고서 파이프라인을 타지 않는다.
   */
  openFormDocument: (articleKey: string, title?: string) => Promise<string | null>;
  stop: () => void;
  resume: (value: unknown) => Promise<void>;
  retry: () => void;
  setError: (message: string | null) => void;
} {
  const onInvalidThreadRef = useRef(options.onInvalidThread);
  onInvalidThreadRef.current = options.onInvalidThread;

  const [state, setState] = useState<ChatState>(emptyChatState());
  const [isRunning, setIsRunning] = useState(false);
  // `done` 이벤트(=텍스트 확정) 수신 여부. isRunning 은 grounding(trailing verified
  // steps) 때문에 스트림 닫힐 때까지 true 지만, 이 플래그로 턴을 *즉시* settle 한다
  // — 인용/태그 노출·"생성중" 해제·입력 잠금 해제. (사용자 리포트 2026-07-15: 텍스트
  // 끝난 뒤 랙·인용 태그 지연.)
  const [streamComplete, setStreamComplete] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  // 보고서 폴링 — 채팅과 독립된 상태·abort. 보고서 도는 동안 채팅 입력을 잠그지
  // 않으려면(병렬 대화) isRunning 과 분리돼야 한다.
  const [reportRunning, setReportRunning] = useState(false);
  const reportAbortRef = useRef<AbortController | null>(null);
  // thread 전환 시 서버 상태 fetch 진행 여부 — 실제 fetch 수명과 동기화
  // (PageShell 이 로딩 화면 게이트로 사용; 고정 타이머 대체, 2026-07-24).
  const [threadLoading, setThreadLoading] = useState(false);
  // 보고서 완료 시 thread 재빌드가 *진행 중인 채팅 스트림*을 덮어쓰지 않게 참조로 확인.
  const isRunningRef = useRef(false);
  useEffect(() => {
    isRunningRef.current = isRunning;
  }, [isRunning]);
  // 이번 send 의 낙관 human id — meta 이벤트가 서버 id 로 치환할 대상.
  const pendingLocalIdRef = useRef<string | null>(null);
  const reportsPollRef = useRef<{ stop: () => void } | null>(null);
  const lastActionRef = useRef<
    | {
        kind: "send";
        text: string;
        localId: string;
        attachments?: ChatAttachmentPayload[];
        skillHint?: string | null;
        hidden?: boolean;
        confidential?: boolean;
        workflowFileIds?: string[];
      }
    | { kind: "report"; prompt: string; idempotencyKey: string }
    | null
  >(null);

  // thread 전환 시 idempotent 복원 (P5.10)
  useEffect(() => {
    let cancelled = false;
    setState(emptyChatState());
    reportsPollRef.current?.stop();
    reportsPollRef.current = null;
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    if (reportAbortRef.current) {
      reportAbortRef.current.abort();
      reportAbortRef.current = null;
    }
    setIsRunning(false);
    setReportRunning(false);
    setStreamComplete(false);
    lastActionRef.current = null;
    if (!threadId) {
      setThreadLoading(false);
      return;
    }
    // 실제 fetch 수명과 동기화된 로딩 — 종전 PageShell 의 고정 300ms 타이머는
    // fetch 완료 전에 꺼져 EmptyHero(새 대화 화면)가 깜빡 노출됐다(피드백 2026-07-24).
    setThreadLoading(true);

    void (async () => {
      try {
        const values = await fetchThreadValues(threadId);
        if (cancelled) return;
        // race 보호: lazy 생성 직후 send()가 로컬 user message를 먼저 박은 사이
        // 서버가 빈/미존재 state 로 응답해 로컬을 덮어쓰는 현상 방지.
        setState((prev) => {
          const next = rebuildFromThreadState(values);
          // 기밀 이력은 재구성 대상이 아니라 서버가 알려주는 값 — 따로 얹는다.
          next.confidential_seen = values.confidential_seen ?? prev.confidential_seen;
          next.kind = values.kind ?? prev.kind;
          next.workflow = values.workflow ?? null;
          if (prev.turns.length > 0 && next.turns.length === 0) return prev;
          // race 보호 2(2026-09-02): 새로고침 복원 effect 가 먼저 넣은 진행
          // 보고서 필드(report_started_at 등)를 이력 재구성이 덮으면, 우측
          // 패널 타이머가 Date.now() 폴백으로 0부터 다시 간다(실측 신고).
          // 이력에는 이 필드들이 없으므로 prev 값을 이어받는 게 항상 옳다.
          return {
            ...next,
            report_started_at: prev.report_started_at ?? next.report_started_at ?? null,
            report_idem_key: prev.report_idem_key ?? next.report_idem_key ?? null,
            report_queue_ahead: prev.report_queue_ahead ?? next.report_queue_ahead ?? null,
            report_progress: prev.report_progress ?? next.report_progress ?? null,
            report_purpose: prev.report_purpose ?? next.report_purpose ?? null,
          };
        });
      } catch (err) {
        if (cancelled) return;
        const status = (err as ApiError).status;
        if (status === 404) {
          // 신경로: thread 는 첫 메시지에 생성 — 새 thread 의 404 는 정상(빈 상태 유지).
          // 로컬에 turn 이 하나도 없고 URL 로 직접 들어온 stale id 인지 구분 불가하므로
          // 조용히 빈 상태 유지(첫 send 가 생성). 삭제된 thread 는 send 시 404 로 잡힘.
          return;
        }
        console.debug("[useChatState] state fetch skipped", err);
      } finally {
        if (!cancelled) setThreadLoading(false);
      }
    })();

    // 서류 초안 상태 복원 — 초안 없는 스레드는 {report_id: null} (저비용 1콜).
    void (async () => {
      try {
        const doc = await fetchDocumentState(threadId);
        if (cancelled || !doc.report_id) return;
        const rid = doc.report_id;
        setState((prev) => ({
          ...prev,
          document: {
            report_id: rid,
            fields: doc.fields ?? [],
            filled: doc.filled ?? {},
            remaining: doc.remaining ?? [],
            rev: 0,
          },
        }));
      } catch {
        // 미배포 백엔드·더미 모드 등 — 문서 패널만 비활성, 채팅은 무관.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [threadId]);

  const handlers = useMemo(
    () => ({
      onValues: (values: {
        messages?: Message[];
        files?: Record<string, FileEntry>;
        steps?: Step[];
      }) => {
        setState((prev) => applyValues(prev, values));
      },
      onMessageChunk: (data: unknown) => {
        setState((prev) => applyMessageChunk(prev, data));
      },
      onInterrupt: (value: Parameters<typeof applyInterrupt>[1]) => {
        setState((prev) => applyInterrupt(prev, value));
      },
      onError: (data: unknown) => {
        setState((prev) => applyError(prev, data));
      },
      onMeta: (humanMessageId: string, hidden?: boolean) => {
        const localId = pendingLocalIdRef.current;
        if (!localId) return;
        setState((prev) => applyMeta(prev, humanMessageId, localId, !!hidden));
      },
      onToolProgress: (event: ToolProgressEvent) => {
        setState((prev) => applyToolProgress(prev, event));
      },
      onStreamDone: () => setStreamComplete(true),
      onDocumentUpdate: (ev: DocumentUpdateEvent) => {
        setState((prev) => applyDocumentUpdate(prev, ev));
      },
    }),
    [],
  );

  const send = useCallback(
    async (
      text: string,
      opts?: {
        reuseId?: string;
        attachments?: ChatAttachmentPayload[];
        /** "irb_drb" — IRB/DRB 버튼 명시 진입(키워드 감지 실패 대비 이중 접근) */
        skillHint?: string | null;
        hidden?: boolean;
        confidential?: boolean;
        workflowFileIds?: string[];
      },
    ) => {
      if (!threadId) return;

      const localId = opts?.reuseId ?? `local-${Date.now()}`;
      lastActionRef.current = {
        kind: "send",
        text,
        localId,
        attachments: opts?.attachments,
        skillHint: opts?.skillHint ?? null,
        hidden: opts?.hidden,
        confidential: opts?.confidential,
        workflowFileIds: opts?.workflowFileIds,
      };
      pendingLocalIdRef.current = localId;
      const isFirstForTitle =
        state.turns.length === 0 || (!!opts?.reuseId && state.turns.length === 1);
      const ts = Date.now();
      // 낙관 표시는 서버 합성 형식과 동일하게 — reload 후 표시 일치(turns.ts 참조).
      const displayContent = composeWithAttachments(text, opts?.attachments);
      setState((prev) => ({
        ...applyValues(prev, {
          messages: [{ id: localId, type: "human", content: displayContent, ts }],
        }),
        live_progress: null,
        live_results: null,
      }));

      const reqId = `req-${Date.now().toString(36).slice(-6)}`;
      const t0 = Date.now();
      if (process.env.NODE_ENV !== "production") {
        console.log(`[send ${reqId}] start tid=${threadId.slice(0, 8)} text="${text.slice(0, 30)}..."`);
      }

      // 직전 스트림(예: grounding 위해 아직 열려 있는 것)이 있으면 정리 후 시작 —
      // done 후 입력이 열려 grounding 창에서 새 메시지를 보낼 수 있으므로.
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;
      setStreamComplete(false);
      setIsRunning(true);

      let fastSucceeded = false;
      try {
        await runStream(
          threadId,
          {
            message: text,
            localId,
            signal: ac.signal,
            attachments: opts?.attachments ?? null,
            skillHint: opts?.skillHint ?? null,
        hidden: opts?.hidden,
        confidential: opts?.confidential,
        workflowFileIds: opts?.workflowFileIds,
          },
          handlers,
        );
        fastSucceeded = true;
        if (abortRef.current === ac) lastActionRef.current = null;
        if (process.env.NODE_ENV !== "production") {
          console.log(`[send ${reqId}] runStream done in ${Date.now() - t0}ms`);
        }
      } catch (err) {
        if (abortRef.current !== ac) {
          // 스레드 전환/새 메시지로 이 스트림이 대체됨(구 스트림 abort) — 공유 상태
          // (isRunning·abortRef·turn)를 건드리면 새 대화가 깨지므로 조용히 종료.
          return;
        }
        if ((err as { name?: string }).name === "AbortError") {
          lastActionRef.current = null;
          if (process.env.NODE_ENV !== "production") {
            console.log(`[send ${reqId}] aborted by user after ${Date.now() - t0}ms`);
          }
        } else if (err instanceof StreamInactivityTimeoutError) {
          console.warn(`[send ${reqId}] inactivity timeout after ${Date.now() - t0}ms`);
          setState((prev) =>
            applyError(prev, { message: err.message, retriable: true }),
          );
        } else {
          console.error(`[send ${reqId}] runStream failed after ${Date.now() - t0}ms`, err);
          const status = (err as ApiError).status;
          if (status === 404 && onInvalidThreadRef.current) {
            setState((prev) =>
              applyError(prev, {
                message: "이 대화 thread를 찾을 수 없습니다. 새 대화를 시작해주세요.",
                retriable: false,
              }),
            );
            onInvalidThreadRef.current();
          } else if (status === 401) {
            setState((prev) =>
              applyError(prev, {
                message:
                  "로그인 세션이 만료되었거나 유효하지 않습니다. 페이지를 새로고침한 뒤 다시 로그인해주세요.",
                retriable: false,
              }),
            );
          } else if (status === 403) {
            // 클로즈 베타 화이트리스트 밖 — 백엔드가 한국어 안내를 detail 로 보냄.
            const detail = parseDetail((err as ApiError).body);
            setState((prev) =>
              applyError(prev, {
                message: detail ?? "클로즈 베타 대상이 아닙니다. 운영팀에 문의해주세요.",
                retriable: false,
              }),
            );
          } else {
            const limit = parse429(err);
            if (limit) {
              const isRate = limit.kind === "rate_limit";
              // 한도(quota) 메시지는 서버가 초기화 시점까지 담아 보낸다 — 덧붙이면 중복.
              const message = isRate
                ? `${limit.message} (${limit.retryAfterSec}초 후 다시 시도)`
                : limit.message;
              setState((prev) =>
                applyError(prev, { message, retriable: isRate }),
              );
            } else {
              const msg = err instanceof Error ? err.message : "메시지 전송 중 오류가 발생했습니다.";
              setState((prev) => applyError(prev, { message: msg, retriable: true }));
            }
          }
        }
      } finally {
        // 이 스트림이 *여전히 현재 스트림*일 때만 공유 상태 리셋. 스레드 전환/새 send
        // 로 대체된 구 스트림의 늦은 finally 가 새 대화의 isRunning·pendingId·turn 을
        // 덮어써 "생성중"에서 안 넘어가던 버그 방지.
        if (abortRef.current === ac) {
          setIsRunning(false);
          abortRef.current = null;
          pendingLocalIdRef.current = null;
          setState((prev) => settleAfterStream(prev));
        }
      }

      if (fastSucceeded && isFirstForTitle) {
        // autoTitle 은 특정 threadId 대상 fire-and-forget(공유 상태 X) — 전환돼도 무해.
        void autoTitleThread(threadId);
      }
    },
    [threadId, handlers, state.turns.length],
  );

  const stop = useCallback(() => {
    // 신경로: SSE 연결 abort = 서버 턴 워커 취소 — 별도 cancel API 없음.
    abortRef.current?.abort();
  }, []);

  /**
   * 보고서 트리거 — `POST /reports`(202 수락) + `GET /reports/runs/{idem}` 폴링.
   * 구경로의 "같은 thread SSE run + 입력창 차단"에서 **비차단 백그라운드 잡**으로
   * 변경 (계약: frontend_chat_v2 §4). isRunning 은 폴링 동안 유지 — 기존 reports
   * 5s 폴링 effect 가 진행 카드를 갱신한다.
   */
  /** 보고서 run 폴링 루프 — triggerReport(트리거 직후)와 새로고침 복원이 공유. */
  const pollReportRun = useCallback(
    async (idempotencyKey: string, ac: AbortController) => {
      if (!threadId) return;
      const deadline = Date.now() + REPORT_POLL_TIMEOUT_MS;
      for (;;) {
        await abortableSleep(REPORT_POLL_INTERVAL_MS, ac.signal);
        const run = await apiFetch<ReportRunStatus>(
          `/reports/runs/${encodeURIComponent(idempotencyKey)}`,
          { signal: ac.signal },
        );
        // 큐 위치 갱신 — running일 때만 queue_ahead가 옴. 종료 시 finally가 null.
        setState((prev) => ({
          ...prev,
          report_queue_ahead:
            run.status === "running" && typeof run.queue_ahead === "number"
              ? run.queue_ahead
              : null,
        }));
        // 세부 진행(분해→수집→작성) — 서버가 폴링 응답에 실어 준다(back
        // 2026-09-10). 종전엔 여기서 `fetchThreadValues(threadId)` 로 **스레드
        // 전체(메시지 포함)** 를 5초마다 받아 라벨 한 줄만 썼다 — 보고서가
        // 5~40분이라 수백 회 돌았고 단일 워커 서버에 그대로 부하였다.
        if (run.status === "running" && !run.queue_ahead) {
          const p = run.progress ?? null;
          const label = p
            ? `${p.label}${p.message ? ` · ${p.message}` : ""}` +
              (p.total > 1 ? ` (${p.phase}/${p.total})` : "")
            : null;
          setState((prev) => ({ ...prev, report_progress: label }));
        }
        if (run.status === "completed") return;
        if (run.status === "cancelled") {
          toast.info("보고서 작성을 중단했어요.");
          return;
        }
        if (run.status === "failed") {
          throw new Error(
            run.error
              ? `보고서 생성에 실패했습니다: ${run.error}`
              : "보고서 생성에 실패했습니다. 다시 시도해주세요.",
          );
        }
        if (Date.now() > deadline) {
          // 폴링 포기 ≠ 백엔드 중단. 잡은 계속 돌아 완료 시 스레드에 개요가 붙음.
          const e = new Error(
            "보고서 생성이 예상보다 오래 걸리고 있습니다. 백그라운드에서 계속 진행되며, 완료되면 대화에 자동 추가됩니다. 잠시 후 새로고침해 확인해주세요.",
          );
          (e as { retriable?: boolean }).retriable = true;
          throw e;
        }
      }
    },
    [threadId],
  );

  /** 보고서 완료 후 thread state 재조회 — '## 개요' 답변 반영(스트림 중이면 스킵). */
  const refreshAfterReport = useCallback(async () => {
    if (!threadId) return;
    try {
      if (!isRunningRef.current) {
        const values = await fetchThreadValues(threadId);
        setState((prev) => {
          const next = rebuildFromThreadState(values);
          // reports 목록·문서 상태는 유지 (rebuild 가 비우므로 이월)
          return { ...next, reports: prev.reports, document: prev.document };
        });
      }
      // 서류 초안(document_draft)이 방금 완료됐을 수 있음 — 상태 재조회.
      const doc = await fetchDocumentState(threadId);
      if (doc.report_id) {
        const rid = doc.report_id;
        setState((prev) => ({
          ...prev,
          document: {
            report_id: rid,
            fields: doc.fields ?? [],
            filled: doc.filled ?? {},
            remaining: doc.remaining ?? [],
            // rev 1 이상 = 패널 자동 오픈 신호(완료 직후 문서를 바로 보여준다).
            rev: (prev.document?.rev ?? 0) + (prev.document?.report_id === rid ? 0 : 1),
          },
        }));
      }
    } catch (err) {
      console.debug("[report] state refresh skipped", err);
    }
  }, [threadId]);

  /**
   * [이 서식으로 작성] — 선택한 별표·서식으로 기입 문서를 **즉시** 연다
   * (2026-08-27). 종전엔 심층 보고서 파이프라인을 태워서 "서식으로 작성을
   * 눌렀는데 왜 심층보고서 생성으로 가냐"는 지적을 받았다. 항목 추출은 LLM이
   * 필요 없는 일이라 서버가 몇 초 만에 돌려준다 — 여기서는 그 결과를
   * `document` 에 얹고 rev 를 올려 패널을 자동으로 연다.
   */
  const formCreatingRef = useRef(false);
  const openFormDocument = useCallback(
    async (articleKey: string, title?: string): Promise<string | null> => {
      if (!threadId) return null;
      // 연타 가드(2026-08-27 실사용: 중복 클릭으로 문서가 여러 개 생성됨).
      if (formCreatingRef.current) return null;
      formCreatingRef.current = true;
      const t = toast.loading("서식을 여는 중이에요…");
      try {
        const doc = await createDocumentFromForm({
          thread_id: threadId,
          article_key: articleKey,
          title,
        });
        if (!doc.report_id) throw new Error("no document");
        const rid = doc.report_id;
        setState((prev) => ({
          ...prev,
          document: {
            report_id: rid,
            fields: doc.fields ?? [],
            filled: doc.filled ?? {},
            remaining: doc.remaining ?? [],
            last_filled: [],
            // rev 증가 = 패널 자동 오픈 신호(기존 완료 경로와 같은 계약).
            rev: (prev.document?.rev ?? 0) + 1,
          },
        }));
        toast.success(`${doc.title ?? title ?? "서식"} — 기입 항목 ${doc.fields?.length ?? 0}개`, {
          id: t,
          description: "도우미와 대화하거나 항목을 눌러 채우세요.",
        });
        // 사이드바 "작성한 서식" 목록 갱신 신호(2026-09-18).
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent(DOCUMENTS_CHANGED_EVENT));
        }
        return rid;
      } catch (err) {
        console.debug("[document] from-form 실패", err);
        // 2026-10-01: "다른 서식을 선택해 보세요" 는 틀린 안내였다. 본문 조회가
        // 막혀 있으면(조문 본문 소스 미연결) **어떤 서식도** 열리지 않는다 —
        // 사용자를 헛된 재시도로 돌리지 말고, 지금 되는 길(원본 내려받기)을 준다.
        toast.error("지금은 서식을 열 수 없어요", {
          id: t,
          description:
            "서식 본문을 가져오지 못했습니다(조문 본문 연결 필요). " +
            "목록의 [원본]으로 관보 원본 파일을 내려받아 작성하실 수 있습니다.",
          duration: 9000,
        });
      } finally {
        formCreatingRef.current = false;
      }
      return null;
    },
    [threadId],
  );

  // 사이드바에서 서식을 삭제하면(2026-09-18) 입력창 위 "작성 중인 서류" pill 도
  // 그 서류를 가리키지 않게 — 안 그러면 지운 서류를 열려다 404 를 본다.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onDeleted = (ev: Event) => {
      const id = (ev as CustomEvent<{ id?: string }>).detail?.id;
      if (!id) return;
      setState((prev) =>
        prev.document?.report_id === id ? { ...prev, document: undefined } : prev,
      );
    };
    window.addEventListener(DOCUMENT_DELETED_EVENT, onDeleted);
    return () => window.removeEventListener(DOCUMENT_DELETED_EVENT, onDeleted);
  }, []);

  const triggerReport = useCallback(
    async (prompt: string, opts?: {
      reuseId?: string; reuseKey?: string; purpose?: string | null;
      formArticleKey?: string | null;
    }) => {
      if (!threadId) return;
      // 스레드당 동시 보고서 1개 — 진행 중엔 새 트리거를 만들지 않는다(백엔드도
      // report_in_progress 409 로 강제). 채팅은 보고서와 무관하게 계속 가능.
      if (reportAbortRef.current) {
        toast.info("이미 심층 보고서를 생성 중이에요 — 완료 후 다시 시도해주세요.", {
          description: "진행 상황은 우측 패널에서 볼 수 있어요. 채팅은 계속 가능합니다.",
        });
        return;
      }

      // 기능 일시 중단(운영자 토글) — 버튼은 비활성이지만 next_steps 칩 등 다른 진입점이
      // 남아 있어 POST 가 503 으로 튀고 배너·콘솔 에러가 났다(2026-09-09). 요청 전에 막고
      // 토스트로만 알린다. 값이 낡았으면 여기서 1회 조회한다 — 종전 모듈 스냅샷은
      // ChatInput 이 마운트돼야만 채워져 진입점에 따라 판정이 샜다(2026-09-10).
      const avail = await ensureReportsAvailability();
      if (avail.paused) {
        toast.warning(
          avail.message ?? "보고서 기능 점검 중입니다. 채팅·검색은 정상 이용 가능합니다.",
          { duration: 6000 },
        );
        return;
      }

      // 완료 브라우저 알림용 권한 — default일 때만 1회 요청 (거부/실패 무해).
      try {
        if (
          typeof Notification !== "undefined" &&
          Notification.permission === "default"
        ) {
          void Notification.requestPermission().catch(() => {});
        }
      } catch {
        // Notification 미지원 브라우저 — 무시
      }

      // 재설계(2026-07-24): 보고서는 채팅 턴 타임라인에 끼지 않는다 — 로컬 human
      // 메시지·report_turn_ids 생성 없음. 진행은 reportRunning + report_* 필드
      // (입력창 위 노티스·우측 패널), 완료는 서버가 append 하는
      // kind:"report_overview" 메시지의 전용 턴이 담당.
      let idempotencyKey = opts?.reuseKey ?? `rpt_${randomUUID()}`;
      lastActionRef.current = { kind: "report", prompt, idempotencyKey };
      const ac = new AbortController();
      reportAbortRef.current = ac;
      setReportRunning(true);
      setState((prev) => ({
        ...prev,
        report_started_at: Date.now(),
        report_idem_key: idempotencyKey,
        report_purpose: opts?.purpose ?? null,
      }));
      toast.info("심층 보고서 생성을 시작했어요 — 오래 걸립니다 (보통 5~20분, 길면 1시간)", {
        description: "기다릴 필요 없어요: 채팅 계속 가능, 완료되면 이메일로도 보내드립니다. 진행은 우측 패널에서.",
        duration: 6000,
      });
      try {
        if (isDummyMode()) {
          // 더미: 보고서 fixture 대신 일반 스트림 재생 (dev 확인용)
          await runStream(threadId, { message: prompt, signal: ac.signal }, handlers);
          lastActionRef.current = null;
          return;
        }

        type TriggerRes = { status: string; report_id?: string };
        const post = (key: string) =>
          apiFetch<TriggerRes>("/reports", {
            method: "POST",
            body: JSON.stringify({
              thread_id: threadId,
              idempotency_key: key,
              prompt,
              purpose: opts?.purpose ?? undefined,
              form_article_key: opts?.formArticleKey ?? undefined,
            }),
            signal: ac.signal,
          });

        let res: TriggerRes;
        try {
          res = await post(idempotencyKey);
        } catch (err) {
          const apiErr = err as ApiError;
          if (
            apiErr.status === 409 &&
            (apiErr.body ?? "").includes("report_in_progress")
          ) {
            // 이 대화에 이미 진행 중 보고서(다른 탭/복원 폴링 등) — 재시도 금지.
            throw new Error(
              "이 대화에서 이미 심층 보고서를 생성 중입니다. 완료 후 다시 시도해주세요.",
            );
          }
          if (apiErr.status === 503) {
            // 기능 단위 일시 중단(2026-09-07) — 서버 detail 이 사용자 문구. 재시도 무의미
            // 이므로 배너(재시도 버튼) 대신 토스트(2026-09-09). 폴링 전에 토글된 경우만 온다.
            let detail = "";
            try {
              detail = String((JSON.parse(apiErr.body ?? "{}") as { detail?: string }).detail ?? "");
            } catch {
              detail = "";
            }
            toast.warning(
              detail || "보고서 기능 점검 중입니다. 채팅·검색은 정상 이용 가능합니다.",
              { duration: 6000 },
            );
            lastActionRef.current = null;
            return;
          }
          if (apiErr.status === 409) {
            // 이전 시도가 failed 로 마감된 키 — 새 키로 1회 자동 재시도 (계약 §4).
            idempotencyKey = `rpt_${randomUUID()}`;
            lastActionRef.current = { kind: "report", prompt, idempotencyKey };
            res = await post(idempotencyKey);
          } else {
            throw err;
          }
        }

        if (res.status !== "completed") {
          // accepted | running → 완료까지 폴링 (5s 간격, 공유 루프).
          await pollReportRun(idempotencyKey, ac);
        }

        // 완료 — 보고서 목록·우측 패널 갱신.
        // ★ 채팅↔보고서 완전 분리(2026-07-25): 서버가 개요를 채팅 메시지로
        // append 하지 않는다. 종전엔 그 '완료 카드'가 유일한 완료 신호였으므로,
        // 대체 신호를 여기서 **채팅 밖으로** 낸다 — 토스트(보고서 열기 액션) +
        // 브라우저 알림(탭 이탈 대비, 위에서 권한 요청함). 이메일도 별도 발송.
        await refreshAfterReport();
        if (reportAbortRef.current === ac) {
          const latest = await listReports(threadId).catch(() => []);
          const done = latest
            .filter((r) => r.status === "done" && r.kind === "final")
            .sort((a, b) =>
              (b.created_at ?? "").localeCompare(a.created_at ?? ""));
          const fresh = done[0];
          toast.success("심층 보고서가 완성되었어요", {
            description: fresh?.title
              ? `${fresh.title} — 좌측 '심층 보고서' 목록에서 열어보세요.`
              : "좌측 '심층 보고서' 목록에서 열어보세요.",
            duration: 10000,
          });
          try {
            if (
              typeof Notification !== "undefined" &&
              Notification.permission === "granted" &&
              document.visibilityState !== "visible"
            ) {
              new Notification("심층 보고서 완성", {
                body: fresh?.title ?? "보고서가 준비되었습니다.",
                tag: `medi-report-${idempotencyKey}`,
              });
            }
          } catch {
            // Notification 미지원·차단 — 토스트만으로 충분
          }
          lastActionRef.current = null;
        }
      } catch (err) {
        if (reportAbortRef.current !== ac) {
          // 스레드 전환/새 트리거로 이 보고서 폴링이 대체됨 — 공유 상태 미변경.
          return;
        }
        if ((err as { name?: string }).name === "AbortError") {
          lastActionRef.current = null;
        } else if (err instanceof StreamInactivityTimeoutError) {
          setState((prev) =>
            applyError(prev, { message: err.message, retriable: true }),
          );
        } else if ((err as ApiError).status === 401) {
          setState((prev) =>
            applyError(prev, {
              message:
                "로그인 세션이 만료되었거나 유효하지 않습니다. 페이지를 새로고침한 뒤 다시 로그인해주세요.",
              retriable: false,
            }),
          );
        } else {
          const limit = parse429(err);
          if (limit) {
            const isRate = limit.kind === "rate_limit";
            const message = isRate
              ? `${limit.message} (${limit.retryAfterSec}초 후 다시 시도)`
              : limit.message;
            setState((prev) =>
              applyError(prev, { message, retriable: isRate }),
            );
          } else {
            const msg =
              err instanceof Error ? err.message : "보고서 트리거 실패";
            setState((prev) =>
              applyError(prev, { message: msg, retriable: true }),
            );
          }
        }
      } finally {
        // 현재 폴링일 때만 리셋 — 대체된 구 폴링의 늦은 finally 가 새 대화 상태를
        // 덮지 않게(채팅 send 와 동일 가드).
        if (reportAbortRef.current === ac) {
          setReportRunning(false);
          reportAbortRef.current = null;
          setState((prev) => ({
            ...settleAfterStream(prev),
            report_queue_ahead: null,
            report_progress: null,
            report_started_at: null,
            report_idem_key: null,
            report_purpose: null,
          }));
        }
      }
    },
    [threadId, handlers, pollReportRun, refreshAfterReport],
  );

  // 새로고침/재접속 복원 — 이 thread 에 진행 중 보고서가 있으면 진행 UI·폴링을
  // 재개한다. 멱등키가 메모리에만 있어 새로고침 시 진행 표시가 통째로 사라지던
  // 문제("진행보기 안 보임" 실측 피드백 2026-07-24)의 해결. 백엔드 짝:
  // GET /reports/runs/active?thread_id= (+재시작 시 orphan run 재기동).
  useEffect(() => {
    if (!threadId || isDummyMode()) return;
    let cancelled = false;
    void (async () => {
      try {
        const act = await apiFetch<{
          status: string;
          idempotency_key?: string;
          started_at?: string;
          queue_ahead?: number;
        }>(`/reports/runs/active?thread_id=${encodeURIComponent(threadId)}`);
        if (cancelled || act.status !== "running" || !act.idempotency_key) return;
        if (reportAbortRef.current) return; // 이 세션이 이미 폴링 중(트리거 직후)
        const ac = new AbortController();
        reportAbortRef.current = ac;
        setReportRunning(true);
        const startedMs = act.started_at ? Date.parse(act.started_at) : NaN;
        setState((prev) => ({
          ...prev,
          report_started_at: Number.isFinite(startedMs) ? startedMs : Date.now(),
          report_idem_key: act.idempotency_key ?? null,
        }));
        toast.info("진행 중인 심층 보고서가 있어요 — 이어서 표시합니다", {
          duration: 4000,
        });
        try {
          await pollReportRun(act.idempotency_key, ac);
          await refreshAfterReport();
        } catch (err) {
          if (
            reportAbortRef.current === ac &&
            (err as { name?: string }).name !== "AbortError"
          ) {
            const msg =
              err instanceof Error ? err.message : "보고서 상태 확인 실패";
            setState((prev) => applyError(prev, { message: msg, retriable: true }));
          }
        } finally {
          if (reportAbortRef.current === ac) {
            setReportRunning(false);
            reportAbortRef.current = null;
            setState((prev) => ({
              ...settleAfterStream(prev),
              report_queue_ahead: null,
              report_progress: null,
            }));
          }
        }
      } catch {
        /* active 조회 실패 — 조용히 스킵(다음 로드에서 재시도) */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId, pollReportRun, refreshAfterReport]);

  /**
   * clarify 응답 — 신계약은 interrupt/resume 이 아니라 **일반 메시지**.
   * InterruptCard payload(`{type:"clarify", choice?, free_text?}`)를 한 줄
   * 텍스트로 정리해 send. (백엔드 `_format_answer` 와 동일 규칙.)
   */
  const resume = useCallback(
    async (value: unknown) => {
      if (!threadId) return;
      const v = (value ?? {}) as { choice?: string; free_text?: string };
      const choice = (v.choice ?? "").trim();
      const free = (v.free_text ?? "").trim();
      const text =
        choice && free ? `${choice} (추가: ${free})` : choice || free;
      if (!text) return;
      await send(text);
    },
    [threadId, send],
  );

  const retry = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
    const last = lastActionRef.current;
    if (!last || abortRef.current) return;
    if (last.kind === "send") {
      void send(last.text, {
        reuseId: last.localId,
        attachments: last.attachments,
        skillHint: last.skillHint ?? null,
      });
    } else {
      void triggerReport(last.prompt, { reuseKey: last.idempotencyKey });
    }
  }, [send, triggerReport]);

  const setError = useCallback((message: string | null) => {
    setState((prev) => ({
      ...prev,
      error: message ? { message, retriable: true } : null,
    }));
  }, []);

  // reports 폴링 — 단일 관리 지점.
  // ⚠️ isRunning(채팅 스트림)만이 아니라 reportRunning(백그라운드 보고서 잡)에도
  // 걸어야 한다. 보고서 잡은 병렬 채팅 위해 reportRunning=true·isRunning=false 로
  // 도는데, isRunning 만 보면 잡이 도는 동안 목록 폴링이 멈춰 완료된 보고서가
  // state.reports 에 유입되지 않음 → 사이드바에 안 뜸(2026-07-23 버그).
  useEffect(() => {
    if (!threadId) return;
    reportsPollRef.current?.stop();
    if (isRunning || reportRunning) {
      let stopped = false;
      const tick = () => {
        if (stopped) return;
        void listReports(threadId)
          .then((r) => {
            if (!stopped) setState((p) => applyReportsUpdate(p, r));
          })
          .catch(() => {});
      };
      tick();
      const id = window.setInterval(tick, 5000);
      reportsPollRef.current = {
        stop: () => {
          stopped = true;
          window.clearInterval(id);
        },
      };
      return () => {
        stopped = true;
        window.clearInterval(id);
      };
    }
    reportsPollRef.current = startReportsRefresh(threadId, setState, 3, 4000);
    return () => reportsPollRef.current?.stop();
  }, [threadId, isRunning, reportRunning]);

  useEffect(() => {
    return () => {
      reportsPollRef.current?.stop();
      reportsPollRef.current = null;
    };
  }, []);

  return {
    state,
    isRunning,
    streamComplete,
    reportRunning,
    threadLoading,
    send,
    triggerReport,
    openFormDocument,
    stop,
    resume,
    retry,
    setError,
  };
}

/** ApiError.body(JSON) 의 detail 추출 — 실패 시 null. */
function parseDetail(body: string | undefined): string | null {
  if (!body) return null;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    return typeof parsed.detail === "string" ? parsed.detail : null;
  } catch {
    return null;
  }
}

/* ─────────────────── Reports refresh (단일 thread) ─────────────────── */

const toastedReportIds = new Set<string>();

function applyReportsUpdate(prev: ChatState, reports: Report[]): ChatState {
  const prevStatus = new Map((prev.reports ?? []).map((r) => [r.id, r.status]));
  // 재설계(2026-07-24): report_turn_ids 폐기 — 이 세션에서 트리거/복원된
  // 보고서 진행 여부는 report_started_at 존재로 판별.
  const triggeredThisSession = prev.report_started_at != null;
  for (const r of reports) {
    // "doc" = 서류 — 보고서 완료 문구로 알리지 않는다(책임 분리 2026-08-27,
    // "서식은 심층보고서와 다른데 왜 보고서로 묶이냐").
    if ((r.kind !== "final" && r.kind !== "doc") || r.status !== "done") continue;
    if (toastedReportIds.has(r.id)) continue;
    const wasRunning = prevStatus.get(r.id) === "running";
    const newlySeen = !prevStatus.has(r.id) && triggeredThisSession;
    if (wasRunning || newlySeen) {
      toastedReportIds.add(r.id);
      const isDoc = r.kind === "doc";
      toast.success(isDoc ? "서류 초안이 준비됐어요" : "심층 보고서가 완성됐어요", {
        description: isDoc
          ? "우측 문서 패널에서 항목을 채우고 원본 서식으로 내려받으세요."
          : "우측 패널 · 사이드바 '보고서'에서 확인하세요. 이메일로도 전송됩니다.",
        duration: 10000,
      });
      // 탭이 백그라운드면 브라우저 알림도 발송 — 사용자가 5~12분 대기 중 다른 탭에
      // 가 있어도 완료를 놓치지 않게. permission==="granted"일 때만 (요청은
      // triggerReport 시작 시 1회).
      try {
        if (
          typeof document !== "undefined" &&
          document.hidden &&
          typeof Notification !== "undefined" &&
          Notification.permission === "granted"
        ) {
          new Notification("심층 보고서가 완성됐어요", {
            body: "탭으로 돌아와 우측 패널에서 확인하세요. 이메일로도 전송됩니다.",
          });
        }
      } catch {
        // 알림 실패는 무해 — toast가 이미 표시됨
      }
    }
  }
  return { ...prev, reports };
}

function startReportsRefresh(
  threadId: string,
  setState: Dispatch<SetStateAction<ChatState>>,
  attempts = 3,
  gapMs = 4000,
): { stop: () => void } {
  let stopped = false;
  void (async () => {
    for (let i = 0; i < attempts && !stopped; i++) {
      try {
        const reports = await listReports(threadId);
        if (stopped) return;
        setState((prev) => applyReportsUpdate(prev, reports));
      } catch (err) {
        console.debug("[reports] refresh 실패 (best-effort)", err);
      }
      if (i < attempts - 1) {
        await new Promise((r) => setTimeout(r, gapMs));
      }
    }
  })();
  return {
    stop: () => {
      stopped = true;
    },
  };
}
