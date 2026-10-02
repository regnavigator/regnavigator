"use client";

/**
 * TurnAnswer — 03 §5, P6.3.
 *
 * MarkdownContent + CitationFootnotes + ArtifactCard 인라인.
 *
 * P6.3 DoD:
 *  - markdown 렌더 + Citation chip + 코드 복사 + 표 스크롤
 *  - chip 시각·클릭(URL `?citation=`)·revoked 취소선
 */

import { useMemo, useState } from "react";
import { useQueryState } from "nuqs";
import { apiFetchBlob } from "@/lib/api/client";
import { articleKeyFromCitation } from "@/lib/client/article";
import { LawGraphPanel } from "@/components/chat/LawGraphPanel";
import { MarkdownContent } from "@/components/chat/MarkdownContent";
import { CitationFootnotes } from "@/components/chat/CitationFootnotes";
import { PathwayCard } from "@/components/chat/PathwayCard";
import { useRightPanel } from "@/lib/store/rightPanel";
import { CiteHighlightProvider } from "@/components/chat/CiteHighlightContext";
import { ArtifactCard } from "@/components/chat/ArtifactCard";
import { ConfidenceBadge } from "@/components/chat/ConfidenceBadge";
import {
  ProcedureTimeline,
  extractProcedureSteps,
} from "@/components/chat/ProcedureTimeline";
import { FeedbackButtons } from "@/components/chat/FeedbackButtons";
import type { PathwayStep } from "@/lib/store/types/state";
import type { Turn } from "@/lib/store/types";

/** 답변 + 참고자료(인용) 를 함께 복사 — RA/QA 가 문서에 근거까지 붙여넣도록. */
async function copyAnswerWithCitations(
  content: string,
  citations: NonNullable<Turn["answer"]>["citations"],
): Promise<void> {
  const refs = (citations ?? [])
    .map((c) => {
      const bits = [c.title, c.publisher, c.article]
        .map((s) => (s ?? "").toString().trim())
        .filter(Boolean)
        .join(" · ");
      const link = c.url || c.download_url || "";
      return `[${c.number}] ${bits}${link ? ` — ${link}` : ""}`;
    })
    .join("\n");
  const text = refs ? `${content}\n\n---\n참고 자료\n${refs}` : content;
  try {
    await navigator.clipboard.writeText(text);
    const { toast } = await import("sonner");
    toast.success(refs ? "인용 포함 복사됨" : "답변 복사됨");
  } catch (err) {
    console.warn("[TurnAnswer] copy(with citations) failed", err);
    const { toast } = await import("sonner");
    toast.error("복사 실패 — 브라우저 권한 확인", { duration: 6000 });
  }
}

/** 답변을 Word(docx) 파일로 내보내기 — 백엔드 pandoc 변환(불가 시 md 폴백). */
async function exportAnswerDocx(
  content: string,
  citations: NonNullable<Turn["answer"]>["citations"],
): Promise<void> {
  try {
    const blob = await apiFetchBlob("/answers/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, citations, format: "docx" }),
    });
    const isDocx = blob.type.includes("wordprocessing");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = isDocx ? "medi-answer.docx" : "medi-answer.md";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    const { toast } = await import("sonner");
    toast.success(isDocx ? "Word 문서로 내보냈습니다" : "Markdown으로 내보냈습니다");
  } catch (err) {
    console.warn("[TurnAnswer] export failed", err);
    const { toast } = await import("sonner");
    toast.error("내보내기 실패 — 잠시 후 다시 시도해주세요.", { duration: 6000 });
  }
}

type Props = {
  answer: NonNullable<Turn["answer"]>;
  /** 스트리밍 중 (turn.status === "running") — 본문 끝에 깜빡이는 caret 노출 */
  streaming?: boolean;
  /** 규제 경로 분해 단계 — 절차성 질의에만 온다(2026-10-01) */
  pathway?: PathwayStep[] | null;
};

/** 근거 법령 네트워크(그래프) 노출 여부 — 2026-08-03 **끔**.
 *
 * 임시 구현이라 베타 사용자에게 내보내지 않는다. 구현(LawGraphPanel·LawGraph2D·
 * backend `/law-graph`)은 그대로 두고 진입점만 막았다 — 보강 후 이 상수를 true 로
 * 되돌리면 복구된다. `NEXT_PUBLIC_LAW_GRAPH=1` 로 개발 중 임시 확인 가능.
 */
const LAW_GRAPH_ENABLED = process.env.NEXT_PUBLIC_LAW_GRAPH === "1";

export function TurnAnswer({ answer, streaming = false, pathway = null }: Props) {
  const { setCitation } = useRightPanel();
  const [threadId] = useQueryState("threadId");
  // 근거 법령 네트워크 — doc 인용의 조 단위 article_key를 seed로 관계 그래프(PIP).
  const [graphOpen, setGraphOpen] = useState(false);
  const graphSeeds = useMemo(
    () =>
      (answer.citations ?? [])
        .map((c) => articleKeyFromCitation(c))
        .filter((k): k is string => !!k),
    [answer.citations],
  );
  // 절차(순서 목록 ≥3단계) 답변이면 체크 가능한 타임라인 제공. streaming 중엔 숨김.
  const procedureSteps = streaming ? [] : extractProcedureSteps(answer.content);
  // streaming 중엔 출처/근거 UI 일체 숨김 — citation chip, References 박스, ConfidenceBadge,
  // ArtifactCard 모두 done 시점에 한꺼번에 노출. 본문은 평문(plain markdown)으로만 라이브.
  // chip이 streaming 도중 깜빡이며 추가되는 산만한 UX 차단.
  return (
    <CiteHighlightProvider>
    <section aria-label="답변" className="group/answer flex flex-col gap-3">
      {!streaming ? <ConfidenceBadge citations={answer.citations} /> : null}
      {/* 본문 끝 `---` 뒤 면책(시스템 부착, 2026-10-03)은 작은 회색으로 — `[&_hr+p]` */}
      <div className={"relative [&_hr+p]:mt-2 [&_hr+p]:text-[12px] [&_hr+p]:leading-relaxed [&_hr+p]:text-md-on-surface-variant" + (streaming ? " ink-stream" : "")}>
        <MarkdownContent
          content={answer.content}
          citations={streaming ? [] : answer.citations}
        />
        {streaming ? (
          <span
            aria-hidden
            className="md-caret-glow ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-md-primary align-middle"
          />
        ) : null}
      </div>
      {procedureSteps.length >= 3 ? (
        <ProcedureTimeline steps={procedureSteps} />
      ) : null}
      {/* 규제 경로 체크리스트 — 본문 아래, 인용 각주 위. 절차를 먼저 보고
          근거를 확인하는 순서가 자연스럽다. */}
      {!streaming && pathway?.length ? (
        <PathwayCard
          steps={pathway}
          storageKey={answer.id}
          onCite={(n) => {
            const c = (answer.citations ?? []).find((x) => x.number === n);
            if (c) setCitation(c.id);
          }}
        />
      ) : null}
      {!streaming ? <CitationFootnotes citations={answer.citations} /> : null}
      {/* ✨ 근거 지도 — References 아래 명시 진입점 (hover toolbar와 이중) */}
      {LAW_GRAPH_ENABLED && !streaming && graphSeeds.length > 0 ? (
        <div>
          <button
            type="button"
            onClick={() => setGraphOpen(true)}
            className="group/graph inline-flex items-center gap-1.5 rounded-pill border border-md-outline-variant px-3 py-1.5 text-[12px] font-medium text-md-on-surface-variant transition-colors hover:border-md-primary hover:text-md-primary"
          >
            <span className="material-symbols-outlined text-[15px]" aria-hidden>
              hub
            </span>
            근거 법령 네트워크 보기
            <span className="text-[10.5px] opacity-60 group-hover/graph:opacity-100">
              인용 관계 지도
            </span>
          </button>
        </div>
      ) : null}
      {LAW_GRAPH_ENABLED && graphOpen ? (
        <LawGraphPanel seeds={graphSeeds} onClose={() => setGraphOpen(false)} />
      ) : null}
      {!streaming && answer.artifacts.length > 0 ? (
        <div className="flex flex-col gap-2">
          {answer.artifacts.map((a) => (
            <ArtifactCard key={a.path} artifact={a} />
          ))}
        </div>
      ) : null}
      {/* 하단 액션 줄 — 내보내기·복사(+피드백). 본문 위 hover 오버레이는
          첫 줄 텍스트와 겹쳐(2026-07-16 피드백) 하단 고정 줄로 이동. */}
      {!streaming && answer.content.length > 0 ? (
        <div className="flex items-center justify-end gap-0.5">
          <button
            type="button"
            onClick={() => void exportAnswerDocx(answer.content, answer.citations)}
            aria-label="Word로 내보내기"
            title="Word(.docx)로 내보내기 — 참고자료 포함"
            className="inline-flex h-7 w-7 items-center justify-center rounded text-md-on-surface-variant hover:bg-md-surface-container-low hover:text-md-on-surface"
          >
            {/* Word 파랑 문서 + W — .docx 내보내기임을 직관적으로. */}
            <svg viewBox="0 0 24 24" className="h-[17px] w-[17px]" aria-hidden>
              <rect x="3" y="2" width="18" height="20" rx="2.6" fill="#2B579A" />
              <text
                x="12"
                y="16.3"
                textAnchor="middle"
                fontSize="11"
                fontWeight="700"
                fill="#ffffff"
                fontFamily="Arial, Helvetica, sans-serif"
              >
                W
              </text>
            </svg>
          </button>
          {/* 복사 — 인용 있으면 참고자료 포함, 없으면 답변만. 단일 버튼으로 통합. */}
          <button
            type="button"
            onClick={() =>
              void copyAnswerWithCitations(answer.content, answer.citations)
            }
            aria-label="복사"
            title="복사 (참고자료 포함)"
            className="inline-flex h-7 w-7 items-center justify-center rounded text-md-on-surface-variant hover:bg-md-surface-container-low hover:text-md-on-surface"
          >
            <span className="material-symbols-outlined text-[16px]" aria-hidden>
              content_copy
            </span>
          </button>
          {answer.id && threadId ? (
            <>
              <span className="mx-1 h-4 w-px bg-md-outline-variant" aria-hidden />
              <FeedbackButtons
                kind="message"
                threadId={threadId}
                messageId={answer.id}
              />
            </>
          ) : null}
        </div>
      ) : null}
    </section>
    </CiteHighlightProvider>
  );
}
