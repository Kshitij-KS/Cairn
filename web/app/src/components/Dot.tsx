import { motion } from "motion/react";
import { cn } from "@/lib/utils";

/** A note's mark: its colour is its level (or its freshness), its size how much it holds. */
export function Dot({ colour, size = 8, layoutId, flagged, glow, className }: {
  colour: string; size?: number; layoutId?: string; flagged?: boolean; glow?: boolean; className?: string;
}) {
  return (
    <motion.span
      layoutId={layoutId}
      transition={{ type: "spring", duration: 0.45, bounce: 0 }}
      aria-hidden="true"
      className={cn("relative inline-block shrink-0 rounded-full", className)}
      style={{
        width: size, height: size, background: colour,
        boxShadow: [
          "inset 0 1px 0 rgba(255,255,255,.35)",
          glow ? `0 0 0 4px color-mix(in srgb, ${colour} 18%, transparent), 0 0 18px color-mix(in srgb, ${colour} 55%, transparent)` : "",
          flagged ? "0 0 0 2px var(--panel), 0 0 0 3.5px var(--flag)" : "",
        ].filter(Boolean).join(", "),
      }}
    />
  );
}

export const dotSize = (observations: number, base = 7) =>
  base + Math.min(5, Math.round(Math.sqrt(Math.max(0, observations)) * 1.1));
