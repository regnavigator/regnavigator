import { Suspense } from "react";
import { PageShell } from "@/components/shell/PageShell";
import { MaintenanceGate } from "@/components/shell/MaintenanceGate";

// (chat) route group — `/`와 `/new`가 공유.
// PageShell을 layout에 박으면 두 라우트 간 navigation 시 page.tsx만 remount되고
// PageShell은 유지됨. 첫 메시지 송신 시 `/new` → `/new?threadId=xxx` router.replace 해도
// 진행 중인 stream / useChatState 상태 보존.
//
// **Suspense 분리**: PageShell과 children을 각각 별도 Suspense boundary로 감싼다.
// 한 boundary로 묶으면 children(async server page) suspend 시 PageShell까지 fallback으로
// 교체되어 useChatState state가 lost — "동적 로딩(스피너) 없어짐" 현상 발생.
export const dynamic = "force-dynamic";

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <MaintenanceGate>
      <Suspense fallback={null}>
        <PageShell />
      </Suspense>
      <Suspense fallback={null}>{children}</Suspense>
    </MaintenanceGate>
  );
}
