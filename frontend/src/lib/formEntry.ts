/**
 * 별표·서식 → 작성 진입점의 문구 (2026-08-27).
 *
 * 같은 버튼이 성격이 다른 자료에 붙는다:
 *  - **서식**(별지 제N호서식): 관청에 내는 *빈 양식* → "이 서식으로 작성"
 *  - **별표**(별표 N): 기준·요건·수수료 *표* → "이 별표로 작성"
 *  - **그 외**(제목에 둘 다 없음): 단정하지 않고 → "이 문서로 작성"
 *    ("별표가 아닐 경우는 어떡할 거냐" — 2026-08-27 지적. 아닌 것을 별표라
 *    부르면 그것대로 어색하다.)
 *
 * 진입점이 여러 곳(인용 패널·별표 모달)이라 판정을 한 군데로 모은다 —
 * 복제하면 화면마다 다른 말을 하게 된다.
 */

export type FormDocKind = "form" | "annex" | "other";

/** 자료 성격 판정 — 제목·조항 문자열 기반. */
export function formDocKind(
  ...texts: (string | null | undefined)[]
): FormDocKind {
  const has = (kw: string) =>
    texts.some((t) => typeof t === "string" && t.includes(kw));
  if (has("서식")) return "form";
  if (has("별표")) return "annex";
  return "other";
}

/**
 * 인용 하나의 성격 판정 (2026-10-01).
 *
 * `attachment_subtype` 은 검색 API 가 **알고 있는 값**이고, 제목 추측은 그것이
 * 없을 때의 폴백이다. 종전엔 추측만 썼는데, `공중위생관리법 시행규칙 별표:
 * 영업신고서` 처럼 **서식인데 제목에 '별표'만 있는** 경우가 흔해 기입 버튼이
 * 뜨지 않았다(실사용 신고).
 */
export function formDocKindOf(c: {
  attachment_subtype?: string | null;
  article?: string | null;
  title?: string | null;
}): FormDocKind {
  const sub = (c.attachment_subtype ?? "").trim();
  // 실측 값: "서식" · "별표" · "별지"(행정규칙 별지 서식). "별지"도 기입 양식이다.
  if (sub.includes("서식") || sub === "별지") return "form";
  if (sub === "별표") return "annex";
  return formDocKind(c.article, c.title);
}

/** (구 API 호환) 서식인가 — AnnexModal 의 다운로드 CTA 분기 등에서 사용. */
export function isFormLike(...texts: (string | null | undefined)[]): boolean {
  return formDocKind(...texts) === "form";
}

const LABELS: Record<FormDocKind, string> = {
  form: "이 서식으로 작성",
  annex: "이 별표로 작성",
  other: "이 문서로 작성",
};

const HINTS: Record<FormDocKind, string> = {
  form: "이 서식의 기입 항목을 열어 바로 작성합니다",
  annex: "이 별표의 항목으로 작성 문서를 엽니다",
  other: "이 문서의 항목으로 작성 문서를 엽니다",
};

/** 버튼 라벨. */
export function formActionLabel(kind: FormDocKind): string {
  return LABELS[kind];
}

/** 버튼 title(툴팁) — 무엇이 열리는지 미리 알린다. */
export function formActionHint(kind: FormDocKind): string {
  return HINTS[kind];
}
