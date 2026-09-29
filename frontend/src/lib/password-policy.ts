/**
 * 비밀번호 정책 — 단일 진실원.
 * 서버(api/auth/set-password)와 클라이언트((auth)/auth/set-password) 양쪽이
 * 본 모듈을 import → 정책 변경 시 한 곳만 고치면 동기.
 *
 * 정책:
 *   - 최소 8자
 *   - 특수문자 1개 이상 포함
 */

export const MIN_LENGTH = 8;
export const PASSWORD_RE =
  /^(?=.*[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?~`])[\s\S]{8,}$/;
export const POLICY_HINT = "최소 8자, 특수문자 1개 이상 포함";

/**
 * 비밀번호 검증 — 통과 시 null, 실패 시 사용자 향 에러 메시지 반환.
 * 서버는 400 응답 body의 error 필드에 그대로 박아 client와 카피 일관.
 */
export function validatePassword(pw: string): string | null {
  if (pw.length < MIN_LENGTH) return `최소 ${MIN_LENGTH}자 이상 입력해주세요.`;
  if (!PASSWORD_RE.test(pw))
    return "특수문자(!@#$%^&* 등)를 1개 이상 포함해주세요.";
  return null;
}
