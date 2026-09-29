/**
 * `custom` 스트림 tool_progress 이벤트 형식 (back v4).
 *
 * ※ Deep 라이브 진행 타입(DeepStage·DeepStageState·DeepProgressState 등)은
 *   단일 thread 전환(2026-05-19)으로 폐기 — 진행 표시는 report_turn_ids +
 *   reports 폴링으로 대체됨.
 */

export type ToolProgressEvent = {
  type: "tool_progress";
  tool: string;
  phase: "started" | "embedding" | "searching" | "result" | "complete" | string;
  message: string;
  /** phase=="result" 시 — 검색 결과 1건 메타 */
  index?: number;
  title?: string;
  subtitle?: string;
  url?: string;
};
