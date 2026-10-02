/**
 * Chat 도메인 타입 — Message·Step·FileEntry·Artifact·InterruptValue·Turn.
 */

import type { Citation } from "./citation";

export type Step = {
  /** 백엔드 발행 unique. `state.steps` reducer가 id 기준 merge */
  id: string;
  /** 시작 시각 — ms epoch */
  ts: number;
  /** 사용자 향 한국어 한 줄 — 백엔드가 가공 */
  label: string;
  status: "running" | "done" | "error";
  ended_at?: number;
  /** 펼침 본문 디테일에서만 노출. 헤더 라벨 X */
  tool_name?: string;
  input_preview?: string;
  output_preview?: string;
  citations?: Citation[];
  /** 사람 향 한국어 메시지 */
  error_message?: string;
  /** 이 step을 트리거한 human message id — turn 분배에 사용 (backend canonical) */
  source_message_id?: string;
  /** 0-based human 메시지 순서 — source_message_id 매칭 실패 시 fallback */
  turn_idx?: number;
  /** 라이브 진행 메시지 — `custom` stream의 tool_progress 이벤트로 갱신.
   *  step.status === "running" 동안 노출되고 done 되면 의미 없음. */
  progress_message?: string;
};

/* ─────────────────── back §2.3 FileEntry / §2.4 Artifact ─────────────────── */

export type FileEntry = {
  /** 줄 단위 (deepagents create_file_data 호환) */
  content: string[];
  /** ms epoch */
  created_at: number;
  /** ms epoch */
  modified_at: number;
  /** true면 부분 작성 중 */
  is_streaming?: boolean;
  /** R3 — 이 파일을 만든 step.id. ArtifactViewer가 직접 lookup (heuristic 대체) */
  generated_by_step_id?: string;
};

/** front-derived view (back §2.4) — 별도 페이로드 X */
export type Artifact = {
  /** files key */
  path: string;
  /** computed from content */
  bytes: number;
  modified_at: number;
  is_streaming: boolean;
  /** markdown 첫 # 또는 path basename */
  title?: string;
  /** "text/markdown" 등 — 확장자에서 추론 */
  mime_type?: string;
  /** 다운로드 링크 (선택) */
  export_url?: string;
};

/* ─────────────────── back §2.5 InterruptValue ─────────────────── */

export type InterruptValue =
  | {
      type: "clarify";
      step_id?: string;
      question: string;
      options?: string[];
      allow_free_text: boolean;
    }
  | {
      type: "approve_action";
      step_id?: string;
      description: string;
      action_name: string;
      args: Record<string, unknown>;
    };

/* ─────────────────── back §3 Message ─────────────────── */

/**
 * LangChain 정규화 — human / ai / tool / system.
 * `tool_calls`는 ai 메시지에만, 백엔드가 `additional_kwargs` / Anthropic block 정규화.
 */
export type Message = {
  id: string;
  type: "human" | "ai" | "tool" | "system";
  /** 평문 또는 Anthropic block 배열 — `aiMessageText`로 정규화 */
  content: string | unknown[];
  /** ms epoch — turn 경계 결정에 사용. send 시점에 frontend가 박고
   *  mergeMessages가 spread merge라 backend echo가 누락해도 보존. */
  ts?: number;
  /** ai 메시지 한정 */
  tool_calls?: Array<{
    id: string;
    name: string;
    args: Record<string, unknown>;
  }>;
  /** tool 메시지 한정 */
  tool_call_id?: string;
  /** tool 메시지 한정 */
  name?: string;
  /** 특수 메시지 태그 — "report_overview"=보고서 완료 개요(전용 카드 렌더,
   *  선행 human 없는 단독 AI 메시지). 파이프라인 재설계 2026-07-24. */
  kind?: string;
  /** kind==="report_overview" 시 원본 보고서 id */
  report_id?: string;
  /** ai 한정 — 자동 이어쓰기 상한 후에도 max_tokens 잘림(라이브 세션 전용) */
  truncated?: boolean;
  /** 기능 조합의 중간 단계(2026-10-02) — 기본 렌더에서 빠지고 "과정 보기"로만
   *  펼쳐진다. 모델 컨텍스트에는 들어가 있다(숨김은 렌더 계층의 일). */
  hidden?: boolean;
};

/* ─────────────────── front-derived Turn (03 §2.2) ─────────────────── */

export type Turn = {
  /** = human message id (report_overview 턴은 해당 ai message id) */
  id: string;
  user_message: { id: string; content: string };
  status: "running" | "done" | "error" | "interrupted";
  /** "report_overview" — 보고서 완료 개요 전용 턴(사용자 말풍선 없음, 완료 카드 렌더) */
  kind?: "report_overview";
  /** 조합의 중간 단계 턴 — 기본 목록에서 숨긴다. 마지막 종합만 보인다. */
  hidden?: boolean;
  /** ms epoch */
  started_at: number;
  ended_at?: number;
  steps: Step[];
  interrupt?: InterruptValue;
  answer?: {
    /** ai message id — feedback POST 라우트 mid 자리에 들어감 */
    id: string;
    /** 마지막 AI message content. 인용은 평문 [n] (back §7) */
    content: string;
    /** [n] + step.citations 합집합 (id dedupe) */
    citations: Citation[];
    /** 이 turn에서 변경된 state.files[path] view */
    artifacts: Artifact[];
  };
  /** 답변이 길이 상한(자동 이어쓰기 포함)에서 잘림 — [이어서 작성] 버튼 노출 */
  truncated?: boolean;
  /**
   * "처리 과정" — 직전 AI 메시지들(도구 호출 preamble, 탐색 narration 등) 텍스트를 합친
   * 것. final answer(answer.content)와 분리. UI는 토글 안에 노출.
   */
  process_content?: string;
};
