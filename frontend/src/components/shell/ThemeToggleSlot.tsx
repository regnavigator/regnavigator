"use client";

/**
 * ThemeToggleSlot — fixed 우상단 ThemeToggle을 *적절한 path에서만* 노출.
 *
 * - /landing/* (URL 단위로 theme 결정되는 페이지)에선 토글 숨김
 * - 그 외 (chat·인증·admin 등)에선 노출
 */

import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/shell/ThemeToggle";

const HIDDEN_PREFIXES = ["/landing"];

export function ThemeToggleSlot() {
  const pathname = usePathname();
  const hide = HIDDEN_PREFIXES.some((p) => pathname?.startsWith(p));
  if (hide) return null;
  return (
    <div className="fixed bottom-3 right-3 z-50">
      <ThemeToggle />
    </div>
  );
}
