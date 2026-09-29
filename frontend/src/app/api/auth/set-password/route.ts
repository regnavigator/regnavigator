import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import bcrypt from "bcryptjs";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { validatePassword } from "@/lib/password-policy";

const BCRYPT_COST = 12;

export async function POST(req: Request) {
  const session = await getServerSession(authOptions);
  const userId = (session?.user as { id?: string } | undefined)?.id;
  if (!userId) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { password } = (await req.json()) as { password?: unknown };
  if (typeof password !== "string") {
    return NextResponse.json({ error: "비밀번호를 입력해주세요." }, { status: 400 });
  }
  const policyError = validatePassword(password);
  if (policyError) {
    return NextResponse.json({ error: policyError }, { status: 400 });
  }
  const hash = await bcrypt.hash(password, BCRYPT_COST);
  await prisma.user.update({
    where: { id: userId },
    // 새 비번 설정 = 본인 확인 완료 — 브루트포스 잠금·실패 카운트 즉시 해제.
    data: { passwordHash: hash, failedLoginCount: 0, lockedUntil: null },
  });
  return NextResponse.json({ ok: true });
}
