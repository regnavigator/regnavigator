/**
 * ChatState — frontend의 thread-scoped state container (P5.13).
 */

import type { FileEntry, Message, Step, Turn } from "./chat";
import type { Report } from "./report";

export type ChatState = {
  messages: Message[];
  files: Record<string, FileEntry>;
  steps: Step[];
  turns: Turn[];
  /** 최근 시스템 에러 (단절·인증 등) — `04 §4.3` InlineErrorBanner */
  error?: { message: string; retriable: boolean } | null;
  // ※ deep_dispatched_at·deep_baseline_done·deep_progress는 단일 thread
  //   전환(2026-05-19)으로 폐기 — 세팅하는 코드가 없어 dead field였다.
  /**
   * 05 §6 — Reports API에서 폴링한 보고서 목록 (최신 우선).
   * 보고서 트리거 후부터 채워짐. 한 thread에서 누적.
   */
  reports?: Report[];
  // ※ report_turn_ids 는 파이프라인 재설계(2026-07-24)로 폐기 — 보고서는 채팅
  //   턴 타임라인에 끼지 않는다. 진행 = reportRunning(+아래 report_* 필드),
  //   완료 = 서버가 append 한 kind:"report_overview" 메시지의 전용 턴.
  /**
   * 보고서 시작 시각(ms) — 진행 카드 경과 타이머 기준. 트리거 시 now, 새로고침
   * 복원 시 runs/active 의 started_at. 종료 시 null.
   */
  report_started_at?: number | null;
  /** 진행 중 run 의 멱등키 — [중단] 버튼이 취소 API 를 부를 때 필요. */
  report_idem_key?: string | null;
  /**
   * 진행 중 산출물의 성격(2026-08-27) — "document_draft" 면 서류 초안이다.
   * 서류도 보고서와 같은 파이프라인을 타서 진행 표시가 "심층 보고서 생성 중"
   * 으로 나왔다("서식으로 작성을 눌렀는데 왜 보고서로 가냐" — 실사용 지적).
   * 화면 문구를 가르기 위한 필드.
   */
  report_purpose?: string | null;
  /**
   * 라이브 진행 한 줄 — backend `_emit_progress`(custom `tool_progress`)가 흘리는
   * "쿼리 임베딩 중…", "결과 수집 중…" 같은 *검색 진행 메시지*. running step이
   * 아직 없는 첫 chunk 대기 구간(검색 시작~첫 step·답변)에 대기 인디케이터로
   * 노출 → 수 초~수십 초 정적 대기를 *살아있게*. 답변 본문이 시작되거나 turn이
   * 끝나면 클리어. (running step이 매칭되면 그 step의 progress_message가 우선.)
   */
  live_progress?: string | null;
  /**
   * 검색 진행 중 라이브 결과 카드 — backend `_emit_result`(tool_progress
   * phase="result")가 결과 1건씩 흘림. (tool, index)로 dedupe하며 누적.
   * 새 turn 시작(send)·`steps` 이벤트 도착 시 클리어. 답변 시작 후 UI에서 숨김.
   */
  live_results?: Array<{
    tool: string;
    index: number;
    title: string;
    subtitle?: string;
    url?: string;
  }> | null;
  /**
   * 보고서 큐 대기 — `GET /reports/runs/{idem}` 폴링 응답의 `queue_ahead`
   * (running일 때만). 앞에 N건 대기 중. 폴링마다 갱신, 종료 시 null.
   */
  report_queue_ahead?: number | null;
  /**
   * 보고서 세부 진행 라벨 — 폴링마다 스레드 report step(분해→수집→작성)에서 추출.
   * running step의 progress_message가 있으면 결합. 종료 시 null.
   */
  report_progress?: string | null;
  /**
   * 서류 초안(document_draft) 상태 — 스레드 로드 시 `GET /documents/state` 로
   * 복원, 채팅 중엔 SSE `document_update` 로 병합(2026-08-24 Phase ③).
   * `last_filled` = 직전 이벤트로 채워진 항목명(패널 하이라이트 트리거),
   * `rev` = 이벤트 수신 횟수(0=복원만) — 자동 패널 오픈·애니메이션 키.
   */
  document?: {
    report_id: string;
    fields: string[];
    filled: Record<string, string>;
    remaining: string[];
    last_filled?: string[];
    /** 그중 대화로 **정정**된 항목 — 새로 채운 것과 다르게 알린다(2026-08-27). */
    last_corrected?: string[];
    rev: number;
  } | null;
};
