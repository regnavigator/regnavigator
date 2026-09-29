/**
 * import-auth-json.mjs — 구 SQLite(prod.db) 인증 데이터를 Postgres(medi_auth)로 이관.
 *
 * 새 npm 의존성 0 — 기존 @prisma/client(PG 대상 generate됨)만 사용.
 * SQLite 읽기는 sqlite3 CLI가 담당(런북에서 JSON export). 이 스크립트는 그 JSON을
 * 받아 FK 순서로 upsert(멱등 — 재실행 안전).
 *
 * 사전(런북 docs/auth_db_postgres_migration.md 참조):
 *   mkdir -p auth-export
 *   for T in User Account Session VerificationToken; do
 *     sqlite3 -json prod.db "SELECT * FROM \"$T\";" > "auth-export/$T.json"
 *   done
 *
 * 실행(migrator 컨테이너 안, DATABASE_URL=medi_auth 주입 상태):
 *   node scripts/import-auth-json.mjs ./auth-export
 *
 * DateTime 필드(emailVerified·expires)는 SQLite 저장형(epoch ms 정수 또는 ISO 문자열)
 * 을 모두 허용해 Date로 변환. Account.expires_at은 Int(초)라 변환하지 않음.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { PrismaClient } from "@prisma/client";

const dir = process.argv[2] || "./auth-export";
const prisma = new PrismaClient();

function load(table) {
  try {
    const raw = readFileSync(join(dir, `${table}.json`), "utf8").trim();
    if (!raw) return [];
    const rows = JSON.parse(raw);
    return Array.isArray(rows) ? rows : [];
  } catch (e) {
    if (e.code === "ENOENT") {
      console.warn(`[skip] ${table}.json 없음 — 이 테이블 건너뜀`);
      return [];
    }
    throw e;
  }
}

/** epoch ms 정수 또는 ISO 문자열 → Date. null/undefined/빈값 → null. */
function toDate(v) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return new Date(v);
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) && /^\d+$/.test(v.trim()) ? new Date(n) : new Date(v);
  }
  return null;
}

async function main() {
  let n = { user: 0, account: 0, session: 0, vtoken: 0 };

  // 1) User — 최상위(FK 부모). id 보존, passwordHash 그대로 이관.
  for (const u of load("User")) {
    await prisma.user.upsert({
      where: { id: u.id },
      update: {
        email: u.email ?? null,
        emailVerified: toDate(u.emailVerified),
        name: u.name ?? null,
        image: u.image ?? null,
        passwordHash: u.passwordHash ?? null,
      },
      create: {
        id: u.id,
        email: u.email ?? null,
        emailVerified: toDate(u.emailVerified),
        name: u.name ?? null,
        image: u.image ?? null,
        passwordHash: u.passwordHash ?? null,
      },
    });
    n.user++;
  }

  // 2) Account — OAuth 연동(있으면). unique(provider, providerAccountId).
  for (const a of load("Account")) {
    await prisma.account.upsert({
      where: {
        provider_providerAccountId: {
          provider: a.provider,
          providerAccountId: a.providerAccountId,
        },
      },
      update: {
        userId: a.userId,
        type: a.type,
        refresh_token: a.refresh_token ?? null,
        access_token: a.access_token ?? null,
        expires_at: a.expires_at ?? null,
        token_type: a.token_type ?? null,
        scope: a.scope ?? null,
        id_token: a.id_token ?? null,
        session_state: a.session_state ?? null,
      },
      create: {
        id: a.id,
        userId: a.userId,
        type: a.type,
        provider: a.provider,
        providerAccountId: a.providerAccountId,
        refresh_token: a.refresh_token ?? null,
        access_token: a.access_token ?? null,
        expires_at: a.expires_at ?? null,
        token_type: a.token_type ?? null,
        scope: a.scope ?? null,
        id_token: a.id_token ?? null,
        session_state: a.session_state ?? null,
      },
    });
    n.account++;
  }

  // 3) Session — 선택(만료되면 재로그인이면 그만). unique(sessionToken).
  for (const s of load("Session")) {
    const expires = toDate(s.expires);
    if (!expires) continue; // 만료값 없으면 스킵(무의미).
    await prisma.session.upsert({
      where: { sessionToken: s.sessionToken },
      update: { userId: s.userId, expires },
      create: { id: s.id, sessionToken: s.sessionToken, userId: s.userId, expires },
    });
    n.session++;
  }

  // 4) VerificationToken — 대기 중 매직링크(선택). unique(identifier, token).
  for (const t of load("VerificationToken")) {
    const expires = toDate(t.expires);
    if (!expires) continue;
    await prisma.verificationToken.upsert({
      where: {
        identifier_token: { identifier: t.identifier, token: t.token },
      },
      update: { expires },
      create: { identifier: t.identifier, token: t.token, expires },
    });
    n.vtoken++;
  }

  console.log(
    `[done] User ${n.user} · Account ${n.account} · Session ${n.session} · VerificationToken ${n.vtoken} 이관 완료`,
  );
}

main()
  .catch((e) => {
    console.error("[error]", e);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
