"use client";

/**
 * EditingCandidateChrome - the persistent "which candidate do edits apply to?"
 * indicator. Reads the store directly so every edit surface stays truthful and
 * in sync with `activeCandidateId` (via the shared candidateDisplay helper).
 *
 * Variants:
 *   - "pill"     compact rounded pill for headers / view-tab area
 *   - "toolbar"  "Editing candidate #N · {bp} · {n} edits" for the sequence toolbar
 *   - "subline"  quiet one-liner under a panel header (mutation / tools / chat)
 *
 * Renders nothing when no candidate has resolved yet.
 */

import { Pencil } from "lucide-react";
import { useEvoStore } from "@/lib/store";
import { getCandidateDisplay } from "@/lib/candidateDisplay";

interface Props {
  variant?: "pill" | "toolbar" | "subline";
  className?: string;
}

export default function EditingCandidateChrome({ variant = "pill", className }: Props) {
  const candidates = useEvoStore((s) => s.candidates);
  const activeCandidateId = useEvoStore((s) => s.activeCandidateId);
  const rawSequence = useEvoStore((s) => s.rawSequence);
  const editCount = useEvoStore((s) => s.editHistory.length);

  const display = getCandidateDisplay(candidates, activeCandidateId);
  if (!display.hasCandidate) return null;

  if (variant === "toolbar") {
    return (
      <span
        className={`inline-flex items-center gap-1.5 text-[11px] font-medium ${className ?? ""}`}
        title={display.subtitle}
        style={{ color: "var(--text-secondary)" }}
      >
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full"
          style={{ background: "color-mix(in oklch, var(--accent), transparent 88%)", color: "var(--accent)" }}
        >
          <Pencil size={11} aria-hidden="true" />
          {display.label}
        </span>
        <span className="font-mono" style={{ color: "var(--text-faint)" }}>
          · {rawSequence.length} bp · {editCount} edit{editCount !== 1 ? "s" : ""}
        </span>
      </span>
    );
  }

  if (variant === "subline") {
    return (
      <span
        className={`inline-flex items-center gap-1 text-[10px] font-medium ${className ?? ""}`}
        title={display.subtitle}
        style={{ color: "var(--text-muted)" }}
      >
        <Pencil size={10} aria-hidden="true" style={{ color: "var(--accent)" }} />
        {display.label}
      </span>
    );
  }

  // "pill"
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-medium ${className ?? ""}`}
      title={display.subtitle}
      style={{
        background: "color-mix(in oklch, var(--accent), transparent 88%)",
        color: "var(--accent)",
      }}
    >
      <Pencil size={12} aria-hidden="true" />
      {display.label}
    </span>
  );
}
