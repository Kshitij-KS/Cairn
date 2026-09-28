import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded-md px-1.5 h-5 text-[11px] font-medium tabular-nums whitespace-nowrap", {
  variants: {
    variant: {
      default: "bg-hover text-fg-2",
      outline: "text-muted shadow-[0_0_0_1px_var(--line-2)]",
      flag: "bg-[color-mix(in_srgb,var(--flag)_14%,transparent)] text-flag",
      ok: "bg-[color-mix(in_srgb,var(--ok)_14%,transparent)] text-ok",
      solid: "bg-fg text-bg",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({ className, variant, ...props }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
