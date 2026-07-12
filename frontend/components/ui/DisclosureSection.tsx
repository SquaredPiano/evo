"use client";

import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight } from "lucide-react";

/**
 * DisclosureSection - a labeled section that is collapsed by default with a
 * chevron. "Simple by default, expand for depth." Open/closed state is LOCAL
 * (this component owns it, or the parent can control it via `open`/`onToggle`).
 *
 * Uses the existing design tokens so it blends into the current look - no new
 * skin. Reuse this for every progressive-disclosure expander in the workspace.
 */
export default function DisclosureSection({
  label,
  icon,
  hint,
  defaultOpen = false,
  open: controlledOpen,
  onToggle,
  labelColor = "var(--text-muted)",
  children,
  className,
  contentClassName = "px-5 pb-5",
}: {
  label: ReactNode;
  icon?: ReactNode;
  /** Small trailing count/hint, e.g. "3" or "2 sources". */
  hint?: ReactNode;
  defaultOpen?: boolean;
  /** Controlled mode: pass both `open` and `onToggle`. */
  open?: boolean;
  onToggle?: (next: boolean) => void;
  labelColor?: string;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : uncontrolledOpen;

  const toggle = () => {
    const next = !open;
    if (isControlled) onToggle?.(next);
    else setUncontrolledOpen(next);
  };

  return (
    <div className={className}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-5 py-4 text-left transition-colors hover:bg-white/[0.04]"
      >
        <motion.span
          animate={{ rotate: open ? 90 : 0 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="shrink-0 inline-flex"
          style={{ color: "var(--text-faint)" }}
        >
          <ChevronRight size={14} aria-hidden="true" />
        </motion.span>
        {icon && <span className="shrink-0 inline-flex">{icon}</span>}
        <span
          className="text-[11px] font-medium uppercase tracking-wider flex-1"
          style={{ color: labelColor }}
        >
          {label}
        </span>
        {hint != null && (
          <span className="text-[11px] font-mono shrink-0" style={{ color: "var(--text-faint)" }}>
            {hint}
          </span>
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            style={{ overflow: "hidden" }}
          >
            <div className={contentClassName}>{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
