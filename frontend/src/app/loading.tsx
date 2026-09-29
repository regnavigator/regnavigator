/**
 * App-level loading — Next.js가 RSC suspense fallback으로 자동 사용.
 * NextAuth session 확인 / DB lookup 등 첫 진입 잠깐 흰 화면 방지.
 * 브랜드 로딩(2026-07-24): 아이콘 + 워드마크 + shimmer 한 줄 — 스피너 단독보다
 * "서비스가 여는 중"이라는 인상을 준다.
 */

export default function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-md-surface">
      <div className="flex flex-col items-center gap-5">
        <div className="flex items-center gap-3">
          <span
            className="material-symbols-outlined text-[34px] text-md-primary"
            aria-hidden
          >
            gavel
          </span>
          <span
            className="text-[19px] font-bold tracking-tight text-md-on-surface"
            style={{ letterSpacing: "-0.02em" }}
          >
            MEDIREG AI
          </span>
        </div>
        <div className="flex items-center gap-2.5 text-md-on-surface-variant">
          <span
            className="inline-block size-4 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin"
            aria-hidden
          />
          <p role="status" className="animate-md-shimmer text-body-sm font-medium">
            의료 규제 상담을 준비하고 있어요…
          </p>
        </div>
      </div>
    </div>
  );
}
