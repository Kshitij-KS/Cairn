import * as React from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

export const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      "peer inline-flex h-[18px] w-[30px] shrink-0 cursor-pointer items-center rounded-full p-[2px] transition-colors duration-150 bg-line-2 data-[state=checked]:bg-fg",
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb className="pointer-events-none block size-[14px] rounded-full bg-bg shadow-sm transition-transform duration-200 ease-out data-[state=checked]:translate-x-3" />
  </SwitchPrimitive.Root>
));
Switch.displayName = "Switch";
