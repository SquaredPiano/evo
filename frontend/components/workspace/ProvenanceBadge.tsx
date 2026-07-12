"use client";

import { Zap, FlaskConical, Info } from "lucide-react";
import { engineBadge, methodLabel, type RegenEngine } from "@/lib/regen";

interface ProvenanceBadgeProps {
  engine: RegenEngine;
  method?: string;
  /** The prefix_only_conditioning caveat from the backend. */
  prefixOnlyConditioning?: boolean;
  /** Optional compact rendering for dense candidate rows. */
  compact?: boolean;
}

/**
 * Reusable, HONEST provenance badge. Shows which engine actually produced a
 * sequence ("Evo 2 · NIM (live)" vs "Evo 2 · mock fallback") and surfaces the
 * prefix-conditioning + rejection-sampling caveats in a hover tooltip so a
 * scientist understands this is prefix-conditioned resampling, not native
 * infilling. Used on regen result cards AND redesign candidates.
 */
export default function ProvenanceBadge({
  engine,
  method,
  prefixOnlyConditioning,
  compact,
}: ProvenanceBadgeProps) {
  const badge = engineBadge(engine);
  const Icon = badge.isLive ? Zap : FlaskConical;

  const tooltipLines = [
    badge.detail,
    method ? `Method: ${methodLabel(method)}.` : null,
    prefixOnlyConditioning
      ? "Caveat: the regenerated bases were conditioned on the PREFIX only (not the downstream context) — this is prefix-conditioned rejection sampling, not native infilling."
      : null,
  ]
    .filter(Boolean)
    .join("\n\n");

  const liveColor = "var(--accent)";
  const mockColor = "var(--base-t)";
  const color = badge.isLive ? liveColor : mockColor;

  return (
    <span
      className="inline-flex items-center gap-1 rounded-full font-medium select-none cursor-help"
      title={tooltipLines}
      style={{
        fontSize: compact ? "9px" : "10px",
        padding: compact ? "1px 6px" : "2px 8px",
        background: `color-mix(in oklch, ${color}, transparent 88%)`,
        color,
        border: `1px solid color-mix(in oklch, ${color}, transparent 70%)`,
        lineHeight: 1.3,
      }}
    >
      <Icon size={compact ? 9 : 10} aria-hidden="true" />
      {badge.label}
      {!compact && <Info size={9} style={{ opacity: 0.7 }} aria-hidden="true" />}
    </span>
  );
}
