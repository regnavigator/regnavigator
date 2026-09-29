"use client";

/**
 * ReportPreviewDialog — 보고서 클릭 시 모달로 .md 본문 미리보기 + 다운로드.
 *
 * 단순화 규칙(2026-05-20 — "스크롤 개많고 화면 부족 시 잘림" 회신):
 *   1. **단일 본문 스크롤** — 다이얼로그 자체가 하나의 세로 flex 컨테이너.
 *      sticky 헤더 + flex-1 본문(overflow-y-auto) + sticky 푸터(다운로드).
 *      이전: 좌(보고서)·우(inspector) 두 영역 각각 overflow → nested 스크롤.
 *   2. **citation 클릭 = body swap** — 옆에 inspector를 붙여 다이얼로그 폭을
 *      키우는 대신 본문 자리를 그대로 inspector로 교체("← 보고서로" 버튼으로
 *      복귀). 모달 폭·높이가 처음과 동일하게 유지(이전 "처음과 똑같이" 요구
 *      만족) + 스크롤이 또 늘지 않음.
 *   3. **반응형 max-h** — `h-[85vh]` 고정 대신 `max-h-[90vh]` + 헤더/푸터만
 *      shrink-0. 작은 viewport에서도 dialog는 viewport 안으로 자연 축소되며
 *      본문이 잘리지 않음(스크롤로 흡수).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { MarkdownContent } from "@/components/chat/MarkdownContent";
import {
  CiteHighlightProvider,
  useCiteHighlight,
} from "@/components/chat/CiteHighlightContext";
import { CitationInspector } from "@/components/panel/CitationInspector";
import { getAuthToken } from "@/lib/client/authToken";
import { getEffectiveSettings } from "@/lib/store/settings";
import type { Citation, Report } from "@/lib/store/types";
import { deriveExternalUrl } from "@/lib/parse/lawLink";
import { citationLabel } from "@/lib/parse/citation";

const KIND_LABEL: Record<Report["kind"], string> = {
  rag: "법령 보고서",
  web: "웹·판례 보고서",
  final: "종합 보고서",
  doc: "서류",
};

const KIND_ICON: Record<Report["kind"], string> = {
  rag: "menu_book",
  web: "public",
  final: "summarize",
  doc: "edit_document",
};

/**
 * References 표시용 정렬 — number 기준 dedupe(첫 항목 유지) + 오름차순.
 * 백엔드 citations 배열 순서가 섞여 와도 [1][2][3]… 으로 통일.
 */
function sortedRefs(cites: Citation[]): Citation[] {
  const byNum = new Map<number, Citation>();
  for (const c of cites) {
    if (!byNum.has(c.number)) byNum.set(c.number, c);
  }
  return [...byNum.values()].sort((a, b) => a.number - b.number);
}

type Props = {
  report: Report | null;
  onClose: () => void;
};

export function ReportPreviewDialog({ report, onClose }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 보고서 본문에서 citation chip 클릭 시 — 본문 자리를 inspector로 *swap*.
  // null = 보고서 보기, 값 있음 = inspector 보기.
  const [citationId, setCitationId] = useState<string | null>(null);
  // PDF 다운로드 — `window.print()` 활용. printing=true면 hidden iframe portal로
  // 보고서 본문을 렌더링 + iframe 내부에서 print() 호출 → 브라우저 대화상자
  // "대상: PDF로 저장" 선택. 라이브러리 0개, FE만.
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    if (!report) {
      setContent(null);
      setError(null);
      setCitationId(null);
      setPrinting(false);
      return;
    }
    setLoading(true);
    setError(null);
    setCitationId(null);
    // 사용자 회신(2026-05-20) "보고서 결과 답변에 citation 링크가 안 달려있음" —
    // backend listReports 응답의 `citations` 필드가 실제로 채워져 오는지(또는
    // number 분포가 본문 `[n]` 마커와 일치하는지) 진단 로깅. 다음 보고서 생성 후
    // 콘솔에서 확인 가능. (production에서도 보여 사용자가 자기 콘솔로 점검 가능.)
    const cites = report.citations ?? [];
    const numbers = cites
      .map((c) => c.number)
      .filter((n): n is number => typeof n === "number")
      .sort((a, b) => a - b);
    console.info(
      `[ReportPreviewDialog] citations: ${cites.length}건 · number=[${numbers.join(",")}] · report=${report.id.slice(0, 8)}`,
    );
    void (async () => {
      try {
        const text = await fetchReportMd(report.id);
        setContent(text);
        // 본문 안 [n] 마커 분포 — citations와 매칭되지 않는 번호가 있으면 chip
        // 미달림 회귀 신호. 둘이 모두 채워져 있는데 chip이 안 보이면 chip 렌더
        // 자체 회귀(MarkdownContent).
        const markers = Array.from(text.matchAll(/\[(\d+)\]/g))
          .map((m) => Number(m[1]))
          .filter((n) => !Number.isNaN(n));
        const unique = Array.from(new Set(markers)).sort((a, b) => a - b);
        const missing = unique.filter((n) => !numbers.includes(n));
        console.info(
          `[ReportPreviewDialog] body markers: ${markers.length}개 · unique=[${unique.join(",")}]` +
            (missing.length > 0
              ? ` · ⚠ citations에 없는 번호=[${missing.join(",")}]`
              : ""),
        );
      } catch (err) {
        console.warn("[ReportPreviewDialog] fetch failed", err);
        setError("본문을 불러오지 못했습니다.");
      } finally {
        setLoading(false);
      }
    })();
  }, [report]);

  const cleanContent = useMemo(() => {
    if (!content) return "";
    const [main] = content.split(/^(?:##|###)\s*(?:참고\s*문헌|참고\s*자료|References?|출처)\b/im);
    return main?.trim() ?? "";
  }, [content]);

  if (!report) return null;

  const downloadFromContent = () => {
    if (!content) return;
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report.title ?? report.kind}_${report.id.slice(0, 8)}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const inInspector = !!citationId;
  // 보고서 본문 고정 너비 — inspector 토글에도 *변하지 않음*(사용자 회신 "처음과
  //   똑같이 유지, 글 간격 달라지면 보기 안좋음"). citation 열리면 다이얼로그가
  //   inspector 폭만큼 *추가 확장*만 하고 보고서 영역은 그대로.
  const REPORT_W = "w-[min(92vw,940px)]";

  return (
    <Dialog open={!!report} onOpenChange={(o) => (!o ? onClose() : null)}>
      {/* `dvh` 단위로 viewport 변화(devtools 열기·모바일 주소창 collapse 등) 동적 추종.
          inspector 열리면 폭만 확장(보고서 너비 고정). */}
      <DialogContent
        className={
          "flex max-h-[calc(100dvh-2rem)] max-w-none flex-col gap-0 border border-md-outline-variant bg-md-surface p-0 text-md-on-surface shadow-xl " +
          (inInspector ? "w-[min(96vw,1380px)]" : "w-[min(92vw,940px)]")
        }
      >
        {/* 헤더 — 항상 보고서 헤더(아이콘+제목+다운로드). 출처는 우측 사이드로
            붙으므로 헤더 전환 없음. */}
        <DialogHeader className="flex shrink-0 flex-row items-center gap-3 space-y-0 border-b border-md-outline-variant px-6 py-4">
          <span
            aria-hidden
            className="material-symbols-outlined shrink-0 text-[24px] text-md-primary"
          >
            {KIND_ICON[report.kind]}
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <DialogTitle className="truncate text-[18px] font-semibold leading-snug text-md-on-surface">
              {report.title ?? KIND_LABEL[report.kind]}
            </DialogTitle>
            <span className="truncate text-[12px] text-md-on-surface-variant">
              {KIND_LABEL[report.kind] +
                (report.completed_at ? ` · ${formatDate(report.completed_at)}` : "")}
            </span>
          </div>
          {/* 다운로드 — PDF(브라우저 print) + .md */}
          <div className="mr-9 flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setPrinting(true)}
              disabled={!content || loading || printing}
              aria-label="PDF 다운로드"
              title="PDF 다운로드 (브라우저 '대상: PDF로 저장' 선택)"
              className="inline-flex h-9 items-center gap-1.5 rounded-full border border-md-outline-variant px-4 text-[12.5px] font-medium text-md-on-surface transition-colors hover:border-md-on-surface hover:bg-md-surface-container-low disabled:opacity-40"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden>
                picture_as_pdf
              </span>
              <span className="hidden sm:inline">PDF</span>
            </button>
            <button
              type="button"
              onClick={downloadFromContent}
              disabled={!content || loading}
              aria-label=".md 다운로드"
              title="원본 markdown 다운로드 (.md)"
              className="inline-flex h-9 items-center gap-1.5 rounded-full border border-md-outline-variant px-4 text-[12.5px] font-medium text-md-on-surface transition-colors hover:border-md-on-surface hover:bg-md-surface-container-low disabled:opacity-40"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden>
                download
              </span>
              <span className="hidden sm:inline">.md</span>
            </button>
          </div>
        </DialogHeader>

        {/* 본문 — 좌(보고서, 고정 너비) + 우(출처 사이드, citation 클릭 시).
            출처가 보고서를 *덮지 않고 옆에 붙음*(사용자 회신 "사이드로 뜨게,
            새로뜨게하면 어떡하냐"). 좌우 각자 overflow 1회씩. */}
        <CiteHighlightProvider>
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className={REPORT_W + " shrink-0 overflow-y-auto px-6 py-6"}>
            {loading ? (
              <div className="flex h-full items-center justify-center py-12 text-md-on-surface-variant">
                <span
                  className="material-symbols-outlined animate-spin text-[24px]"
                  aria-hidden
                >
                  progress_activity
                </span>
              </div>
            ) : error ? (
              <div className="flex h-full items-center justify-center py-12 text-body-sm text-md-error">
                {error}
              </div>
            ) : content ? (
              <div className="flex flex-col gap-8">
                <MarkdownContent
                  content={cleanContent}
                  citations={report.citations ?? []}
                  onCitationClick={(id) =>
                    setCitationId((prev) => (prev === id ? null : id))
                  }
                />
                {/* Beautiful custom references section at the bottom */}
                {report.citations && report.citations.length > 0 && (
                  <div className="mt-8 border-t border-md-outline-variant pt-8">
                    <div className="flex items-center gap-2 mb-6">
                      <span className="material-symbols-outlined text-[20px] text-md-primary" aria-hidden>
                        menu_book
                      </span>
                      <h3 className="text-[15.5px] font-semibold text-md-on-surface">
                        참고자료 및 출처 (References)
                      </h3>
                    </div>
                    <ul className="flex flex-col gap-4">
                      {sortedRefs(report.citations).map((c) => (
                        <ReportReferenceItem key={c.id} citation={c} />
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : null}
          </div>
          {inInspector ? (
            <aside
              aria-label="출처"
              className="flex min-h-0 w-[420px] shrink-0 flex-col overflow-hidden border-l border-md-outline-variant bg-md-surface-container-lowest"
            >
              <CitationInspector
                citationId={citationId!}
                citationsOverride={report.citations ?? []}
                onClose={() => setCitationId(null)}
                onSelectCitation={(id) => setCitationId(id || null)}
              />
            </aside>
          ) : null}
        </div>
        </CiteHighlightProvider>
      </DialogContent>
      {printing && content ? (
        <PrintFrame
          title={report.title ?? KIND_LABEL[report.kind]}
          content={content}
          citations={report.citations ?? []}
          completedAt={report.completed_at}
          onClose={() => setPrinting(false)}
        />
      ) : null}
    </Dialog>
  );
}

/**
 * 보고서 References 항목 — 본문 칩과 상호 하이라이트.
 *  - hover → 본문 같은 번호 [n] 칩 강조 + 항목 자체 강조
 *  - click(항목 여백) → 본문 첫 해당 칩으로 스크롤 + pulse. (제목 링크 클릭은
 *    stopPropagation으로 원문 새 탭 열기 유지)
 */
function ReportReferenceItem({ citation: c }: { citation: Citation }) {
  const { hovered, setHovered, scrollTo } = useCiteHighlight();
  const url = deriveExternalUrl(c);
  const label = citationLabel(c);
  const isRevoked = c.status === "revoked";
  return (
    <li
      onMouseEnter={() => setHovered(c.number)}
      onMouseLeave={() => setHovered(null)}
      onClick={() => scrollTo(c.number)}
      className={
        "flex cursor-pointer items-start gap-3 rounded-md px-2 py-1 text-[13px] leading-relaxed text-md-on-surface-variant transition-colors duration-200 ease-out " +
        (hovered === c.number ? "bg-md-primary-container/40" : "")
      }
    >
      <span className="shrink-0 font-mono font-bold text-md-primary w-7 text-right select-none">
        [{c.number}]
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          {url ? (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className={`font-semibold hover:underline inline-flex items-center gap-1 leading-snug transition-colors duration-150 ${
                isRevoked ? "text-md-error line-through" : "text-md-secondary hover:text-md-primary"
              }`}
            >
              {c.title}
              <span className="material-symbols-outlined text-[13px] text-md-on-surface-variant no-underline">
                north_east
              </span>
            </a>
          ) : (
            <span className={`font-semibold leading-snug ${isRevoked ? "line-through text-md-error" : "text-md-on-surface"}`}>
              {c.title}
            </span>
          )}
          <span className="inline-flex items-center rounded-pill bg-md-surface-container px-1.5 py-0.5 text-[10.5px] font-medium text-md-on-surface-variant select-none">
            {label}
          </span>
        </div>
        {(c.publisher || c.date || c.article || typeof c.page === "number") && (
          <p className="mt-1 text-[11.5px] text-md-on-surface-variant">
            {[
              c.publisher,
              c.date,
              c.article,
              typeof c.page === "number" ? `p.${c.page}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        )}
      </div>
    </li>
  );
}

/**
 * 보고서 본문을 hidden iframe에 portal로 렌더하고 `window.print()` 호출 →
 * 브라우저 대화상자 "대상: PDF로 저장" 선택 시 PDF 파일로 저장. afterprint
 * 이벤트(또는 dialog 자체 종료)로 onClose 호출 → 상위에서 printing=false.
 *
 * 의존성 0 — `react-dom/createPortal`만(기본 react-dom). 한국어 폰트는 OS 기본
 * 사용(별도 임베딩 X). chip은 iframe 안에 그대로 button으로 렌더되지만 print
 * media에선 background/border가 약하게 표시되도록 inline `@media print` 규칙.
 */
function PrintFrame({
  title,
  content,
  citations,
  completedAt,
  onClose,
}: {
  title: string;
  content: string;
  citations: Citation[];
  completedAt?: string | null;
  onClose: () => void;
}) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const win = iframe.contentWindow;
    const doc = iframe.contentDocument;
    if (!win || !doc) return;

    // base HTML skeleton — body에 React가 portal로 컨텐츠 주입.
    doc.open();
    doc.write(
      `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8" />` +
        `<title>${escapeHtml(title)}</title>` +
        `<style>${PRINT_CSS}</style>` +
        `</head><body><div id="root"></div></body></html>`,
    );
    doc.close();
    setReady(true);

    const afterPrint = () => onClose();
    win.addEventListener("afterprint", afterPrint);
    return () => {
      win.removeEventListener("afterprint", afterPrint);
    };
  }, [title, onClose]);

  // ready=true가 되면 짧은 tick 후 print() 호출 — React가 portal 렌더 완료할 시간.
  useEffect(() => {
    if (!ready) return;
    const iframe = iframeRef.current;
    if (!iframe?.contentWindow) return;
    const t = window.setTimeout(() => {
      iframe.contentWindow?.focus();
      iframe.contentWindow?.print();
    }, 150);
    return () => window.clearTimeout(t);
  }, [ready]);

  const target = ready
    ? iframeRef.current?.contentDocument?.getElementById("root")
    : null;

  return (
    <>
      <iframe
        ref={iframeRef}
        title="보고서 인쇄 미리보기"
        aria-hidden
        style={{
          position: "fixed",
          right: 0,
          bottom: 0,
          width: 0,
          height: 0,
          border: 0,
          visibility: "hidden",
        }}
      />
      {target
        ? createPortal(
            <PrintBody
              title={title}
              content={content}
              citations={citations}
              completedAt={completedAt}
            />,
            target,
          )
        : null}
    </>
  );
}

function PrintBody({
  title,
  content,
  citations,
  completedAt,
}: {
  title: string;
  content: string;
  citations: Citation[];
  completedAt?: string | null;
}) {
  const cleanContent = useMemo(() => {
    if (!content) return "";
    const [main] = content.split(/^(?:##|###)\s*(?:참고\s*문헌|참고\s*자료|References?|출처)\b/im);
    return main?.trim() ?? "";
  }, [content]);

  return (
    <article className="print-report">
      <header className="print-header">
        <h1>{title}</h1>
        {completedAt ? (
          <p className="print-meta">생성: {formatDate(completedAt)}</p>
        ) : null}
      </header>
      <MarkdownContent content={cleanContent} citations={citations} />
      {citations && citations.length > 0 && (
        <div className="print-references" style={{ marginTop: "10mm", borderTop: "1pt solid #aaa", paddingTop: "5mm" }}>
          <h2 style={{ fontSize: "12pt", fontWeight: 600, marginBottom: "4mm" }}>참고자료 및 출처 (References)</h2>
          <ul style={{ listStyleType: "none", paddingLeft: 0, margin: 0 }}>
            {sortedRefs(citations).map((c) => {
              const url = deriveExternalUrl(c);
              const isRevoked = c.status === "revoked";
              return (
                <li key={c.id} style={{ fontSize: "9.5pt", marginBottom: "3mm", display: "flex", gap: "3mm" }}>
                  <span style={{ fontWeight: "bold", color: "#0a58ca", width: "8mm", textAlign: "right" }}>[{c.number}]</span>
                  <div>
                    {url ? (
                      <a href={url} target="_blank" rel="noopener noreferrer" style={{ fontWeight: 600, color: "#0a58ca", textDecoration: isRevoked ? "line-through" : "underline" }}>
                        {c.title}
                      </a>
                    ) : (
                      <span style={{ fontWeight: 600, textDecoration: isRevoked ? "line-through" : undefined }}>{c.title}</span>
                    )}
                    <span style={{ marginLeft: "2mm", color: "#555", fontSize: "8.5pt" }}>
                      {[
                        c.publisher,
                        c.date,
                        c.article,
                        typeof c.page === "number" ? `p.${c.page}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </article>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * 인쇄용 스타일 — iframe 안에서만 적용. 기본 시스템 한글 폰트(`Apple SD
 * Gothic Neo`/`맑은 고딕`/`Noto Sans KR` 폴백)를 사용. citation button은
 * 인쇄 media에서 *작은 윗첨자 [n]*으로 변환(클릭 없는 인쇄물 정합).
 */
const PRINT_CSS = `
  :root { color-scheme: light; }
  html, body { margin: 0; padding: 0; background: #fff; color: #111; }
  body {
    font-family: "Pretendard", "Apple SD Gothic Neo", "맑은 고딕",
      "Malgun Gothic", "Noto Sans KR", system-ui, -apple-system, sans-serif;
    font-size: 11pt;
    line-height: 1.7;
    word-break: keep-all;
    overflow-wrap: anywhere;
  }
  .print-report { padding: 16mm 14mm; max-width: 100%; }
  .print-header { border-bottom: 1pt solid #999; margin-bottom: 8mm; padding-bottom: 4mm; }
  .print-header h1 { font-size: 18pt; font-weight: 700; margin: 0 0 2mm 0; }
  .print-meta { font-size: 9pt; color: #555; margin: 0; }
  h1, h2, h3, h4 { line-height: 1.35; page-break-after: avoid; }
  h1 { font-size: 16pt; margin-top: 10mm; }
  h2 { font-size: 14pt; margin-top: 8mm; }
  h3 { font-size: 12pt; margin-top: 6mm; }
  p, li { orphans: 3; widows: 3; }
  ul, ol { padding-left: 6mm; }
  table { border-collapse: collapse; width: 100%; margin: 4mm 0; }
  th, td { border: 0.5pt solid #aaa; padding: 1.5mm 2mm; text-align: left; vertical-align: top; }
  th { background: #f3f3f3; font-weight: 600; }
  code { font-family: ui-monospace, Consolas, monospace; background: #f5f5f5; padding: 0 1mm; border-radius: 1mm; font-size: 10pt; }
  pre { background: #f5f5f5; padding: 3mm; border-radius: 1mm; overflow-x: auto; }
  blockquote { border-left: 2pt solid #999; padding-left: 4mm; color: #444; margin: 3mm 0; }
  /* citation chip — CitationChip의 aria-label은 "{카테고리} 출처 [n] …" 형식.
     인쇄용으로 작은 윗첨자 chip(카테고리 한글 라벨 + [n])로 정합. 클릭 X, color
     약간. 카테고리 라벨은 평문이라 인쇄 안전. */
  button[aria-label*="출처 ["] {
    display: inline !important;
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    margin: 0 0.5pt !important;
    font-size: 0.78em !important;
    color: #0a58ca !important;
    vertical-align: super !important;
    line-height: 1 !important;
    cursor: default !important;
  }
  a { color: #0a58ca; text-decoration: underline; }
  @page { size: A4; margin: 12mm; }
`;

async function fetchReportMd(reportId: string): Promise<string> {
  const base = getEffectiveSettings().deployment_url?.replace(/\/$/, "");
  if (!base) throw new Error("deployment_url 미설정");
  const token = getAuthToken();
  const headers: Record<string, string> = { Accept: "text/markdown" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(
    `${base}/reports/${encodeURIComponent(reportId)}/download`,
    { headers },
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
