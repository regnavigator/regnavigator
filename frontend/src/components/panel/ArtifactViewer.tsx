"use client";

/**
 * ArtifactViewer — 02 §4.2, 03 §7.2.
 *
 * `?docPath=<path>` URL 진입 시 RightPanel 슬롯 점유.
 *
 * **리스트 마스터-디테일** 구성 (사용자 요구 — 보고서 리스트 누적 + 생성단계 노출):
 *   - 모든 `state.files`를 modified_at 내림차순으로 행으로 표시.
 *   - 각 행: status 아이콘(✓/⏳) · filename · size · 시각 · 생성 Turn(+best-effort step label).
 *   - URL `?docPath` 매칭 행만 펼쳐서 markdown 본문 보임.
 *   - 다른 행 클릭 → URL 갱신 → 펼침/접힘 swap.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatState, FileEntry, Report, Step } from "@/lib/store/types";
import { MarkdownContent } from "@/components/chat/MarkdownContent";
import { downloadFromMemory, downloadReport } from "@/lib/client/reports";
import { useRightPanel } from "@/lib/store/rightPanel";

type Props = {
  state: ChatState;
  /** URL 쿼리에서 받은 활성 path. 없으면 첫 행 기본 활성. */
  path: string;
  /**
   * 자체 헤더 숨김. 우측 패널 split 모드처럼 외부에서 이미 라벨 띠를 제공하는
   * 경우 사용 — 헤더 중복(SectionHeader + 본문 헤더) 방지.
   */
  hideHeader?: boolean;
};

function getFileText(file: FileEntry): string {
  return Array.isArray(file.content) ? file.content.join("\n") : "";
}

function basenameOf(path: string): string {
  return path.replace(/^\/+/, "").split("/").pop() ?? path;
}

function formatBytes(file: FileEntry): string {
  const text = getFileText(file);
  const bytes = new TextEncoder().encode(text).length;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(ms: number): string {
  if (!ms) return "";
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

/**
 * file path가 어느 Turn에서 어느 step이 만든 것인지 매핑.
 *
 * 우선순위:
 *  1) **R3 — `file.generated_by_step_id` 직접 lookup** (backend가 박은 정확한 매핑)
 *  2) 시간 윈도우 heuristic fallback — `file.modified_at`이 turn 범위 안인지 + tool_name 일치
 */
function findOrigin(
  state: ChatState,
  path: string,
): { turnIndex: number; step?: Step } | null {
  const file = state.files[path];
  if (!file) return null;

  // 1) R3 직접 lookup
  if (file.generated_by_step_id) {
    for (let i = 0; i < state.turns.length; i++) {
      const turn = state.turns[i];
      if (!turn) continue;
      const step = turn.steps.find((s) => s.id === file.generated_by_step_id);
      if (step) return { turnIndex: i + 1, step };
    }
  }

  // 2) heuristic fallback
  const t = file.modified_at ?? file.created_at;
  for (let i = 0; i < state.turns.length; i++) {
    const turn = state.turns[i];
    if (!turn) continue;
    const turnEnd = turn.ended_at ?? Number.MAX_SAFE_INTEGER;
    if (t >= turn.started_at && t <= turnEnd) {
      const writerStep = turn.steps.find((s) => {
        const tool = s.tool_name ?? "";
        return /(task|write_file|save_file|save_report|edit_file)/.test(tool);
      });
      const stepInWindow = turn.steps
        .filter((s) => s.ts <= t && (s.ended_at ?? Number.MAX_SAFE_INTEGER) >= t)
        .at(-1);
      return { turnIndex: i + 1, step: writerStep ?? stepInWindow };
    }
  }
  return null;
}

export function ArtifactViewer({ state, path, hideHeader = false }: Props) {
  const { setCitation, setDocPath } = useRightPanel();

  const close = useCallback(() => {
    setCitation(null);
    setDocPath(null);
  }, [setCitation, setDocPath]);

  const sortedPaths = useMemo(() => {
    const entries = Object.entries(state.files ?? {});
    return entries
      .sort(
        ([, a], [, b]) =>
          (b.modified_at ?? b.created_at ?? 0) -
          (a.modified_at ?? a.created_at ?? 0),
      )
      .map(([p]) => p);
  }, [state.files]);

  // URL이 가리키는 path가 list에 없으면 첫 행 기본 활성. (URL은 그대로 둠 — 사용자 명시 의도 보존)
  const activePath = sortedPaths.includes(path) ? path : (sortedPaths[0] ?? null);

  return (
    <div className="flex h-full flex-col" aria-label="Artifact Viewer">
      {!hideHeader ? (
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-md-outline-variant px-3">
          <span
            className="material-symbols-outlined text-[18px] text-md-on-surface-variant"
            aria-hidden
          >
            article
          </span>
          <span className="text-body-sm font-semibold text-md-on-surface">
            보고서 / 산출물
          </span>
          <span className="rounded-pill bg-md-surface-container px-2 py-0.5 text-[11px] font-semibold text-md-on-surface-variant">
            {sortedPaths.length}
          </span>
          <button
            type="button"
            onClick={close}
            aria-label="닫기"
            className="ml-auto rounded-button p-1 text-md-on-surface-variant hover:text-md-on-surface"
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden>
              close
            </span>
          </button>
        </header>
      ) : null}

      {sortedPaths.length === 0 ? (
        <div className="flex-1 p-card-padding text-body-sm text-md-on-surface-variant">
          (이 대화에 생성된 산출물이 없습니다)
        </div>
      ) : (
        <ul className="flex-1 overflow-y-auto">
          {sortedPaths.map((p) => {
            const file = state.files[p];
            if (!file) return null;
            const origin = findOrigin(state, p);
            const isActive = p === activePath;
            const matchingReport = findMatchingReport(state.reports, p);
            return (
              <ArtifactRow
                key={p}
                path={p}
                file={file}
                origin={origin}
                report={matchingReport}
                expanded={isActive}
                onSelect={() => setDocPath(p)}
              />
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ─────────────────────── ArtifactRow ─────────────────────── */

type RowProps = {
  path: string;
  file: FileEntry;
  origin: { turnIndex: number; step?: Step } | null;
  /** 05 §6 — 동일 filename의 Reports API 항목. status='done' 시 다운로드 가능. */
  report: Report | null;
  expanded: boolean;
  onSelect: () => void;
};

/**
 * state.files의 path와 Reports API의 entry를 매칭.
 *
 * 매칭 규칙: 파일명이 `{kind}_report.md` 패턴이면 같은 `kind`의 Report 매칭.
 * 그 외 파일은 매칭 X (Reports API는 deep 그래프의 final/rag/web 보고서만 추적).
 */
function findMatchingReport(
  reports: Report[] | undefined,
  path: string,
): Report | null {
  if (!reports || reports.length === 0) return null;
  const basename = path.replace(/^\/+/, "").split("/").pop() ?? "";
  const m = basename.match(/^(rag|web|final)_report\.md$/i);
  if (!m || !m[1]) return null;
  const kind = m[1].toLowerCase() as "rag" | "web" | "final";
  // 같은 kind의 가장 최신 done 우선, 없으면 아무거나
  const candidates = reports.filter((r) => r.kind === kind);
  return (
    candidates.find((r) => r.status === "done") ?? candidates[0] ?? null
  );
}

function ArtifactRow({ path, file, origin, report, expanded, onSelect }: RowProps) {
  const text = getFileText(file);
  const filename = basenameOf(path);
  const size = formatBytes(file);
  const time = formatTime(file.modified_at ?? file.created_at ?? 0);
  const isStreaming = file.is_streaming ?? false;

  // 펼친 본문 자동 스크롤 (스트리밍 중 바닥 sticky)
  const bodyRef = useRef<HTMLDivElement>(null);
  const stickyBottomRef = useRef(true);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      stickyBottomRef.current = atBottom;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [expanded]);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    if (expanded && isStreaming && stickyBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [expanded, text, isStreaming]);

  return (
    <li
      className={`border-b border-md-outline-variant ${
        isStreaming ? "bg-md-surface-container-low" : "bg-md-surface-container-lowest"
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-expanded={expanded}
        className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-md-surface-container-low focus-visible:bg-md-surface-container-low"
      >
        <StatusIcon streaming={isStreaming} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <span className="material-symbols-outlined text-[14px] text-md-on-surface-variant" aria-hidden>
              article
            </span>
            <span className="truncate text-body-sm font-semibold text-md-on-surface">
              {filename}
            </span>
            {isStreaming ? (
              <span className="ml-1 rounded-pill bg-md-primary-fixed px-1.5 py-0.5 text-[10px] font-semibold text-md-on-primary-fixed-variant">
                작성 중
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 text-[11px] text-md-on-surface-variant">
            {size}
            {time ? ` · ${time}` : null}
            {origin ? ` · Turn ${origin.turnIndex}` : null}
          </div>
          {origin?.step ? (
            <div className="mt-0.5 flex items-center gap-1 text-[11px] text-md-on-surface-variant">
              <span
                className="material-symbols-outlined text-[12px]"
                aria-hidden
              >
                bolt
              </span>
              <span className="truncate">{origin.step.label}</span>
            </div>
          ) : null}
        </div>
        <span
          className={`material-symbols-outlined text-[16px] text-md-on-surface-variant transition-transform duration-[var(--motion-fast)] ${
            expanded ? "rotate-180" : ""
          }`}
          aria-hidden
        >
          expand_more
        </span>
      </button>

      {expanded ? (
        <div className="border-t border-md-outline-variant bg-md-surface-container-lowest">
          {!isStreaming ? (
            <DownloadButton path={path} text={text} report={report} />
          ) : null}
          <div ref={bodyRef} className="max-h-[60vh] overflow-y-auto p-card-padding">
            {text.trim() === "" ? (
              <p className="text-body-sm text-md-on-surface-variant">
                (빈 파일)
              </p>
            ) : (
              <MarkdownContent content={text} />
            )}
            {isStreaming ? (
              <span
                className="ml-1 inline-block h-4 w-0.5 align-middle bg-md-primary"
                style={{ animation: "md-pulse 0.8s ease-in-out infinite" }}
                aria-hidden
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  );
}

/* ─────────────────── 03 §11b 다운로드 버튼 ─────────────────── */

/**
 * 우선순위:
 *   1) `report.status === 'done'` → Reports API `/reports/{id}/download` 사용 (원본 .md, 인증 헤더)
 *   2) Reports API 매칭 없거나 미준비 → `state.files[path].content`를 메모리에서 Blob 변환해 다운로드
 *
 * 스트리밍 중인 파일은 caller가 본 컴포넌트를 마운트하지 않음 (불완전 다운로드 방지).
 */
function DownloadButton({
  path,
  text,
  report,
}: {
  path: string;
  text: string;
  report: Report | null;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const useReportsApi = report?.status === "done";
  const filename =
    (report?.title ? (report.title.endsWith(".md") ? report.title : `${report.title}.md`) : null) ??
    path.replace(/^\/+/, "").split("/").pop() ??
    "artifact";

  const onClick = async () => {
    setBusy(true);
    setError(null);
    try {
      if (useReportsApi && report) {
        await downloadReport(report);
      } else {
        downloadFromMemory(path, text);
      }
    } catch (e) {
      setError((e as Error).message || "다운로드 실패");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2 border-b border-md-outline-variant bg-md-surface-container-low px-3 py-2">
      <button
        type="button"
        onClick={() => void onClick()}
        disabled={busy}
        className="inline-flex items-center gap-1 rounded-button border border-md-outline-variant bg-md-surface-container-lowest px-3 py-1 text-body-sm text-md-on-surface hover:border-md-primary disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-[16px]" aria-hidden>
          download
        </span>
        {busy ? "다운로드 중…" : `${filename} 다운로드`}
      </button>
      {report?.kind ? (
        <span className="rounded-pill bg-md-secondary-fixed px-2 py-0.5 text-[11px] font-semibold text-md-on-secondary-fixed-variant">
          {report.kind}
        </span>
      ) : !useReportsApi ? (
        <span
          className="text-[11px] text-md-on-surface-variant"
          title="Reports API 미연결 — 본문 메모리에서 직접 다운로드"
        >
          local
        </span>
      ) : null}
      {error ? (
        <span className="text-[11px] text-md-error">{error}</span>
      ) : null}
    </div>
  );
}

function StatusIcon({ streaming }: { streaming: boolean }) {
  if (streaming) {
    return (
      <span
        className="mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-md-primary-fixed"
        aria-label="작성 중"
      >
        <span
          className="size-1.5 rounded-full bg-md-on-primary-fixed-variant"
          style={{ animation: "md-pulse 1.6s ease-in-out infinite" }}
          aria-hidden
        />
      </span>
    );
  }
  return (
    <span
      className="material-symbols-outlined mt-0.5 text-[16px] text-md-success"
      aria-label="생성 완료"
    >
      check_circle
    </span>
  );
}
