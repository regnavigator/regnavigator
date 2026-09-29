/**
 * 테스트 계정 생성 — 매직링크(이메일 인증) 생략하고 auth DB에 직접 upsert.
 *
 * 베타 전 내부 테스트용(2026-07-16). 테스터의 실제 이메일로 등록하면
 * 보고서 완료 메일도 그 주소로 수신된다. 이미 있는 이메일이면 비밀번호만 갱신.
 *
 * 사용 (medi-front 루트에서, DATABASE_URL은 env 파일에서):
 *   node --env-file=.env.development.local scripts/create_test_account.mjs <이메일> <비밀번호> [이름]
 *   (운영: --env-file=.env.production 또는 컨테이너 env)
 *
 * ⚠️ 클로즈 베타 게이트: medi-back BETA_WHITELIST_EMAILS 가 설정돼 있으면
 *    이 이메일도 화이트리스트(env 또는 admin 화면)에 추가해야 로그인 후 API 사용 가능.
 */
import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const [email, password, name] = process.argv.slice(2);
if (!email || !password) {
  console.error("사용법: node --env-file=<env파일> scripts/create_test_account.mjs <이메일> <비밀번호> [이름]");
  process.exit(1);
}
if (password.length < 8) {
  console.error("비밀번호는 8자 이상 (password-policy 최소 기준)");
  process.exit(1);
}

const prisma = new PrismaClient();
const passwordHash = await bcrypt.hash(password, 12);
const user = await prisma.user.upsert({
  where: { email },
  update: { passwordHash, emailVerified: new Date() },
  create: {
    email,
    name: name ?? email.split("@")[0],
    passwordHash,
    emailVerified: new Date(), // 매직링크 인증 생략
  },
});
console.log(`✅ ${user.email} (id=${user.id}, name=${user.name}) — 비밀번호 설정 완료`);
console.log("   로그인: /login 에서 이메일+비밀번호. 첫 로그인 시 약관 동의 모달이 뜹니다.");
await prisma.$disconnect();
