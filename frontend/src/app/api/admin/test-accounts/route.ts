/**
 * 테스트 계정 관리 API (admin 전용) — 2026-07-16.
 *
 * POST   { email, password, name? } → auth DB(prisma) upsert(매직링크 인증 생략)
 *                                     + backend 베타 화이트리스트 자동 등록
 * DELETE { email }                  → auth DB 삭제(세션·계정 cascade)
 *                                     + 화이트리스트에서 제거(best-effort)
 *
 * admin 판정: 세션의 backend JWT 로 `GET {BACKEND}/admin/whitelist` 호출 —
 * 200 = admin(백엔드 require_admin 이 진실원, 프런트에 admin 목록 중복 보관 X).
 */
import { NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import bcrypt from "bcryptjs";
import { authOptions } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const BACKEND =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_DEPLOYMENT_URL ||
  "";

async function requireAdminToken(): Promise<string | NextResponse> {
  const session = await getServerSession(authOptions);
  const token = (session as { accessToken?: string } | null)?.accessToken;
  if (!token) {
    return NextResponse.json({ error: "로그인이 필요합니다" }, { status: 401 });
  }
  if (!BACKEND) {
    return NextResponse.json({ error: "backend URL 미설정" }, { status: 500 });
  }
  const res = await fetch(`${BACKEND}/admin/whitelist`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  }).catch(() => null);
  if (!res || res.status !== 200) {
    return NextResponse.json({ error: "관리자 권한이 필요합니다" }, { status: 403 });
  }
  return token;
}

export async function POST(req: Request) {
  const tokenOrErr = await requireAdminToken();
  if (tokenOrErr instanceof NextResponse) return tokenOrErr;

  const body = (await req.json().catch(() => null)) as {
    email?: unknown;
    password?: unknown;
    name?: unknown;
  } | null;
  const email = String(body?.email ?? "").trim().toLowerCase();
  const password = String(body?.password ?? "");
  const name = String(body?.name ?? "").trim() || email.split("@")[0];
  if (!email.includes("@")) {
    return NextResponse.json({ error: "올바른 이메일이 필요합니다" }, { status: 422 });
  }
  if (password.length < 8) {
    return NextResponse.json({ error: "비밀번호는 8자 이상" }, { status: 422 });
  }

  const passwordHash = await bcrypt.hash(password, 12);
  const user = await prisma.user.upsert({
    where: { email },
    update: { passwordHash, emailVerified: new Date() },
    create: { email, name, passwordHash, emailVerified: new Date() },
  });

  // 화이트리스트 자동 등록 — 계정만 있고 게이트에 막히는 상태 방지.
  let whitelisted = false;
  try {
    const wl = await fetch(`${BACKEND}/admin/whitelist`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${tokenOrErr}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ entry: email }),
    });
    whitelisted = wl.ok;
  } catch {
    /* best-effort — 실패해도 계정은 생성됨 */
  }

  return NextResponse.json({
    ok: true,
    email: user.email,
    name: user.name,
    whitelisted,
  });
}

export async function DELETE(req: Request) {
  const tokenOrErr = await requireAdminToken();
  if (tokenOrErr instanceof NextResponse) return tokenOrErr;

  const body = (await req.json().catch(() => null)) as { email?: unknown } | null;
  const email = String(body?.email ?? "").trim().toLowerCase();
  if (!email.includes("@")) {
    return NextResponse.json({ error: "올바른 이메일이 필요합니다" }, { status: 422 });
  }

  const existing = await prisma.user.findUnique({ where: { email } });
  if (!existing) {
    return NextResponse.json({ error: "해당 이메일 계정 없음" }, { status: 404 });
  }
  await prisma.user.delete({ where: { email } }); // sessions·accounts cascade

  // 화이트리스트에서도 제거 (best-effort — env 항목이면 404 무시)
  let unwhitelisted = false;
  try {
    const wl = await fetch(
      `${BACKEND}/admin/whitelist/${encodeURIComponent(email)}`,
      { method: "DELETE", headers: { Authorization: `Bearer ${tokenOrErr}` } },
    );
    unwhitelisted = wl.ok;
  } catch {
    /* 무시 */
  }

  return NextResponse.json({ ok: true, email, unwhitelisted });
}
