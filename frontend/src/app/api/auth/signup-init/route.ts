/**
 * POST /api/auth/signup-init
 *
 * 회원가입 사전 단계 — user record를 미리 upsert(`passwordHash=NULL`)해
 * 이후 signIn("email") 호출 시 sendVerificationRequest의 *가입 가드*를 통과시킴.
 * 가드 자체는 lib/auth.ts에서 자동 가입(passwordless signup)을 차단하기 위해 박혔다.
 *
 * 베타 게이트 — 화이트리스트 외 이메일은 user 생성 자체 차단.
 *
 * job·organization 같은 부가 정보는 schema에 컬럼이 없어 여기선 받기만 하고
 * 무시(client에서 sessionStorage로 후속 set-password 단계까지 유지).
 */

import { SUPPORT_EMAIL } from "@/lib/site";
import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { isBetaAllowed } from "@/lib/betaGate";

export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as {
    email?: unknown;
    name?: unknown;
  } | null;

  const emailRaw =
    typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
  const name =
    typeof body?.name === "string" && body.name.trim().length > 0
      ? body.name.trim()
      : null;

  if (!emailRaw) {
    return NextResponse.json({ error: "이메일이 필요합니다." }, { status: 400 });
  }
  if (!(await isBetaAllowed(emailRaw))) {
    return NextResponse.json(
      {
        error:
          `가입이 허용되지 않은 이메일입니다. 운영팀(${SUPPORT_EMAIL})에 문의해주세요.`,
      },
      { status: 403 },
    );
  }

  // upsert — 이미 가입된 이메일이면 update branch는 빈 객체로 두어 기존 데이터(특히
  // passwordHash) 보존. 신규면 create로 email + name만 박음.
  await prisma.user.upsert({
    where: { email: emailRaw },
    update: {},
    create: { email: emailRaw, name },
  });

  return NextResponse.json({ ok: true });
}
