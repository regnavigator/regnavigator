"use client";

/**
 * CitationInspector — 02 §4.1, 03 §7.1.
 *
 * `?citation=<id>` URL 진입 시 RightPanel 슬롯 점유.
 * 출처 메타(제목·발행기관·일자·조항·page) + 본문 스니펫 + 푸터 액션(원문/외부 링크).
 *
 * 데이터: 별도 fetch X — 현재 thread의 ChatState에서 *id로 매칭*해 찾는다 (back §13.3).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatState, Citation } from "@/lib/store/types";
import {
  deriveExternalUrl,
  externalUrlKind,
  stripBareAnnexSegment,
} from "@/lib/parse/lawLink";
import { normalizeMetaField, stripArticleNumPadding, citationLabel } from "@/lib/parse/citation";
import { useRightPanel } from "@/lib/store/rightPanel";
import { extractAnnexNum } from "@/lib/client/annex";
import { articleKeyFromCitation, getArticle, type Article } from "@/lib/client/article";
import { AnnexModal } from "@/components/chat/AnnexModal";
import { formActionHint, formActionLabel, formDocKind, isFormLike } from "@/lib/formEntry";
import { BookmarkButton } from "@/components/chat/BookmarkButton";
import { MarkdownContent, preprocessLawText } from "@/components/chat/MarkdownContent";

const ANNEX_CATEGORIES = new Set([
  "법령별표서식",
  "행정규칙별표서식",
  "자치법규별표서식",
]);

// 본문 시작점 — ①·②·... 또는 `1.` 또는 `제X조`
const ARTICLE_BODY_RE = /^\s*(?:[①-⑳㉑-㉟]|\d+\.\s|제\d+조)/;
// 법령명 라인 — `...법/령/규칙/조례/규정/지침/예규/고시/훈령/헌법` 으로 끝
const LAW_NAME_LINE_RE =
  /^[가-힣A-Za-z0-9\s·,·()「」『』]+(?:법|률|령|규칙|조례|규정|지침|예규|고시|훈령|헌법|기준|협약|학칙|규약|공단)$/;

/**
 * snippet 시작부에 박힌 메타 헤더(법령명·조항 헤더가 반복 노출되는 케이스) 분리.
 * `header` = 본문(①·② 등) 시작 직전까지의 trim된 라인 배열, `body` = 본문 markdown.
 */
function splitSnippetHeader(snippet: string): { header: string[]; body: string } {
  if (!snippet) return { header: [], body: "" };
  const lines = snippet.split("\n");
  const bodyIdx = lines.findIndex((l) => ARTICLE_BODY_RE.test(l));
  if (bodyIdx <= 0) return { header: [], body: snippet };
  return {
    header: lines
      .slice(0, bodyIdx)
      .map((l) => l.trim())
      .filter(Boolean),
    body: lines.slice(bodyIdx).join("\n"),
  };
}

function extractLawNameFromHeader(header: string[]): string | null {
  for (const l of header) {
    if (LAW_NAME_LINE_RE.test(l)) return l;
  }
  return null;
}

/**
 * 본문 텍스트에서 `supporting_quote`(보고서 grounding 검증 span)를 찾아 `<mark>`
 * 하이라이트(NotebookLM-lite). quote의 공백을 `\s+`로 풀어 원문 줄바꿈/공백 차이를
 * 흡수해 매칭. 못 찾으면 원문 그대로(하이라이트 없음 — 호출자가 별도 인용 박스로
 * fallback). 반환은 ReactNode(텍스트 + 1개 mark span).
 */
function highlightSupportingQuote(
  text: string,
  quote: string | undefined,
): React.ReactNode {
  const q = (quote ?? "").trim();
  if (!q || !text) return text;
  const pattern = q
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\s+/g, "\\s+");
  let m: RegExpExecArray | null = null;
  try {
    m = new RegExp(pattern).exec(text);
  } catch {
    return text;
  }
  if (!m) return text;
  const start = m.index;
  const end = start + m[0].length;
  return (
    <>
      {text.slice(0, start)}
      <mark className="rounded bg-md-tertiary-fixed px-0.5 text-md-on-tertiary-fixed-variant">
        {text.slice(start, end)}
      </mark>
      {text.slice(end)}
    </>
  );
}

/**
 * 챗 답변에서 이 citation(`[number]`)이 달린 *claim 문장*을 추출.
 * state.turns에서 citation id가 속한 turn의 answer.content를 찾아, `[number]`
 * 마커 직전 문장 경계(마침표/물음표/줄바꿈)부터 마커까지를 claim으로.
 * 보고서 모달(state 없음)·매칭 실패 시 null.
 */
function extractClaimForCitation(
  state: ChatState | undefined,
  citation: Citation,
): string | null {
  if (!state) return null;
  for (const turn of state.turns) {
    if (!turn.answer) continue;
    if (!turn.answer.citations.some((x) => x.id === citation.id)) continue;
    const content = turn.answer.content;
    const m = new RegExp(`\\[${citation.number}\\]`).exec(content);
    if (!m) return null;
    const before = content.slice(0, m.index);
    const cut = Math.max(
      before.lastIndexOf("\n"),
      before.lastIndexOf(". "),
      before.lastIndexOf("다. "),
      before.lastIndexOf("? "),
      before.lastIndexOf("! "),
      before.lastIndexOf("。"),
    );
    return before.slice(cut + 1).trim() || null;
  }
  return null;
}

/**
 * claim과 source 사이 *최장 공통 연속 어구*(원문에 그대로 존재하는 부분). LLM
 * grounding 없이 FE가 "답변에 쓰인 표현이 원문에 실제 있는" 구간만 보수적으로
 * 매칭 — minWords 이상 연속 어절이 source에 substring으로 존재할 때만. 우연 일치
 * 최소화 위해 결과 길이 하한(minChars)도 둠. 없으면 null(하이라이트 안 함).
 */
function longestCommonPhrase(
  claim: string,
  source: string,
  { minWords = 3, minChars = 6 }: { minWords?: number; minChars?: number } = {},
): string | null {
  const words = claim.split(/\s+/).filter(Boolean);
  if (words.length < minWords) return null;
  const normSource = source.replace(/\s+/g, " ");
  let best = "";
  for (let i = 0; i < words.length; i++) {
    for (let j = i + minWords; j <= words.length; j++) {
      const phrase = words.slice(i, j).join(" ");
      if (phrase.length <= best.length) continue;
      if (normSource.includes(phrase)) best = phrase;
    }
  }
  return best.length >= minChars ? best : null;
}

/**
 * 표시용 풀 제목 합성 — backend `/article` 응답이 있으면 그걸 신뢰,
 * 없으면 snippet 헤더에서 추출한 법령명 + c.title + c.article 합성.
 *
 * 결과 예: "의료기기법 제12조 (변경허가 등)"
 */
function composeDisplayTitle(
  c: Citation,
  article: Article | null,
  fallbackLawName: string | null,
): string {
  let raw: string;
  if (article) {
    const lt = normalizeMetaField(article.law_title);
    const an = normalizeMetaField(article.article_num);
    const composed = [lt, an].filter(Boolean).join(" ");
    // 별표/서식 — `/article` 응답엔 별표 *제목*(부제) 필드가 없어 law_title+"별표"만
    // 조합하면 backend display_title의 콜론 뒷부분(별표 제목)이 짤림(사용자 보고:
    // "의료기기 제조 및 품질관리 기준 별표" 로 "...: 적합인정서" 누락). 별표/서식이고
    // c.title이 콜론 부제를 갖고 더 완전하면 c.title(backend display_title) 우선.
    const cTitle = normalizeMetaField(c.title).trim();
    const isAnnex = /별표|서식/.test(an);
    raw =
      isAnnex && cTitle.includes(":") && cTitle.length > composed.length
        ? cTitle
        : composed;
  } else {
    const title = normalizeMetaField(c.title).trim();
    const cArticle = normalizeMetaField(c.article).trim();
    const law = fallbackLawName?.trim() ?? "";

    // title이 이미 "제X조"·별표·서식을 포함하면 그대로 — 단 lawName이 별도 추출됐고
    // title에 없으면 prefix. (별표는 번호 없는 "별표: 부제" 형태도 있어 \d 미요구.)
    if (/제\d+조|별표|서식/.test(title)) {
      raw = law && !title.includes(law) ? `${law} ${title}` : title;
    } else {
      // title을 부제(subtitle)로 처리: `{law} {article} ({title})`
      const parts: string[] = [];
      if (law) parts.push(law);
      if (cArticle && !parts.join(" ").includes(cArticle)) parts.push(cArticle);
      let result = parts.join(" ").trim();
      if (title && title !== law) {
        result = result ? `${result} (${title})` : title;
      }
      raw = result || cArticle || title;
    }
  }
  return stripArticleNumPadding(raw);
}

type Props = {
  /** state가 있으면 turns에서 lookup. citationsOverride 있으면 무시됨. */
  state?: ChatState;
  citationId: string;
  /**
   * 보고서 모달 등에서 — state.turns 대신 이 리스트로 lookup. 모달 내부 nested
   * inspector에서 사용. 있으면 collectAllCitations도 이 리스트만 노출.
   */
  citationsOverride?: Citation[];
  /** dialog host가 직접 close 처리. 미지정 시 useRightPanel.setCitation(null) 기본 동작. */
  onClose?: () => void;
  /** dialog host가 자체 X를 제공할 때 inspector 헤더의 닫기 버튼을 숨김. */
  hideCloseButton?: boolean;
  /**
   * inspector 자체 헤더 전체(라벨·badge·X)를 숨김. 우측 패널처럼 외부에서 이미
   * 영역 라벨/토글 띠를 제공하는 경우 사용. number badge + status pill은 본문
   * displayTitle 옆에 inline으로 노출됨.
   */
  hideHeader?: boolean;
  /**
   * list 항목 클릭 시 callback. 미지정 시 useRightPanel.setCitation 호출(default).
   * 보고서 모달처럼 *모달 안*에서 list를 클릭했을 때, 우측 패널 대신 모달 inspector를
   * 갱신하려면 이 prop으로 가로채.
   */
  onSelectCitation?: (citationId: string) => void;
  /** 별표·서식을 골라 그 형식으로 서류 작성 요청(2026-08-26). 미지정=버튼 숨김 */
  onUseAsForm?: (articleKey: string, title: string) => void;
};

function findCitation(state: ChatState, id: string): Citation | null {
  for (const turn of state.turns) {
    if (turn.answer) {
      const c = turn.answer.citations.find((c) => c.id === id);
      if (c) return c;
    }
    for (const step of turn.steps) {
      if (step.citations) {
        const c = step.citations.find((c) => c.id === id);
        if (c) return c;
      }
    }
  }
  return null;
}

/**
 * thread 안 *답변에 인용된* citation만 한 곳에 모음 + turn 인덱스 같이 보존.
 *
 * **신뢰성 원칙**: turn.answer.citations만 사용 (deriveCitations 거친 결과 = 본문 인용
 * 출처 + web 출처). step.citations 직접 모음은 *답변에 안 쓴 검색 결과*까지 끌고 오게
 * 되어 사용자 신뢰성 떨어뜨림. 답변 하단 References 박스와 동일 데이터 소스로 통일.
 *
 * 정렬: turnIdx ASC → number ASC (turn 별 1·2·3 그룹화).
 */
type CitationWithTurn = Citation & { turnIdx: number };

function collectAllCitations(state: ChatState): CitationWithTurn[] {
  const list: CitationWithTurn[] = [];
  const seen = new Set<string>();
  state.turns.forEach((turn, ti) => {
    if (!turn.answer) return;
    for (const c of turn.answer.citations) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      list.push({ ...c, turnIdx: ti });
    }
  });
  return list.sort((a, b) =>
    a.turnIdx !== b.turnIdx ? a.turnIdx - b.turnIdx : a.number - b.number,
  );
}

export function CitationInspector({
  state,
  citationId,
  citationsOverride,
  onClose: onCloseOverride,
  hideCloseButton = false,
  hideHeader = false,
  onSelectCitation,
  onUseAsForm,
}: Props) {
  const { setCitation, setDocPath, setOpen: setRpOpen } = useRightPanel();
  /**
   * list 항목 클릭 — 이미 활성 항목이면 *닫기*(list-only로 복귀), 아니면 디테일 전환.
   * 같은 chip 두 번 누르면 토글되는 UX.
   */
  const selectCitation = useCallback(
    (id: string) => {
      const next = id === citationId ? "" : id;
      if (onSelectCitation) onSelectCitation(next);
      else setCitation(next || null);
    },
    [onSelectCitation, setCitation, citationId],
  );
  const [annexArgs, setAnnexArgs] = useState<{
    lawId: string;
    annexNum: string;
  } | null>(null);

  const close = useCallback(() => {
    if (onCloseOverride) {
      onCloseOverride();
      return;
    }
    // 우측 패널에서 X — citation 해제 + 패널 전체 닫기 (사용자 의도: "닫기" = 패널 사라짐)
    setCitation(null);
    setDocPath(null);
    setRpOpen(false);
  }, [onCloseOverride, setCitation, setDocPath, setRpOpen]);

  // override 있으면 그 리스트로 lookup, 없으면 state.turns에서.
  const c = useMemo(() => {
    if (citationsOverride) {
      return citationsOverride.find((x) => x.id === citationId) ?? null;
    }
    return state ? findCitation(state, citationId) : null;
  }, [citationsOverride, state, citationId]);

  // 최근 열람 기록 — 팔레트(빈 검색)에서 재진입용. best-effort.
  useEffect(() => {
    if (!c) return;
    import("@/lib/store/recentArticles").then(({ recordRecentArticle }) => {
      recordRecentArticle({
        id: c.id,
        title: normalizeMetaField(c.title) || c.id,
        article: normalizeMetaField(c.article) || null,
        url: deriveExternalUrl(c) ?? c.url ?? null,
      });
    });
  }, [c]);
  const allCitations = useMemo(() => {
    if (citationsOverride) {
      // **id 기준 dedup** — 보고서 `citations`는 writer가 여러 step에서 모은
      // 결과라 같은 id가 중복 포함되기도 함. dedup 없으면 (1) 리스트 중복
      // 노출, (2) `<li key={item.id}>` React key 충돌, (3) `findIndex(citationId)`
      // 가 첫 매칭만 잡아 reorder/sticky가 *클릭한 항목이 아닌* 다른 인스턴스
      // 로 가버림(사용자 보고: 클릭한 게 안 뜨고 다른 게 상단 고정). state
      // 경로는 `collectAllCitations`가 이미 dedup함 — override만 미흠.
      const seen = new Set<string>();
      const deduped = citationsOverride.filter((c) => {
        if (seen.has(c.id)) return false;
        seen.add(c.id);
        return true;
      });
      return deduped
        .sort((a, b) => a.number - b.number)
        .map((x) => ({ ...x, turnIdx: 0 }));
    }
    return state ? collectAllCitations(state) : [];
  }, [citationsOverride, state]);
  const hasMultiTurn = useMemo(
    () => new Set(allCitations.map((a) => a.turnIdx)).size > 1,
    [allCitations],
  );
  // **active 항목을 list 최상단에 reorder** — CSS sticky는 위로 스크롤 시 stick
  // 해제되어 사용자가 "위로 올리면 고정 안 됨" 짜증. array 자체를 재정렬해 어떤
  // 스크롤 시점에도 active가 항상 list 첫 번째 위치 = 항상 보임.
  const orderedCitations = useMemo(() => {
    if (!citationId) return allCitations;
    const idx = allCitations.findIndex((c) => c.id === citationId);
    if (idx <= 0) return allCitations;
    const active = allCitations[idx]!;
    return [
      active,
      ...allCitations.slice(0, idx),
      ...allCitations.slice(idx + 1),
    ];
  }, [allCitations, citationId]);
  const [listOpen, setListOpen] = useState(true);

  // list scroll 위치 보존 — list-only ↔ 디테일 모드 전환으로 ul element가 새로 mount되어도
  // 직전 scrollTop 복원. 컴포넌트 자체는 항상 mount 유지하므로 ref 값 보존됨.
  const listScrollRef = useRef(0);
  const listRef = useRef<HTMLUListElement | null>(null);
  const handleListRef = useCallback((el: HTMLUListElement | null) => {
    if (el) {
      // 새 element mount — 저장된 scrollTop 복원
      el.scrollTop = listScrollRef.current;
    }
    listRef.current = el;
  }, []);
  const handleListScroll = useCallback((e: React.UIEvent<HTMLUListElement>) => {
    listScrollRef.current = e.currentTarget.scrollTop;
  }, []);
  // 활성 항목 변경 시 list 박스 상단으로 자동 스크롤
  useEffect(() => {
    if (!citationId) return;
    const list = listRef.current;
    if (!list) return;
    const raf = requestAnimationFrame(() => {
      const li = list.querySelector<HTMLLIElement>(
        `li[data-cid="${CSS.escape(citationId)}"]`,
      );
      if (!li) return;
      const liRect = li.getBoundingClientRect();
      const listRect = list.getBoundingClientRect();
      list.scrollTop += liRect.top - listRect.top;
      listScrollRef.current = list.scrollTop;
    });
    return () => cancelAnimationFrame(raf);
  }, [citationId]);

  const annexAvailable = useMemo(() => {
    if (!c) return null;
    if (!c.doc_category || !ANNEX_CATEGORIES.has(c.doc_category)) return null;
    if (!c.doc_id) return null;
    const annexNum = extractAnnexNum(c.article);
    if (!annexNum) return null;
    // articleKey·title 을 함께 실어 별표 모달에서도 [작성] 진입이 가능하게
    // 한다(2026-08-27) — 모달까지 열어 본문을 확인한 사용자가 정작 거기서는
    // 작성으로 못 넘어가던 막다른 길.
    return {
      lawId: c.doc_id,
      annexNum,
      articleKey: articleKeyFromCitation(c) ?? undefined,
      title: c.title ?? undefined,
      isForm: isFormLike(c.article, c.title),
    };
  }, [c]);

  // 별표서식이 아닌 doc citation이면 article modal 활용 가능 (backend `/article` endpoint)
  const articleAvailable = useMemo(() => {
    if (!c) return null;
    if (c.source_kind !== "doc") return null;
    if (annexAvailable) return null; // 별표서식은 AnnexModal 우선
    return articleKeyFromCitation(c);
  }, [c, annexAvailable]);

  // 인스펙터 진입 시 article 본문 자동 prefetch — backend가 snippet에 chunk 일부만
  // 박는 케이스 대비. 성공 시 본문은 article.full_text(전체), 실패 시 snippet으로 fallback.
  // 헤더 제목도 article.law_title/article_num 우선 신뢰.
  //
  // **prefetch loading 추적**: snippet → article 본문이 *교체*되는 jump를 사용자가
  // "내용이 바뀐다"라고 느낌. doc citation이면 prefetch 동안 본문 영역에 spinner만
  // 노출하고, article 도착하면 한 번에 본문 표시. snippet은 article 실패 시에만.
  const [article, setArticle] = useState<Article | null>(null);
  const [articleLoading, setArticleLoading] = useState(false);
  useEffect(() => {
    setArticle(null);
    if (!articleAvailable) {
      setArticleLoading(false);
      return;
    }
    let cancelled = false;
    setArticleLoading(true);
    void getArticle(articleAvailable)
      .then((a) => {
        if (!cancelled) {
          setArticle(a);
          setArticleLoading(false);
        }
      })
      .catch((err) => {
        // 404 등 — snippet fallback. 사용자는 외부 링크(법령정보센터)로 전체 본문 접근.
        console.debug("[CitationInspector] article prefetch failed", err);
        if (!cancelled) {
          setArticle(null);
          setArticleLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [articleAvailable]);

  // snippet 시작부 메타 헤더(법령명·조항 헤더 중복 노출) 분리. 본문만 표시하고 헤더에서
  // 추출한 법령명은 display title 합성에 활용.
  const snippetParts = useMemo(() => splitSnippetHeader(c?.snippet ?? ""), [c?.snippet]);
  const fallbackLawName = useMemo(
    () => extractLawNameFromHeader(snippetParts.header),
    [snippetParts.header],
  );
  const displayTitle = useMemo(
    () => (c ? composeDisplayTitle(c, article, fallbackLawName) : ""),
    [c, article, fallbackLawName],
  );

  // 챗 citation FE 매칭 근거 — backend grounding(supporting_quote)이 없는 챗에서,
  //   *답변에 쓰인 표현이 원문(snippet·조문)에 실제 존재하는 부분*을 FE가 문자열로
  //   매칭(사용자 회신 "답변에 사용된 내용이 실제 있다면 매칭시켜서 표시"). LLM 없이
  //   claim↔source 최장 공통 연속 어구만 보수적으로 — 매칭되면 그 구간을 본문에서
  //   하이라이트, 없으면 무표시(경고 X). backend supporting_quote가 있으면 그게 우선.
  const feMatchedQuote = useMemo<string | null>(() => {
    if (!c || c.supporting_quote) return null;
    if (articleLoading) return null;
    // 조 전문(article.full_text)은 MarkdownContent로 렌더돼 하이라이트 주입이
    //   불가 → snippet(blockquote 평문)을 본문으로 쓸 때만 FE 매칭/하이라이트.
    const usingArticle = !!(articleAvailable && article?.full_text?.trim());
    if (usingArticle) return null;
    const source = (c.snippet || "").trim();
    if (!source) return null;
    const claim = extractClaimForCitation(state, c);
    if (!claim) return null;
    return longestCommonPhrase(claim, source);
  }, [c, state, article, articleAvailable, articleLoading]);

  if (!c) {
    // citationId가 비어있거나 매칭 실패 — 출처가 있으면 list-only 모드(사용자가 클릭해서 디테일로),
    // 출처도 없으면 "찾을 수 없음" 메시지.
    const isEmpty = !citationId || citationId.length === 0;
    return (
      <div
        className="flex h-full flex-col"
        aria-label={isEmpty ? "Citation Inspector — list" : "Citation Inspector — not found"}
      >
        {!hideHeader ? (
          <header className="flex h-12 items-center gap-2 border-b border-md-outline-variant px-3">
            <span className="text-body-sm font-semibold text-md-on-surface">출처</span>
            {!hideCloseButton ? (
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
            ) : null}
          </header>
        ) : null}
        {allCitations.length > 0 ? (
          <ul
            ref={handleListRef}
            onScroll={handleListScroll}
            className="flex-1 overflow-y-auto py-1"
          >
            {allCitations.map((item, idx) => {
              const itemRevoked = item.status === "revoked";
              const itemTitle = stripArticleNumPadding(
                normalizeMetaField(item.title),
              );
              const prevTurnIdx = idx > 0 ? allCitations[idx - 1]!.turnIdx : -1;
              const showTurnHeader =
                hasMultiTurn && item.turnIdx !== prevTurnIdx;
              return (
                <li key={item.id} data-cid={item.id}>
                  {showTurnHeader ? (
                    <div className="px-3 pb-0.5 pt-1.5 text-[10.5px] font-semibold text-md-on-surface-variant">
                      대화 {item.turnIdx + 1}
                    </div>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => selectCitation(item.id)}
                    className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-body-sm text-md-on-surface transition-colors hover:bg-md-surface-container-low"
                  >
                    <span className="shrink-0 font-semibold text-md-primary">
                      [{item.number}]
                    </span>
                    <span
                      className={
                        "min-w-0 flex-1 truncate " +
                        (itemRevoked ? "line-through" : "")
                      }
                      title={itemTitle}
                    >
                      {itemTitle}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="flex-1 p-card-padding text-body-sm text-md-on-surface-variant">
            {isEmpty
              ? "출처가 없습니다."
              : "이 대화에서 해당 인용을 찾을 수 없습니다."}
          </div>
        )}
      </div>
    );
  }

  // article 응답에 external_url이 박혀있으면 그게 정확 — backend deep-link 우선,
  // 없으면 heuristic 도출. 번호 없는 별표/서식이 끝에 붙어 404 나는 backend URL은
  // stripBareAnnexSegment로 부모 문서 URL로 정리 (deriveExternalUrl도 내부 적용됨).
  const url =
    stripBareAnnexSegment(article?.external_url ?? "") || deriveExternalUrl(c);
  const kind = url ? externalUrlKind(c, url) : null;
  const isRevoked = c.status === "revoked";
  const isAmendedPending = c.status === "amended_pending";
  // 시행 상태 배지 문구(back 2026-08-16) — "미시행"(공포됐으나 시행일 미도래)은
  // 폐지가 아니라 **아직 효력 없음**이라 문구를 나눈다. 시행일을 알면 함께 표기해
  // 사용자가 언제부터 유효한지 바로 안다.
  // 현행본과 짝지어 온 개정본은 '개정 예정'(= 이렇게 바뀐다), 단독 미시행은
  // '시행 예정'(= 아직 효력 없음). 사용자에게 의미가 다르다.
  const isAmendmentOfCurrent = c.version_status === "pending";
  const pendingLabel =
    c.effective_status === "미시행" || c.enforced === false
      ? isAmendmentOfCurrent
        ? c.date
          ? `${c.date} 개정 예정`
          : "개정 예정"
        : c.date
          ? `${c.date} 시행 예정`
          : "시행 예정"
      : "변경 예정";
  const revokedLabel = c.effective_status === "구법" ? "구법" : "폐지";

  // hideHeader 모드에서 status 정보(폐지/변경예정/법원·심급)만 displayTitle 위에 노출.
  // 출처 번호 [N]은 list chip이 이미 시각화하므로 본문에선 생략.
  const hasInlineStatus =
    isRevoked || isAmendedPending || Boolean(c.court || c.instance);
  const inlineBadges = hasInlineStatus ? (
    <>
      {isRevoked ? (
        <span className="rounded-pill bg-md-error-container px-2 py-0.5 text-[11px] font-semibold text-md-on-error-container">
          {revokedLabel}
        </span>
      ) : null}
      {isAmendedPending ? (
        <span className="rounded-pill bg-md-tertiary-fixed px-2 py-0.5 text-[11px] font-semibold text-md-on-tertiary-fixed-variant">
          {pendingLabel}
        </span>
      ) : null}
      {c.court || c.instance ? (
        <span className="rounded-pill bg-md-secondary-fixed px-2 py-0.5 text-[11px] font-semibold text-md-on-secondary-fixed-variant">
          {c.court}
          {c.instance ? ` ${c.instance}심` : ""}
        </span>
      ) : null}
    </>
  ) : null;

  return (
    <div className="vt-citation-card flex h-full flex-col" aria-label="Citation Inspector">
      {!hideHeader ? (
        <header className="flex h-12 items-center gap-2 border-b border-md-outline-variant px-3">
          <span className="text-body-sm font-semibold text-md-primary">[{c.number}]</span>
          <span className="text-body-sm font-semibold text-md-on-surface">Citation</span>
          {isRevoked ? (
            <span className="rounded-pill bg-md-error-container px-2 py-0.5 text-[11px] font-semibold text-md-on-error-container">
              {revokedLabel}
            </span>
          ) : null}
          {isAmendedPending ? (
            <span className="rounded-pill bg-md-tertiary-fixed px-2 py-0.5 text-[11px] font-semibold text-md-on-tertiary-fixed-variant">
              {pendingLabel}
            </span>
          ) : null}
          {c.court || c.instance ? (
            <span className="rounded-pill bg-md-secondary-fixed px-2 py-0.5 text-[11px] font-semibold text-md-on-secondary-fixed-variant">
              {c.court}
              {c.instance ? ` ${c.instance}심` : ""}
            </span>
          ) : null}
          {!hideCloseButton ? (
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
          ) : null}
        </header>
      ) : null}

      {/* 출처 리스트 — list 전체가 inspector 상단에 항상 떠 있음. list 안에서 활성 항목
          li가 sticky top-0 → 사용자가 list 스크롤해도 *선택한 항목은 항상 위에* 보임.
          활성 chip 다시 누르면 토글로 list-only 복귀. */}
      {allCitations.length > 1 ? (
        <div className="shrink-0 border-b border-md-outline-variant bg-md-surface-container-lowest">
          {!hideHeader ? (
            <button
              type="button"
              onClick={() => setListOpen((v) => !v)}
              aria-expanded={listOpen}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-label-caps text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low"
            >
              <span className="material-symbols-outlined text-[14px]" aria-hidden>
                list_alt
              </span>
              <span>다른 출처 보기 ({allCitations.length}건)</span>
              <span
                className="ml-auto material-symbols-outlined text-[16px]"
                aria-hidden
              >
                {listOpen ? "expand_less" : "expand_more"}
              </span>
            </button>
          ) : null}
          {hideHeader || listOpen ? (
            <ul
              ref={handleListRef}
              onScroll={handleListScroll}
              className={
                "overflow-y-auto py-1 " +
                (hideHeader ? "max-h-[180px]" : "max-h-44 border-t border-md-outline-variant")
              }
            >
              {orderedCitations.map((item, idx) => {
                const isActive = item.id === citationId;
                const itemRevoked = item.status === "revoked";
                const itemTitle = stripArticleNumPadding(
                  normalizeMetaField(item.title),
                );
                const prevTurnIdx = idx > 0 ? orderedCitations[idx - 1]!.turnIdx : -1;
                const showTurnHeader =
                  hasMultiTurn && item.turnIdx !== prevTurnIdx;
                return (
                  <li
                    key={item.id}
                    data-cid={item.id}
                    className={
                      // reorder + sticky 둘 다 — reorder로 array 첫 번째 = 항상 visible top,
                      // sticky로 다른 항목들이 스크롤될 때도 active li가 list 상단에 stuck.
                      isActive
                        ? "sticky top-0 z-10 bg-md-surface-container-lowest"
                        : ""
                    }
                  >
                    {showTurnHeader ? (
                      <div className="px-3 pb-0.5 pt-1.5 text-[10.5px] font-semibold text-md-on-surface-variant">
                        대화 {item.turnIdx + 1}
                      </div>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => selectCitation(item.id)}
                      title={isActive ? "다시 누르면 목록으로 돌아갑니다" : itemTitle}
                      className={
                        "flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-body-sm transition-colors " +
                        (isActive
                          ? "bg-md-secondary-fixed text-md-on-secondary-fixed-variant"
                          : "text-md-on-surface hover:bg-md-surface-container-low")
                      }
                    >
                      <span
                        className={
                          "shrink-0 font-semibold " +
                          (isActive ? "" : "text-md-primary")
                        }
                      >
                        [{item.number}]
                      </span>
                      {/* 출처 타입 라벨 — 본문 chip과 동일(citationLabel 공유). */}
                      <span
                        className={
                          "shrink-0 self-center rounded px-1 text-[10px] font-medium leading-none " +
                          (isActive
                            ? "bg-md-on-secondary-fixed-variant/15 text-md-on-secondary-fixed-variant"
                            : "bg-md-surface-container text-md-on-surface-variant")
                        }
                      >
                        {citationLabel(item)}
                      </span>
                      <span
                        className={
                          "min-w-0 flex-1 truncate " +
                          (itemRevoked ? "line-through" : "")
                        }
                        title={itemTitle}
                      >
                        {itemTitle}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="flex-1 overflow-y-auto p-card-padding">
        {hideHeader && inlineBadges ? (
          <div className="mb-2 flex flex-wrap items-center gap-1.5">{inlineBadges}</div>
        ) : null}
        <h2
          className={`text-h2 text-md-on-surface ${isRevoked ? "line-through" : ""}`}
          style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
        >
          {displayTitle}
        </h2>
        <ul className="mt-3 flex flex-col gap-1 text-body-sm text-md-on-surface-variant">
          {(() => {
            // article 응답이 있으면 department 우선 (정확), 없으면 c.publisher fallback
            const publisher = article?.department
              ? normalizeMetaField(article.department)
              : normalizeMetaField(c.publisher);
            return publisher ? (
              <li style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}>
                <span className="font-semibold">발행</span> · {publisher}
              </li>
            ) : null;
          })()}
          {(() => {
            const date = article?.enforce_date
              ? `시행 ${normalizeMetaField(article.enforce_date)}`
              : c.date
                ? normalizeMetaField(c.date)
                : "";
            return date ? (
              <li>
                <span className="font-semibold">일자</span> · {date}
              </li>
            ) : null;
          })()}
          {typeof c.page === "number" ? (
            <li>
              <span className="font-semibold">페이지</span> · p.{c.page}
            </li>
          ) : null}
          {c.doc_id ? (
            <li>
              <span className="font-semibold">문서 ID</span> ·{" "}
              <code className="break-all text-code">{c.doc_id}</code>
            </li>
          ) : null}
        </ul>

        {/* 액션 — 외부 링크·다운로드·근거 저장을 *본문 위*로(사용자 요청 "법령정보센터
            보기·다운로드 버튼을 본문 상위로"). 메타 직후 노출 → 사용자가 본문
            스크롤 전에 원문/다운로드/저장에 바로 접근. 근거 저장은 "법령정보센터에서
            보기"와 같은 행·같은 링크 톤으로 정렬해 헷갈리지 않게. */}
        <div className="mt-4 flex flex-wrap items-center gap-3">
            {annexAvailable ? (
              <button
                type="button"
                onClick={() => setAnnexArgs(annexAvailable)}
                className="inline-flex items-center gap-1 rounded-full bg-md-primary-fixed px-3 py-1.5 text-body-sm font-medium text-md-on-primary-fixed-variant transition-colors hover:bg-md-primary-fixed-dim"
              >
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  description
                </span>
                별표 미리보기
              </button>
            ) : null}
            {/* 별표/서식 HWP·PDF 직접 다운로드 — backend가 source_kind=doc +
                doc_category가 별표서식일 때 download_url 박음. */}
            {c.download_url && ANNEX_CATEGORIES.has(c.doc_category ?? "") ? (
              <a
                href={c.download_url}
                target="_blank"
                rel="noopener noreferrer"
                download
                className="inline-flex h-9 items-center gap-1.5 rounded-full border border-md-outline-variant px-4 text-[12.5px] font-medium text-md-on-surface transition-colors hover:border-md-on-surface hover:bg-md-surface-container-low"
              >
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  download
                </span>
                HWP 다운로드
              </a>
            ) : null}
            {/* 검색해서 확인한 그 서식으로 작성 — 보고서가 자체 검색으로 다른
                서식을 집는 것을 막는다(2026-08-26). 별표·서식 인용에만 노출. */}
            {/* 2026-09-08: 별표(기준표)는 기입 항목이 없는 게 대부분이라 직접 [작성]을
                두지 않는다 — 미리보기 모달이 기입 가능 여부를 판정해 버튼을 낸다. */}
            {onUseAsForm && ANNEX_CATEGORIES.has(c.doc_category ?? "") &&
             articleKeyFromCitation(c) && formDocKind(c.article, c.title) === "form" ? (
              <button
                type="button"
                onClick={() =>
                  onUseAsForm(articleKeyFromCitation(c)!, c.title ?? "")
                }
                title={formActionHint(formDocKind(c.article, c.title))}
                className="inline-flex h-9 items-center gap-1.5 rounded-full bg-md-primary px-4 text-[12.5px] font-semibold text-md-on-primary transition-colors hover:opacity-90"
              >
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  edit_document
                </span>
                {formActionLabel(formDocKind(c.article, c.title))}
              </button>
            ) : null}
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-body-sm text-md-secondary hover:underline"
              >
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  {kind === "law-portal" ? "gavel" : "north_east"}
                </span>
                {kind === "law-portal" ? "법령정보센터에서 보기" : "원문 새 탭에서 열기"}
              </a>
            ) : null}
            {/* 근거 라이브러리 저장 — 위 링크들과 같은 행·같은 링크 톤. */}
            <BookmarkButton citation={c} inline />
          </div>

        {/* 보고서 grounding 검증(`_ground_citations`) 표시 — supporting_quote/
            verified 부착된 보고서 citation에만 의미. verified=false면 "근거 확인
            필요", supporting_quote 있으면(verified=true) "검증된 근거" 박스로 명시
            노출 + 아래 본문에서 그 문장 하이라이트(NotebookLM-lite). */}
        {c.verified === false ? (
          <div className="mt-4 flex items-start gap-2 rounded-card border border-md-outline-variant bg-md-surface-container-low px-3 py-2.5">
            <span
              className="material-symbols-outlined mt-px text-[18px] text-md-on-surface-variant"
              aria-hidden
            >
              error
            </span>
            <div className="min-w-0">
              <span className="text-body-sm font-semibold text-md-on-surface">
                근거 확인 필요
              </span>
              <p className="text-[12.5px] leading-relaxed text-md-on-surface-variant">
                이 인용은 원문 문장과 자동 매칭되지 않았습니다. 원문을 직접 확인하세요.
              </p>
            </div>
          </div>
        ) : c.supporting_quote ? (
          <div className="mt-4 rounded-card border border-md-outline-variant bg-md-surface-container-lowest px-3 py-2.5">
            <div className="mb-1.5 flex items-center gap-1 text-[11.5px] font-semibold text-md-on-tertiary-fixed-variant">
              <span className="material-symbols-outlined text-[15px]" aria-hidden>
                verified
              </span>
              검증된 근거
            </div>
            <blockquote
              className="border-l-2 border-md-tertiary-fixed pl-2.5 text-body-sm leading-[1.6] text-md-on-surface"
              style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
            >
              {c.supporting_quote}
            </blockquote>
          </div>
        ) : feMatchedQuote ? (
          <div className="mt-4 flex items-center gap-1.5 text-[12px] font-medium text-md-on-tertiary-fixed-variant">
            <span className="material-symbols-outlined text-[15px]" aria-hidden>
              check_circle
            </span>
            답변에 쓰인 표현이 원문에서 확인됨 — 아래 본문에 표시
          </div>
        ) : null}

        {/* 본문 표시 우선순위:
            articleAvailable = *조 단위* key(cite_doc_)가 있을 때만 truthy.
            법령 전체(doc_id=law_id)로는 절대 fetch 안 함 — "전체 말고 그 조만".
            1) 조 단위 key + prefetch 진행 중 → spinner
            2) 조 단위 key + article.full_text 도착 → 그 조 본문
            3) 조 단위 key + article 실패(loading 끝남) → "본문을 불러오지 못했습니다"
            4) 조 단위 key 없음(web·접두어 없는 legacy 등) → c.snippet 그대로
               (= backend가 보낸 인용된 그 조 본문) */}
        {articleAvailable ? (
          articleLoading ? (
            <>
              <hr className="my-4 border-md-outline-variant" />
              <div className="flex items-center gap-2 px-1 py-6 text-body-sm text-md-on-surface-variant">
                <span
                  className="inline-block size-4 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin"
                  aria-hidden
                />
                <span>본문을 불러오는 중...</span>
              </div>
            </>
          ) : article?.full_text && article.full_text.trim().length > 0 ? (
            <>
              <hr className="my-4 border-md-outline-variant" />
              <div className="border-l-2 border-md-secondary-fixed pl-3">
                {/* compact — 좁은 우측 패널에서 조문·별표 원문 가독성(폰트·행간 축소) */}
                <MarkdownContent content={article.full_text} compact />
              </div>
            </>
          ) : (
            <>
              <hr className="my-4 border-md-outline-variant" />
              <p className="px-1 py-4 text-body-sm text-md-on-surface-variant">
                본문을 불러오지 못했습니다. 위 “법령정보센터에서 보기”로 원문을 확인하세요.
              </p>
            </>
          )
        ) : c.snippet ? (
          <>
            <hr className="my-4 border-md-outline-variant" />
            {c.source_kind === "web" ? (
              <p className="mb-1.5 text-[11.5px] font-medium text-md-on-surface-variant">
                웹 본문 발췌 — 전체 아님. 원문은 위 링크에서 확인하세요.
              </p>
            ) : null}
            <blockquote
              className="whitespace-pre-wrap border-l-2 border-md-secondary-fixed pl-3 text-body-base leading-[1.7] text-md-on-surface"
              style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
            >
              {/* 하이라이트 대상: 보고서 grounding supporting_quote(verified≠false)
                  우선, 없으면 챗 FE 매칭(feMatchedQuote). 둘 다 없으면 평문. */}
              {(() => {
                const hl =
                  (c.verified !== false && c.supporting_quote) ||
                  feMatchedQuote ||
                  undefined;
                const body = preprocessLawText(snippetParts.body || c.snippet);
                return hl ? highlightSupportingQuote(body, hl) : body;
              })()}
              {/* 웹 발췌는 페이지 본문 일부 — 끊겨있음을 시각적으로(…). 원문
                  텍스트는 그대로 두고 truncation 마커만 별도 노출 (가공 X). */}
              {c.source_kind === "web" ? (
                <span className="text-md-on-surface-variant" aria-hidden>
                  {" "}
                  …
                </span>
              ) : null}
            </blockquote>
          </>
        ) : null}

      </div>

      <AnnexModal
        args={annexArgs}
        onClose={() => setAnnexArgs(null)}
        onUseAsForm={onUseAsForm}
      />
    </div>
  );
}
