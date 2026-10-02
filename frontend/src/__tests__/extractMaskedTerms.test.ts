import { describe, expect, it } from "vitest";

import { extractMaskedTerms } from "@/lib/store/turns";

/**
 * PII 마스킹 역추적 — 감사(2026-10-02) 치명 항목.
 *
 * 오정렬되면 엉뚱한 단어가 `reportPiiTerm` 으로 가고, 서버는 "선보고 후조치"로
 * **즉시 전역 허용어에 등재**한다(feedback.py) → 실명 마스킹이 전 사용자에게 해제.
 * 테스트 0 이던 함수다.
 */
describe("extractMaskedTerms", () => {
  it("한 자리 치환을 원문 단어로 되돌린다", () => {
    expect(extractMaskedTerms("제 이름은 홍길동입니다", "제 이름은 [이름]입니다"))
      .toEqual([{ term: "홍길동", placeholder: "[이름]" }]);
  });

  it("두 자리 치환도 순서대로", () => {
    const out = extractMaskedTerms(
      "홍길동이 서울특별시 강남구 역삼동 123 에 삽니다",
      "[이름]이 [주소] 에 삽니다",
    );
    expect(out).toEqual([
      { term: "홍길동", placeholder: "[이름]" },
      { term: "서울특별시 강남구 역삼동 123", placeholder: "[주소]" },
    ]);
  });

  it("리터럴이 원문과 어긋나면 부분 결과만 — 엉뚱한 단어를 만들지 않는다", () => {
    // masked 의 리터럴 "다른말" 이 원문에 없다 → 정렬 실패 → 빈 결과
    expect(extractMaskedTerms("홍길동입니다", "[이름]다른말")).toEqual([]);
  });

  it("연속 placeholder 는 경계가 모호해 중단한다", () => {
    expect(extractMaskedTerms("홍길동 서울시", "[이름][주소]")).toEqual([]);
  });

  it("2자 미만·30자 초과 후보는 버린다", () => {
    expect(extractMaskedTerms("김 입니다", "[이름] 입니다")).toEqual([]);
    const long = "가".repeat(31);
    expect(extractMaskedTerms(`${long} 입니다`, "[이름] 입니다")).toEqual([]);
  });

  it("법률 문구 속 대법원 사건번호는 placeholder 가 아니므로 건드리지 않는다", () => {
    expect(extractMaskedTerms("대법원 2008도6829", "대법원 2008도6829")).toEqual([]);
  });
});
