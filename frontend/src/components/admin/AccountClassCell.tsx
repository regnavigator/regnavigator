"use client";

/**
 * 계정 구분 셀(2026-09-21) — 관리자·테스트·실사용자.
 *
 * "실사용" 통계·이용 조회·검수 큐는 관리자·테스트(=내부) 계정을 뺀다. 정본 판정은 backend
 * `src/account_class.py`. 2026-09-22 통합: '운영진' 라벨을 없애고 관리자(권한)로 일원화 —
 * 관리자 계정은 여기서 바꿀 수 없고(뱃지로만 표시), 관리 화면이 필요 없는 팀원은 '관리자'로
 * 지정해 권한 없는 관리자로 둔다(루트만). 해제는 편집(연필)에서.
 * 자동 규칙: 관리자 → 관리자 · 오픈 전 가입 + 베타 초대 기록 없음 → 테스트 · 그 외 실사용자.
 */
import { useState } from "react";
import {
  ACCOUNT_CLASS_LABEL,
  type AccountClass,
  type AdminUser,
} from "@/lib/client/admin";

const TONE: Record<AccountClass, string> = {
  staff: "bg-md-secondary-container text-md-on-secondary-container",
  test: "bg-md-surface-container-high text-md-on-surface-variant",
  user: "bg-md-primary-container text-md-on-primary-container",
};

function sourceHint(src?: string): string {
  if (src === "manual") return "관리자가 지정";
  if (src === "auto:admin") return "자동 — 관리자 계정";
  if (src === "auto:pre_launch") return "자동 — 베타 오픈 전 가입, 초대 기록 없음";
  if (src === "auto:beta_invited") return "자동 — 오픈 전 가입이지만 베타 초대 명단";
  return "자동";
}

export function AccountClassCell({
  user,
  onSave,
  canMakeAdmin = false,
}: {
  user: AdminUser;
  onSave: (value: AccountClass | "auto") => Promise<void>;
  /** 루트 관리자만 — '관리자'로 지정(권한 없음에서 시작) */
  canMakeAdmin?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const cls: AccountClass = user.account_class ?? (user.is_test_account ? "test" : "user");
  if (cls === "staff" || user.is_admin || user.is_root_admin) {
    return (
      <span
        title={user.is_root_admin ? "루트 관리자 · 실사용 집계에서 제외" : "관리자 · 실사용 집계에서 제외 — 해제는 편집(연필)에서"}
        className={`inline-flex h-7 w-full items-center rounded px-1.5 text-[11.5px] font-semibold ${TONE.staff}`}
      >
        관리자
      </span>
    );
  }
  const manual = user.account_class_source === "manual";
  const value = manual ? cls : "auto";

  return (
    <select
      aria-label={`${user.email} 계정 구분`}
      title={`${sourceHint(user.account_class_source)}${cls !== "user" ? " · 실사용 집계에서 제외" : ""}`}
      value={value}
      disabled={busy}
      onChange={async (e) => {
        setBusy(true);
        try {
          await onSave(e.target.value as AccountClass | "auto");
        } finally {
          setBusy(false);
        }
      }}
      className={`h-7 w-full cursor-pointer rounded border-0 px-1 text-[11.5px] font-semibold focus:outline-none focus:ring-2 focus:ring-md-primary disabled:opacity-60 ${TONE[cls]}`}
    >
      {/* 자동 항목에 지금 판정 결과를 붙여, 드롭다운을 열지 않아도 무엇으로 집계되는지 보인다 */}
      <option value="auto">{manual ? "자동 판정" : `${ACCOUNT_CLASS_LABEL[cls]}·자동`}</option>
      <option value="user">실사용자</option>
      <option value="test">테스트</option>
      {canMakeAdmin ? <option value="staff">관리자로 지정</option> : null}
    </select>
  );
}
