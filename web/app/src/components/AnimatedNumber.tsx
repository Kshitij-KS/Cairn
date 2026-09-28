import * as React from "react";
import { animate, useReducedMotion } from "motion/react";

/** A number that counts up once, the first time it is shown. The final value is in the markup
 *  from the start (data-value, aria-label), so nothing reading the page ever sees a wrong one. */
export function AnimatedNumber({ value, className }: { value: number; className?: string }) {
  const ref = React.useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduced || value < 4) { el.textContent = value.toLocaleString("en-US"); return; }
    const c = animate(0, value, {
      duration: 0.7, ease: [0.23, 1, 0.32, 1],
      onUpdate: (v) => { el.textContent = Math.round(v).toLocaleString("en-US"); },
    });
    return () => c.stop();
  }, [value, reduced]);
  return <span ref={ref} data-value={value} aria-label={String(value)} className={className}>{value.toLocaleString("en-US")}</span>;
}
