"use client";

/**
 * MarkdownContent — 03 §5.1, P6.3.1·P6.3.2·P6.3.3·P6.3.4·P6.3.5·P6.3.6·P6.3.7.
 *
 * react-markdown + remark-gfm. Citation chip은 *text 노드를 가로채* 토큰 분해 후
 * 인라인 button으로 렌더 (back §7 컨벤션). escape `\[1\]`은 평문 그대로.
 *
 * 코드블록은 syntax highlight는 후미루고(P9 폴리싱) — 모노 + 1px 보더 + 복사 버튼만.
 * 표는 가로 스크롤 wrapper로 감쌈.
 */

import { useCallback, useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "@/lib/store/types";
import { parseCitationTokens, citationLabel } from "@/lib/parse/citation";
import { useRightPanel } from "@/lib/store/rightPanel";
import { CitationEvidenceTooltip } from "@/components/chat/CitationEvidenceTooltip";
import { useCiteHighlight } from "@/components/chat/CiteHighlightContext";
import { useIsWatched } from "@/lib/store/watchedCitations";
import { articleKeyFromCitation } from "@/lib/client/article";

type Props = {
  content: string;
  /** Turn answer.citations — chip 렌더에 필요. 없으면 평문 fallback */
  citations?: Citation[];
  /**
   * chip 클릭 핸들러 override. 미지정 시 useRightPanel().setCitation 호출 (default).
   * 보고서 모달 등 *모달 안*에서 chip을 클릭했을 때, 우측 패널 대신 nested 모달로
   * inspector를 띄우려면 이 prop으로 가로채.
   */
  onCitationClick?: (citationId: string) => void;
  /**
   * 컴팩트 모드 — 우측 패널 원문(조문·별표서식)처럼 좁은 영역에서 폰트·행간·
   * 여백을 줄여 가독성 확보(실측 피드백 2026-07-24). 채팅 본문은 기본(false).
   */
  compact?: boolean;
};

/**
 * 본문 텍스트 전처리 — backend v9+가 모든 정규화를 처리하므로 *no-op*.
 *
 * (legacy) 이전 단계: ASCII 박스 → markdown 표 변환, 한 줄 표 분리, paragraph
 * 줄바꿈, 항 번호 앞 빈 줄, 개정 이력 뒤 빈 줄, 헤더 중복 제거 등.
 * 2026-05-13 backend의 `normalize_law_text`가 10개 항목 전부 처리로 통합되어
 * frontend 후처리 단계 일괄 제거.
 *
 * 시그니처는 외부 호출자(CitationInspector snippet 등) 호환 위해 유지.
 * backend regression이 발견되면 여기에 단일 처리 추가.
 */
export function preprocessLawText(text: string): string {
  return text ?? "";
}

export function MarkdownContent({
  content,
  citations = [],
  onCitationClick: onCitationClickOverride,
  compact = false,
}: Props) {
  // citation chip 클릭 — context의 citation/docPath state로 처리 (URL에 안 박힘).
  const {
    citation: activeCitation,
    setCitation,
    open: rpOpen,
    setOpen: setRpOpen,
  } = useRightPanel();

  const onCitationClick = useCallback(
    (id: string) => {
      if (onCitationClickOverride) {
        onCitationClickOverride(id);
        return;
      }
      if (id && id === activeCitation) {
        setRpOpen(!rpOpen);
      } else {
        setCitation(id || null);
        setRpOpen(true);
      }
    },
    [onCitationClickOverride, activeCitation, setCitation, rpOpen, setRpOpen],
  );

  // citation number → Citation 매핑.
  // 같은 number 중복이 들어오면 *마지막*(= 시간순 더 최근)을 우선 — 이전엔 첫 번째를
  // 잡아서 새 turn에서 추가된 citation이 *기존 거*로 chip 매칭되는 버그가 있었음.
  const byNumber = useMemo(() => {
    const m = new Map<number, Citation>();
    for (const c of citations) {
      m.set(c.number, c);
    }
    return m;
  }, [citations]);

  // 본문 텍스트를 chip으로 변환 — react-markdown의 모든 text 노드에 적용
  const renderTextWithCitations = useCallback(
    (text: string): ReactNode => {
      const tokens = parseCitationTokens(text, citations);
      if (tokens.length === 0) return text;
      // 매칭된 citation이 0개면 평문 fallback (P6.3.4)
      if (!tokens.some((t) => t.kind === "citation")) return text;
      return tokens.map((tok, i) => {
        if (tok.kind === "text") return <span key={i}>{tok.value}</span>;
        const citation = byNumber.get(tok.number);
        if (!citation) {
          // 번호가 citations에 없으면 평문 fallback (콘솔 경고만 — back §7)
          if (typeof window !== "undefined") {
            console.warn(`[MarkdownContent] citation [${tok.number}] missing`);
          }
          return <span key={i}>{tok.raw}</span>;
        }
        return (
          <CitationChip
            key={i}
            citation={citation}
            onClick={() => onCitationClick(citation.id)}
          />
        );
      });
    },
    [byNumber, citations, onCitationClick],
  );

  const components: Components = {
    // P6.3.4 — 텍스트 노드를 가로채 chip 변환. 한글 가독성을 위해 leading 1.75.
    p: ({ children }) => (
      <p className="leading-[1.8]">
        {wrapTextChildren(children, renderTextWithCitations)}
      </p>
    ),
    li: ({ children }) => (
      <li className="leading-[1.75]">
        {wrapTextChildren(children, renderTextWithCitations)}
      </li>
    ),
    td: ({ children }) => (
      <td className="leading-[1.65]">
        {wrapTextChildren(children, renderTextWithCitations)}
      </td>
    ),
    th: ({ children }) => (
      <th>{wrapTextChildren(children, renderTextWithCitations)}</th>
    ),
    h1: ({ children }) => (
      <h1 className="mt-7 mb-3.5 text-h1 leading-tight tracking-tight text-md-on-surface first:mt-0">
        {wrapTextChildren(children, renderTextWithCitations)}
      </h1>
    ),
    h2: ({ children }) => (
      <h2 className="mt-7 mb-3 text-h2 leading-tight tracking-tight text-md-on-surface first:mt-0">
        {wrapTextChildren(children, renderTextWithCitations)}
      </h2>
    ),
    h3: ({ children }) => (
      <h3 className="mt-6 mb-2 text-[15.5px] font-semibold leading-snug text-md-on-surface first:mt-0">
        {wrapTextChildren(children, renderTextWithCitations)}
      </h3>
    ),
    h4: ({ children }) => (
      <h4 className="mt-5 mb-1.5 text-body-base font-semibold leading-snug text-md-on-surface first:mt-0">
        {wrapTextChildren(children, renderTextWithCitations)}
      </h4>
    ),
    h5: ({ children }) => (
      <h5 className="mt-4 mb-1 text-body-sm font-semibold leading-snug text-md-on-surface first:mt-0">
        {wrapTextChildren(children, renderTextWithCitations)}
      </h5>
    ),
    h6: ({ children }) => (
      <h6 className="mt-4 mb-1 text-body-sm font-semibold leading-snug text-md-on-surface-variant first:mt-0">
        {wrapTextChildren(children, renderTextWithCitations)}
      </h6>
    ),
    // P6.3.3 — 표 wrapper (가로 스크롤). 행간 넉넉히.
    table: ({ children }) => (
      <div className="my-4 max-w-full overflow-x-auto rounded border border-md-outline-variant">
        <table className="min-w-full text-body-sm">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-md-surface-container-low">{children}</thead>,
    tr: ({ children }) => (
      <tr className="border-b border-md-outline-variant last:border-b-0">{children}</tr>
    ),
    code: (props) => <CodeBlock {...props} />,
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="break-all text-md-secondary underline-offset-2 hover:underline"
      >
        {wrapTextChildren(children, renderTextWithCitations)}
      </a>
    ),
    blockquote: ({ children }) => (
      <blockquote className="my-5 border-l-[3px] border-md-outline pl-4 leading-[1.75] text-md-on-surface-variant">
        {children}
      </blockquote>
    ),
    ul: ({ children }) => (
      <ul className="my-4 list-disc space-y-2 pl-6 marker:text-md-on-surface-variant">
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol className="my-4 list-decimal space-y-2 pl-6 marker:text-md-on-surface-variant">
        {children}
      </ol>
    ),
    hr: () => <hr className="my-6 border-md-outline-variant" />,
  };

  return (
    <div
      // 한글 가독성: word-break keep-all (단어 중간 잘림 방지) + overflow-wrap anywhere (긴 URL fallback) + leading 1.8.
      // 단락 spacing my-5 — 답변 본문이 호흡 있게.
      className={
        (compact
          ? "text-[12.5px] leading-[1.65] [&>p]:my-3 [&_th]:px-2 [&_th]:py-1.5 [&_td]:px-2 [&_td]:py-1.5 "
          : "text-body-base [&>p]:my-5 [&_th]:px-3 [&_th]:py-2 [&_td]:px-3 [&_td]:py-2.5 ") +
        "text-md-on-surface [&>p:first-child]:mt-0 [&>p:last-child]:mb-0 [&_li>p]:my-1.5 [&_th]:text-left [&_th]:font-semibold [&_td]:align-top [&_strong]:font-semibold [&_strong]:text-[color:var(--md-strong)]"
      }
      style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
    >
      {/* singleTilde:false — 한국어 범위 표기 "18~24개월"의 홑물결이 GFM 취소선으로
          해석돼 물결 소실+가운데 취소선("1824개월") 되던 버그. 취소선은 ~~쌍물결~~만. */}
      <ReactMarkdown
        remarkPlugins={[[remarkGfm, { singleTilde: false }]]}
        components={components}
      >
        {preprocessLawText(content)}
      </ReactMarkdown>
    </div>
  );
}

/* ─────────────────── helpers ─────────────────── */

/**
 * react-markdown은 text 노드를 string children으로 넘김. string인 children만
 * citation 변환 적용, 그 외는 그대로 통과.
 */
function wrapTextChildren(
  children: ReactNode,
  fn: (s: string) => ReactNode,
): ReactNode {
  if (typeof children === "string") return fn(children);
  if (Array.isArray(children)) {
    return children.map((c, i) => {
      if (typeof c === "string") return <span key={i}>{fn(c)}</span>;
      return c;
    });
  }
  return children;
}

/* ─────────────────── Citation chip ─────────────────── */

/**
 * P6.3.5 — chip 시각.
 * - active(기본)  : `--md-secondary-fixed` bg, `--md-on-secondary-fixed-variant` text
 * - hover         : `--md-primary` bg, `--md-on-primary` text
 * - revoked       : `--md-error-container` bg, 취소선 + 툴팁 (05 §2.3, P6.3.7)
 * - amended_pending: `--md-tertiary-fixed` bg, 툴팁 "곧 변경 예정"
 *
 * 2026-05-21 — `source_kind`/`doc_category`별 *한글 짧은 라벨*을 `[n]` 앞에 inline
 *   으로 박아 출처 타입을 시각 구분. 13 카테고리를 5 그룹(법령/행정/판례/별표/웹)+
 *   문서 폴백으로 그룹화 — chip 본문 흐름에 끼어들 수 있게 짧게.
 */

/** 출처 종별 → 칩 색. citationLabel 의 라벨 기준. 범례(CitationFootnotes)·신뢰도 배지와 **같은 표**.
 *  색은 globals.css `--cite-*` 고정 팔레트(테마 무관). 범례 견본도 칩과 같은 `cls` 를 그대로 쓴다 —
 *  종전엔 범례 점은 진한 본색, 칩은 연한 배경이라 같은 종별로 안 보였다(2026-09-21). */
export const CITATION_KIND_STYLE: { label: string; match: string[]; cls: string }[] = [
  { label: "법령", match: ["법령", "조약"], cls: "bg-[var(--cite-law-bg)] text-[var(--cite-law-fg)]" },
  { label: "행정규칙·고시", match: ["행정규칙", "자치법규", "학칙"], cls: "bg-[var(--cite-rule-bg)] text-[var(--cite-rule-fg)]" },
  { label: "판례·해석", match: ["판례", "헌재", "해석", "심판"], cls: "bg-[var(--cite-case-bg)] text-[var(--cite-case-fg)]" },
  { label: "가이드라인", match: ["가이드라인"], cls: "bg-[var(--cite-guide-bg)] text-[var(--cite-guide-fg)]" },
  { label: "별표·서식", match: ["별표"], cls: "bg-[var(--cite-annex-bg)] text-[var(--cite-annex-fg)]" },
  { label: "웹", match: ["웹"], cls: "bg-[var(--cite-web-bg)] text-[var(--cite-web-fg)] ring-1 ring-inset ring-md-outline" },
];
const OTHER_KIND_CLS = "bg-md-surface-container-high text-md-on-surface-variant";

/** 종별 건수 — 출처 목록 범례·신뢰도 배지가 **같은 표**로 센다. 표에 없는 종별은
 *  "기타"로 모아 합계가 항상 출처 수와 같게 한다(종전엔 조용히 빠져 숫자가 안 맞았다). */
export function citationKindCounts(
  citations: Citation[],
): { label: string; n: number; cls: string }[] {
  const out = CITATION_KIND_STYLE.map((k) => ({ label: k.label, cls: k.cls, n: 0 }));
  let other = 0;
  for (const c of citations) {
    const label = citationLabel(c);
    const i = CITATION_KIND_STYLE.findIndex((k) => k.match.includes(label));
    if (i >= 0) out[i]!.n += 1;
    else other += 1;
  }
  if (other) out.push({ label: "기타", cls: OTHER_KIND_CLS, n: other });
  return out.filter((k) => k.n > 0);
}

export function citationKindClass(label: string): string {
  const hit = CITATION_KIND_STYLE.find((k) => k.match.includes(label));
  return hit ? hit.cls : OTHER_KIND_CLS;
}

function CitationChip({
  citation,
  onClick,
}: {
  citation: Citation;
  onClick: () => void;
}) {
  // References 목록과 상호 하이라이트 — 같은 번호가 hover되면 이 칩도 강조.
  const { hovered, setHovered } = useCiteHighlight();
  const highlighted = hovered === citation.number;
  const status = citation.status ?? "active";
  const label = citationLabel(citation);
  // verified 전환 시각화 (UX 배치 #3) — verified===true 칩은 체크 표시 + 강조색,
  // false/미도착은 중립색. steps 이벤트로 늦게(답변 후 ~2s) 도착하는 전환이
  // transition-colors로 부드럽게 보임 (과한 애니메이션 X).
  const verified = citation.verified === true;
  // 관찰 중인지(2026-10-02) — 모니터링 스레드에서만 참이 된다. 담았는지 보려고
  // 인용을 하나씩 열어 보는 건 일이다(실사용 지적).
  const watched = useIsWatched(articleKeyFromCitation(citation));

  // Style as a clean inline hyperlink that flows naturally within the text sentence,
  // similar to academic/legal web citations.
  // 2026-09-07: 본문 흐름을 끊던 종별 라벨("법령")·체크 아이콘을 뺐다 — 번호만 작은
  // 칩으로. 종별·검증 여부는 색·툴팁·aria 로만. (OpenAI 출처 칩 톤)
  let cls =
    "relative -top-px mx-[2px] inline-flex h-[19px] min-w-[19px] items-center justify-center rounded-[5px] px-[5px] align-middle text-[11.5px] font-bold leading-none transition-colors duration-300 ease-out";

  // 칩 색은 **항상 종별 색**. 폐지·개정 예정을 색으로 덮으면(종전: 빨강·황) 개정 예정
  // 법령이 판례·해석 칩처럼 보였다(2026-09-21). 상태는 색이 아닌 표식으로 — 폐지는
  // 취소선·흐림, 개정 예정은 우상단 점, 미검증은 점선 테두리.
  let title = `${label} · ${citation.title}`;
  cls += " " + citationKindClass(label);
  if (status === "revoked") {
    cls += " line-through opacity-60";
    title += " (폐지된 근거)";
  } else if (status === "amended_pending") {
    title += " (곧 변경 예정)";
  }
  if (watched) {
    title += " · 관찰 중";
  }
  if (verified) {
    title += " · 원문 대조 검증됨";
  } else {
    cls += " outline outline-1 -outline-offset-1 outline-dashed outline-current/50";
    title += " · 미검증(참고용)";
  }

  return (
    <CitationEvidenceTooltip citation={citation}>
      <button
        type="button"
        onClick={onClick}
        onMouseEnter={() => setHovered(citation.number)}
        onMouseLeave={() => setHovered(null)}
        onFocus={() => setHovered(citation.number)}
        onBlur={() => setHovered(null)}
        data-cite-n={citation.number}
        title={title}
        aria-label={`${label} 출처 [${citation.number}] ${citation.title}${status === "revoked" ? " (폐지)" : status === "amended_pending" ? " (개정 예정)" : ""}${watched ? " (관찰 중)" : ""}${verified ? " (원문 대조 검증됨)" : ""}`}
        className={`${cls} ${highlighted ? "ring-2 ring-md-primary/40" : ""}`}
      >
        {citation.number}
        {status === "amended_pending" ? (
          <span
            aria-hidden
            className="absolute -right-[3px] -top-[3px] size-[7px] rounded-full bg-md-error ring-2 ring-md-surface"
          />
        ) : null}
        {/* 관찰 중 — 개정예정 점(우상단)과 **다른 자리·다른 색**에 둔다.
            둘이 겹치면 무엇이 무엇인지 알 수 없다. 왼쪽에 두면 앞 글자와 붙어
            별개 기호처럼 읽혀서(2026-10-02 실측) 오른쪽 아래로 뺐다. */}
        {watched ? (
          <span
            aria-hidden
            data-watched="1"
            className="absolute -bottom-[3px] -right-[3px] size-[7px] rounded-full bg-md-primary ring-2 ring-md-surface"
          />
        ) : null}
      </button>
    </CitationEvidenceTooltip>
  );
}

/* ─────────────────── Code block ─────────────────── */

/**
 * 코드블록 — syntax highlight는 P9에서 다듬음. 지금은 모노 + 1px 보더 + 복사 버튼.
 * inline code(`foo`)는 단순 모노 chip.
 */
function CodeBlock(props: {
  children?: ReactNode;
  className?: string;
  inline?: boolean;
  node?: unknown;
}) {
  const { children, className, inline } = props;
  const text = String(children ?? "").replace(/\n$/, "");
  // react-markdown v9는 `inline`을 더 이상 넘기지 않고, 언어 태그 없는 ``` 코드펜스는
  // className(language-*)도 없다 → 예전 판정으론 inline 칩으로 뭉개져 깨져 보였음.
  // language-* 이거나 개행 포함(여러 줄)이면 fenced 블록으로 렌더.
  const isFenced =
    !inline &&
    (/language-/.test(className ?? "") || text.includes("\n"));

  if (!isFenced) {
    return (
      <code className="rounded border border-md-outline-variant bg-md-surface-container-low px-1 py-[1px] text-code text-md-on-surface">
        {children}
      </code>
    );
  }
  return (
    <pre className="my-3 overflow-x-auto rounded border border-md-outline-variant bg-md-surface-container-lowest p-3 text-code text-md-on-surface">
      <CopyButton text={text} />
      <code className="block whitespace-pre">{text}</code>
    </pre>
  );
}

function CopyButton({ text }: { text: string }) {
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      const { toast } = await import("sonner");
      toast.success("코드 복사됨");
    } catch (e) {
      console.warn("[MarkdownContent] copy failed", e);
    }
  };
  return (
    <button
      type="button"
      onClick={() => void onCopy()}
      aria-label="코드 복사"
      className="float-right inline-flex h-7 items-center gap-1 rounded border border-md-outline-variant bg-md-surface px-2 text-body-sm text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container-low hover:text-md-on-surface"
    >
      <span className="material-symbols-outlined text-[14px]" aria-hidden>
        content_copy
      </span>
      복사
    </button>
  );
}
