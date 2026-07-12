"use client";

import { useEffect, useState } from "react";
import type { RegionEvidence, SequenceRegion } from "@/types";
import RegionHighlight from "@/components/sequence/RegionHighlight";
import RegionEvidenceCard from "@/components/annotation/RegionEvidenceCard";
import { useEvoStore } from "@/lib/store";

interface AnnotationTrackProps {
  regions: SequenceRegion[];
  sequenceLength: number;
  /** Optional explicit evidence; defaults to the store's regionEvidence. */
  evidence?: RegionEvidence[];
  /** Optional gene symbol to scope ClinVar evidence for the fetch. */
  gene?: string | null;
}

/** Items overlapping [region.start, region.end) - half-open ranges. */
function evidenceForRegion(items: RegionEvidence[], region: SequenceRegion): RegionEvidence[] {
  return items.filter((e) => e.end > region.start && e.start < region.end);
}

export default function AnnotationTrack({
  regions,
  sequenceLength,
  evidence,
  gene = null,
}: AnnotationTrackProps) {
  const rawSequence = useEvoStore((s) => s.rawSequence);
  const storeEvidence = useEvoStore((s) => s.regionEvidence);
  const loadRegionEvidence = useEvoStore((s) => s.loadRegionEvidence);
  const selectedRegion = useEvoStore((s) => s.selectedRegion);
  const setSelectedRegion = useEvoStore((s) => s.setSelectedRegion);
  const setSelectedPosition = useEvoStore((s) => s.setSelectedPosition);
  const setChatOpen = useEvoStore((s) => s.setChatOpen);
  const setChatDraft = useEvoStore((s) => s.setChatDraft);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  // Clicking a region bar SELECTS that range for a region-aware Helio ask, then
  // opens Helio pre-filled with the explain prompt (the user still hits send).
  const selectRegion = (region: SequenceRegion) => {
    setSelectedRegion({ start: region.start, end: region.end });
    setSelectedPosition(region.start);
    setChatOpen(true);
    setChatDraft(
      "Explain the selected region in plain English - what it does, why it matters, and how confident the model is."
    );
  };

  const items = evidence ?? storeEvidence;

  // Fetch coordinate-bound evidence whenever the sequence changes. Deduped in
  // the store, so both AnnotationTrack instances share one fetch.
  useEffect(() => {
    if (rawSequence) loadRegionEvidence(rawSequence, gene);
  }, [rawSequence, gene, loadRegionEvidence]);

  if (sequenceLength === 0) return null;

  const hoveredRegion = hoveredIndex !== null ? regions[hoveredIndex] : null;
  const hoveredEvidence = hoveredRegion ? evidenceForRegion(items, hoveredRegion) : [];

  return (
    <div className="flex flex-col gap-1">
      <span
        className="select-none uppercase tracking-wider"
        style={{ fontSize: "10px", color: "var(--text-faint)", fontWeight: 600, letterSpacing: "0.05em" }}
      >
        Annotations
      </span>
      <div
        className="relative"
        style={{
          height: "20px",
          backgroundColor: "var(--surface-base)",
          borderRadius: "3px",
        }}
      >
        {/* Visual bars - existing rendering, unchanged. */}
        <div className="absolute inset-0 overflow-hidden" style={{ borderRadius: "3px" }}>
          {regions.map((region, i) => (
            <RegionHighlight
              key={`${region.start}-${region.end}-${i}`}
              region={region}
              sequenceLength={sequenceLength}
            />
          ))}
        </div>

        {/* Hover/evidence layer - transparent hitboxes over each region. */}
        <div className="absolute inset-0">
          {regions.map((region, i) => {
            const leftPct = (region.start / sequenceLength) * 100;
            const widthPct = ((region.end - region.start) / sequenceLength) * 100;
            const count = evidenceForRegion(items, region).length;
            const isSelected =
              selectedRegion !== null &&
              selectedRegion.start === region.start &&
              selectedRegion.end === region.end;
            return (
              <div
                key={`hit-${region.start}-${region.end}-${i}`}
                className="absolute top-0 bottom-0 cursor-pointer"
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                role="button"
                tabIndex={0}
                aria-label={`Explain region ${region.label ?? region.type} (${region.start}–${region.end})`}
                title="Click to explain this region with Helio"
                onClick={() => selectRegion(region)}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter" || ev.key === " ") {
                    ev.preventDefault();
                    selectRegion(region);
                  }
                }}
                onMouseEnter={() => setHoveredIndex(i)}
                onMouseLeave={() => setHoveredIndex((cur) => (cur === i ? null : cur))}
              >
                {isSelected && (
                  <span
                    aria-hidden
                    className="absolute inset-0"
                    style={{
                      border: "1.5px solid var(--accent)",
                      borderRadius: "3px",
                      boxShadow: "0 0 0 1px color-mix(in oklch, var(--accent), transparent 60%)",
                    }}
                  />
                )}
                {count > 0 && (
                  <span
                    aria-hidden
                    className="absolute"
                    style={{
                      top: "2px",
                      right: "2px",
                      width: "5px",
                      height: "5px",
                      borderRadius: "50%",
                      backgroundColor: "var(--accent)",
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Evidence card popover. */}
        {hoveredRegion && (
          <div
            className="absolute z-50"
            style={{
              top: "26px",
              left: `${Math.min(85, (hoveredRegion.start / sequenceLength) * 100)}%`,
            }}
            onMouseEnter={() => setHoveredIndex(hoveredIndex)}
            onMouseLeave={() => setHoveredIndex(null)}
          >
            <RegionEvidenceCard region={hoveredRegion} evidence={hoveredEvidence} />
          </div>
        )}
      </div>
    </div>
  );
}
