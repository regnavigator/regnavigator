/**
 * 인증 메일 본문 템플릿 — 단일 진실원천.
 * lib/auth.ts(NextAuth EmailProvider)와 /auth/email-preview(dev 도구) 양쪽이
 * 본 모듈을 import. 디자인 변경 시 여기 한 곳만 고치면 발송·프리뷰 자동 동기.
 *
 * 디자인: MEDIREG AI Quiet Forest 톤 (globals.css 토큰 mirror).
 * 메일 클라이언트는 외부 CSS 못 받으니 inline style + raw hex 사용.
 */

import { MAIL_FROM_DEFAULT } from "@/lib/site";

export const EMAIL_SUBJECT = "MEDIREG AI 이메일 인증";
export const EMAIL_FROM_DEFAULT = MAIL_FROM_DEFAULT;

/* ─────────────────── Quiet Forest 토큰 (globals.css mirror) ─────────────────── */

const TOKENS = {
  accent: "#0F6B4A", // Quiet Emerald (--md-primary)
  ink: "#0B1F17", // Deep Forest Ink (--md-on-surface)
  ink2: "#4A6B5E", // Forest-tinted Slate (--md-on-surface-variant)
  bg: "#F7FAF8", // Off-white forest tint (--md-surface)
  surface: "#FFFFFF", // 카드 (--md-surface-bright)
  border: "#C5D4CC", // Forest gray (--md-outline)
  sansFont:
    "'Sora','Pretendard Variable',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
  monoFont:
    "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace",
} as const;

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* ─────────────────── HTML 본문 ─────────────────── */

export function htmlBody(url: string, host: string): string {
  const t = TOKENS;
  return `<!DOCTYPE html>
<html lang="ko">
  <body style="margin:0;padding:0;background:${t.bg};font-family:${t.sansFont};color:${t.ink};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${t.bg};padding:48px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="520" cellpadding="0" cellspacing="0" style="max-width:520px;background:${t.surface};border:1px solid ${t.border};border-radius:8px;">
            <tr>
              <td style="padding:36px 40px 20px;">
                <div style="font-family:${t.monoFont};font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:${t.accent};font-weight:600;">
                  MEDIREG AI · 이메일 인증
                </div>
                <h1 style="margin:16px 0 0;font-size:28px;line-height:1.2;letter-spacing:-0.02em;color:${t.ink};font-weight:700;">
                  이메일 인증을 완료하세요
                </h1>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 40px 24px;color:${t.ink2};font-size:15px;line-height:1.7;">
                아래 버튼을 눌러 인증을 완료하면 가입·로그인이 진행됩니다.
                요청 출처는 <strong style="color:${t.ink};font-weight:600;">${escapeHtml(host)}</strong>이며,
                링크는 <strong style="color:${t.ink};font-weight:600;">10분간</strong> 유효합니다.
                본인이 요청하지 않았다면 이 메일을 무시해도 됩니다.
              </td>
            </tr>
            <tr>
              <td align="left" style="padding:0 40px 32px;">
                <a href="${url}"
                  style="display:inline-block;background:${t.accent};color:#FFFFFF;text-decoration:none;font-size:15px;font-weight:600;padding:14px 32px;border-radius:9999px;">
                  이메일 인증 →
                </a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 40px 24px;border-top:1px solid ${t.border};">
                <div style="padding-top:20px;color:${t.ink2};font-size:12px;line-height:1.65;word-break:break-all;">
                  버튼이 동작하지 않으면 아래 주소를 브라우저에 직접 붙여넣으세요.<br>
                  <a href="${url}" style="font-family:${t.monoFont};color:${t.accent};text-decoration:none;font-size:11.5px;">${url}</a>
                </div>
              </td>
            </tr>
          </table>
          <div style="margin-top:20px;font-family:${t.monoFont};font-size:11px;color:${t.ink2};letter-spacing:0.08em;">
            © MEDIREG AI · 의료·규제 도메인 AI
          </div>
        </td>
      </tr>
    </table>
  </body>
</html>`;
}

/* ─────────────────── Plain text fallback ─────────────────── */

export function textBody(url: string, host: string): string {
  return `MEDIREG AI · 이메일 인증

이메일 인증을 완료하세요.

아래 링크를 10분 안에 클릭하면 가입·로그인이 진행됩니다.
요청 출처: ${host}

${url}

본인이 요청하지 않았다면 이 메일을 무시해도 됩니다.

—
MEDIREG AI · 의료·규제 도메인 AI`;
}

/** 프리뷰 페이지 배경색 — iframe 안 메일 카드 주변 톤. */
export const PREVIEW_BG = TOKENS.bg;
