/**
 * 개인정보처리방침 — /privacy (공개 라우트, middleware 화이트리스트).
 *
 * 본문은 백엔드 정본(`GET /legal/privacy`)을 렌더한다 — 프런트 하드코딩 금지.
 * 과거 하드코딩 본문이 실제 동작(§3 보유기간·§5 이전받는 자)과 어긋나 있었다.
 * 정본: medi-back `docs/legal/privacy.md` · 연동: `docs/frontend_legal_handoff.md` §2.
 */

import type { Metadata } from "next";
import { LegalDocPage } from "@/components/legal/LegalDocPage";

export const metadata: Metadata = {
  title: "개인정보처리방침 · MEDIREG AI",
  description: "MEDIREG AI 개인정보처리방침",
};

export default function PrivacyPage() {
  return (
    <LegalDocPage
      doc="privacy"
      title="개인정보처리방침"
      subtitle="MEDIREG AI는 이용자의 개인정보를 다음과 같이 처리합니다. AI 답변 생성을 위해 일부 정보가 국외 사업자에게 이전될 수 있습니다(제5조)."
    />
  );
}
