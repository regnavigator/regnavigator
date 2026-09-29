"use client";

/**
 * /documents/{id} — 서류 초안 전체화면 뷰 (Phase ③, 2026-08-24).
 *
 * 우측 패널 DocumentPanel의 단독(standalone) 모드 — 채팅 라이브 병합(live) 없이
 * fill API 직접 호출로 직접 입력·✨ AI 작성·Word 다운로드를 제공한다.
 * 인증은 middleware(NextAuth)가 라우트 단위로 보호.
 */

import { useParams, useRouter } from "next/navigation";
import { DocumentPanel } from "@/components/panel/DocumentPanel";

export default function DocumentPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = typeof params?.id === "string" ? params.id : "";

  return (
    <div className="flex h-dvh flex-col bg-md-surface-container-lowest">
      <header className="flex h-[52px] shrink-0 items-center gap-2 border-b border-md-outline-variant bg-md-surface px-3">
        <button
          type="button"
          onClick={() => router.back()}
          aria-label="뒤로가기"
          className="inline-flex size-8 items-center justify-center rounded text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low hover:text-md-on-surface"
        >
          <span className="material-symbols-outlined text-[20px]" aria-hidden>
            arrow_back
          </span>
        </button>
        <span className="material-symbols-outlined text-[20px] text-md-primary" aria-hidden>
          edit_document
        </span>
        <h1 className="text-[14px] font-semibold text-md-on-surface">서류 작성</h1>
        <p className="ml-auto text-[11.5px] text-md-on-surface-variant">
          AI 생성 초안 — 제출 전 담당자 검토 필수
        </p>
      </header>
      <main className="min-h-0 flex-1">
        {id ? (
          <DocumentPanel reportId={id} fullScreen />
        ) : (
          <div className="flex h-full items-center justify-center text-body-sm text-md-on-surface-variant">
            문서 ID가 없습니다.
          </div>
        )}
      </main>
    </div>
  );
}
