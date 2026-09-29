"use client";

/**
 * CitationFootnotes — 03 §5.2.
 *
 * 답변 본문 아래 References 박스. 0개면 *박스 자체 미렌더* (04 §4.1).
 * StepCarousel과 같은 한-칸 carousel 패턴 — 화면 점유 최소화.
 *  - 헤더: 출처 N건 + (펼친 상태에서) 카운터/`<`/`>` + chevron
 *  - 펼침 본문: 한 항목만 표시. 사용자가 nav로 탐색.
 */

import { citationKindCounts } from "@/components/chat/MarkdownContent";
import { useCallback, useState } from "react";
import type { Citation } from "@/lib/store/types";
import { deriveExternalUrl, externalUrlKind } from "@/lib/parse/lawLink";
import { normalizeMetaField } from "@/lib/parse/citation";
import { useRightPanel } from "@/lib/store/rightPanel";
import { CitationEvidenceTooltip } from "@/components/chat/CitationEvidenceTooltip";
import { BookmarkButton } from "@/components/chat/BookmarkButton";
import { useCiteHighlight } from "@/components/chat/CiteHighlightContext";

type Props = {
  citations: Citation[];
};

export function CitationFootnotes({ citations }: Props) {
  const {
    citation: activeCitation,
    setCitation,
    open: rpOpen,
    setOpen: setRpOpen,
  } = useRightPanel();
  const { hovered, setHovered, scrollTo } = useCiteHighlight();
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);

  const onInspect = useCallback(
    (id: string) => {
      if (id && id === activeCitation) {
        setRpOpen(!rpOpen);
      } else {
        setCitation(id || null);
        setRpOpen(true);
      }
    },
    [activeCitation, setCitation, rpOpen, setRpOpen],
  );

  if (!citations || citations.length === 0) return null;

  const safeIndex = Math.min(index, citations.length - 1);
  const c = citations[safeIndex]!;
  const isFirst = safeIndex === 0;
  const isLast = safeIndex === citations.length - 1;
  const showNav = citations.length > 1;
  const goPrev = () => {
    if (isFirst) return;
    setIndex((i) => Math.max(0, i - 1));
  };
  const goNext = () => {
    if (isLast) return;
    setIndex((i) => Math.min(citations.length - 1, i + 1));
  };
  const goFirst = () => setIndex(0);

  // 취소선 — 폐지본과 구법(개정으로 대체된 옛 조문) 둘 다. 시행 전 조문은
  // 아직 유효해질 예정이므로 취소선을 긋지 않는다(배지로만 구분).
  const isRevoked = c.status === "revoked" || c.effective_status === "구법";
  // 현행성 배지 — active(현행)는 기본 가정이라 미표시, 경고성만 노출.
  //
  // 2026-09-10: `effective_status`/`version_status` 를 함께 본다. 종전엔 `status`
  // (active|revoked|amended_pending)만 봐서 **시행 전 조문**을 현행처럼 보여줬다 —
  // 공포됐지만 시행일이 안 온 조문(enforced=false)은 폐지와도, 개정 예정과도 다르고,
  // 그걸 근거로 지금 움직이면 실무에서 틀린다. 배지는 인용 패널에만 있었고
  // (CitationInspector) 목록에는 없어, 패널을 열지 않으면 알 수 없었다.
  const statusBadge =
    c.status === "revoked" || c.effective_status === "구법"
      ? {
          label: c.effective_status === "구법" ? "구법" : "폐지",
          cls: "bg-md-error/10 text-md-error",
        }
      : c.effective_status === "미시행" || c.enforced === false
        ? { label: "시행 전", cls: "bg-md-tertiary/15 text-md-tertiary" }
        : c.version_status === "pending" || c.status === "amended_pending"
          ? { label: "개정 예정", cls: "bg-md-tertiary/15 text-md-tertiary" }
          : null;
  // 별표/서식 인용 — HWP/PDF 원본 다운로드(download_url) 강조 + 칩으로 구분.
  const isAnnex =
    c.doc_category === "법령별표서식" ||
    c.doc_category === "행정규칙별표서식" ||
    c.doc_category === "자치법규별표서식";
  const downloadUrl = c.download_url;
  const externalUrl = deriveExternalUrl(c);
  const externalKind = externalUrl ? externalUrlKind(c, externalUrl) : null;
  const externalLabel =
    externalKind === "law-portal" ? "법령정보센터에서 보기" : "원문 새 탭에서 열기";
  const titleStr = normalizeMetaField(c.title);
  const publisherStr = normalizeMetaField(c.publisher);
  const articleStr = normalizeMetaField(c.article);
  const dateStr = normalizeMetaField(c.date);

  return (
    <aside
      aria-label="References"
      className="mt-2 overflow-hidden rounded-card border border-md-outline-variant bg-md-surface-container-low transition-shadow duration-200 ease-out hover:shadow-sm"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={
          "flex w-full items-center gap-2 rounded-card px-3 py-2 text-left transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container " +
          (open ? "border-b border-md-outline-variant" : "")
        }
      >
        <span
          className="material-symbols-outlined text-[14px] text-md-on-surface-variant"
          aria-hidden
        >
          format_quote
        </span>
        <span className="text-label-caps text-md-on-surface-variant">
          출처 {citations.length}건
        </span>
        {/* 종별 색 범례(2026-09-08) — 본문 칩 색과 같은 표. 실제 등장한 종별만.
            2026-09-10: **건수를 함께** 표시한다. 종전엔 색 범례뿐이라 "무엇으로
            답했는지"가 안 보였다. 특히 R&D·정부과제처럼 법령 코퍼스 밖 주제는
            근거가 사실상 웹인데 사용자는 그걸 알 수 없었다 — "법령 7 · 웹 2" 로
            드러나면 답변의 성격과 한계를 스스로 판단할 수 있다.
            aria-hidden 을 뗀다: 종전엔 스크린리더에서 통째로 사라졌는데, 이제
            장식이 아니라 정보다. */}
        <span className="ml-2 hidden items-center gap-2 text-[11px] text-md-on-surface-variant sm:inline-flex">
          {citationKindCounts(citations).map((k) => (
              <span key={k.label} className="inline-flex items-center gap-1">
                {/* 견본 = 본문 칩과 같은 클래스(배경·글자색) + 글자색 테두리 — 연한 배경만으론 안 보였다(2026-09-21) */}
                <span
                  className={`inline-block size-3 rounded-[3px] ring-[1.5px] ring-inset ring-current/70 ${k.cls}`}
                  aria-hidden
                />
                {k.label} <span className="tabular-nums">{k.n}</span>
              </span>
            ))}
        </span>
        {showNav && open ? (
          <>
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                goFirst();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.stopPropagation();
                  goFirst();
                }
              }}
              title="처음 출처로"
              aria-label="처음 출처로"
              className="ml-auto rounded-pill bg-md-surface-container px-2 py-0.5 font-mono text-[11px] text-md-on-surface-variant hover:bg-md-surface-container-high"
            >
              {safeIndex + 1}/{citations.length}
            </span>
            <NavBtn dir="prev" disabled={isFirst} onClick={goPrev} />
            <NavBtn dir="next" disabled={isLast} onClick={goNext} />
          </>
        ) : null}
        <span
          className={
            "material-symbols-outlined text-[16px] text-md-on-surface-variant transition-transform duration-300 ease-out " +
            (showNav && open ? "" : "ml-auto") +
            (open ? " rotate-180" : "")
          }
          aria-hidden
        >
          expand_more
        </span>
      </button>

      {/* 부드러운 펼침/닫힘 — grid-rows trick으로 height auto에도 transition 적용 */}
      <div
        className={
          "grid transition-[grid-template-rows] duration-300 ease-out " +
          (open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")
        }
      >
        <div className="overflow-hidden">
          <div
            className={
              "px-3 py-3 transition-colors duration-200 ease-out " +
              (hovered === c.number ? "bg-md-primary-container/40" : "")
            }
            onMouseEnter={() => setHovered(c.number)}
            onMouseLeave={() => setHovered(null)}
          >
          <div className="flex min-w-0 items-start gap-2">
            {/* [N] 근거 팝오버 — 인스펙터 버튼 밖 sibling. quote 없으면 비대화 마커
                (button 안 button/a 중첩·클릭 충돌 방지). 출처 링크는 우측 아이콘. */}
            <CitationEvidenceTooltip citation={c}>
              <span
                className={`shrink-0 pt-px text-[13px] font-semibold text-md-primary ${
                  isRevoked ? "line-through" : ""
                }`}
              >
                [{c.number}]
              </span>
            </CitationEvidenceTooltip>
            <button
              type="button"
              onClick={() => {
                // 본문 해당 칩으로 스크롤 + pulse, 그리고 인스펙터 오픈(기존 동작 유지).
                scrollTo(c.number);
                onInspect(c.id);
              }}
              aria-label={`인용 [${c.number}] ${titleStr} 인스펙터 열기`}
              className="flex min-w-0 flex-1 flex-col gap-1.5 text-left"
            >
              <span
                className={`min-w-0 truncate leading-snug ${
                  isRevoked ? "line-through" : ""
                }`}
                title={titleStr}
              >
                {titleStr}
              </span>
              {(statusBadge || isAnnex) && (
                <span className="flex flex-wrap items-center gap-1">
                  {isAnnex ? (
                    <span className="rounded-pill bg-md-secondary-fixed px-1.5 py-0.5 text-[10px] font-medium text-md-on-secondary-fixed-variant">
                      별표/서식
                    </span>
                  ) : null}
                  {statusBadge ? (
                    <span
                      className={`inline-flex items-center gap-0.5 rounded-pill px-1.5 py-0.5 text-[10px] font-medium ${statusBadge.cls}`}
                    >
                      <span className="material-symbols-outlined text-[11px]" aria-hidden>
                        warning
                      </span>
                      {statusBadge.label}
                    </span>
                  ) : null}
                </span>
              )}
              {(publisherStr || dateStr || articleStr || typeof c.page === "number") && (
                <span className="flex flex-wrap gap-x-1.5 gap-y-0.5 text-[11.5px] leading-snug text-md-on-surface-variant">
                  {publisherStr ? <span>{publisherStr}</span> : null}
                  {dateStr ? <span aria-hidden>· {dateStr}</span> : null}
                  {articleStr ? <span aria-hidden>· {articleStr}</span> : null}
                  {typeof c.page === "number" ? <span aria-hidden>· p.{c.page}</span> : null}
                </span>
              )}
              {c.snippet ? (
                <span
                  className="block overflow-hidden text-[12px] leading-relaxed text-md-on-surface-variant"
                  style={{
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                  }}
                  title={c.snippet}
                >
                  “{c.snippet}”
                </span>
              ) : null}
            </button>
            <BookmarkButton citation={c} />
            {downloadUrl && (
              <a
                href={downloadUrl}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="별표/서식 원본 내려받기 (HWP/PDF)"
                title="별표/서식 원본 내려받기 (HWP/PDF)"
                className="shrink-0 rounded-button p-1 text-md-on-surface-variant hover:text-md-primary"
              >
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  download
                </span>
              </a>
            )}
            {externalUrl && (
              <a
                href={externalUrl}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={externalLabel}
                title={externalLabel}
                className="shrink-0 rounded-button p-1 text-md-on-surface-variant hover:text-md-secondary"
              >
                <span
                  className="material-symbols-outlined text-[16px]"
                  aria-hidden
                >
                  {externalKind === "law-portal" ? "gavel" : "north_east"}
                </span>
              </a>
            )}
          </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

function NavBtn({
  dir,
  disabled,
  onClick,
}: {
  dir: "prev" | "next";
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <span
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      aria-label={dir === "prev" ? "이전 출처" : "다음 출처"}
      onClick={(e) => {
        if (disabled) return;
        e.stopPropagation();
        onClick();
      }}
      onKeyDown={(e) => {
        if (disabled) return;
        if (e.key === "Enter" || e.key === " ") {
          e.stopPropagation();
          onClick();
        }
      }}
      className={
        "rounded-button p-1 text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container " +
        (disabled ? "opacity-30 hover:bg-transparent cursor-default" : "cursor-pointer")
      }
    >
      <span className="material-symbols-outlined text-[18px]" aria-hidden>
        {dir === "prev" ? "chevron_left" : "chevron_right"}
      </span>
    </span>
  );
}
