"use client";

/**
 * Turn — 03 §2, P6.1.1 (rev).
 *
 * 한 턴 컨테이너: UserMessage + StepCarousel(한 칸) + TurnAnswer + NextStepsCard.
 *
 * NextStepsCard 데이터 소스: 답변 본문 끝의 `<next_steps>` 마커 블록 (backend v4).
 * `parseNextStepsMarker`가 본문에서 마커 strip + items 추출.
 */

import { useMemo } from "react";
import { UserMessage } from "@/components/chat/UserMessage";
import { StepCarousel } from "@/components/chat/StepCarousel";
import { LiveSearchGlass } from "@/components/chat/LiveSearchGlass";
import { TurnAnswer } from "@/components/chat/TurnAnswer";
import { NextStepsCard } from "@/components/chat/NextStepsCard";
import { RelatedFormsCard } from "@/components/chat/RelatedFormsCard";
import { InterruptCard } from "@/components/chat/InterruptCard";
import { parseNextStepsMarker } from "@/lib/parse/nextSteps";
import { parsePathwayMarker, stripPathwayMarker } from "@/lib/parse/pathwayMarker";
import { stripVerdictMarker } from "@/lib/parse/verdict";
import type { Turn as TurnType } from "@/lib/store/types";

type Props = {
  turn: TurnType;
  /** `kind:"chat"` 후속 질문 카드 클릭 시 — host가 ChatInput prefill 결정 */
  onPickNextStep?: (prompt: string) => void;
  /** `kind:"report"` 후속 질문 클릭 시 — host가 report-mode dispatch */
  onTriggerReport?: (prompt: string, purpose?: string) => void;
  /** clarify/approve_action 인터럽트 응답 — useChatState.resume 연결 */
  onResume?: (value: unknown) => void;
  /** 관련 서식 카드 [이 서식으로 작성] — host 의 openFormDocument(2026-09-08). 없으면 카드 미노출 */
  onUseAsForm?: (articleKey: string, title: string) => void;
  /**
   * 이 turn이 *활성 turn이고 스트림이 아직 진행 중*일 때 true (host가 마지막 turn에만 전달).
   * turn.status는 백엔드 흐름에 따라 본문 스트리밍 전에 transient하게 "done"이 될 수 있어
   * (중간 ai 메시지 → step 재시작), 그 사이 References/근거 UI가 깜빡 노출됐다 사라짐.
   * 스트림이 실제 끝날 때까지(`isRunning=false`)는 streaming으로 못박아 *본문이 확정된
   * 뒤에만* 인용문서·근거가 한 번에 노출되게 한다.
   */
  streamingActive?: boolean;
  /**
   * 활성 turn 한정 — backend `_emit_progress`(custom)가 흘리는 라이브 진행 한 줄
   * ("쿼리 임베딩 중…" 등). running step·답변이 아직 없는 대기 구간에 정적 대기
   * 대신 이 메시지를 노출해 체감 지연을 완화. host(PageShell)가 state.live_progress
   * 전달.
   */
  liveProgress?: string | null;
  /**
   * 활성 turn 한정 — backend `_emit_result`(tool_progress phase="result")가 검색 중
   * 흘리는 결과 1건씩의 라이브 카드. 답변 시작 전 대기 구간에 컴팩트 리스트로 노출.
   */
  liveResults?: Array<{
    tool: string;
    index: number;
    title: string;
    subtitle?: string;
    url?: string;
  }> | null;
};

export function Turn({
  turn,
  onPickNextStep,
  onTriggerReport,
  onResume,
  onUseAsForm,
  streamingActive = false,
  liveProgress = null,
  liveResults = null,
}: Props) {
  // 본문/근거 게이트 단일 진실: turn.status가 transient하게 done이어도, 스트림이
  // 실제로 도는 동안(streamingActive)은 streaming으로 취급 → 인용문서·References·
  // ConfidenceBadge·Artifact는 스트림이 끝난 *뒤에만* 한 번에 노출.
  const streaming = turn.status === "running" || streamingActive;
  // 경로는 본문 마커에서 꺼낸다 — 스레드를 다시 열어도 그대로 살아난다.
  const pathway = useMemo(
    () => (turn.answer?.content ? parsePathwayMarker(turn.answer.content) : []),
    [turn.answer?.content],
  );
  // running 상태인데 step도 답변도 아직 없음 → 즉시 피드백 (백엔드 첫 chunk 대기 중).
  // chunk 무수신 60s 도달 시 useChatState가 자동 abort + InlineErrorBanner 노출 →
  // 사용자가 정지 버튼 누를 필요 없음. 경과 초 표시는 제거 — 대기 불안만 키움.
  const isWaitingFirstChunk =
    turn.status === "running" && turn.steps.length === 0 && !turn.answer;

  // 답변 본문 끝의 `<next_steps>` 마커 파싱.
  // streaming 중 partial 마커는 본문에서 stripping만 하고 items는 빈 배열.
  const parsed = turn.answer
    ? parseNextStepsMarker(stripPathwayMarker(turn.answer.content))
    : { clean: "", items: [] };
  // IRB/DRB 스킬 판정 턴의 `<verdict>` 블록 숨김 — 판정 데이터는 skill_verdict
  // 이벤트로 별도 수신, 본문에는 노출하지 않음 (backend v2 §2-4).
  const clean = stripVerdictMarker(parsed.clean);
  const items = parsed.items;
  const showNextSteps =
    turn.status === "done" &&
    !streamingActive &&
    items.length > 0 &&
    !!onPickNextStep;

  // TurnAnswer에 cleaned content 전달 — 마커가 본문에 노출되지 않게.
  const cleanedAnswer = turn.answer ? { ...turn.answer, content: clean } : null;

  // 답변 영역 — content 있으면 streaming 중에도 노출 (citation chip 라이브 표시).
  // 안전장치: lastAi 필터에서 tool_calls 가진 preamble 메시지 제외 → intermediate 텍스트가
  // answer.content에 안 들어옴.
  // "처리 과정" 토글: preamble 텍스트가 있을 때만 노출. 단순 chat은 토글 자체 안 뜸.
  const hasAnswerContent =
    !!cleanedAnswer && cleanedAnswer.content.trim().length > 0;
  const showFinalAnswer = hasAnswerContent;
  // 라이브 근거수집 글라스(LiveSearchGlass)가 뜨는 검색 구간엔 하단 step disclosure
  // ("근거 찾는 중")를 숨겨 "결과 수집 중"이 이중 노출되지 않게 한다(2026-07-23).
  const showLiveGlass =
    streaming && !hasAnswerContent && !!liveResults && liveResults.length > 0;
  const processContent = (turn.process_content ?? "").trim();
  const showProcessToggle = processContent.length > 0;

  // 보고서 완료 개요 전용 턴(재설계 2026-07-24) — 서버가 append 한
  // kind:"report_overview" 메시지. 사용자 말풍선 없이 개요 + 완료 카드만.
  if (turn.kind === "report_overview") {
    return (
      <article
        aria-label={`Report overview ${turn.id}`}
        className="flex flex-col gap-3"
      >
        {hasAnswerContent ? (
          <TurnAnswer answer={cleanedAnswer!} streaming={false} pathway={pathway} />
        ) : null}
        <ReportDoneCard />
      </article>
    );
  }

  return (
    <article aria-label={`Turn ${turn.id}`} className="flex flex-col gap-stack-gap">
      <UserMessage content={turn.user_message.content} />

      {isWaitingFirstChunk ? (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2.5 px-1 text-body-sm text-md-on-surface-variant"
        >
          {/* 시차 펄스 typing dots(기존 animate-md-typing-dot 재사용) — 회전
              스피너+경과초보다 차분하고 "생각 중" 느낌. 경과 시간 표기 없음. */}
          <span className="flex items-end gap-1" aria-hidden>
            <span
              className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
              style={{ animationDelay: "0ms" }}
            />
            <span
              className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
              style={{ animationDelay: "160ms" }}
            />
            <span
              className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
              style={{ animationDelay: "320ms" }}
            />
          </span>
          {/* live_progress(검색 진행 한 줄)가 오면 그걸 노출 — 정적 "준비 중"
              대신 "쿼리 임베딩 중…" 등 라이브 메시지로 대기 시간을 살아있게.
              아직 없으면 기본 문구. */}
          <span className="animate-md-shimmer font-medium">
            {liveProgress || "답변을 준비하고 있어요"}
          </span>
        </div>
      ) : null}

      {turn.steps.length > 0 && !showLiveGlass
        ? (() => {
            // 단계 디스클로저(Claude web식). 이 step들은 LLM 사고가 아니라
            // 웹 검색·법령 RAG 조회(=근거 수집)이라 "근거 찾는 중/근거 수집".
            // **진행 중(streaming)엔 자동 펼침** → 검색 내용·tool 입출력·step
            // 상세를 라이브로 노출(이전 '접힘 기본'은 그게 안 보인다는 지적의
            // 원인). 끝나면 접혀 "근거 수집 (N단계)"로 — 화면 정리. 에러 step은
            // 펼침 유지(skill §2). StepCard 내부 auto 동작 미변경(skill §2).
            const lastStep = turn.steps[turn.steps.length - 1];
            const liveLabel = lastStep?.label?.trim() ?? "";
            const hasErrorStep = turn.steps.some(
              (s) => s.status === "error",
            );
            return (
              <details
                open={(streaming && !hasAnswerContent) || hasErrorStep}
                className="rounded-card border border-md-outline-variant bg-md-surface-container-lowest"
              >
                <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-body-sm transition-colors hover:bg-md-surface-container-low">
                  {streaming ? (
                    <span className="flex items-end gap-1" aria-hidden>
                      <span
                        className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
                        style={{ animationDelay: "0ms" }}
                      />
                      <span
                        className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
                        style={{ animationDelay: "160ms" }}
                      />
                      <span
                        className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
                        style={{ animationDelay: "320ms" }}
                      />
                    </span>
                  ) : (
                    <span
                      className="material-symbols-outlined text-[17px] text-md-on-surface-variant"
                      aria-hidden
                    >
                      manage_search
                    </span>
                  )}
                  <span
                    className="min-w-0 flex-1 truncate font-medium text-md-on-surface-variant"
                    aria-live="polite"
                  >
                    {streaming && !hasAnswerContent ? (
                      <span className="animate-md-shimmer">
                        {liveLabel
                          ? `근거 찾는 중… ${liveLabel}`
                          : "근거 찾는 중…"}
                      </span>
                    ) : streaming ? (
                      // 검색은 끝나고 본문 스트리밍 중 — "검색중" 지속 표기는
                      // 사용감 저하(2026-07-16 피드백) → 단계 전환 명시.
                      <span className="animate-md-shimmer">
                        {`근거 수집 완료 (${turn.steps.length}단계) — 답변 작성 중…`}
                      </span>
                    ) : (
                      `근거 수집 (${turn.steps.length}단계)`
                    )}
                  </span>
                  <span
                    className="material-symbols-outlined shrink-0 text-[18px] text-md-on-surface-variant"
                    aria-hidden
                  >
                    expand_more
                  </span>
                </summary>
                <div className="border-t border-md-outline-variant p-2">
                  <StepCarousel steps={turn.steps} />
                </div>
              </details>
            );
          })()
        : null}

      {/* ✨ 라이브 근거 수집 글라스 카드 — 검색 중 phase="result"로 한 건씩
          도착하는 결과 + 현재 쿼리 + 진행 한 줄을 글라스 피드로 라이브 노출.
          (구 컴팩트 리스트를 대체.) 답변 본문이 시작되면 숨김. */}
      {showLiveGlass ? (
        <LiveSearchGlass
          results={liveResults}
          query={
            [...turn.steps]
              .reverse()
              .find((s) => s.status === "running")?.input_preview ?? null
          }
          progress={liveProgress}
        />
      ) : null}

      {showProcessToggle ? (
        <details className="rounded-card border border-md-outline-variant bg-md-surface-container-lowest">
          <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-body-sm text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low">
            {turn.status === "running" ? (
              <span
                className="inline-block size-3.5 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin"
                aria-hidden
              />
            ) : (
              <span
                className="material-symbols-outlined text-[16px]"
                aria-hidden
              >
                expand_more
              </span>
            )}
            <span className="font-medium">
              {turn.status === "running" ? (
                <span className="animate-md-shimmer">진행 중...</span>
              ) : (
                "처리 과정 보기"
              )}
            </span>
          </summary>
          {processContent ? (
            <div className="whitespace-pre-wrap border-t border-md-outline-variant px-4 py-3 text-body-sm text-md-on-surface-variant">
              {processContent}
            </div>
          ) : (
            <div className="border-t border-md-outline-variant px-4 py-3 text-body-sm text-md-on-surface-variant">
              아직 표시할 내용 없음.
            </div>
          )}
        </details>
      ) : null}

      {/* 보고서 분기는 재설계(2026-07-24)로 제거 — 보고서는 채팅 턴에 끼지
          않는다. 진행 = 입력창 위 노티스+우측 패널(reportRunning), 완료 =
          kind:"report_overview" 전용 턴(위 early return). */}
      {showFinalAnswer ? (
        <>
          <TurnAnswer answer={cleanedAnswer!} streaming={streaming} pathway={pathway} />
          {!streaming && onUseAsForm ? (
            <RelatedFormsCard
              question={turn.user_message.content}
              answer={cleanedAnswer!.content}
              citations={cleanedAnswer!.citations}
              onUseAsForm={onUseAsForm}
            />
          ) : null}
        </>
      ) : streaming && !showLiveGlass && turn.steps.length > 0 && !turn.interrupt ? (
        // showLiveGlass 중엔 미렌더 — 글라스 카드가 이미 progress 를 표시하므로
        // 같은 "결과 수집 중…" 문구가 카드 안팎 이중 노출되던 문제(2026-07-25).
        // 검색 step 완료 ~ 답변 스트리밍 시작 사이 공백 — 답변도 없고 첫 chunk
        // 대기 dots(steps=0 전제)도 안 떠 정적 공백이 됨(사용자 회신 "벡터검색
        // 뜨고도 수 초 뒤 스트리밍 시작해 답답"). 이 구간을 라이브 인디케이터로
        // 채움. liveProgress(writer 등 진행) 있으면 그걸, 없으면 "답변 작성 중".
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2.5 px-1 text-body-sm text-md-on-surface-variant"
        >
          <span className="flex items-end gap-1" aria-hidden>
            <span
              className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
              style={{ animationDelay: "0ms" }}
            />
            <span
              className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
              style={{ animationDelay: "160ms" }}
            />
            <span
              className="size-1.5 rounded-full bg-md-primary animate-md-typing-dot"
              style={{ animationDelay: "320ms" }}
            />
          </span>
          <span className="animate-md-shimmer font-medium">
            {liveProgress || "답변 작성 중"}
          </span>
        </div>
      ) : null}

      {turn.interrupt && onResume ? (
        <InterruptCard interrupt={turn.interrupt} onResume={onResume} />
      ) : null}

      {/* 길이 상한 잘림(자동 이어쓰기 상한 초과) — 이어서 작성 폴백 (2026-08-24) */}
      {turn.truncated && turn.status === "done" && onPickNextStep ? (
        <div className="mt-1 flex items-center gap-2">
          <span className="text-[11.5px] text-md-on-surface-variant">
            답변이 길이 제한으로 잘렸습니다.
          </span>
          <button
            type="button"
            onClick={() => onPickNextStep("이어서 계속 작성해줘")}
            className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] font-medium text-md-primary hover:bg-md-surface-container-low"
          >
            이어서 작성
          </button>
        </div>
      ) : null}

      {showNextSteps ? (
        <NextStepsCard
          items={items}
          onPick={onPickNextStep!}
          onTriggerReport={onTriggerReport}
        />
      ) : null}
    </article>
  );
}

/**
 * 보고서 진행 카드 — *답변 영역*에 띄워 "생성 중" 흐름을 줌. 1초 tick으로
 * 경과 시간(mm:ss) 갱신. 새 컴포넌트 파일 추가 X(복잡도 최소) — Turn.tsx 안
 * 로컬 helper로 유지.
 *
 * 표시 요소:
 *   - 회전 spinner — 활동 신호
 *   - "답변 생성 중" shimmer 텍스트 — 흐름 신호
 *   - 경과 시간(mm:ss) — 진행 누적 신호(사용자 체감)
 *   - 약 5분 안내(부제) — 기대 관리
 *
 * `prefers-reduced-motion` 시 shimmer/spin은 토큰 정의에서 자동 차단(globals).
 */
/**
 * report-mode 완료 — *보고서 전문은 사이드바 전용*임을 알리는 포인터 카드.
 * 개요 답변(TurnAnswer) 아래에 함께 노출되어 "전문은 사이드바에서"를 안내한다.
 * (개요 자체는 답변으로 노출 — 2026-05-22 결정. 개요 ≠ 보고서 전문.)
 * 개요가 비어있을 땐(미수신) 이 카드 단독으로 폴백.
 *
 * 실패 사유는 본 카드가 아니라 step disclosure(`근거 수집`)의 error step에서
 * 노출되어야 함 — backend RFC에 step_error 박기 항목 추가됨.
 */
function ReportDoneCard() {
  return (
    <section
      aria-label="보고서 준비 완료"
      className="rounded-card border border-md-primary/40 bg-md-surface-container-lowest p-4"
    >
      <div className="flex items-center gap-3">
        <span
          className="material-symbols-outlined shrink-0 text-[20px] text-md-primary"
          aria-hidden
        >
          check_circle
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-body-sm font-semibold text-md-on-surface">
            보고서가 준비됐어요
          </span>
          <span className="text-[12px] text-md-on-surface-variant">
            우측 사이드바에서 본문을 확인하세요
          </span>
        </div>
      </div>
    </section>
  );
}




// (ReportPendingNotice 는 재설계 2026-07-24 로 PageShell 입력창 위 고정
//  슬롯으로 이동 — 보고서 진행 표시는 턴 타임라인 밖에서 reportRunning 구독.)
