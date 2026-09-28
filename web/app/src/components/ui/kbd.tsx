import { cn } from "@/lib/utils";
export function Kbd({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <kbd className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded-[5px] px-1 font-mono text-[10.5px] text-muted shadow-[0_0_0_1px_var(--line-2)] bg-panel", className)}>
      {children}
    </kbd>
  );
}
