"use client";

/**
 * ConfirmDialog — 테마 확인 다이얼로그. `window.confirm`(비테마·차단형) 대체.
 *
 * 제어 컴포넌트: 부모가 `open` + `options` 상태를 들고, onConfirm/onCancel 처리.
 * 파괴적 액션은 `danger`로 destructive 버튼.
 */

import {
  Dialog,
  DialogAction,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type ConfirmOptions = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
};

export function ConfirmDialog({
  open,
  options,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  options: ConfirmOptions | null;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onCancel()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{options?.title}</DialogTitle>
          {options?.description ? (
            <DialogDescription className="whitespace-pre-line">
              {options.description}
            </DialogDescription>
          ) : null}
        </DialogHeader>
        <DialogFooter>
          <DialogAction variant="secondary" onClick={onCancel} disabled={busy}>
            {options?.cancelLabel ?? "취소"}
          </DialogAction>
          <DialogAction
            variant={options?.danger ? "destructive" : "primary"}
            onClick={onConfirm}
            disabled={busy}
          >
            {options?.confirmLabel ?? "확인"}
          </DialogAction>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
