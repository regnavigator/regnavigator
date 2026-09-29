"use client";

/**
 * LiveSearchGlass — ✨ 검색 과정 라이브 시각화 (2026-07-16 킥).
 *
 * 답변 대기 구간에서 *실제* SSE 이벤트(검색 쿼리·히트 문서)가 글라스 카드
 * 위로 실시간 흘러 쌓이는 피드. 가짜 연출이 아니라 backend `_emit_result`
 * (tool_progress phase="result")가 흘리는 진짜 수집 과정이 보인다.
 *
 * - 헤더: 레이더 펄스 + "실시간 근거 수집" + 라이브 진행 한 줄(shimmer).
 * - 쿼리 행: 현재 running step의 input_preview (있을 때만).
 * - 피드: 최근 도착 5건 — 새 항목은 아래에서 blur→선명 상승(live-item-in),
 *   오래된 것은 위로 밀리며 서서히 딤. 상단 mask로 페이드아웃.
 * - 기존 Turn.tsx의 컴팩트 리스트(UX 배치 #1)를 대체. reduced-motion은
 *   전역 미디어 쿼리가 애니메이션 정지.
 */

export type LiveResult = {
  tool: string;
  index: number;
  title: string;
  subtitle?: string;
  url?: string;
};

type Props = {
  results: LiveResult[];
  /** 현재 running step의 검색 쿼리 (input_preview) */
  query?: string | null;
  /** backend 라이브 진행 한 줄 ("리랭킹 중…" 등) */
  progress?: string | null;
};

const VISIBLE = 5;

export function LiveSearchGlass({ results, query, progress }: Props) {
  if (results.length === 0 && !query && !progress) return null;
  const tail = results.slice(-VISIBLE);
  const total = results.length;

  return (
    <section
      aria-label="검색 결과 수신 중"
      aria-live="polite"
      className="live-glass px-4 py-3"
    >
      <div className="flex items-center gap-2.5">
        <span className="live-radar" aria-hidden>
          <span />
        </span>
        <span className="text-[12px] font-semibold tracking-[0.04em] text-md-on-surface">
          실시간 근거 수집
        </span>
        {total > 0 ? (
          <span className="rounded-pill bg-md-primary-fixed px-1.5 py-0.5 font-mono text-[10px] font-semibold text-md-on-primary-fixed-variant">
            {total}건
          </span>
        ) : null}
        {progress ? (
          <span className="min-w-0 flex-1 truncate text-right text-[11px]">
            <span className="animate-md-shimmer font-medium">{progress}</span>
          </span>
        ) : null}
      </div>

      {query ? (
        <p className="mt-2 flex min-w-0 items-baseline gap-1.5 text-[11.5px] text-md-on-surface-variant">
          <span className="material-symbols-outlined shrink-0 translate-y-[2px] text-[13px] text-md-primary" aria-hidden>
            search
          </span>
          <span className="truncate font-mono">{query}</span>
        </p>
      ) : null}

      {tail.length > 0 ? (
        <ul
          className="mt-2.5 flex flex-col gap-1"
          style={{
            maskImage:
              "linear-gradient(to bottom, transparent 0, black 14px, black 100%)",
            WebkitMaskImage:
              "linear-gradient(to bottom, transparent 0, black 14px, black 100%)",
          }}
        >
          {tail.map((r, i) => {
            const isLatest = i === tail.length - 1;
            return (
              <li
                key={`${r.tool}#${r.index}`}
                className={
                  "live-glass-item flex min-w-0 items-baseline gap-1.5 text-[12px] transition-opacity duration-300 " +
                  (isLatest
                    ? "text-md-on-surface"
                    : "text-md-on-surface-variant opacity-60")
                }
              >
                <span
                  className={
                    "shrink-0 font-mono text-[11px] font-semibold " +
                    (isLatest ? "text-md-primary" : "text-md-on-surface-variant")
                  }
                  aria-hidden
                >
                  [{r.index}]
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {r.title}
                  {r.subtitle ? (
                    <span className="opacity-70"> — {r.subtitle}</span>
                  ) : null}
                </span>
                {isLatest ? (
                  <span
                    className="inline-block size-1.5 shrink-0 translate-y-[-1px] rounded-full bg-md-primary animate-md-pulse"
                    aria-hidden
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
