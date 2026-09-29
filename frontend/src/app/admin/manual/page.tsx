"use client";

/**
 * Admin · 운영 매뉴얼 — 운영진 기능 설명서 (2026-09-23).
 *
 * 서비스 기능 설명서(기능·위치·제한). 원본은 backend
 * `docs/product/ops_feature_manual.md` 하나 — `GET /admin/ops-manual` 이 그대로 주고
 * 여기서 렌더만 한다(복사본을 두지 않아 문서를 고치면 배포와 함께 화면도 바뀐다).
 * 기능 권한과 무관하게 모든 관리자가 본다.
 */

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { getOpsManual } from "@/lib/client/admin";
import { ErrorBanner, Spinner } from "@/components/admin/common";

function slug(text: string): string {
  return "m-" + text.replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "");
}

function plain(children: React.ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(plain).join("");
  if (children && typeof children === "object" && "props" in children) {
    return plain((children as { props: { children?: React.ReactNode } }).props.children);
  }
  return "";
}

const components: Components = {
  h1: () => null, // 제목은 페이지 헤더가 맡는다
  h2: ({ children }) => (
    <h2
      id={slug(plain(children))}
      className="mt-10 scroll-mt-4 border-b border-md-outline-variant pb-2 text-[19px] font-bold text-md-on-surface first:mt-0"
    >
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-6 text-[15px] font-semibold text-md-primary">{children}</h3>
  ),
  p: ({ children }) => <p className="my-2 max-w-[78ch] leading-7">{children}</p>,
  ul: ({ children }) => <ul className="my-2 max-w-[78ch] list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 max-w-[78ch] list-decimal space-y-1 pl-5">{children}</ol>,
  blockquote: ({ children }) => (
    <blockquote className="my-3 rounded-md bg-md-surface-container px-4 py-2 text-md-on-surface-variant">
      {children}
    </blockquote>
  ),
  code: ({ children }) => (
    <code className="rounded bg-md-surface-container px-1 py-0.5 font-mono text-[0.88em]">{children}</code>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-md-outline-variant">
      <table className="w-full border-collapse text-[13.5px] leading-6">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="whitespace-nowrap border-b border-md-outline-variant bg-md-surface-container px-3 py-2 text-left text-[12.5px] font-semibold text-md-on-surface-variant">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="min-w-[7rem] border-b border-md-outline-variant px-3 py-2 align-top">{children}</td>
  ),
  hr: () => null,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-md-primary underline">
      {children}
    </a>
  ),
};

export default function OpsManualPage() {
  const [doc, setDoc] = useState<{ markdown: string; updated_at: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getOpsManual()
      .then(setDoc)
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : "매뉴얼을 불러오지 못했습니다."));
  }, []);

  const toc = useMemo(
    () =>
      (doc?.markdown.match(/^## .+$/gm) ?? []).map((l) => {
        const t = l.slice(3).trim();
        return { t, id: slug(t) };
      }),
    [doc],
  );

  if (err) return <ErrorBanner message={err} />;
  if (!doc) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav aria-label="매뉴얼 목차" className="self-start text-[13px] lg:sticky lg:top-4">
        <p className="mb-2 text-label-caps text-md-on-surface-variant">목차</p>
        <ol className="grid gap-0.5">
          {toc.map((h) => (
            <li key={h.id}>
              <a
                href={`#${h.id}`}
                className="block rounded px-2 py-1 text-md-on-surface-variant hover:bg-md-surface-container hover:text-md-on-surface"
              >
                {h.t}
              </a>
            </li>
          ))}
        </ol>
      </nav>
      <article className="min-w-0 text-[14.5px] text-md-on-surface">
        <header className="mb-6">
          <h1 className="text-[22px] font-bold">운영진 기능 설명서</h1>
          <p className="mt-1 text-body-sm text-md-on-surface-variant">
            MEDIREG AI의 기능이 무엇을 하는지, 화면 어디에 있는지, 어떤 제한이 있는지 정리한 문서입니다. · 최종 수정{" "}
            {new Date(doc.updated_at).toLocaleDateString("ko-KR")}
          </p>
        </header>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {doc.markdown}
        </ReactMarkdown>
      </article>
    </div>
  );
}
