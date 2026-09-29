"use client";

/**
 * 관리자 기능별 권한(2026-09-22) — GET /admin/me 를 레이아웃에서 한 번 읽어 하위 페이지에 공유.
 *
 * 화면 가드는 편의(탭·버튼 숨김)일 뿐이고 실제 차단은 backend `require_admin` 이 라우트마다 한다
 * (`src/admin_perms.py`). /admin/me 조회가 실패하면(구버전 backend 등) 전 권한으로 간주해
 * 화면을 막지 않는다 — 권한 밖 요청은 어차피 서버가 403 으로 돌려준다.
 */

import { createContext, useContext, type ReactNode } from "react";
import type { AdminMe, AdminPerm } from "@/lib/client/admin";

export type AdminPermsState = {
  me: AdminMe | null;
  loaded: boolean;
  can: (perm: AdminPerm) => boolean;
  /** 권한 미리보기 중이면 false(루트 전용 UI 도 숨겨 실제 권한 관리자 화면과 같게) */
  isRoot: boolean;
  /** 권한 미리보기(루트만, 2026-09-22) — null = 끔. 화면만 흉내, 서버 요청은 루트 권한 그대로. */
  previewPerms: AdminPerm[] | null;
  setPreviewPerms: (perms: AdminPerm[] | null) => void;
};

const Ctx = createContext<AdminPermsState>({
  me: null,
  loaded: false,
  can: () => true,
  isRoot: false,
  previewPerms: null,
  setPreviewPerms: () => {},
});

export function AdminPermsProvider({ value, children }: { value: AdminPermsState; children: ReactNode }) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAdminPerms(): AdminPermsState {
  return useContext(Ctx);
}

export function NoPermission({ label }: { label: string }) {
  return (
    <div className="rounded-card border border-md-outline-variant bg-md-surface-container-low px-5 py-8 text-center text-body-sm text-md-on-surface-variant">
      <span className="material-symbols-outlined mb-2 block text-[28px]" aria-hidden>
        lock
      </span>
      <p className="font-medium text-md-on-surface">‘{label}’ 권한이 없습니다</p>
      <p className="mt-1">루트 관리자에게 사용자 관리 › 관리자 권한에서 켜 달라고 요청하세요.</p>
    </div>
  );
}
