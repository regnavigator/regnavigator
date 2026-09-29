"use client";

/**
 * useConfirm — Promise 기반 확인 다이얼로그 훅. `window.confirm`(비테마·차단형) 대체.
 *
 *   const { confirm, confirmDialog } = useConfirm();
 *   if (!(await confirm({ title: "...", danger: true }))) return;
 *   ...JSX 어딘가에 {confirmDialog}
 */

import { useCallback, useRef, useState, type ReactNode } from "react";
import {
  ConfirmDialog,
  type ConfirmOptions,
} from "@/components/ui/confirm-dialog";

export function useConfirm(): {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  confirmDialog: ReactNode;
} {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);

  const confirm = useCallback((opts: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      resolver.current?.(false); // 이전 다이얼로그가 열려 있었다면 취소 처리
      resolver.current = resolve;
      setOptions(opts);
    });
  }, []);

  const settle = (ok: boolean) => {
    resolver.current?.(ok);
    resolver.current = null;
    setOptions(null);
  };

  const confirmDialog = (
    <ConfirmDialog
      open={options !== null}
      options={options}
      onCancel={() => settle(false)}
      onConfirm={() => settle(true)}
    />
  );

  return { confirm, confirmDialog };
}
