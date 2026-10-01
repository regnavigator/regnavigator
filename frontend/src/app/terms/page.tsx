/**
 * 이용약관 — /terms (공개 라우트, middleware 화이트리스트).
 *
 * 본문은 백엔드 정본(`GET /legal/terms`)을 렌더한다 — 프런트 하드코딩 금지
 * (이중 관리로 실제 동작과 어긋난 전례). 정본: medi-back `docs/legal/terms.md` ·
 * 연동: `docs/frontend_legal_handoff.md` §2.
 */

import type { Metadata } from "next";
import { LegalDocPage } from "@/components/legal/LegalDocPage";

export const metadata: Metadata = {
  title: "이용약관 · RegNavigator",
  description: "RegNavigator 서비스 이용약관",
};

export default function TermsPage() {
  return (
    <LegalDocPage
      doc="terms"
      title="이용약관"
      subtitle="RegNavigator(이하 “서비스”) 이용에 관한 회사와 이용자 간 권리·의무를 규정합니다. 본 서비스는 베타(시험 운영) 단계입니다."
    />
  );
}
