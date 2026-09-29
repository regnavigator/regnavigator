"use client";

/**
 * CiteHighlightContext — 본문 인용 칩 ↔ References 목록 상호 하이라이트.
 *
 * MarkdownContent(본문 칩)와 CitationFootnotes / ReportPreviewDialog(References
 * 목록)가 같은 부모 안에서 hover 상태(hovered: 번호)를 공유해 서로를 강조한다.
 *  - 칩 hover  → 같은 번호 References 항목 강조
 *  - 항목 hover → 같은 번호 본문 칩 전부 강조
 *  - 항목 click → 본문 첫 해당 칩으로 스크롤 + 짧은 pulse
 *
 * Provider는 `display:contents` wrapper로 레이아웃에 영향 없이 스코프 root를
 * 잡는다(scrollTo가 이 root 안에서만 칩을 찾아 여러 turn 간 오염 방지).
 * Provider가 없으면 no-op — 개별 컴포넌트는 provider 밖에서도 안전하게 동작.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type CiteHighlightValue = {
  hovered: number | null;
  setHovered: (n: number | null) => void;
  scrollTo: (n: number) => void;
};

const NOOP: CiteHighlightValue = {
  hovered: null,
  setHovered: () => {},
  scrollTo: () => {},
};

const CiteHighlightContext = createContext<CiteHighlightValue>(NOOP);

export function useCiteHighlight(): CiteHighlightValue {
  return useContext(CiteHighlightContext);
}

export function CiteHighlightProvider({ children }: { children: ReactNode }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  const scrollTo = useCallback((n: number) => {
    const root = rootRef.current;
    if (!root) return;
    const chips = root.querySelectorAll<HTMLElement>(`[data-cite-n="${n}"]`);
    if (chips.length === 0) return;
    chips[0]!.scrollIntoView({ behavior: "smooth", block: "center" });
    chips.forEach((c) => {
      c.classList.remove("cite-pulse");
      // reflow로 애니메이션 재시작 보장 (연속 클릭 시)
      void c.offsetWidth;
      c.classList.add("cite-pulse");
      window.setTimeout(() => c.classList.remove("cite-pulse"), 1300);
    });
  }, []);

  const value = useMemo<CiteHighlightValue>(
    () => ({ hovered, setHovered, scrollTo }),
    [hovered, scrollTo],
  );

  return (
    <CiteHighlightContext.Provider value={value}>
      <div ref={rootRef} className="contents">
        {children}
      </div>
    </CiteHighlightContext.Provider>
  );
}
