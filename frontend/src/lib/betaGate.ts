/**
 * 클로즈 베타 가입 게이트 (server-side) — 진실원은 **백엔드 화이트리스트**
 * (env ∪ DB, admin 관리). `POST {BACKEND}/beta/check` 로 boolean 만 조회.
 *
 * 이전엔 front 자체 env(`BETA_ALLOWED_EMAILS`/`_DOMAINS`)를 봤는데, admin 이
 * DB 에 추가한 사람이 가입 못 하는 분리 문제가 있었다(2026-07-15 통일).
 *
 * 백엔드 조회 실패 시 **front env 로 폴백**(부트스트랩·백엔드 다운 방어) —
 * 게이트가 조용히 열려버리지 않도록: env 게이트가 켜져 있으면 그 판정을,
 * env 도 비어 있으면(=폴백 불가) 안전하게 **차단**(fail-closed)한다.
 * NextAuth 콜백·API 라우트(서버)에서만 호출.
 */

const BACKEND =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_DEPLOYMENT_URL ||
  "";

const ENV_EMAILS = (process.env.BETA_ALLOWED_EMAILS ?? "")
  .split(",")
  .map((s) => s.trim().toLowerCase())
  .filter(Boolean);
const ENV_DOMAINS = (process.env.BETA_ALLOWED_DOMAINS ?? "")
  .split(",")
  .map((s) => s.trim().toLowerCase().replace(/^@/, ""))
  .filter(Boolean);
const ENV_GATE_ON = ENV_EMAILS.length > 0 || ENV_DOMAINS.length > 0;

function envAllowed(email: string): boolean {
  if (ENV_EMAILS.includes(email)) return true;
  const domain = email.split("@")[1];
  return !!domain && ENV_DOMAINS.includes(domain);
}

/** 백엔드 폴백 판정 — env 게이트 켜져 있으면 그 결과, 아니면 fail-closed. */
function fallbackAllowed(email: string): boolean {
  if (ENV_GATE_ON) return envAllowed(email);
  // env 폴백 불가 + 백엔드 조회 실패 → 가입은 보수적으로 차단(로그인 흐름은
  // 이 함수를 성공 경로에서만 부르므로, 차단돼도 재시도로 복구 가능).
  return false;
}

/**
 * 이 이메일이 클로즈 베타 가입 대상인가. 백엔드 `/beta/check` 우선, 실패 시 폴백.
 */
export async function isBetaAllowed(
  emailRaw: string | null | undefined,
): Promise<boolean> {
  if (!emailRaw) return false;
  const email = emailRaw.trim().toLowerCase();
  if (!BACKEND) return ENV_GATE_ON ? envAllowed(email) : true;

  try {
    const res = await fetch(`${BACKEND.replace(/\/+$/, "")}/beta/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
      // NextAuth 콜백은 짧아야 함 — 백엔드 지연 방어
      signal: AbortSignal.timeout(5000),
      cache: "no-store",
    });
    if (!res.ok) return fallbackAllowed(email);
    const data = (await res.json()) as { allowed?: boolean; gate_active?: boolean };
    // gate_active=false 면 백엔드가 "전면 허용" 상태 — 그대로 허용.
    if (data.gate_active === false) return true;
    return data.allowed === true;
  } catch {
    return fallbackAllowed(email);
  }
}
