import * as React from "react";
import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";

// A segmented control. The active pill MOVES between options (a shared layout animation) rather
// than two backgrounds cross-fading: it shows where the choice went.
export function Segmented<T extends string>({
  value, onChange, options, label, id, className,
}: {
  value: T; onChange: (v: T) => void; options: { value: T; label: React.ReactNode; title?: string }[];
  label: string; id: string; className?: string;
}) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v as T)}
      aria-label={label}
      id={id}
      className={cn("inline-flex h-8 items-center rounded-lg bg-panel p-[3px] shadow-sm", className)}
    >
      {options.map((o) => (
        <ToggleGroup.Item
          key={o.value}
          value={o.value}
          title={o.title}
          data-value={o.value}
          className="pressable relative h-[26px] rounded-[6px] px-2.5 text-[12.5px] font-medium text-muted outline-none hover:text-fg data-[state=on]:text-fg focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          {value === o.value && (
            <motion.span
              layoutId={id + "-thumb"}
              className="absolute inset-0 rounded-[6px] bg-hover shadow-[0_0_0_1px_var(--line-2)]"
              transition={{ type: "spring", duration: 0.3, bounce: 0 }}
            />
          )}
          <span className="relative">{o.label}</span>
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
