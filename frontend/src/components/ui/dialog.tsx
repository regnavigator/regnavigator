"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";

import { cn } from "@/lib/utils";

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogPortal = DialogPrimitive.Portal;
const DialogClose = DialogPrimitive.Close;

/** 한국어 자연 줄바꿈 — 단어 중간 끊김 방지 + 긴 제목은 어디서든 줄바꿈 */
const dialogText = "min-w-0 break-keep text-pretty [overflow-wrap:anywhere]";

const DialogOverlay = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-black/25 backdrop-blur-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className,
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

type DialogContentProps = React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
  /** 내장 우상단 X 숨김 — 자체 헤더에 닫기를 그리는 모달용(문서 작성 등).
   *  내장 X 는 absolute 라 p-0 커스텀 헤더와 겹친다(2026-08-27 지적). */
  hideClose?: boolean;
  /** 오버레이 덮어쓰기 — 밝은 배경 위 밝은 모달처럼 구분이 약한 자리에서 더 어둡게(2026-09-02) */
  overlayClassName?: string;
};

const DialogContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(({ className, children, hideClose = false, overlayClassName, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay className={overlayClassName} />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        // Apple-style sheet — bright surface, deep soft shadow, subtle ring, zoom-in.
        "fixed left-1/2 top-1/2 z-50 flex w-full max-w-lg -translate-x-1/2 -translate-y-1/2 flex-col gap-6 rounded-[16px] border-0 bg-md-surface-bright p-9 text-md-on-surface shadow-[0_22px_70px_rgba(0,0,0,0.16),0_2px_10px_rgba(0,0,0,0.05)] ring-1 ring-md-outline-variant/15 duration-200 outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95",
        className,
      )}
      {...props}
    >
      {children}
      {hideClose ? null : (
        <DialogPrimitive.Close className="absolute right-3.5 top-3.5 inline-flex h-8 w-8 items-center justify-center rounded-full bg-md-surface-container-low/80 text-md-on-surface-variant outline-none backdrop-blur-sm transition-all duration-[var(--motion-fast)] hover:bg-md-surface-container-high hover:text-md-on-surface focus-visible:ring-2 focus-visible:ring-md-primary/40 disabled:pointer-events-none">
          <span className="material-symbols-outlined text-[18px]" aria-hidden>
            close
          </span>
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      )}
    </DialogPrimitive.Content>
  </DialogPortal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

const DialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col gap-0 pr-9 text-left", className)} {...props} />
);
DialogHeader.displayName = "DialogHeader";

/** 헤더·푸터 사이 본문 */
const DialogBody = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      dialogText,
      "text-body-sm leading-[1.75] text-md-on-surface",
      className,
    )}
    {...props}
  />
);
DialogBody.displayName = "DialogBody";

const DialogFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-row flex-wrap items-center justify-end gap-2.5",
      className,
    )}
    {...props}
  />
);
DialogFooter.displayName = "DialogFooter";

const DialogTitle = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn(
      dialogText,
      "text-h2 font-semibold tracking-[-0.02em] text-md-on-surface",
      className,
    )}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

const DialogDescription = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn(
      dialogText,
      "mt-3 text-body-sm leading-[1.75] text-md-on-surface-variant",
      className,
    )}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

type DialogActionProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "destructive";
};

/** Apple-style 액션 버튼 — rounded rect, subtle press */
const DialogAction = React.forwardRef<HTMLButtonElement, DialogActionProps>(
  ({ className, variant = "primary", type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex h-9 min-w-[4.25rem] items-center justify-center rounded-[10px] px-4 text-body-sm font-medium transition-all duration-[var(--motion-fast)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-md-surface-bright disabled:pointer-events-none disabled:opacity-45",
        variant === "primary" &&
          "bg-md-primary text-md-on-primary shadow-[0_1px_2px_rgba(0,0,0,0.08)] hover:bg-md-primary/92",
        variant === "secondary" &&
          "bg-md-surface-container-high/55 text-md-on-surface hover:bg-md-surface-container-high",
        variant === "destructive" &&
          "bg-md-error text-md-on-error shadow-[0_1px_2px_rgba(0,0,0,0.08)] hover:bg-md-error/92",
        className,
      )}
      {...props}
    />
  ),
);
DialogAction.displayName = "DialogAction";

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogBody,
  DialogFooter,
  DialogTitle,
  DialogDescription,
  DialogAction,
};
