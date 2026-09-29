/**
 * 매직링크 발송 기록 — /auth/verify 페이지가 (1) 어느 주소로 보냈는지 표시하고
 * (2) 같은 조건으로 재발송할 수 있게, 발송 지점(signup·login·forgot)이 남긴다.
 * sessionStorage(탭 한정)라 다른 탭/재방문에선 없을 수 있음 — verify 페이지는
 * 없으면 재발송 버튼을 숨기고 로그인 링크만 안내.
 */

export const VERIFY_REQUEST_KEY = "medi-front-verify-request";

export type VerifyRequest = { email: string; callbackUrl: string };

export function saveVerifyRequest(email: string, callbackUrl: string): void {
  try {
    sessionStorage.setItem(
      VERIFY_REQUEST_KEY,
      JSON.stringify({ email, callbackUrl } satisfies VerifyRequest),
    );
  } catch {
    // private browsing 등 — verify 페이지가 일반 안내로 폴백
  }
}

export function readVerifyRequest(): VerifyRequest | null {
  try {
    const raw = sessionStorage.getItem(VERIFY_REQUEST_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<VerifyRequest>;
    if (typeof parsed.email !== "string" || !parsed.email) return null;
    return { email: parsed.email, callbackUrl: parsed.callbackUrl ?? "/" };
  } catch {
    return null;
  }
}
