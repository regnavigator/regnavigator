/**
 * 데이터 컨트랙트 타입 — `../medi-back/02_INTERFACE.md` v0.4 (canonical).
 * 모든 필드 네이밍은 **snake_case** (back §10 I11). 시간은 ms epoch int (Report.*만 ISO).
 *
 * **도메인별 분할** — 본 파일은 barrel re-export. 새 타입 추가는 적합한 도메인 파일에:
 *  - `types/citation.ts` — Citation, doc_category 13 분야
 *  - `types/chat.ts`     — Step, Message, FileEntry, Artifact, InterruptValue, Turn
 *  - `types/deep.ts`     — ToolProgressEvent (custom 스트림)
 *  - `types/report.ts`   — Report
 *  - `types/state.ts`    — ChatState
 *
 * 기존 `import { ... } from "@/lib/store/types"`는 그대로 작동.
 */

export type { Citation } from "./types/citation";
export type {
  Step,
  Message,
  FileEntry,
  Artifact,
  InterruptValue,
  Turn,
  FeatureMeta,
} from "./types/chat";
export type { ToolProgressEvent } from "./types/deep";
export type { Report } from "./types/report";
export type { ChatState } from "./types/state";
