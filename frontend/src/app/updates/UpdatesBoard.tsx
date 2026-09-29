"use client";

/**
 * 업데이트 내역 목록 + 키워드 검색 (2026-09-02).
 *
 * 목록은 최대 100건이라 한 번 받아 두고 클라이언트에서 거른다 — 타이핑마다
 * 왕복하지 않고, 검색어는 URL(?q=)에 실어 공유·뒤로가기가 된다. 서버 `q`
 * 파라미터도 같은 규칙(공백 구분 AND, 제목+항목 부분 일치)이라 첫 로드는
 * URL 의 q 로 서버 검색, 이후는 로컬 필터. 매치 구간은 <mark> 강조.
 *
 * 팝업 [업데이트 목록 보기]는 `/updates#<note id>` 로 오므로 로드 후 해당
 * 카드로 스크롤·하이라이트.
 *
 * 2026-09-07 기능 단위 전환(사용자 지적: "버전별 릴리스 노트라 사용자 대상이
 * 아니다"): 노트 하나 = 기능 하나의 변화. 상단에 기능 탭(전체·검색·답변·심층
 * 보고서·…)을 두고 `?f=` 로 URL 동기화. 카드 첫 줄은 기능 배지, 버전은 보조.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ANNOUNCEMENT_FEATURES,
  listPublicAnnouncements,
  type AnnouncementNote,
} from "@/lib/client/quota";

function tokens(q: string): string[] {
  return q
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.trim())
    .filter(Boolean)
    .slice(0, 8);
}

function matches(n: AnnouncementNote, toks: string[]): boolean {
  if (!toks.length) return true;
  const hay = [n.title, n.version ?? "", n.feature ?? "", ...n.items].join(" ").toLowerCase();
  return toks.every((t) => hay.includes(t));
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 매치 토큰을 <mark> 로 감싼다 — 검색 결과에서 "왜 걸렸는지" 바로 보이게. */
function Highlight({ text, toks }: { text: string; toks: string[] }) {
  if (!toks.length) return <>{text}</>;
  const re = new RegExp(`(${toks.map(escapeRe).join("|")})`, "gi");
  const parts = text.split(re);
  return (
    <>
      {parts.map((p, i) =>
        toks.some((t) => t === p.toLowerCase()) ? (
          <mark
            key={i}
            className="rounded-[3px] bg-md-primary-fixed px-0.5 text-md-on-primary-fixed-variant"
          >
            {p}
          </mark>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

export function UpdatesBoard() {
  const router = useRouter();
  const params = useSearchParams();
  const initialQ = params.get("q") ?? "";
  const [q, setQ] = useState(initialQ);
  const [feature, setFeature] = useState(params.get("f") ?? "");
  const [notes, setNotes] = useState<AnnouncementNote[] | null>(null);
  const [error, setError] = useState(false);

  // 최초 1회 전체 로드(서버는 숨김 제외·최신순). 검색은 로컬.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const items = await listPublicAnnouncements();
        if (alive) setNotes(items);
      } catch {
        if (alive) setError(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // URL ?q=&f= 동기화 — 공유·뒤로가기. 타이핑마다 히스토리를 쌓지 않게 replace.
  useEffect(() => {
    const curQ = params.get("q") ?? "";
    const curF = params.get("f") ?? "";
    if (curQ === q && curF === feature) return;
    const t = window.setTimeout(() => {
      const qs = new URLSearchParams();
      if (q) qs.set("q", q);
      if (feature) qs.set("f", feature);
      const s = qs.toString();
      router.replace(s ? `/updates?${s}` : "/updates", { scroll: false });
    }, 250);
    return () => window.clearTimeout(t);
  }, [q, feature, params, router]);

  // 팝업에서 #note_id 로 들어온 경우 — 로드 뒤 해당 카드로.
  useEffect(() => {
    if (!notes || !window.location.hash) return;
    const el = document.getElementById(window.location.hash.slice(1));
    if (!el) return;
    el.scrollIntoView({ block: "start", behavior: "smooth" });
    el.classList.add("ring-2", "ring-md-primary/50");
    const t = window.setTimeout(() => el.classList.remove("ring-2", "ring-md-primary/50"), 2400);
    return () => window.clearTimeout(t);
  }, [notes]);

  const toks = useMemo(() => tokens(q), [q]);
  // 탭 목록: 실제 노트가 있는 기능만, 정해진 순서(ANNOUNCEMENT_FEATURES) + 목록 밖 값은 뒤에.
  const features = useMemo(() => {
    const present = new Set((notes ?? []).map((n) => (n.feature ?? "").trim()).filter(Boolean));
    const ordered = ANNOUNCEMENT_FEATURES.filter((f) => present.has(f));
    const extra = [...present].filter((f) => !(ANNOUNCEMENT_FEATURES as readonly string[]).includes(f));
    return [...ordered, ...extra];
  }, [notes]);
  const shown = useMemo(
    () =>
      (notes ?? []).filter(
        (n) => (!feature || (n.feature ?? "") === feature) && matches(n, toks),
      ),
    [notes, toks, feature],
  );

  return (
    <section className="mt-12">
      {/* 기능 탭 — 기능 단위로 훑는다. 전체 + 노트가 있는 기능만 */}
      {features.length ? (
        <nav aria-label="기능별 보기" className="-mx-1 flex flex-wrap gap-1.5 px-1">
          {["", ...features].map((f) => {
            const on = feature === f;
            return (
              <button
                key={f || "__all"}
                type="button"
                onClick={() => setFeature(f)}
                aria-pressed={on}
                className={
                  "inline-flex h-9 items-center rounded-full border px-4 text-[13.5px] font-semibold transition-colors " +
                  (on
                    ? "border-md-primary bg-md-primary text-md-on-primary"
                    : "border-md-outline-variant bg-md-surface-container-lowest text-md-on-surface-variant hover:border-md-outline hover:text-md-on-surface")
                }
              >
                {f || "전체"}
              </button>
            );
          })}
        </nav>
      ) : null}

      {/* 검색 */}
      <label className="mt-2 flex items-center gap-2.5 rounded-[14px] border border-md-outline-variant bg-md-surface-container-lowest px-4 py-3 focus-within:border-md-primary">
        <span className="material-symbols-outlined text-[20px] text-md-on-surface-variant" aria-hidden>
          search
        </span>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="키워드로 찾기 — 예: 보고서 중단, 서식, IRB, 첨부"
          aria-label="업데이트 내역 검색"
          className="min-w-0 flex-1 bg-transparent text-[16px] text-md-on-surface outline-none placeholder:text-md-on-surface-variant/60"
        />
        {q ? (
          <button
            type="button"
            onClick={() => setQ("")}
            className="rounded-full px-2 py-0.5 text-[12px] text-md-on-surface-variant hover:bg-md-surface-container hover:text-md-on-surface"
          >
            지우기
          </button>
        ) : null}
      </label>

      {/* 상태 */}
      <p className="mt-3 text-[12.5px] text-md-on-surface-variant" aria-live="polite">
        {error
          ? "목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."
          : notes === null
            ? "불러오는 중…"
            : toks.length || feature
              ? `${feature ? `[${feature}] ` : ""}${toks.length ? "검색 결과 " : ""}${shown.length}건 / 전체 ${notes.length}건`
              : `전체 ${notes.length}건`}
      </p>

      {/* 목록 */}
      <ol className="mt-8 flex flex-col gap-8">
        {shown.map((n) => (
          <li
            key={n.id}
            id={n.id}
            className="scroll-mt-24 overflow-hidden rounded-[16px] border border-md-outline-variant bg-md-surface-container-lowest transition-shadow"
          >
            {/* 헤더 블록 — 버전·날짜 한 줄 + 제목. 본문과 배경·구분선으로 분리(2026-09-02 가독성 지적) */}
            <header className="border-b border-md-outline-variant bg-md-surface-container-low px-8 py-7">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13.5px] text-md-on-surface-variant">
                {n.feature ? (
                  <button
                    type="button"
                    onClick={() => setFeature(n.feature ?? "")}
                    title={`${n.feature} 만 보기`}
                    className="inline-flex items-center rounded-full bg-md-primary-container px-2.5 py-0.5 text-[12px] font-semibold text-md-on-primary-container transition-opacity hover:opacity-85"
                  >
                    <Highlight text={n.feature} toks={toks} />
                  </button>
                ) : null}
                <time dateTime={n.date}>{n.date}</time>
                {n.version ? (
                  <span className="font-mono text-[11.5px] text-md-on-surface-variant/80">
                    <Highlight text={n.version} toks={toks} />
                  </span>
                ) : null}
              </div>
              <h2 className="mt-3 min-w-0 break-keep text-[22px] font-bold leading-[1.35] tracking-[-0.01em] text-md-on-surface [overflow-wrap:anywhere]">
                <Highlight text={n.title} toks={toks} />
              </h2>
            </header>
            <ul className="flex flex-col gap-4 px-8 py-7">
              {n.items.map((it, i) => (
                <li key={i} className="flex gap-3.5 text-[16px] leading-[1.8] text-md-on-surface">
                  <span aria-hidden className="mt-[0.7em] h-1.5 w-1.5 shrink-0 rounded-full bg-md-primary" />
                  <span className="min-w-0 break-keep text-pretty [overflow-wrap:anywhere]">
                    <Highlight text={it} toks={toks} />
                  </span>
                </li>
              ))}
            </ul>
          </li>
        ))}
        {notes && shown.length === 0 && !error ? (
          <li className="rounded-[14px] border border-dashed border-md-outline-variant px-5 py-10 text-center text-[14px] text-md-on-surface-variant">
            {toks.length || feature
              ? "일치하는 업데이트가 없습니다. 다른 키워드로 찾아보거나, 아직 없는 기능이면 피드백으로 알려주세요."
              : "아직 발행된 업데이트가 없습니다."}
          </li>
        ) : null}
      </ol>
    </section>
  );
}
