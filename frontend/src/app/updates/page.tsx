import type { Metadata } from "next";
import { SiteNav } from "@/components/shell/SiteNav";
import { Suspense } from "react";
import { UpdatesBoard } from "./UpdatesBoard";

/**
 * /updates — 업데이트 내역 게시판 (공개 라우트, 2026-09-02).
 *
 * 사용자 피드백 3건에서 출발:
 *  1) 랜딩에서 업데이트 내용을 찾아볼 수 있게 — nav·footer 링크.
 *  2) 팝업에서 "지금까지의 업데이트"로 건너갈 수 있게 — 놓친 것·원하던 기능이
 *     들어왔는지 확인. 팝업 [업데이트 목록 보기] → 여기(#note_id 앵커).
 *  3) 제목은 주요 변경이 드러나게(발행 화면 안내) + 키워드 검색.
 *
 * 데이터: backend `GET /announcements?q=` (숨김 제외, 최신순). 비로그인 열람
 * 가능 — middleware matcher 제외 + backend 공개 경로.
 *
 * 2026-09-07: 버전별 릴리스 노트 → **기능 단위**(노트 하나 = 기능 하나의 변화,
 * 기능 탭·배지). 사용자가 알 필요 없는 내부 수정은 싣지 않는다.
 */

export const metadata: Metadata = {
  title: "업데이트 내역 · MEDIREG AI",
  description: "MEDIREG AI 에 새로 들어온 기능과 개선 사항 — 키워드로 찾아보세요.",
};

export default function UpdatesPage() {
  return (
    <main className="min-h-screen bg-md-surface text-md-on-surface">
      <SiteNav />

      <div className="mx-auto max-w-[960px] px-6 py-16">
        <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-md-on-surface-variant">
          What&apos;s New
        </p>
        <h1
          className="mt-3 text-[34px] font-bold leading-tight sm:text-[42px]"
          style={{ letterSpacing: "-0.025em" }}
        >
          업데이트 내역
        </h1>
        <p className="mt-5 max-w-[620px] text-[16px] leading-[1.8] text-md-on-surface-variant">
          새로 할 수 있게 된 일을 기능별로 모았습니다. 기능 탭으로 훑거나,
          기다리던 기능이 들어왔는지 키워드로 찾아보세요.
        </p>

        {/* useSearchParams(?q=) 는 Suspense 경계 필요 — 없으면 정적 빌드가 실패한다 */}
        <Suspense fallback={<p className="mt-8 text-[12.5px] text-md-on-surface-variant">불러오는 중…</p>}>
          <UpdatesBoard />
        </Suspense>

        <p className="mt-12 text-[13px] text-md-on-surface-variant">
          원하는 기능이 아직 없다면 채팅 입력창의 [피드백]으로 알려주세요. 반영되면
          이 목록에 올라옵니다.
        </p>
      </div>
    </main>
  );
}
