"use client";

/**
 * ReportCardGroup — deep report 3편 완료 후 표시되는 카드 묶음.
 * 각 카드에 다운로드(.docx/.md) + 👍/👎 피드백.
 *
 * - state.reports 중 status=="done"만 표시
 * - kind별 한국어 라벨
 * - download: lib/client/reports.downloadReport — `?format=docx|md`, 폴백 대비
 *   응답 헤더의 실제 포맷 신뢰. blob 30일 만료 시 배지 + 버튼 비활성(409 안내).
 */

import { useMemo, useState } from "react";
import { toast } from "sonner";
import type { Report } from "@/lib/store/types";
import { FeedbackButtons } from "@/components/chat/FeedbackButtons";
import { ReportPreviewDialog } from "@/components/chat/ReportPreviewDialog";
import {
  deleteReport,
  downloadReport,
  isReportExpired,
  type ReportFormat,
} from "@/lib/client/reports";

const KIND_LABEL: Record<Report["kind"], string> = {
  rag: "법령 벡터 검색 보고서",
  web: "웹·판례 통합 검색 보고서",
  final: "최종 종합 보고서",
  doc: "서류", // 목록에선 걸러지지만 타입 완전성 유지
};

const KIND_ICON: Record<Report["kind"], string> = {
  rag: "menu_book",
  web: "public",
  final: "summarize",
  doc: "edit_document",
};

const KIND_ORDER: Record<Report["kind"], number> = {
  final: 0,
  rag: 1,
  web: 2,
  doc: 9,
};

type Props = {
  reports: Report[];
};

export function ReportCardGroup({ reports }: Props) {
  const [preview, setPreview] = useState<Report | null>(null);
  // 삭제 낙관 반영 — API 성공 즉시 카드 제거(다음 폴링에서 DB 삭제로 확정).
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());
  const done = useMemo(
    () =>
      reports
        // "doc" = 서류 — 보고서 카드가 아니다(문서 패널 진입 카드가 따로 있다).
        // 종전엔 kind="final" 로 저장돼 "최종 종합 보고서"로 떴다(실사용 지적).
        .filter(
          (r) => r.status === "done" && r.kind !== "doc" && !deletedIds.has(r.id),
        )
        .sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9)),
    [reports, deletedIds],
  );

  const handleDelete = async (r: Report) => {
    // confirm — 삭제는 복구 불가(전문 blob 도 지움). 실수 클릭 방지 최소 장치.
    if (!window.confirm(`'${r.title ?? KIND_LABEL[r.kind]}' 보고서를 삭제할까요?
삭제하면 되돌릴 수 없어요.`)) return;
    try {
      await deleteReport(r.id);
      setDeletedIds((prev) => new Set([...prev, r.id]));
      toast.success("보고서를 삭제했어요.");
    } catch {
      toast.error("삭제하지 못했어요. 잠시 후 다시 시도해 주세요.");
    }
  };

  if (done.length === 0) return null;

  // 가장 최근 완료된 보고서의 completed_at — 푸터에 "마지막 업데이트" 시각 노출
  const lastCompletedAt = done
    .map((r) => r.completed_at)
    .filter((t): t is string => !!t)
    .sort()
    .pop();

  return (
    <section
      aria-label="심층 보고서"
      className="border-y border-md-outline-variant"
    >
      <ul className="divide-y divide-md-outline-variant border-t border-md-outline-variant">
        {done.map((r) => (
          <ReportCard key={r.id} report={r} onPreview={() => setPreview(r)}
                      onDelete={() => void handleDelete(r)} />
        ))}
      </ul>
      {/* 리스트 끝 — sticky bottom-0으로 scroll container viewport 하단에 항상 고정.
          사용자가 스크롤 어디 있든 "총 N건 / 마지막 업데이트"가 보임. */}
      <footer
        aria-label="목록 끝"
        className="sticky bottom-0 z-10 flex flex-wrap items-center justify-center gap-x-2 gap-y-0.5 border-t border-md-outline-variant bg-md-surface-container-lowest px-3 py-2 text-[11px] text-md-on-surface-variant backdrop-blur-sm"
      >
        <span className="font-semibold">
          목록 끝
        </span>
        <span aria-hidden>·</span>
        <span>총 {done.length}건</span>
        {lastCompletedAt ? (
          <>
            <span aria-hidden>·</span>
            <span>마지막 업데이트 {formatTime(lastCompletedAt)}</span>
          </>
        ) : null}
      </footer>
      <ReportPreviewDialog report={preview} onClose={() => setPreview(null)} />
    </section>
  );
}

function ReportCard({
  report,
  onPreview,
  onDelete,
}: {
  report: Report;
  onPreview: () => void;
  /** 삭제(2026-08-27) — 확인은 호출자(handleDelete)가 한다. */
  onDelete: () => void;
}) {
  const [downloading, setDownloading] = useState<ReportFormat | null>(null);
  // blob 보존 30일 경과 — 메타·인용은 남지만 전문 다운로드 불가(409)
  const expired = isReportExpired(report);

  const onDownload = async (format: ReportFormat) => {
    if (downloading) return;
    setDownloading(format);
    try {
      await downloadReport(report, format);
    } catch (err) {
      console.error("[ReportCard] download failed", err);
      const status = (err as Error & { status?: number }).status;
      toast.error(
        status === 409
          ? "보고서 전문 보관기간(30일)이 지나 다운로드할 수 없습니다."
          : "다운로드에 실패했습니다. 잠시 후 다시 시도해주세요.",
        { duration: 6000 },
      );
    } finally {
      setDownloading(null);
    }
  };

  return (
    <li className="group/report flex items-start gap-3 px-2 py-3 transition-colors hover:bg-md-surface-container-low">
      <button
        type="button"
        onClick={onPreview}
        className="flex min-w-0 flex-1 items-start gap-3 text-left"
        aria-label={`${report.title || KIND_LABEL[report.kind]} 미리보기`}
      >
        <span
          className="material-symbols-outlined mt-0.5 text-[20px] text-md-on-surface-variant transition-colors duration-200 ease-out group-hover/report:text-md-primary"
          aria-hidden
        >
          {KIND_ICON[report.kind]}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="text-body-sm font-medium text-md-on-surface transition-colors duration-200 ease-out group-hover/report:text-md-primary">
            {report.title || KIND_LABEL[report.kind]}
          </span>
          <span className="text-[11px] text-md-on-surface-variant">
            {KIND_LABEL[report.kind]}
            {report.completed_at ? ` · ${formatTime(report.completed_at)}` : ""}
            {expired ? (
              <span className="ml-1 text-md-error">· 전문 만료(30일 경과)</span>
            ) : null}
          </span>
          {report.summary ? (
            <span
              className="line-clamp-2 text-[12.5px] leading-snug text-md-on-surface-variant"
              style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
            >
              {report.summary}
            </span>
          ) : null}
        </div>
      </button>
      {/* trailing 액션 — 평소엔 숨고 hover 시 fade in. 미리보기 chevron으로 affordance. */}
      <div
        className="flex shrink-0 items-center gap-1 opacity-60 transition-opacity duration-200 ease-out group-hover/report:opacity-100 group-focus-within/report:opacity-100"
        onClick={(e) => e.stopPropagation()}
      >
        <FeedbackButtons kind="report" reportId={report.id} />
        <button
          type="button"
          onClick={() => void onDownload("docx")}
          disabled={downloading !== null || expired}
          aria-label="Word 다운로드 (.docx)"
          title={expired ? "전문 만료(30일 경과)" : "Word 다운로드 (.docx)"}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface disabled:opacity-40"
        >
          <span
            className={
              "material-symbols-outlined text-[16px] " +
              (downloading === "docx" ? "animate-spin" : "")
            }
            aria-hidden
          >
            {downloading === "docx" ? "progress_activity" : "docs"}
          </span>
        </button>
        <button
          type="button"
          onClick={() => void onDownload("md")}
          disabled={downloading !== null || expired}
          aria-label="Markdown 다운로드 (.md)"
          title={expired ? "전문 만료(30일 경과)" : "Markdown 다운로드 (.md)"}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface disabled:opacity-40"
        >
          <span
            className={
              "material-symbols-outlined text-[16px] " +
              (downloading === "md" ? "animate-spin" : "")
            }
            aria-hidden
          >
            {downloading === "md" ? "progress_activity" : "download"}
          </span>
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label="보고서 삭제"
          title="보고서 삭제 (복구 불가)"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-md-on-surface-variant transition-colors hover:bg-md-error-container hover:text-md-on-error-container"
        >
          <span className="material-symbols-outlined text-[16px]" aria-hidden>
            delete
          </span>
        </button>
        <span
          className="material-symbols-outlined text-[16px] text-md-on-surface-variant opacity-0 transition-opacity duration-200 ease-out group-hover/report:opacity-100"
          aria-hidden
        >
          chevron_right
        </span>
      </div>
    </li>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}
