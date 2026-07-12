"use client";

import { RotateCcw, Crosshair, Palette } from "lucide-react";

interface StructureControlsProps {
  onReset: () => void;
  onHighlight: () => void;
  onToggleColorMode?: () => void;
  colorMode?: "confidence" | "chain";
}

function IconButton({
  onClick,
  label,
  children,
}: {
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className="w-8 h-8 rounded-full bg-[var(--surface-raised)] hover:bg-[var(--surface-elevated)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-muted)] transition-colors"
    >
      {children}
    </button>
  );
}

export default function StructureControls({
  onReset,
  onHighlight,
  onToggleColorMode,
}: StructureControlsProps) {
  return (
    <div className="flex items-center gap-1.5 mt-2">
      <IconButton onClick={onHighlight} label="Highlight selected residue">
        <Crosshair size={14} />
      </IconButton>
      <IconButton onClick={onReset} label="Reset view">
        <RotateCcw size={14} />
      </IconButton>
      {onToggleColorMode && (
        <IconButton onClick={onToggleColorMode} label="Toggle color mode">
          <Palette size={14} />
        </IconButton>
      )}

      {/* pLDDT legend - AlphaFold / ESMFold standard confidence bands */}
      <div className="flex items-center gap-2 ml-auto">
        {[
          { color: "#0053D6", label: ">90" },
          { color: "#65CBF3", label: ">70" },
          { color: "#FFDB13", label: ">50" },
          { color: "#FF7D45", label: "<50" },
        ].map(({ color, label }) => (
          <div key={label} className="flex items-center gap-1">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="text-[10px] text-[var(--text-faint)] font-mono">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
