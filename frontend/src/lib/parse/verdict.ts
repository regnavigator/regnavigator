/**
 * 답변 본문의 `<verdict>` 마커 블록 제거 (backend frontend_chat_v2 §2-4).
 *
 * 기관 내부 지침 스킬(IRB/DRB) 판정 턴에서 backend 가 답변 말미에 구조화 판정
 * JSON 을 마커로 감싸 보낸다:
 *
 *   [답변 본문]
 *   <verdict>
 *   ```json
 *   {"irb": {"verdict": "EXEMPT", ...}}
 *   ```
 *   </verdict>
 *
 * - `done.text` 에는 backend 가 이미 제거해 주지만, **token 스트리밍 원문**과
 *   **스레드 리로드(/chat/{tid}/state 의 저장 메시지)** 에는 남아 있으므로
 *   FE 렌더 경로에서 항상 strip 한다.
 * - 판정 데이터 자체는 SSE `skill_verdict` 이벤트로 별도 수신(배지/패널용) —
 *   이 모듈은 본문 위생만 담당한다.
 * - 스트리밍 partial 처리는 nextSteps.ts 와 동일 3단: closed → open-only →
 *   여는 태그 미완성 꼬리(`<verdi` 등) 잠정 strip.
 */

const CLOSED_RE = /<verdict>[\s\S]*?<\/verdict>/g;
const OPEN_RE = /<verdict>[\s\S]*$/;
const OPEN_TAG = "<verdict>";
// `<`, `<v`, `<verdict` … 여는 태그의 접두 조각이 본문 끝에 걸린 경우.
// nextSteps.PARTIAL_OPEN_RE 와 별개 판정 — 두 태그 모두 각자 startsWith 로 확인.
const PARTIAL_OPEN_RE = /<[a-z_/]{0,8}$/;

export function stripVerdictMarker(content: string): string {
  if (!content || !content.includes("<")) return content;

  let out = content;
  if (CLOSED_RE.test(out)) {
    out = out.replace(CLOSED_RE, "").trim();
  }
  if (OPEN_RE.test(out)) {
    return out.replace(OPEN_RE, "").trim();
  }
  const partial = out.match(PARTIAL_OPEN_RE);
  if (partial && OPEN_TAG.startsWith(partial[0]!)) {
    return out.slice(0, out.length - partial[0]!.length).trim();
  }
  return out;
}
