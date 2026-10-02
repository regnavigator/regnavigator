/**
 * 자체 SSE 채팅 전송층 — ADR-0001 Phase 4 (`@langchain/langgraph-sdk` 대체).
 *
 * 계약: medi-back `docs/contracts/frontend_chat_v2.md` (이벤트 8종 실측 payload 기준).
 * REST(조회·보고서)는 `apiFetch`(auth·mock 자동) 재사용, 스트림만 본 모듈이
 * fetch + ReadableStream 파싱으로 직접 처리한다.
 */

import { getAuthToken } from "@/lib/client/authToken";
import { getEffectiveSettings } from "@/lib/store/settings";
import type { ApiError } from "@/lib/api/client";
import type { Step } from "@/lib/store/types";

/* ─────────────────── 이벤트 타입 (frontend_chat_v2 §2) ─────────────────── */

export type ChatSseEvent =
  | {
      type: "meta";
      thread_id: string;
      human_message_id: string;
      /** 조합 중간 단계(2026-10-02) — 이 턴은 렌더하지 않는다 */
      hidden?: boolean;
    }
  | {
      // 입력이 PII 필터링됨 — 프론트 배지/토스트로 "개인정보 자동 제거" 고지.
      type: "pii_notice";
      thread_id: string;
      human_message_id: string;
      categories: string[];
      /** 서버 저장본(마스킹된 전문, 2026-08-13) — 원문(클라 메모리)과 대조해
       *  어떤 단어가 치환됐는지 짚고 [오류 신고] 버튼을 띄우는 재료. */
      masked_text?: string;
    }
  | {
      /**
       * 이 턴이 어떤 경로로 처리되는지 고지(2026-10-01). 원내(온프레미스) 모델로
       * 라우팅이 확정된 턴에만 온다 — 오지 않으면 상용 모델 + 웹 도구 경로다.
       */
      type: "processing_mode";
      thread_id: string;
      local: boolean;
      confidential: boolean;
      web_search: boolean;
    }
  | { type: "token"; text: string; message_id?: string | null }
  | {
      type: "tool_progress";
      tool: string;
      phase: string;
      message: string;
      index?: number;
      title?: string;
      subtitle?: string;
      url?: string;
    }
  | { type: "step_lifecycle"; phase: "start"; step: Step }
  | { type: "steps"; steps: Step[] }
  | {
      type: "clarify";
      step_id: string;
      question: string;
      options?: string[];
      allow_free_text: boolean;
    }
  | {
      // done 뒤 trailing — 서류 초안(document_draft) 채팅 기입 결과.
      // FE 문서 패널에 방금 채워진 항목을 라이브 반영(2026-08-24 Phase ③).
      type: "document_update";
      report_id: string;
      filled: { field: string; value: string }[];
      /** 그중 **이미 값이 있던** 항목(대화로 정정된 것) — 새로 채운 것과
       *  구분해 보여줘야 사용자가 자기 값이 바뀐 걸 알아챈다(2026-08-27). */
      corrected?: string[];
      remaining: string[];
    }
  | { type: "error"; message: string }
  | {
      type: "done";
      thread_id: string;
      message_id: string | null;
      text: string;
      steps: Step[];
      clarify_pending?: boolean;
      /** 자동 이어쓰기 상한까지 갔는데도 max_tokens 잘림 — FE [이어서 작성] 폴백 */
      truncated?: boolean;
    };

function baseUrl(): string | null {
  const url = getEffectiveSettings().deployment_url;
  if (!url) return null;
  return url.replace(/\/+$/, "");
}

function makeApiError(status: number, body: string): ApiError {
  // apiFetch와 동일 shape — parse429/status 분기 로직 재사용 가능.
  const err = new Error(`HTTP ${status}: ${body}`) as ApiError;
  err.status = status;
  err.body = body;
  return err;
}

/**
 * POST /chat SSE — 이벤트를 콜백으로 흘린다. 스트림 종료 시 resolve.
 *
 * - `signal` abort = 사용자 정지(서버가 턴 워커를 취소 — 별도 cancel API 없음).
 * - `inactivityTimeoutMs` 동안 이벤트 무수신이면 자체 abort 후
 *   `timedOut: true`를 콜백 밖 caller가 식별할 수 있게 throw는 caller 쪽
 *   (turns.runStream)에서 — 본 함수는 순수 전송.
 */
export async function streamChatEvents(
  body: {
    thread_id: string;
    message: string;
    selected_law_keys?: string[] | null;
    style?: string | null;
    /** 첨부 문서(파일 업로드 v1) — /files/extract 추출 텍스트 */
    attachments?: { name: string; text: string }[] | null;
    /** 스킬 명시 진입 — "irb_drb": IRB/DRB 버튼(키워드 감지 실패 대비 이중 접근) */
    skill_hint?: string | null;
    /** 기밀 모드 — 온프레미스 모델 전용 처리(웹 도구 미부여, 상용 폴백 없음) */
    confidential?: boolean;
    /** 조합 중간 단계(2026-10-02) — 이 턴은 채팅에 렌더되지 않는다 */
    hidden?: boolean;
    /** 조합 첨부 id — 서버가 본문을 꺼내 합친다 */
    workflow_file_ids?: string[] | null;
    /** 턴 기본 검색 종별 — 기능 힌트(2026-10-03) */
    doc_kinds?: string[] | null;
  },
  opts: { signal?: AbortSignal },
  onEvent: (ev: ChatSseEvent) => void,
): Promise<void> {
  const base = baseUrl();
  if (!base) throw new Error("backend URL 미설정");
  const token = getAuthToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${base}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: opts.signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw makeApiError(res.status, text);
  }

  // SSE 파싱 — `data: <json>` 라인만 소비(이벤트 타입은 payload.type에 이미 있음).
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).replace(/\r$/, "");
        buffer = buffer.slice(nl + 1);
        if (!line.startsWith("data: ")) continue;
        try {
          onEvent(JSON.parse(line.slice(6)) as ChatSseEvent);
        } catch {
          // 잘린/비정상 프레임 — 무시 (다음 프레임 계속)
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/* ─────────────────── 조회 REST (frontend_chat_v2 §3) ─────────────────── */

export type ChatThreadRow = {
  thread_id: string;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
  pinned?: boolean;
  /** 스레드 종류(2026-10-02) — `'chat'` | `'monitor'`. 사이드바 섹션 기준. */
  kind?: string;
  /** `/chat/search` 전용 — 검색어가 걸린 부분의 발췌(back 2026-08-16).
   *  비슷한 제목이 여러 개일 때 어느 대화인지 고르는 근거. */
  match_snippet?: string;
};

export type ChatStateResponse = {
  thread_id: string;
  title: string | null;
  messages: Array<{
    id: string | null;
    type: "human" | "ai" | "tool" | "system";
    content: string;
    tool_calls?: string[];
    /** "report_overview" 등 특수 메시지 태그(재설계 2026-07-24) */
    kind?: string;
    report_id?: string;
    /** 조합 중간 단계(2026-10-02) — 기본 렌더에서 제외("과정 보기"로만) */
    hidden?: boolean;
  }>;
  steps: Step[];
  selected_law_keys: string[];
  /** 이 스레드에 기밀 턴이 있었는가 — 기밀을 끌 때 경고 근거(2026-10-01) */
  confidential_seen?: boolean;
  /** 스레드 종류(2026-10-02) — 'monitor' 면 관찰 패널을 띄운다 */
  kind?: string;
  /** 진행 중인 기능 조합(2026-10-02). 없으면 null */
  workflow?: { steps: string[]; cursor: number } | null;
};

export type ReportRunStatus = {
  status: "running" | "completed" | "failed" | "cancelled";
  report_id: string | null;
  thread_id: string;
  error: string | null;
  /** running일 때만 — 앞에 N건 생성 대기 중 (보고서 큐) */
  queue_ahead?: number | null;
  /** 세부 진행(back 2026-09-10) — 분해→수집→작성 3단계 중 현재 위치.
   *  종전엔 FE 가 5초마다 스레드 전체를 받아 라벨을 뽑았다(메시지까지 딸려옴). */
  progress?: {
    phase: number;
    total: number;
    label: string;
    /** 새벽 데이터 갱신 대기 등 — 멈춰 보이는 이유 */
    message?: string | null;
  } | null;
};
