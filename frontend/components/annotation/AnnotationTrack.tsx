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

/** Items overlapping [region.start, region.end) — half-open ranges. */
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
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

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
        {/* Visual bars — existing rendering, unchanged. */}
        <div className="absolute inset-0 overflow-hidden" style={{ borderRadius: "3px" }}>
          {regions.map((region, i) => (
            <RegionHighlight
              key={`${region.start}-${region.end}-${i}`}
              region={region}
              sequenceLength={sequenceLength}
            />
          ))}
        </div>

        {/* Hover/evidence layer — transparent hitboxes over each region. */}
        <div className="absolute inset-0">
          {regions.map((region, i) => {
            const leftPct = (region.start / sequenceLength) * 100;
            const widthPct = ((region.end - region.start) / sequenceLength) * 100;
            const count = evidenceForRegion(items, region).length;
            return (
              <div
                key={`hit-${region.start}-${region.end}-${i}`}
                className="absolute top-0 bottom-0 cursor-pointer"
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                onMouseEnter={() => setHoveredIndex(i)}
                onMouseLeave={() => setHoveredIndex((cur) => (cur === i ? null : cur))}
              >
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
