"use client";

/**
 * 이메일 본문 프리뷰 — dev 디자인 점검용.
 *
 * 실제 발송되는 인증 메일을 그대로 렌더. 본문 함수는 `lib/email-template`에서
 * import — 발송(lib/auth.ts)과 프리뷰가 영원히 동기.
 *
 * 접근: /auth/email-preview (middleware 화이트리스트 추가 필요)
 */

import { APP_HOST, APP_URL } from "@/lib/site";
import Link from "next/link";
import {
  EMAIL_FROM_DEFAULT,
  EMAIL_SUBJECT,
  PREVIEW_BG,
  htmlBody,
  textBody,
} from "@/lib/email-template";

const SAMPLE_URL =
  `${APP_URL}/api/auth/callback/email?callbackUrl=%2F&token=abc123def456&email=you%40example.com`;
const SAMPLE_HOST = APP_HOST;
const SAMPLE_TO = "you@example.com";

export default function EmailPreviewPage() {
  const html = htmlBody(SAMPLE_URL, SAMPLE_HOST);
  const text = textBody(SAMPLE_URL, SAMPLE_HOST);

  return (
    <main className="min-h-screen bg-md-surface px-6 py-8 text-md-on-surface sm:px-10">
      <div className="mx-auto flex max-w-[1100px] flex-col gap-6">
        {/* 헤더 */}
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-col gap-1">
            <span
              className="text-[11px] font-semibold uppercase tracking-[0.12em] text-md-primary"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              dev · email preview
            </span>
            <h1
              className="text-[26px] font-bold tracking-tight text-md-on-surface"
              style={{ letterSpacing: "-0.02em" }}
            >
              인증 메일 프리뷰
            </h1>
            <p className="text-[13px] leading-relaxed text-md-on-surface-variant">
              실제 발송되는 본문 — <code className="rounded bg-md-surface-container-low px-1.5 py-0.5 text-[11.5px]">lib/email-template.ts</code>를
              수정하면 메일·프리뷰가 동시에 갱신됩니다.
            </p>
          </div>
          <Link
            href="/login"
            className="inline-flex h-9 items-center gap-1.5 rounded-full border border-md-outline-variant px-4 text-[12.5px] font-medium text-md-on-surface transition-colors hover:bg-md-surface-container-low"
          >
            <span className="material-symbols-outlined text-[14px]" aria-hidden>
              arrow_back
            </span>
            로그인으로
          </Link>
        </header>

        {/* 메일 헤더 메타 */}
        <div className="grid grid-cols-1 gap-3 rounded-card border border-md-outline-variant bg-md-surface-container-low px-5 py-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetaCell label="From" value={EMAIL_FROM_DEFAULT} />
          <MetaCell label="To" value={SAMPLE_TO} />
          <MetaCell label="Subject" value={EMAIL_SUBJECT} />
          <MetaCell label="Host" value={SAMPLE_HOST} />
        </div>

        {/* HTML preview */}
        <section className="flex flex-col gap-2">
          <h2
            className="text-[11px] font-semibold uppercase tracking-[0.12em] text-md-on-surface-variant"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            HTML 본문
          </h2>
          <div className="overflow-hidden rounded-card border border-md-outline-variant">
            <iframe
              title="인증 메일 HTML 프리뷰"
              srcDoc={html}
              className="block w-full"
              style={{ height: "720px", background: PREVIEW_BG, border: 0 }}
            />
          </div>
        </section>

        {/* Plain text fallback */}
        <section className="flex flex-col gap-2">
          <h2
            className="text-[11px] font-semibold uppercase tracking-[0.12em] text-md-on-surface-variant"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            Plain text fallback
          </h2>
          <pre
            className="overflow-auto whitespace-pre-wrap rounded-card border border-md-outline-variant bg-md-surface-container-low px-5 py-4 text-[13px] leading-relaxed text-md-on-surface"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {text}
          </pre>
        </section>

        <p className="text-[11.5px] leading-relaxed text-md-on-surface-variant">
          이 페이지는 개발 점검용입니다. 운영 발송 본문은{" "}
          <code className="rounded bg-md-surface-container-low px-1.5 py-0.5 text-[10.5px]">
            src/lib/email-template.ts
          </code>{" "}
          단일 진실원천 — 디자인 변경 시 그 파일만 수정하면 본 프리뷰와
          실제 메일이 함께 갱신됩니다.
        </p>
      </div>
    </main>
  );
}

function MetaCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span
        className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-md-on-surface-variant"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {label}
      </span>
      <span className="truncate text-[13px] font-medium text-md-on-surface">
        {value}
      </span>
    </div>
  );
}
