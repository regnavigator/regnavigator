/**
 * 내 프로필(/me/profile) — 표시명·소속·직군 (backend users 테이블 영속).
 *
 * admin 이용조회의 작성자 표시 재료. 가입 폼의 draft(job/organization)를
 * ProfileInit 이 로그인 직후 자동 영속한다.
 */
import { apiFetch } from "@/lib/api/client";

export type MyProfile = {
  display_name: string | null;
  affiliation: string | null;
  job_role: string | null;
  /** 소속 입력 완료 여부 — 온보딩 자동 제출 스킵 판별 */
  completed: boolean;
};

export async function getMyProfile(): Promise<MyProfile> {
  return apiFetch("/me/profile");
}

export async function putMyProfile(p: {
  display_name?: string | null;
  affiliation?: string | null;
  job_role?: string | null;
}): Promise<void> {
  await apiFetch("/me/profile", {
    method: "PUT",
    body: JSON.stringify(p),
  });
}
