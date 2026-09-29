/**
 * accessToken(HS256 JWS) 검증 — backend scripts/verify_jwt.py 와 동일한 관점의 6단계 체크.
 *
 * 사용:
 *   npm run verify:jwt -- "<eyJ...세그먼트...>"
 *   npm run verify:jwt -- --smoke
 *
 * 환경: .env.local 의 NEXTAUTH_SECRET (또는 셸에서 export). ADMIN_EMAILS 는 선택(콤마 구분).
 */
import { readFileSync, existsSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import { SignJWT, decodeProtectedHeader, jwtVerify } from "jose";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

/** @param {string} t @returns {Record<string,string>} */
function parseDotenv(t) {
  const out = {};
  for (let line of t.split(/\r?\n/)) {
    line = line.trim();
    if (!line || line.startsWith("#")) continue;
    const i = line.indexOf("=");
    if (i < 1) continue;
    let k = line.slice(0, i).trim();
    let v = line.slice(i + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))
      v = v.slice(1, -1);
    out[k] = v;
  }
  return out;
}

/** @param {string | undefined} raw @returns {string[]} */
function parseAdminEmails(raw) {
  if (!raw?.trim()) return [];
  return raw
    .split(/[,;]/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

const fileEnv = existsSync(join(root, ".env.local"))
  ? parseDotenv(readFileSync(join(root, ".env.local"), "utf8"))
  : {};

const SECRET = process.env.NEXTAUTH_SECRET ?? fileEnv.NEXTAUTH_SECRET;
const ADMIN_EMAILS = parseAdminEmails(
  process.env.ADMIN_EMAILS ?? fileEnv.ADMIN_EMAILS,
);

const args = process.argv.slice(2).filter((a) => a !== "--");
const isSmoke = args.includes("--smoke");
const tokenArg = args.find((a) => !a.startsWith("--"));

function fail(step, msg) {
  console.error(`[fail] 단계 ${step}: ${msg}`);
  process.exit(1);
}

async function verifyAccessToken(jwt) {
  if (!jwt || typeof jwt !== "string") fail(1, "토큰이 비어 있음");

  const parts = jwt.split(".");
  if (parts.length !== 3) fail(1, `JWS 세그먼트 ${parts.length}개 (3개 필요)`);
  console.log("[ok] ① JWS 형식 (3 세그먼트)");

  let header;
  try {
    header = decodeProtectedHeader(jwt);
  } catch (e) {
    fail(2, `헤더 디코드 실패: ${e instanceof Error ? e.message : String(e)}`);
  }
  if (header.alg !== "HS256") fail(2, `alg=${header.alg} (HS256 필요)`);
  console.log("[ok] ② 헤더 alg=HS256");

  if (!SECRET) fail(3, "NEXTAUTH_SECRET 없음 (.env.local 또는 환경변수)");

  const key = new TextEncoder().encode(SECRET);
  /** @type {import('jose').JWTPayload} */
  let payload;
  try {
    const { payload: p } = await jwtVerify(jwt, key, { algorithms: ["HS256"] });
    payload = p;
  } catch (e) {
    const m = e instanceof Error ? e.message : String(e);
    if (/expired|exp/i.test(m)) fail(4, `만료 또는 시간: ${m}`);
    if (/signature|mac|verify/i.test(m)) fail(3, `서명/secret 불일치: ${m}`);
    fail(3, m);
  }
  console.log("[ok] ③ HS256 서명 검증 (jwtVerify)");

  const now = Math.floor(Date.now() / 1000);
  if (typeof payload.exp === "number" && payload.exp < now)
    fail(4, `exp 만료 (exp=${payload.exp}, now=${now})`);
  if (typeof payload.iat !== "number") fail(4, "iat 클레임 없음");
  console.log("[ok] ④ 만료·iat (현재 시각 기준 유효)");

  const sub = payload.sub;
  if (!sub || String(sub).trim() === "") fail(5, "sub 비어 있음");
  console.log("[ok] ⑤ sub 존재");

  const email =
    typeof payload.email === "string" ? payload.email.trim().toLowerCase() : "";
  if (!email) fail(6, "페이로드 email 없음");

  if (ADMIN_EMAILS.length > 0 && !ADMIN_EMAILS.includes(email))
    fail(
      6,
      `이메일 허용 목록에 없음 (token=${email}, ADMIN_EMAILS=${ADMIN_EMAILS.join(",")})`,
    );
  if (ADMIN_EMAILS.length === 0) {
    console.log(`[ok] ⑥ ADMIN_EMAILS 미설정 — email 클레임만 확인 (${email})`);
  } else {
    console.log(`[ok] ⑥ ADMIN_EMAILS 허용 (“${email}”)`);
  }

  console.log("");
  console.log("[ok] 6단계 모두 통과");
}

async function main() {
  if (isSmoke) {
    if (!SECRET) {
      console.error("NEXTAUTH_SECRET 이 필요합니다 (.env.local).");
      process.exit(1);
    }
    const key = new TextEncoder().encode(SECRET);
    const emailForSmoke =
      ADMIN_EMAILS[0] ?? fileEnv.TEST_VERIFY_EMAIL ?? "smoke@test.local";
    const listNote =
      ADMIN_EMAILS.length > 0
        ? emailForSmoke
        : `${emailForSmoke} (ADMIN_EMAILS 없음 — ⑥은 클레임만)`;
    console.log("(smoke) 테스트 토큰 발급, 대상 이메일:", listNote);
    const jwt = await new SignJWT({
      email: emailForSmoke,
      email_verified: true,
    })
      .setProtectedHeader({ alg: "HS256" })
      .setSubject("smoke-verify-sub")
      .setIssuedAt()
      .setExpirationTime("7d")
      .sign(key);
    await verifyAccessToken(jwt);
    return;
  }

  const jwt = tokenArg?.trim();
  if (!jwt) {
    console.log(`사용법:
  1) npm run dev → /login 매직링크 후 DevTools 에서 세션 복사
  2) npm run verify:jwt -- "<accessToken 붙여넣기>"
  선택: ADMIN_EMAILS=admin@one.com,a@two.com npm run verify:jwt -- "<token>"
  로컴만: npm run verify:jwt -- --smoke (.env.local NEXTAUTH_SECRET + 선택 ADMIN_EMAILS)`);
    process.exit(2);
    return;
  }

  await verifyAccessToken(jwt);
}

await main();
