"use client";

import dynamic from "next/dynamic";
import { Box, ArrowRight, Loader2 } from "lucide-react";
import { ScienceTooltip } from "@/components/ui/ScienceTooltip";

// The single live viewer for the Overview. Lazy/dynamic so it never bloats the
// initial page load and only mounts when a structure actually exists.
const ProteinViewer = dynamic(() => import("@/components/structure/ProteinViewer"), {
  ssr: false,
  loading: () => <ViewerStage label="Preparing viewer" spinning />,
});

interface InlineStructureCardProps {
  pdbData: string | null;
  structureModel: string | null;
  highlightResidues: number[];
  /** True while ESMFold is actively predicting a fold for this design. */
  folding: boolean;
  onExplore: () => void;
  onResidueClick?: (residueSeq: number) => void;
  onResidueHover?: (residueSeq: number | null) => void;
}

/** Shared dark stage used for the loading and skeleton states. */
function ViewerStage({ label, spinning = false }: { label: string; spinning?: boolean }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2.5" style={{ background: "#0A0A0A" }}>
      {spinning ? (
        <Loader2 size={22} className="animate-spin" style={{ color: "var(--honey-400)" }} aria-hidden="true" />
      ) : (
        <Box size={26} style={{ color: "var(--honey-400)", opacity: 0.7 }} aria-hidden="true" />
      )}
      <span className="text-[11px]" style={{ color: "rgba(250,249,246,0.6)" }}>{label}</span>
    </div>
  );
}

export default function InlineStructureCard({
  pdbData,
  structureModel,
  highlightResidues,
  folding,
  onExplore,
  onResidueClick,
  onResidueHover,
}: InlineStructureCardProps) {
  const hasStructure = Boolean(pdbData && pdbData.trim());
  const modelTag = structureModel === "user_pdb" ? "uploaded" : (structureModel ?? "ESMFold");

  return (
    <div className="card-elevated is-interactive overflow-hidden h-full flex flex-col">
      <div className="flex items-center justify-between px-5 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <Box size={14} style={{ color: "var(--accent)" }} aria-hidden="true" />
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em]" style={{ color: "var(--accent)" }}>
            <ScienceTooltip term="protein-structure">Protein structure</ScienceTooltip>
          </span>
        </div>
        {hasStructure && (
          <span className="text-[10px] font-mono" style={{ color: "var(--text-faint)" }}>{modelTag}</span>
        )}
      </div>

      {/* Live 3D stage: real mini scene when a fold exists, honest states otherwise. */}
      <div
        className="relative mx-3 rounded-2xl overflow-hidden"
        style={{ height: 240, background: "#0A0A0A", boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.05)" }}
      >
        {hasStructure ? (
          <ProteinViewer
            pdbData={pdbData!}
            highlightResidues={highlightResidues}
            onResidueClick={onResidueClick}
            onResidueHover={onResidueHover}
            theme="dark"
            structureModel={structureModel}
          />
        ) : folding ? (
          <ViewerStage label="Folding with ESMFold…" spinning />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2.5 px-6 text-center" style={{ background: "#0A0A0A" }}>
            <Box size={26} style={{ color: "var(--honey-400)", opacity: 0.55 }} aria-hidden="true" />
            <span className="text-[12px] font-medium" style={{ color: "rgba(250,249,246,0.78)" }}>
              No folded structure for this design
            </span>
            <span className="text-[11px] leading-snug max-w-[240px]" style={{ color: "rgba(250,249,246,0.45)" }}>
              ESMFold needs a coding ORF of roughly 40 or more amino acids. Short or non-coding sequences will not fold.
            </span>
          </div>
        )}
      </div>

      <div className="px-3 pt-3 pb-3 mt-auto">
        <button
          onClick={onExplore}
          className="w-full inline-flex items-center justify-center gap-1.5 py-2.5 rounded-full text-xs font-medium transition-colors"
          style={{ color: "var(--accent)", background: "color-mix(in oklch, var(--accent), transparent 92%)" }}
        >
          {hasStructure ? "Explore in 3D" : "Open Structure view"}
          <ArrowRight size={12} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
