/**
 * 답변 본문 끝의 `<next_steps>` 마커 블록 파싱.
 *
 * backend가 답변 텍스트 마지막에 다음 모양으로 박음:
 *
 *   [답변 본문]
 *
 *   <next_steps>
 *   [
 *     {"title": "면제 대상", "prompt": "사전심의 면제 대상 광고는?"},
 *     ...
 *   ]
 *   </next_steps>
 *
 * 룰:
 *  - items 2~4개, 각 {title, prompt}, title ≤12자 / prompt ≤60자
 *  - 보고서·ask_clarify turn엔 마커 없음
 *
 * 스트리밍 중 마커가 partial일 수 있으므로:
 *  - close 마커까지 도달 + JSON 파싱 성공 → items 추출 + 본문에서 제거
 *  - open 마커만 도달 → 본문에서 open 이후 stripping (partial JSON 노출 방지), items 없음
 *  - 마커 없음 → 본문 그대로
 */

export type NextStep = {
  title: string;
  prompt: string;
  /** FE-derived: title/prompt에 "보고서"|"리포트" 어휘면 "report"(→ 클릭 시
   *  report-mode dispatch), 아니면 "chat"(→ ChatInput prefill). supervisor
   *  마커는 `{title,prompt}`만 — kind 박지 않으므로 텍스트로 추론. supervisor
   *  프롬프트가 보고서 prompt에 "보고서/리포트" 어휘를 일관 사용 가정.
   *  백엔드가 향후 마커에 명시 kind를 박으면 우선 신뢰하도록 확장 가능. */
  kind: "report" | "chat";
  /** 백엔드가 마커에 명시한 보고서 목적(예: "document_draft" — 서류 초안 모드).
   *  report dispatch 시 POST /reports body.purpose 로 전달. */
  purpose?: string;
};

const CLOSED_RE = /<next_steps>\s*(\[[\s\S]*?\])\s*<\/next_steps>/;
const OPEN_RE = /<next_steps>[\s\S]*$/;
// 토큰 스트리밍 중엔 여는 태그 자체가 `<next`, `_steps`처럼 쪼개져 도착할 수 있다 —
// `<next_steps>`의 *접두 부분 문자열*이 본문 끝에 걸려 있으면 잠정 strip
// (안 하면 `...입니다.<next_step` 같은 raw 조각이 한 프레임 깜빡 노출).
const OPEN_TAG = "<next_steps>";
const PARTIAL_OPEN_RE = /<[a-z_]{0,11}$/;

export function parseNextStepsMarker(content: string): {
  clean: string;
  items: NextStep[];
} {
  if (!content) return { clean: content, items: [] };

  const closed = content.match(CLOSED_RE);
  if (closed) {
    let items: NextStep[] = [];
    try {
      const parsed = JSON.parse(closed[1]!) as unknown;
      if (Array.isArray(parsed)) {
        items = parsed
          .map((v) => normalize(v))
          .filter((v): v is NextStep => v !== null);
      }
    } catch {
      // JSON 깨짐 — 마커는 strip하되 items는 빈 배열로
    }
    const clean = content.replace(CLOSED_RE, "").trim();
    return { clean, items };
  }

  // 스트리밍 partial — open만 있고 close 없음. open 이후 모두 strip.
  if (OPEN_RE.test(content)) {
    return { clean: content.replace(OPEN_RE, "").trim(), items: [] };
  }

  // 여는 태그가 아직 완성되지 않은 꼬리(`<next_step` 등) — OPEN_TAG의 접두면 strip.
  const partial = content.match(PARTIAL_OPEN_RE);
  if (partial && OPEN_TAG.startsWith(partial[0])) {
    return {
      clean: content.slice(0, content.length - partial[0].length).trim(),
      items: [],
    };
  }

  return { clean: content, items: [] };
}

const REPORT_KEYWORD_RE = /(보고서|리포트)/;

function inferKind(title: string, prompt: string): "report" | "chat" {
  return REPORT_KEYWORD_RE.test(prompt) || REPORT_KEYWORD_RE.test(title)
    ? "report"
    : "chat";
}

function normalize(v: unknown): NextStep | null {
  if (!v || typeof v !== "object") return null;
  const o = v as { title?: unknown; prompt?: unknown; kind?: unknown; purpose?: unknown };
  const title = typeof o.title === "string" ? o.title.trim() : "";
  const prompt = typeof o.prompt === "string" ? o.prompt.trim() : "";
  if (!prompt) return null;
  // 백엔드가 마커에 kind를 명시했으면 그걸 신뢰, 아니면 텍스트 추론.
  const explicitKind = o.kind === "report" || o.kind === "chat" ? o.kind : null;
  const kind = explicitKind ?? inferKind(title, prompt);
  const purpose = typeof o.purpose === "string" && o.purpose ? o.purpose : undefined;
  return { title: title || prompt, prompt, kind, purpose };
}
