"use client";

/**
 * RightPanel — 02 §4, §5. 03 §7.
 *
 * 모드 슬롯 (우선순위):
 *   - `citation` → CitationInspector (reports 있으면 아래로 분할)
 *   - `docPath` → ArtifactViewer (reports 있으면 아래로 분할)
 *   - done 보고서만 있고 강제 모드 없음 → ReportCardGroup (자동)
 *   - 모두 해당 X → null (패널 unmount)
 *
 * citation·docPath 두 키는 상호 배타.
 * ※ deep 진행(DeepProgressPanel) 분기는 단일 thread 전환(2026-05-19)으로 폐기 —
 *   deep_dispatched_at을 세팅하는 코드가 없어 도달 불가 분기였다. 진행 표시는
 *   ReportInProgressCard(report_turn_ids)로 대체.
 */

import { toast } from "sonner";
import { cancelReportRun } from "@/lib/client/reports";
import { useCallback, useEffect, useState } from "react";
import type { ChatState } from "@/lib/store/types";
import { CitationInspector } from "@/components/panel/CitationInspector";
import { ArtifactViewer } from "@/components/panel/ArtifactViewer";
import { ReportCardGroup } from "@/components/chat/ReportCardGroup";
import { useRightPanel } from "@/lib/store/rightPanel";

type Props = {
  state: ChatState;
  isRunning?: boolean;
  /** 보고서 폴링 중(채팅과 분리) — 진행 카드의 **단일 진실원**(재설계 2026-07-24). */
  reportRunning?: boolean;
  reportQueueAhead?: number | null;
  reportProgress?: string | null;
  /** 별표·서식 인용에서 "이 서식으로 작성" — PageShell 이 보고서를 트리거 */
  onUseAsForm?: (articleKey: string, title: string) => void;
};

function hasDoneReports(state: ChatState): boolean {
  // "doc"(서류)는 보고서가 아니다 — 문서 존재는 state.document 가 담당.
  return (state.reports ?? []).some(
    (r) => r.status === "done" && r.kind !== "doc");
}

function ReportsView({ state, reportRunning, reportQueueAhead, reportProgress }: Props) {
  // 라벨은 외부 SectionHeader가 제공 — 자체 <h2> 두면 헤더 중복.
  // 재설계(2026-07-24): 진행 여부 = reportRunning 단일 진실원. 턴 타임라인
  // (report_turn_ids) 의존은 폐기 — 마지막 턴 여부·새로고침과 무관하게 정확.
  const inFlight = !!reportRunning;
  return (
    <aside
      aria-label="생성된 보고서"
      className="vt-right-panel flex h-full w-full flex-col bg-md-surface-container-lowest p-4"
    >
      <div className="flex-1 overflow-y-auto">
        {inFlight ? (
          <ReportInProgressCard
            startedAt={state.report_started_at ?? Date.now()}
            queueAhead={reportQueueAhead ?? null}
            progress={reportProgress ?? null}
            isDraft={state.report_purpose === "document_draft"}
            idemKey={state.report_idem_key ?? null}
          />
        ) : null}
        <ReportCardGroup reports={state.reports ?? []} />
      </div>
    </aside>
  );
}

/**
 * sidebar용 "보고서 생성 중" placeholder. ReportCardGroup 상단(또는 단독)으로
 * 노출돼 완료 전에도 *어디선가 뭔가 도는 신호*를 사용자에게 준다. 채팅 안
 * 안정 카드(Turn.tsx)는 그 턴 본문 자리, 이 카드는 사이드 보고서 영역.
 */
function ReportInProgressCard({
  startedAt,
  queueAhead = null,
  progress = null,
  isDraft = false,
  idemKey = null,
}: {
  startedAt: number;
  queueAhead?: number | null;
  progress?: string | null;
  /** 서류 초안 — 같은 파이프라인이지만 사용자에겐 다른 작업이다(2026-08-27) */
  isDraft?: boolean;
  /** 진행 run 멱등키 — [중단] 버튼용(없으면 버튼 미노출). */
  idemKey?: string | null;
}) {
  const [cancelling, setCancelling] = useState(false);
  const onCancel = async () => {
    if (!idemKey) return;
    if (!window.confirm("보고서 작성을 중단할까요? 지금까지의 진행은 저장되지 않습니다.")) return;
    setCancelling(true);
    try {
      await cancelReportRun(idemKey);
      // 상태 정리는 폴링이 status=cancelled 를 받아 수행(토스트 포함).
    } catch (err) {
      console.error("[report] cancel failed", err);
      toast.error("중단하지 못했습니다 — 이미 완료됐거나 잠시 후 다시 시도해주세요.");
      setCancelling(false);
    }
  };
  const noun = isDraft ? "서류 초안" : "심층 보고서";
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  // 대기 판정 — 큐에 앞선 건이 있거나, 진행 라벨이 대기를 말할 때.
  const waiting =
    (typeof queueAhead === "number" && queueAhead > 0) ||
    Boolean(progress && progress.includes("대기"));
  const sec = Math.max(0, Math.floor((now - startedAt) / 1000));
  const mm = String(Math.floor(sec / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  const STEPS = isDraft
    ? ["서식 확인", "근거 수집", "초안 작성"]
    : ["쿼리 분해", "자료 수집", "보고서 작성"];
  const stepIdx = !progress
    ? -1
    : progress.includes("작성") ? 2 : progress.includes("수집") ? 1 : progress.includes("분해") ? 0 : -1;
  return (
    <section
      aria-label="보고서 생성 중"
      aria-live="polite"
      className="mb-3 rounded-card border border-md-outline-variant bg-md-surface-container-lowest p-3"
    >
      <div className="flex items-center gap-2.5">
        <span
          className="inline-block size-4 shrink-0 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-md-on-surface">
            {/* 대기 ≠ 생성 — GPU 를 다른 보고서가 쓰는 동안엔 내 보고서가
                작성되는 게 아니라 순서를 기다리는 중이다(2026-08-26). */}
            <span className="animate-md-shimmer text-md-primary">
              {waiting ? `${noun} 대기 중` : `${noun} 작성 중`}
            </span>
          </p>
          <p className="text-[11px] text-md-on-surface-variant">
            {waiting
              ? "다른 보고서가 먼저 작성 중 · 순서가 되면 자동 시작"
              : `${progress ?? "보통 5~20분, 길면 1시간"} · ${
                  isDraft ? "완료되면 문서 패널에서 채울 수 있어요" : "완료 시 사이드바 목록·이메일로"
                }`}
          </p>
        </div>
        <span className="shrink-0 rounded bg-md-surface-container-high px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-md-on-surface-variant">
          {mm}:{ss}
        </span>
        {idemKey ? (
          <button
            type="button"
            onClick={() => void onCancel()}
            disabled={cancelling}
            title="보고서 작성 중단"
            className="shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium text-md-error transition-colors hover:bg-md-error/10 disabled:opacity-50"
          >
            {cancelling ? "중단 중…" : "중단"}
          </button>
        ) : null}
      </div>
      {typeof queueAhead === "number" && queueAhead > 0 ? (
        <p className="mt-2 text-[11px] font-medium text-md-tertiary">
          앞에 {queueAhead}건 대기 중 · 순서가 되면 자동 시작
        </p>
      ) : (
        <div className="mt-2.5 flex items-end gap-1.5" aria-hidden>
          {STEPS.map((label, i) => (
            <div key={label} className="flex flex-1 flex-col gap-1">
              <div
                className={
                  "h-1 rounded-full transition-colors duration-500 " +
                  (i < stepIdx
                    ? "bg-md-primary"
                    : i === stepIdx
                      ? "bg-md-primary animate-md-shimmer"
                      : "bg-md-outline-variant")
                }
              />
              <span
                className={
                  "text-[10px] leading-none " +
                  (i <= stepIdx ? "font-medium text-md-primary" : "text-md-on-surface-variant")
                }
              >
                {label}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * collapse 상태를 localStorage에 persist — 우측 패널이 unmount(닫힘)/remount(재오픈)
 * 되어도 직전 상태 그대로 복원. 페이지 새로고침에도 유지.
 */
function usePersistedCollapsed(
  key: string,
  fallback = false,
): [boolean, (v: boolean | ((p: boolean) => boolean)) => void] {
  const [value, setValueRaw] = useState<boolean>(fallback);
  // mount 시 localStorage에서 복원 (SSR 안전).
  useEffect(() => {
    try {
      const v = window.localStorage.getItem(key);
      if (v === "1" || v === "0") setValueRaw(v === "1");
    } catch {
      // ignore — private mode 등
    }
  }, [key]);
  const setValue = useCallback(
    (v: boolean | ((p: boolean) => boolean)) => {
      setValueRaw((prev) => {
        const next =
          typeof v === "function" ? (v as (p: boolean) => boolean)(prev) : v;
        try {
          window.localStorage.setItem(key, next ? "1" : "0");
        } catch {
          // ignore
        }
        return next;
      });
    },
    [key],
  );
  return [value, setValue];
}

/**
 * vertical split — flexbox 기반. 각 영역 *최상단의 타이틀 띠*가 클릭 가능 → 그 영역
 * collapse/expand. collapsed 시 본문 div가 `h-0`로 차지 0이라 *여백 없이* 깔끔히 닫힘.
 * 접힌 상태에서도 타이틀 띠는 계속 보임. collapse 상태는 localStorage persist —
 * 패널 닫고 다시 열어도 직전 상태 그대로.
 */
function VerticalSplit({
  top,
  bottom,
  topLabel,
  bottomLabel,
  topIcon,
  bottomIcon,
  forceExpandTopKey,
}: {
  top: React.ReactNode;
  bottom: React.ReactNode;
  /** 미사용 — PanelGroup 제거로 deprecated. signature 호환 위해 optional 유지. */
  autoSaveId?: string;
  topLabel: string;
  bottomLabel: string;
  topIcon?: string;
  bottomIcon?: string;
  /**
   * 변경 시 top section auto-expand 강제. 본문 chip 클릭으로 citation/docPath 새로
   * 박힐 때 사용 — 사용자가 "출처" 섹션 collapsed 해놨어도 새 컨텐츠는 노출되어야.
   */
  forceExpandTopKey?: string;
}) {
  const [topCollapsed, setTopCollapsed] = usePersistedCollapsed(
    "medi.rp.split.top.collapsed",
  );
  const [bottomCollapsed, setBottomCollapsed] = usePersistedCollapsed(
    "medi.rp.split.bottom.collapsed",
  );
  // citation/docPath 새로 set 시 top 섹션 강제 expand
  useEffect(() => {
    if (forceExpandTopKey) setTopCollapsed(false);
  }, [forceExpandTopKey, setTopCollapsed]);

  // top은 기본 `flex-1`로 grow → bottom이 collapse되면 자동으로 남은 공간을 다
  // 차지(사용자 회신 "보고서 목록 닫으면 citation 본문 더 넓게"). bottom toggle bar는
  // flex-col 흐름상 top 본문 바로 아래 — top이 flex-1로 부풀면 자연스럽게 화면 *맨
  // 아래*에 위치. bottom 열리면 자체 basis(40%)로 노출.
  // height transition은 max-height에 적용(basis/flex는 transition 안 먹음).
  return (
    <div className="flex h-full flex-col bg-md-surface-container-lowest">
      <SectionHeader
        label={topLabel}
        icon={topIcon}
        collapsed={topCollapsed}
        onClick={() => setTopCollapsed((v) => !v)}
      />
      <div
        className={
          "min-h-0 overflow-hidden transition-[max-height,flex-basis,flex-grow] duration-300 ease-out " +
          (topCollapsed
            ? "max-h-0 flex-none basis-0"
            : "max-h-full flex-1 basis-0")
        }
      >
        {top}
      </div>
      <SectionHeader
        label={bottomLabel}
        icon={bottomIcon}
        collapsed={bottomCollapsed}
        onClick={() => setBottomCollapsed((v) => !v)}
      />
      <div
        className={
          "min-h-0 overflow-y-auto transition-[max-height] duration-300 ease-out " +
          // basis-[40%] 고정을 폐기(2026-08-27) — 보고서가 1~2건일 때도 40%를
          // 점유해 목록 아래가 텅 빈 여백이 됐다("여백이 쓸데없이 큼" 지적).
          // 내용 높이만큼만 차지하고 40%는 상한으로만 쓴다. 넘치면 자체 스크롤.
          (bottomCollapsed ? "max-h-0 flex-none" : "max-h-[40%] flex-none")
        }
      >
        {bottom}
      </div>
    </div>
  );
}

/**
 * 영역 상단의 클릭 가능한 타이틀 띠. chevron 방향이 collapsed 상태 시각화.
 * 호버 시 hint 배경 — 사용자가 클릭 가능함을 인지하기 쉽게.
 */
function SectionHeader({
  label,
  icon,
  collapsed,
  onClick,
}: {
  label: string;
  icon?: string;
  collapsed: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={!collapsed}
      title={collapsed ? `${label} 펼치기` : `${label} 접기`}
      className="flex w-full shrink-0 items-center gap-2 border-b border-md-outline-variant bg-md-surface-container-low px-3 py-2 text-left text-[11.5px] font-semibold text-md-on-surface-variant transition-colors duration-200 ease-out hover:bg-md-surface-container hover:text-md-on-surface"
    >
      <span
        className={
          "material-symbols-outlined text-[16px] transition-transform duration-300 ease-out " +
          (collapsed ? "" : "rotate-90")
        }
        aria-hidden
      >
        chevron_right
      </span>
      {icon ? (
        <span className="material-symbols-outlined text-[16px]" aria-hidden>
          {icon}
        </span>
      ) : null}
      <span>{label}</span>
    </button>
  );
}

export function RightPanel({
  state,
  isRunning,
  reportRunning,
  reportQueueAhead,
  reportProgress,
  onUseAsForm,
}: Props) {
  const { citation, docPath } = useRightPanel();

  const hasReports = hasDoneReports(state);
  // 재설계(2026-07-24): reportRunning 단일 진실원 — done 0개여도 진행 중이면 패널 유지.
  const inFlightReport = !!reportRunning;
  // ReportsView는 reports done OR 보고서 진행 중 OR 서류 초안 존재 시 노출.
  // 서류 진입은 입력창 위 pill 하나로 일원화(2026-08-27, "복잡하게 가면
  // 안 됨") — 보고서 섹션에 서류 카드를 겹치지 않는다(서류≠보고서).
  const showReports = hasReports || inFlightReport;
  const hasDocPath = Boolean(docPath);
  const hasCitation = Boolean(citation);

  // 서류 모달은 PageShell 이 호스팅한다(2026-08-27 재재설계) — 패널이
  // 닫혀 있어도 모달이 떠야 하고, 문서가 사이드를 점유하면 안 된다
  // ("작성 중인 서류가 사이드 다 차지" 지적). 여기는 진입 카드만 남긴다.

  // 컨텍스트 패널 — artifact > citation (문서는 모달로 분리됨).
  const ctxPanel = hasDocPath ? (
    <aside
      aria-label="Artifact Viewer"
      className="flex h-full w-full flex-col bg-md-surface-container-lowest"
    >
      <ArtifactViewer state={state} path={docPath} hideHeader />
    </aside>
  ) : hasCitation ? (
    <aside
      aria-label="Citation Inspector"
      className="flex h-full w-full flex-col bg-md-surface-container-lowest"
    >
      <CitationInspector state={state} citationId={citation || ""} hideHeader
                         onUseAsForm={onUseAsForm} />
    </aside>
  ) : null;

  // 노출 자체 결정 — citation/artifact/문서/reports(완료 or 진행 중) 중 하나라도.
  // 문서는 패널을 강제하지 않는다 — 진입 카드는 reports 섹션에 얹혀 갈 뿐.
  const anyContent = hasCitation || hasDocPath || showReports;
  if (!anyContent) return null;

  // 컨텍스트(citation/artifact 클릭) 없음 → 이 분기 도달 = hasReports 참
  //   (anyContent 상 필연). **보고서 목록을 패널 전체로 노출.**
  //   이전 버그: 빈 CitationInspector를 top 64%에 박고 ReportsView를 28%
  //   bottom으로 밀어넣음 → 보고서가 생성돼도 작은 하단 띠 + VerticalSplit
  //   collapse가 localStorage 영속이라 접힌 채 완전히 숨어 "생성됐는데 안
  //   보임"이 반복됐음(폴링과 무관). 컨텍스트 없으면 split 자체를 안 쓴다.
  if (!ctxPanel) {
    if (showReports) {
      return (
        <>
        <aside
          aria-label="우측 패널 (보고서 목록)"
          className="flex h-full w-full flex-col bg-md-surface-container-lowest"
        >
          <ReportsView
            state={state}
            isRunning={isRunning}
            reportRunning={reportRunning}
            reportQueueAhead={reportQueueAhead}
            reportProgress={reportProgress}
          />
        </aside>
        </>
      );
    }
    return null; // anyContent로 이미 걸러짐 — 방어적.
  }

  // 컨텍스트 있음 — citation/artifact가 top. 보고서 있으면 아래로 split.
  const bottom = showReports ? (
    <ReportsView
      state={state}
      isRunning={isRunning}
      reportRunning={reportRunning}
      reportQueueAhead={reportQueueAhead}
      reportProgress={reportProgress}
    />
  ) : null;
  if (bottom) {
    return (
      <>
      <aside
        aria-label="우측 패널 (출처/보고서)"
        className="flex h-full w-full flex-col bg-md-surface-container-lowest"
      >
        <VerticalSplit
          autoSaveId="right-split-cite-reports"
          top={ctxPanel}
          bottom={bottom}
          topLabel={hasDocPath ? "Artifact" : "출처"}
          topIcon={hasDocPath ? "description" : "format_quote"}
          bottomLabel="보고서 목록"
          bottomIcon="summarize"
          forceExpandTopKey={citation || docPath || undefined}
        />
      </aside>
      </>
    );
  }
  return (
    <aside
      aria-label="우측 패널"
      className="flex h-full w-full flex-col bg-md-surface-container-lowest"
    >
      {ctxPanel}
    </aside>
  );
}

/**
 * RightPanel이 열려야 하는지 — PageShell의 Panel 마운트 분기에 사용.
 * 통합 분기: artifact 단독은 폭 분기 위해 별도 식별, 그 외(citation/reports/split)는
 * 모두 "side"로 통합. 패널 자체는 RightPanel 컴포넌트가 split을 시도함.
 */
export function useRightPanelMode(
  state?: ChatState,
  isRunning?: boolean,
  reportRunning?: boolean,
): "artifact" | "side" | null {
  const { citation, docPath } = useRightPanel();
  if (!state) {
    if (docPath && !citation) return "artifact";
    if (citation || docPath) return "side";
    return null;
  }
  const hasReports = hasDoneReports(state);
  // reportRunning 명시 전달 — 종전엔 isRunning 에 뭉뚱그려져 legacy 경로
  // (마지막 턴==report 턴)로 빠졌고, 보고서 중 채팅을 이어가면 mode 가 null
  // → 패널 자체가 언마운트돼 "진행 보기"가 빈 화면(실측 재발 2026-07-24).
  const inFlightReport = !!reportRunning; // 재설계: reportRunning 단일 진실원
  // 문서 존재는 패널을 열지 않는다(2026-08-27) — 모달·pill 이 담당.
  const showReports = hasReports || inFlightReport;
  // artifact 단독 — docPath 있고 그 외(reports·citation)는 없음
  if (docPath && !citation && !showReports) return "artifact";
  if (citation || docPath || showReports) return "side";
  return null;
}

