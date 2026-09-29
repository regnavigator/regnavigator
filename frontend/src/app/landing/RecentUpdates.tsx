"use client";

/**
 * 랜딩에서 업데이트 내용을 바로 보는 두 자리(2026-09-02 요청 "랜딩에서 볼 방법").
 *
 * - variant="ticker": Hero CTA 아래 한 줄 — 최신 노트 1건(버전·제목) → /updates#id.
 * - variant="section": 푸터 앞 "최근 업데이트" 섹션 — 최신 3건 카드(버전·날짜·제목·
 *   항목 2줄) + [전체 업데이트 보기]. 카드 클릭 → 게시판의 그 노트로.
 *
 * 데이터는 same-origin 프록시(/api/announcements) — 비로그인·타 출처에서도 동작.
 * 실패하거나 0건이면 조용히 숨긴다(랜딩이 빈 카드로 어색해지지 않게).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { listPublicAnnouncements, type AnnouncementNote } from "@/lib/client/quota";

function useRecent(limit: number) {
  const [notes, setNotes] = useState<AnnouncementNote[] | null>(null);
  useEffect(() => {
    let alive = true;
    void listPublicAnnouncements("", limit)
      .then((items) => alive && setNotes(items))
      .catch(() => alive && setNotes([]));
    return () => {
      alive = false;
    };
  }, [limit]);
  return notes;
}

export function RecentUpdates({ variant }: { variant: "ticker" | "section" }) {
  const notes = useRecent(variant === "ticker" ? 1 : 3);
  if (!notes || notes.length === 0) return null;

  if (variant === "ticker") {
    const n = notes[0]!;
    return (
      <Link
        href={`/updates#${n.id}`}
        className="mt-8 inline-flex max-w-[92vw] items-center gap-2.5 rounded-full border border-md-outline-variant bg-md-surface-container-low py-2 pl-2.5 pr-4 text-[13.5px] text-md-on-surface-variant transition-colors hover:border-md-primary/50 hover:text-md-on-surface"
      >
        <span className="rounded-full bg-md-primary px-2.5 py-0.5 font-mono text-[11.5px] font-semibold text-md-on-primary">
          {n.version ?? "NEW"}
        </span>
        <span className="truncate">{n.title}</span>
        <span className="material-symbols-outlined shrink-0 text-[16px]" aria-hidden>
          arrow_forward
        </span>
      </Link>
    );
  }

  return (
    <section className="flex min-h-screen snap-start flex-col items-center justify-center px-8 py-16 sm:px-16">
      <div className="mx-auto w-full max-w-[1100px]">
        <div className="text-center">
          <span
            className="text-[11px] font-semibold uppercase tracking-[0.16em] text-md-primary"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            08 · What&apos;s new
          </span>
          <h2
            className="mt-5 text-[34px] font-bold leading-[1.15] tracking-tight text-md-on-surface sm:text-[44px]"
            style={{ letterSpacing: "-0.025em" }}
          >
            <span>매주 </span>
            <span className="theme-grad-text">좋아지고 있습니다.</span>
          </h2>
          <p className="mx-auto mt-8 max-w-[600px] text-[17px] leading-[1.8] text-md-on-surface-variant">
            최근 들어온 기능과 고쳐진 점입니다. 기다리던 기능이 있는지 키워드로도 찾아볼 수 있습니다.
          </p>
        </div>

        <ol className="mt-16 grid grid-cols-1 gap-6 lg:grid-cols-3 [&>*:last-child:nth-child(odd)]:lg:col-span-1">
          {notes.map((n) => (
            <li key={n.id}>
              <Link
                href={`/updates#${n.id}`}
                className="group flex h-full flex-col rounded-card border border-md-outline-variant bg-md-surface-container-low transition-all duration-200 hover:-translate-y-0.5 hover:border-md-primary/50 hover:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.25)]"
              >
                <div className="border-b border-md-outline-variant px-7 py-5">
                  <div className="flex items-center gap-3 text-[13px] text-md-on-surface-variant">
                    {n.version ? (
                      <span className="rounded-full bg-md-primary-container px-2.5 py-0.5 font-mono text-[11.5px] font-semibold text-md-on-primary-container">
                        {n.version}
                      </span>
                    ) : null}
                    <time dateTime={n.date}>{n.date}</time>
                  </div>
                  <h3 className="mt-3 break-keep text-[17.5px] font-bold leading-[1.4] text-md-on-surface [overflow-wrap:anywhere]">
                    {n.title}
                  </h3>
                </div>
                <ul className="flex flex-1 flex-col gap-3 px-7 py-5">
                  {n.items.slice(0, 2).map((it, i) => (
                    <li key={i} className="flex gap-3 text-[14.5px] leading-[1.7] text-md-on-surface-variant">
                      <span aria-hidden className="mt-[0.65em] h-1.5 w-1.5 shrink-0 rounded-full bg-md-primary" />
                      <span className="line-clamp-2 min-w-0 break-keep [overflow-wrap:anywhere]">{it}</span>
                    </li>
                  ))}
                  {n.items.length > 2 ? (
                    <li className="text-[13px] text-md-on-surface-variant/80">외 {n.items.length - 2}건</li>
                  ) : null}
                </ul>
                <span className="inline-flex items-center gap-1 px-7 pb-5 text-[13px] font-semibold text-md-primary">
                  자세히
                  <span className="material-symbols-outlined text-[16px] transition-transform group-hover:translate-x-0.5" aria-hidden>
                    arrow_forward
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ol>

        <div className="mt-14 flex justify-center">
          <Link
            href="/updates"
            className="inline-flex h-12 items-center gap-2 rounded-full border border-md-outline-variant bg-md-surface px-7 text-[15px] font-semibold text-md-on-surface transition-all hover:-translate-y-0.5 hover:border-md-primary/50"
          >
            전체 업데이트 보기 · 키워드 검색
            <span className="material-symbols-outlined text-[18px]" aria-hidden>
              arrow_forward
            </span>
          </Link>
        </div>
      </div>
    </section>
  );
}
