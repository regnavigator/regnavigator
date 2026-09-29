/**
 * NextAuth config — Email magic link + HS256 JWT 발급.
 *
 * - DB: PrismaAdapter (verification token + user/account/session)
 * - Provider: Email(SMTP) — Resend 등
 * - Session strategy: jwt (DB session 안 씀 — backend에 raw JWT 보내기 위함)
 * - jwt() callback에서 jose로 HS256 서명 토큰을 별도 발급해 token.accessToken에 박음.
 *   backend가 같은 NEXTAUTH_SECRET으로 jwtVerify. (NextAuth default JWT는 JWE라 외부 검증 까다로움)
 */

import type { NextAuthOptions } from "next-auth";
import EmailProvider from "next-auth/providers/email";
import CredentialsProvider from "next-auth/providers/credentials";
import type { SendVerificationRequestParams } from "next-auth/providers/email";
import { PrismaAdapter } from "@next-auth/prisma-adapter";
import { SignJWT } from "jose";
import { createTransport } from "nodemailer";
import bcrypt from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { EMAIL_FROM_DEFAULT, EMAIL_SUBJECT, htmlBody, textBody } from "@/lib/email-template";

const SECRET = process.env.NEXTAUTH_SECRET;
// runtime에서만 throw. NEXT_PHASE='phase-production-build' 단계엔 .env.docker가 주입되기 전이라
// 모듈 로드 시 throw하면 `next build`가 깨진다 ("Failed to collect page data for /api/auth/...").
if (
  !SECRET &&
  process.env.NODE_ENV === "production" &&
  process.env.NEXT_PHASE !== "phase-production-build"
) {
  throw new Error("NEXTAUTH_SECRET 미설정");
}

const ACCESS_TOKEN_TTL = "7d";

// 로그인 브루트포스 잠금 — 연속 실패 임계 도달 시 일정 시간 비번 로그인 차단.
// 매직링크·비번 재설정 경로는 별개 채널이라 영향 없음(재설정 완료 시 잠금 해제).
const MAX_LOGIN_FAILS = 5;
const LOGIN_LOCK_MINUTES = 10;

/**
 * 클로즈베타 게이트 — 진실원은 **백엔드 화이트리스트**(env ∪ DB, admin 관리).
 * `lib/betaGate.ts` 가 `POST /beta/check` 로 조회(실패 시 front env 폴백).
 * (2026-07-15 통일 — 이전 front 자체 env 는 admin DB 추가분을 못 봐서 분리 문제.)
 */
import { isBetaAllowed } from "@/lib/betaGate";

/**
 * Admin 화이트리스트 — `ADMIN_EMAILS` env에 콤마 구분 이메일.
 * 매칭되면 session.user.isAdmin=true → UI에서 admin 메뉴 노출.
 * 미설정/빈 값 시 admin 없음.
 */
const ADMIN_EMAILS = (process.env.ADMIN_EMAILS ?? "")
  .split(",")
  .map((s) => s.trim().toLowerCase())
  .filter(Boolean);

export function isAdminEmail(emailRaw: string | null | undefined): boolean {
  if (!emailRaw) return false;
  return ADMIN_EMAILS.includes(emailRaw.trim().toLowerCase());
}

/** Resend는 465 + implicit TLS. connection URL만 쓰면 secure 누락으로 전송 실패하는 경우가 있어 API 키 분리 권장. */
function emailTransport():
  | string
  | {
      host: string;
      port: number;
      secure: boolean;
      auth: { user: string; pass: string };
    } {
  const key = process.env.RESEND_API_KEY?.trim();
  if (key) {
    return {
      host: "smtp.resend.com",
      port: 465,
      secure: true,
      auth: { user: "resend", pass: key },
    };
  }
  const url = process.env.EMAIL_SERVER?.trim();
  if (url) return url;
  // 빌드 단계엔 env가 주입되지 않은 상태에서 모듈이 로드된다 — placeholder 반환.
  // 런타임에는 .env.docker로 RESEND_API_KEY 또는 EMAIL_SERVER가 채워져 위 분기로 빠진다.
  if (process.env.NEXT_PHASE === "phase-production-build") {
    return "smtp://noop@noop.invalid:25";
  }
  throw new Error(
    "메일 전송 설정 없음: .env.local에 RESEND_API_KEY=re_... 또는 EMAIL_SERVER 를 넣으세요.",
  );
}

/**
 * 한국어 이메일 인증 메일 — 브랜드 컬러(Green #00965E primary).
 * NextAuth 기본 영문 템플릿 대체. plain text fallback 포함.
 */
async function sendVerificationRequest(params: SendVerificationRequestParams) {
  const { identifier: to, url, provider } = params;
  const { host } = new URL(url);

  // 클로즈베타 게이트 — 화이트리스트 외 이메일은 매직링크 발송 전 차단.
  if (!(await isBetaAllowed(to))) {
    console.warn(`[auth] beta gate blocked email: ${to}`);
    // NextAuth는 throw 시 /api/auth/error?error=Verification 으로 redirect.
    // signup 페이지에서 error param 보고 안내 표시.
    throw new Error("베타 미허가 이메일입니다. 운영팀에 문의해주세요.");
  }

  // 가입 가드 — DB에 user가 없으면 매직링크 발송 차단.
  // NextAuth + PrismaAdapter 기본 동작은 매직링크 클릭 시 user 자동 생성(passwordless signup).
  // 그걸 우회해 임의 이메일로 메일 폭탄·signup 부가정보 우회 방지.
  // signup 흐름은 /api/auth/signup-init이 사전 upsert하므로 통과,
  // 비밀번호 재설정 매직링크도 이미 가입된 user에 대해서만 의미가 있어 통과.
  const existing = await prisma.user.findUnique({
    where: { email: to.toLowerCase() },
    select: { id: true },
  });
  if (!existing) {
    console.warn(`[auth] verification request for unregistered email: ${to}`);
    throw new Error("등록되지 않은 이메일입니다. 회원가입 후 이용해주세요.");
  }

  const transport = createTransport(provider.server);
  const result = await transport.sendMail({
    to,
    from: provider.from,
    subject: EMAIL_SUBJECT,
    text: textBody(url, host),
    html: htmlBody(url, host),
  });

  const failed = result.rejected.concat(result.pending).filter(Boolean);
  if (failed.length) {
    throw new Error(`메일 전송 실패: ${failed.join(", ")}`);
  }
}

export const authOptions: NextAuthOptions = {
  adapter: PrismaAdapter(prisma),
  secret: SECRET,
  debug: process.env.NODE_ENV === "development",
  logger: {
    error(code, metadata) {
      console.error("[next-auth]", code, metadata);
    },
  },
  // 자동 로그인 — 한 번 인증 후 90일간 세션 유지. 매 요청 시 갱신(updateAge 1일).
  // JWT 토큰의 exp claim도 maxAge에 맞춰 박힘 (NextAuth 기본 동작).
  session: { strategy: "jwt", maxAge: 90 * 24 * 60 * 60, updateAge: 24 * 60 * 60 },
  providers: [
    EmailProvider({
      server: emailTransport(),
      from: process.env.EMAIL_FROM || EMAIL_FROM_DEFAULT,
      maxAge: 10 * 60, // 이메일 인증 링크 10분 유효 (신규 가입 + 비번 재설정용)
      sendVerificationRequest,
    }),
    CredentialsProvider({
      id: "credentials",
      name: "Email/Password",
      credentials: {
        email: { label: "이메일", type: "email" },
        password: { label: "비밀번호", type: "password" },
      },
      async authorize(creds) {
        const email = creds?.email?.trim().toLowerCase();
        const password = creds?.password ?? "";
        if (!email || !password) return null;
        const user = await prisma.user.findUnique({ where: { email } });
        if (!user || !user.passwordHash) return null;
        // 잠금 중 — bcrypt 비교조차 하지 않고 차단. throw 메시지가
        // signIn(redirect:false) 의 res.error 로 전달돼 프런트가 안내 렌더.
        if (user.lockedUntil && user.lockedUntil > new Date()) {
          throw new Error("LOCKED");
        }
        const ok = await bcrypt.compare(password, user.passwordHash);
        if (!ok) {
          const failed = (user.failedLoginCount ?? 0) + 1;
          const lock = failed >= MAX_LOGIN_FAILS;
          await prisma.user.update({
            where: { id: user.id },
            data: {
              // 잠금 발동 시 카운트 리셋 — 만료 후 새로 5회 기회.
              failedLoginCount: lock ? 0 : failed,
              lockedUntil: lock
                ? new Date(Date.now() + LOGIN_LOCK_MINUTES * 60_000)
                : null,
            },
          });
          if (lock) throw new Error("LOCKED");
          return null;
        }
        // 성공 — 실패 흔적 정리(불필요한 write 방지 위해 있을 때만).
        if (user.failedLoginCount || user.lockedUntil) {
          await prisma.user.update({
            where: { id: user.id },
            data: { failedLoginCount: 0, lockedUntil: null },
          });
        }
        return {
          id: user.id,
          email: user.email,
          name: user.name,
          emailVerified: user.emailVerified,
        } as { id: string; email: string | null; name: string | null; emailVerified: Date | null };
      },
    }),
  ],
  pages: {
    signIn: "/login",
    verifyRequest: "/auth/verify",
  },
  callbacks: {
    /**
     * 클로즈베타 게이트 — credentials provider도 차단 (sendVerificationRequest는
     * EmailProvider만 차단하므로 비번 로그인 경로는 여기서 한 번 더 체크).
     *
     * 추가 가드 — EmailProvider 콜백 단계에서도 user 존재 여부를 다시 확인해
     * sendVerificationRequest 단계를 우회한 자동 가입 경로를 차단(이중 안전).
     */
    async signIn({ user, account }) {
      const email = user?.email ?? null;
      if (!(await isBetaAllowed(email))) {
        console.warn(`[auth] beta gate blocked signin: ${email}`);
        return false;
      }
      if (account?.provider === "email" && email) {
        const existing = await prisma.user.findUnique({
          where: { email: email.toLowerCase() },
          select: { id: true },
        });
        if (!existing) {
          console.warn(`[auth] signIn blocked — unregistered email: ${email}`);
          return false;
        }
      }
      return true;
    },
    async jwt({ token, user, trigger }) {
      // 첫 로그인 시 user 객체 도착 — 표준 클레임 박음
      if (user) {
        token.sub = user.id;
        token.email = user.email ?? token.email;
        token.email_verified = !!(user as { emailVerified?: Date | null }).emailVerified;
      }
      // isAdmin 클레임 — ADMIN_EMAILS 화이트리스트 매칭 (이메일은 매 jwt 호출마다 재평가)
      (token as { isAdmin?: boolean }).isAdmin = isAdminEmail(
        (token.email as string | undefined) ?? null,
      );

      // hasPassword 클레임 — middleware가 /auth/set-password 강제 redirect에 사용.
      // 비번 설정 직후 client에서 update() 호출 시 trigger="update"로 갱신.
      if (user || trigger === "update" || token.hasPassword === undefined) {
        const sub = token.sub as string | undefined;
        if (sub) {
          const u = await prisma.user.findUnique({
            where: { id: sub },
            select: { passwordHash: true },
          });
          (token as { hasPassword?: boolean }).hasPassword = !!u?.passwordHash;
        }
      }

      // backend 호출용 HS256 signed JWT (raw JWS) 별도 발급 — JWE인 NextAuth 토큰과 분리.
      if (SECRET) {
        const key = new TextEncoder().encode(SECRET);
        const accessToken = await new SignJWT({
          email: token.email,
          email_verified: token.email_verified ?? false,
        })
          .setProtectedHeader({ alg: "HS256" })
          .setSubject((token.sub as string) ?? "")
          .setIssuedAt()
          .setExpirationTime(ACCESS_TOKEN_TTL)
          .sign(key);
        (token as { accessToken?: string }).accessToken = accessToken;
      }

      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as { id?: string; isAdmin?: boolean }).id =
          token.sub as string | undefined;
        (session.user as { isAdmin?: boolean }).isAdmin = !!(
          token as { isAdmin?: boolean }
        ).isAdmin;
      }
      (session as { accessToken?: string; hasPassword?: boolean }).accessToken = (
        token as { accessToken?: string }
      ).accessToken;
      (session as { hasPassword?: boolean }).hasPassword = (
        token as { hasPassword?: boolean }
      ).hasPassword;
      return session;
    },
  },
};
