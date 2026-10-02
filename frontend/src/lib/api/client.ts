/**
 * 통합 API 클라이언트 — 모든 백엔드 REST 호출의 단일 진입점.
 *
 * 처리 책임:
 *  - base URL · auth header 자동 주입
 *  - DUMMY 모드 시 `mockFetch` 인터셉트
 *  - 401 → /login redirect (호출자가 자체 처리)
 *  - 에러 정합 (status·body 필드 일관성)
 *
 * 기존 `quota.ts`·`admin.ts`·`reports.ts`의 jsonFetch 중복 제거. 같은 wrapper 호출.
 */

import { getAuthToken } from "@/lib/client/authToken";
import { getEffectiveSettings } from "@/lib/store/settings";
import { maybeMockFetch } from "@/lib/client/mockFetch";

export type ApiError = Error & {
  status?: number;
  body?: string;
};

function baseUrl(): string | null {
  const url = getEffectiveSettings().deployment_url;
  if (!url) return null;
  return url.replace(/\/$/, "");
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * REST GET·POST·PATCH·DELETE 단일 wrapper. 응답 JSON 파싱.
 *
 * @throws ApiError — !res.ok 시 status·body 필드 박힘
 * @throws Error("backend URL 미설정") — settings 미충족 + DUMMY 모드도 아님
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();

  // 1) DUMMY 모드 — public/mocks 우선 반환
  const mocked = await maybeMockFetch<T>(path, method);
  if (mocked !== null) return mocked;

  // 2) 실 backend 호출
  const base = baseUrl();
  if (!base) throw new Error("backend URL 미설정");
  // FormData 는 Content-Type 을 **브라우저가** 정해야 한다 — 직접 박으면
  // multipart 경계(boundary)가 빠져 서버가 본문을 못 읽는다(조합 파일 업로드).
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...authHeaders(),
      ...init.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    const err = new Error(`HTTP ${res.status}: ${body}`) as ApiError;
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return (await res.json()) as T;
}

/**
 * 평문 응답용 — `/reports/{id}/download` 같은 markdown body.
 */
export async function apiFetchText(
  path: string,
  init: RequestInit = {},
): Promise<string> {
  // DUMMY 모드의 download 분기는 별도 helper로 (mockFetch가 .json만 처리)
  const base = baseUrl();
  if (!base) throw new Error("backend URL 미설정");
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      ...authHeaders(),
      ...init.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    const err = new Error(`HTTP ${res.status}: ${body}`) as ApiError;
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return res.text();
}

/**
 * Blob 응답용 — 다운로드 트리거.
 */
/** blob + 서버 지정 확장자(X-File-Ext, 기본 hwp) — 원본 서식 다운로드용. */
export async function apiFetchBlobWithExt(
  path: string,
  init: RequestInit = {},
): Promise<{ blob: Blob; ext: string }> {
  const base = baseUrl();
  if (!base) throw new Error("backend URL 미설정");
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...init.headers },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    const err = new Error(`HTTP ${res.status}: ${body}`) as ApiError;
    err.status = res.status;
    err.body = body;
    throw err;
  }
  const ext = (res.headers.get("X-File-Ext") || "hwp").replace(/[^a-z0-9]/gi, "");
  return { blob: await res.blob(), ext: ext || "hwp" };
}

export async function apiFetchBlob(
  path: string,
  init: RequestInit = {},
): Promise<Blob> {
  const base = baseUrl();
  if (!base) throw new Error("backend URL 미설정");
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      ...authHeaders(),
      ...init.headers,
    },
  });
  if (!res.ok) {
    // status·body 부착 — 호출자가 404(대상 없음)/503(도구 미배포) 등을
    // 구분해 안내해야 한다(apiFetch·apiFetchText 와 동일 shape).
    const body = await res.text().catch(() => "");
    const err = new Error(`HTTP ${res.status}: ${body}`) as ApiError;
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return res.blob();
}
