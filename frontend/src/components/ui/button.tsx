import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-button text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary focus-visible:ring-offset-2 focus-visible:ring-offset-md-surface disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      // 브랜드 토큰 기반(md-*) — 3개 테마(basic/medra/regia) 자동 반영.
      // 호출부에서 className 으로 override 하면 twMerge 로 마지막이 이김.
      variant: {
        default: "bg-md-primary text-md-on-primary hover:bg-md-primary/90",
        destructive: "bg-md-error text-md-on-error hover:bg-md-error/90",
        outline:
          "border border-md-outline-variant bg-md-surface text-md-on-surface hover:bg-md-surface-container-low",
        secondary:
          "bg-md-surface-variant text-md-on-surface hover:bg-md-surface-variant/80",
        ghost: "text-md-on-surface hover:bg-md-surface-container-low",
        link: "text-md-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
