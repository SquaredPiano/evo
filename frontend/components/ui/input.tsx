import * as React from "react";
import { cn } from "@/lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => (
  <input
    type={type}
    className={cn(
      "flex h-10 w-full rounded-xl border-2 bg-transparent px-4 py-2 text-sm transition-colors",
      "placeholder:text-[var(--text-faint)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--honey-500)]",
      "disabled:cursor-not-allowed disabled:opacity-50",
      className
    )}
    style={{ borderColor: "var(--ghost-border)", color: "var(--text-primary)" }}
    ref={ref}
    {...props}
  />
));
Input.displayName = "Input";

export { Input };
