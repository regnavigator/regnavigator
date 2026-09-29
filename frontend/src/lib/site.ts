/**
 * 배포별 식별값 — 도메인·문의 메일·루트 관리자. 화면·메일에 하드코딩하지 말고 여기서 가져온다.
 *
 * `NEXT_PUBLIC_*` 는 빌드 시점에 번들에 인라인된다(Dockerfile ARG → compose build.args).
 * 비었으면 `||` 로 기본값(현 운영 값)을 쓴다 — env 를 안 넣은 기존 배포는 동작이 그대로다.
 */

export const APP_URL = (process.env.NEXT_PUBLIC_APP_URL || "https://app.example.com").replace(/\/$/, "");

export const APP_HOST = new URL(APP_URL).host;

/** 사용자 문의 안내 주소(로그인·가입·베타 차단 안내 등). */
export const SUPPORT_EMAIL = process.env.NEXT_PUBLIC_SUPPORT_EMAIL || "admin@example.com";

/** 인증 메일 발신 주소 기본값 — 서버 발송은 `EMAIL_FROM` 이 우선. */
export const MAIL_FROM_DEFAULT = process.env.NEXT_PUBLIC_MAIL_FROM || "noreply@example.com";

/** 루트 관리자 — 관리자 화면에서 삭제·비활성 버튼을 숨긴다. 백엔드 `ROOT_ADMIN_EMAILS` 와 맞출 것. */
export const ROOT_ADMIN_EMAIL = (process.env.NEXT_PUBLIC_ROOT_ADMIN_EMAIL || SUPPORT_EMAIL).toLowerCase();
