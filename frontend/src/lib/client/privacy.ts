/**
 * 동의 기록 + 정보주체 권리 클라이언트 — 개인정보보호법 이행 (JWT 인증 필요).
 *
 * - `GET  /me/consent` : 동의 상태 — `needs_consent` 면 동의 화면을 띄운다
 * - `POST /me/consent` : 동의 영속 — 필수 `terms`+`transfer`(국외이전, 법 제28조의8)
 * - `GET  /me/data`    : 열람 요구(법 제35조) — 보관 데이터·보유기간·국외이전 수령자
 * - `POST /me/erase`   : 삭제 요구(법 제36·37조) 접수 — 운영자가 파기 실행
 *
 * ⚠️ 동의는 서버 events(legal_consent)에 남아야 입증 가능 — 체크박스를 화면에서만
 * 받고 버리면 안 된다. 연동 스펙: medi-back `docs/frontend_legal_handoff.md` §1·§5.
 */

import { apiFetch, type ApiError } from "@/lib/api/client";

export type ConsentScope = "terms" | "transfer" | "marketing";

export type ConsentStatus = {
  current_version: string;
  agreed_version: string | null;
  agreed_at: string | null;
  agreed_scopes: ConsentScope[];
  required_scopes: ConsentScope[];
  needs_consent: boolean;
};

export async function getConsentStatus(): Promise<ConsentStatus> {
  return apiFetch<ConsentStatus>("/me/consent");
}

/**
 * 동의 기록. version 미지정 시 서버 current_version을 먼저 조회해 사용.
 * 전송 중 고지가 개정돼 409(버전 불일치)가 오면 최신 버전으로 1회 재시도.
 */
export async function giveConsent(
  scopes: ConsentScope[],
  version?: string,
): Promise<{ ok: boolean; version: string; scopes: ConsentScope[] }> {
  const v = version ?? (await getConsentStatus()).current_version;
  const post = (ver: string) =>
    apiFetch<{ ok: boolean; version: string; scopes: ConsentScope[] }>("/me/consent", {
      method: "POST",
      body: JSON.stringify({ version: ver, scopes }),
    });
  try {
    return await post(v);
  } catch (err) {
    if ((err as ApiError).status === 409) {
      const fresh = await getConsentStatus();
      return post(fresh.current_version);
    }
    throw err;
  }
}

export type MyData = {
  user: { id: string; email: string | null; created_at: string | null };
  consent: { version: string | null; agreed_at: string | null; scopes: string[] } | null;
  counts: { events: number };
  retention: Record<string, string>;
  국외이전: string[];
  notice: string;
};

export async function getMyData(): Promise<MyData> {
  return apiFetch<MyData>("/me/data");
}

export async function requestErasure(
  reason?: string,
): Promise<{ ok: boolean; status: string; note: string }> {
  return apiFetch("/me/erase", {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? "" }),
  });
}

/**
 * 회원탈퇴 (자발적) — 소프트삭제. 즉시 계정 접근 차단(데이터는 보존 정책대로).
 * 완전 파기는 requestErasure(제36조). 성공 후 호출자가 signOut 한다.
 */
export async function withdrawAccount(
  reason?: string,
): Promise<{ ok: boolean; status: string; note: string }> {
  return apiFetch("/me/withdraw", {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? "" }),
  });
}
