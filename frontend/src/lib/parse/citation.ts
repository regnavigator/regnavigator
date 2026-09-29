/**
 * Citation 본문 파싱 — back §7, P6.3.4.
 *
 * 답변 본문 안 `[...]` 인용 마커를 chip 토큰으로 분해. 두 가지 형식 지원:
 *   1) **숫자 마커**: `[1]`, `[2]` — number로 직접 매핑 (canonical)
 *   2) **텍스트 마커**: `[의료기기법 시행규칙 제4조, 별표 1]` — citations 배열에서 fuzzy
 *      title·article 매칭으로 number 도출 (backend가 텍스트 ref 박을 때 fallback)
 *
 * - escape `\[1\]` → 평문 `[1]` (chip X)
 * - 매칭 실패한 번호·텍스트 → 원문 그대로 (정보 손실 X)
 */

import type { Citation } from "@/lib/store/types";

/**
 * backend가 메타 필드를 string이 아닌 object로 박아 보내는 경우 흡수.
 * 예: `{ content: "식품의약품안전처", 소관부처코드: "1471000" }` → "식품의약품안전처"
 *
 * 사용: `normalizeMetaField(c.publisher)`, `normalizeMetaField(c.title)` 등.
 */
/**
 * "제0001조" → "제1조". backend가 zero-padded로 보내는 article 번호 정규화.
 * 조·항·호 모두 적용 ("제0012항" → "제12항"). 1자리 이상은 항상 유지 (예: "제0조" 그대로).
 */
export function stripArticleNumPadding(s: string): string {
  if (!s) return s;
  return s.replace(/제0+(\d)/g, "제$1");
}

export function normalizeMetaField(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "object") {
    const obj = v as Record<string, unknown>;
    for (const k of ["content", "value", "name", "text", "title"]) {
      if (typeof obj[k] === "string" && (obj[k] as string).length > 0) {
        return obj[k] as string;
      }
    }
    return "";
  }
  return String(v);
}

export type CitationToken =
  | { kind: "text"; value: string }
  | { kind: "citation"; number: number; raw: string };

/**
 * 텍스트 ref(예: "의료기기법 시행규칙 제4조") → citations 배열에서 매칭되는 1건 number.
 * 매칭 규칙 (구체적인 것부터):
 *   1) 텍스트 안에 citation.title 포함 + article 포함 → 정확 매칭
 *   2) 텍스트 안에 citation.title 포함 → 제목 매칭
 *   3) 첫 segment(콤마 앞)가 citation.title의 부분 문자열 또는 그 반대 → 느슨 매칭
 */
function matchTextRef(text: string, citations: Citation[]): Citation | null {
  const trimmed = text.trim();
  const firstSeg = (trimmed.split(",")[0] ?? trimmed).trim();
  // 1) title + article 정확
  for (const c of citations) {
    if (!c.title) continue;
    if (trimmed.includes(c.title)) {
      if (!c.article || trimmed.includes(c.article)) return c;
    }
  }
  // 2) title 포함
  for (const c of citations) {
    if (c.title && trimmed.includes(c.title)) return c;
  }
  // 3) 느슨 매칭 — 첫 segment 부분 문자열
  for (const c of citations) {
    if (!c.title) continue;
    if (c.title.includes(firstSeg) || firstSeg.includes(c.title)) return c;
  }
  return null;
}

/**
 * 입력 텍스트를 토큰 배열로 분해.
 * - 숫자 마커 `[N]` → citation chip token
 * - 텍스트 마커 `[<text>]` → citations 매칭되면 chip, 아니면 평문
 * - escape `\[...\]` → 백슬래시 떼고 평문
 */
export function parseCitationTokens(
  input: string,
  citations: Citation[] = [],
): CitationToken[] {
  if (!input) return [];
  const tokens: CitationToken[] = [];
  // `[ ... ]` 안 임의 문자(`]` 제외) 매칭. 백슬래시 escape 지원.
  const re = /(\\?)\[([^\]\n]+)\]/g;
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(input)) !== null) {
    const [full, esc, body] = m;
    const start = m.index;
    if (start > lastIndex) {
      tokens.push({ kind: "text", value: input.slice(lastIndex, start) });
    }
    if (esc === "\\") {
      // escape — 평문 `[body]` 출력
      tokens.push({ kind: "text", value: `[${body}]` });
    } else if (/^\s*\d+\s*$/.test(body!)) {
      // 숫자 마커 — number 직접
      tokens.push({
        kind: "citation",
        number: Number(body!.trim()),
        raw: full!,
      });
    } else {
      // 텍스트 마커 — citations에서 매칭 시도
      const matched = matchTextRef(body!, citations);
      if (matched) {
        tokens.push({
          kind: "citation",
          number: matched.number,
          raw: full!,
        });
      } else {
        // 매칭 실패 — 원문 그대로 (정보 손실 방지)
        tokens.push({ kind: "text", value: full! });
      }
    }
    lastIndex = start + full!.length;
  }
  if (lastIndex < input.length) {
    tokens.push({ kind: "text", value: input.slice(lastIndex) });
  }
  return tokens;
}

/**
 * 출처 타입 한글 라벨 — chip·inspector list 공통. `source_kind`/`doc_category`를
 * *분류값 그대로 매핑*(텍스트 가공 X, skill `medi-front-data-contract §6.1`).
 * 한국법령정보센터(law.go.kr) 분류 체계 정합. 13 doc_category → 9 라벨(별표서식
 * 3종은 단일 "별표"), web → "웹", 그 외 doc → "문서".
 */
const DOC_CATEGORY_LABEL: Record<string, string> = {
  법령: "법령",
  영문법령: "법령",
  조약: "조약",
  행정규칙: "행정규칙",
  자치법규: "자치법규",
  학칙공단: "학칙",
  판례: "판례",
  헌재결정례: "헌재",
  법령해석례: "해석",
  행정심판례: "심판",
  법령별표서식: "별표",
  행정규칙별표서식: "별표",
  자치법규별표서식: "별표",
  // 식약처 가이드라인·안내서(back target_type=guide, 2026-07-24~). 빠져 있어 "문서"로
  // 떨어졌고, 칩은 무색·범례 건수에서 누락됐다(2026-09-21 지적 "가이드라인은 아예 안 뜬다").
  가이드라인: "가이드라인",
};

export function citationLabel(c: Citation): string {
  if (c.source_kind === "web") return "웹";
  if (c.doc_category) {
    const l = DOC_CATEGORY_LABEL[c.doc_category];
    if (l) return l;
  }
  return "문서";
}
