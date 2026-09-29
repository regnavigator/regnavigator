"use client";

/**
 * LegalDocPage — 약관·개인정보처리방침을 백엔드 정본(`GET /legal/{doc}`)에서
 * 받아 렌더. 본문을 프런트에 하드코딩하면 두 벌이 되어 실제 동작과 어긋난다
 * (실제로 §3 보유기간·§5 이전받는 자가 어긋나 있었다 — medi-back
 * docs/frontend_legal_handoff.md §2).
 *
 * - markdown → react-markdown(remark-gfm). H1은 LegalShell 타이틀과 중복이라 숨김.
 * - YAML frontmatter는 표시 전 제거(effective_date만 추출해 시행일 표기).
 * - 조회 실패 시 안내 + 재시도 — 공개 페이지라 백엔드 다운이어도 빈 화면은 금지.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { LegalShell } from "@/components/legal/LegalShell";
import { fetchLegalDocument, type LegalDocId } from "@/lib/client/legal";

/** frontmatter 제거 + effective_date 추출. */
function splitFrontmatter(raw: string): { body: string; effectiveDate?: string } {
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  if (!m) return { body: raw };
  const fm = m[1] ?? "";
  const eff = fm.match(/^effective_date:\s*(.+)$/m)?.[1]?.trim();
  return { body: raw.slice(m[0].length), effectiveDate: eff };
}

const mdComponents: Components = {
  // 문서 타이틀은 LegalShell이 렌더 — 본문 h1은 중복이라 숨김
  h1: () => null,
  h2: ({ children }) => (
    <h2 className="mt-8 text-[17px] font-semibold text-md-on-surface first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-5 text-[15px] font-semibold text-md-on-surface">{children}</h3>
  ),
  p: ({ children }) => (
    <p className="text-[14px] leading-[1.8] text-md-on-surface-variant">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-md-on-surface">{children}</strong>
  ),
  ul: ({ children }) => (
    <ul className="flex list-disc flex-col gap-1 pl-5 text-[14px] leading-[1.8] text-md-on-surface-variant">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="flex list-decimal flex-col gap-1 pl-5 text-[14px] leading-[1.8] text-md-on-surface-variant">
      {children}
    </ol>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="font-medium text-md-primary underline-offset-2 hover:underline"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-md-outline-variant bg-md-surface-container-low px-4 py-2.5 text-[13px] leading-relaxed text-md-on-surface-variant">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-md-outline-variant" />,
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13.5px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-md-outline-variant bg-md-surface-container-low px-3 py-2 text-left font-semibold text-md-on-surface">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-md-outline-variant px-3 py-2 leading-[1.7] text-md-on-surface-variant">
      {children}
    </td>
  ),
};

export function LegalDocPage({
  doc,
  title,
  subtitle,
}: {
  doc: LegalDocId;
  title: string;
  subtitle?: string;
}) {
  const [state, setState] = useState<
    | { phase: "loading" }
    | { phase: "error" }
    | { phase: "ready"; body: string; version: string; effectiveDate?: string }
  >({ phase: "loading" });

  const load = useCallback(() => {
    setState({ phase: "loading" });
    fetchLegalDocument(doc)
      .then((res) => {
        const { body, effectiveDate } = splitFrontmatter(res.content);
        setState({ phase: "ready", body, version: res.version, effectiveDate });
      })
      .catch((err) => {
        console.error(`[legal] ${doc} 정본 조회 실패`, err);
        setState({ phase: "error" });
      });
  }, [doc]);

  useEffect(() => {
    load();
  }, [load]);

  let content: ReactNode;
  if (state.phase === "loading") {
    content = (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="문서 불러오는 중">
        {[64, 96, 80, 96, 72].map((h, i) => (
          <div
            key={i}
            className="animate-pulse rounded-card bg-md-surface-container-low"
            style={{ height: h }}
          />
        ))}
      </div>
    );
  } else if (state.phase === "error") {
    content = (
      <div className="flex flex-col items-start gap-3 rounded-card border border-md-outline-variant bg-md-surface-container-low px-5 py-6">
        <p className="text-[14px] leading-relaxed text-md-on-surface">
          문서를 불러오지 못했습니다. 네트워크 상태를 확인한 뒤 다시 시도해주세요.
        </p>
        <p className="text-[12.5px] text-md-on-surface-variant">
          계속 실패하면 서비스 내 문의 기능으로 알려주세요.
        </p>
        <button
          type="button"
          onClick={load}
          className="inline-flex h-9 items-center gap-1.5 rounded-full border border-md-outline-variant px-4 text-[13px] font-medium text-md-on-surface transition-colors hover:bg-md-surface-container"
        >
          <span className="material-symbols-outlined text-[16px]" aria-hidden>
            refresh
          </span>
          다시 시도
        </button>
      </div>
    );
  } else {
    content = (
      <div className="flex flex-col gap-4">
        {/* singleTilde:false — "18~24개월" 류 홑물결 범위 표기가 취소선으로 먹히는 것 방지 */}
        <ReactMarkdown
          remarkPlugins={[[remarkGfm, { singleTilde: false }]]}
          components={mdComponents}
        >
          {state.body}
        </ReactMarkdown>
      </div>
    );
  }

  return (
    <LegalShell
      title={title}
      subtitle={subtitle}
      effectiveDate={
        state.phase === "ready"
          ? (state.effectiveDate ?? state.version)
          : undefined
      }
    >
      {content}
    </LegalShell>
  );
}
