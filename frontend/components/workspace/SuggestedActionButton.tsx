"use client";

import { RefreshCw } from "lucide-react";
import type { SuggestedAction } from "@/lib/agentTypes";

/**
 * A prominent one-click chip for Helio's proactive `suggested_action`. Clicking
 * it fires the follow-up that triggers the underlying tool (regenerate_region /
 * optimize_candidate) via the existing agent send path - this is the
 * proactivity that makes Helio feel alive.
 */
export default function SuggestedActionButton({
  action,
  onClick,
  disabled,
}: {
  action: SuggestedAction;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <div
        className="text-[9px] font-semibold uppercase tracking-wider mb-1"
        style={{ color: "var(--accent)" }}
      >
        Helio suggests
      </div>
      <button
        onClick={onClick}
        disabled={disabled}
        className="w-full text-left rounded-2xl px-3.5 py-2.5 transition-all hover:brightness-105 disabled:opacity-50 disabled:cursor-not-allowed"
        style={{
          background: "color-mix(in oklch, var(--accent), transparent 88%)",
          border: "1px solid color-mix(in oklch, var(--accent), transparent 62%)",
        }}
      >
        <div className="flex items-center gap-2">
          <RefreshCw size={13} style={{ color: "var(--accent)" }} />
          <span className="text-[12.5px] font-semibold" style={{ color: "var(--text-primary)" }}>
            {action.label}
          </span>
        </div>
        {action.rationale && (
          <div className="text-[10.5px] mt-1 leading-snug" style={{ color: "var(--text-secondary)" }}>
            {action.rationale}
          </div>
        )}
        {action.objective && (
          <div className="text-[9.5px] mt-1 font-mono" style={{ color: "var(--text-faint)" }}>
            objective: {action.objective}
          </div>
        )}
      </button>
    </div>
  );
}
