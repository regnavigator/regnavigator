/**
 * 기능 조합(워크플로) 진행 상태 — 서버 왕복 (2026-10-02).
 *
 * 왜 서버에 두는가: 단계마다 멈추는 설계라 "지금 몇 단계인지"가 곧 조합 그 자체다.
 * 클라이언트 상태로만 들면 새로고침 한 번에 사라진다.
 *
 * 저장되는 것은 **기능 id 배열과 커서**뿐이다. 단계 사이의 맥락(쟁점·인용)은
 * 같은 스레드의 메시지·`chat_steps[].citations` 에 이미 쌓이므로 따로 옮기지
 * 않는다 — 누적분을 프롬프트에 직렬화하는 것은 과거 사고 이력이 있다
 * (`report_pipeline.py` 의 24만자 전멸).
 */

import { apiFetch } from "@/lib/api/client";

export type Workflow = {
  /** 실행 순서대로의 기능 id (`lib/features/catalog.ts` 의 `Feature.id`) */
  steps: string[];
  /** 다음에 실행할 단계의 인덱스. `steps.length` 면 조합 완료 */
  cursor: number;
};

/** 조합 저장. `steps` 가 비면 조합을 끝낸다(서버가 null 로 비운다). */
export async function saveWorkflow(
  threadId: string,
  wf: Workflow,
): Promise<{ workflow: Workflow | null }> {
  return apiFetch(`/chat/${encodeURIComponent(threadId)}/workflow`, {
    method: "PATCH",
    body: JSON.stringify({ steps: wf.steps, cursor: wf.cursor }),
  });
}

/** 조합 종료 — 카드가 사라진다. */
export async function clearWorkflow(threadId: string): Promise<void> {
  await saveWorkflow(threadId, { steps: [], cursor: 0 });
}
