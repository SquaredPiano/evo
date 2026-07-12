"use client";

import { useMemo } from "react";
import { RefreshCw, Check, X, TriangleAlert } from "lucide-react";
import ProvenanceBadge from "./ProvenanceBadge";
import { computeDiff } from "@/lib/seqDiff";
import {
  hasRealConfidence,
  type RegenerationMutation,
} from "@/lib/regen";

const BC: Record<string, string> = {
  A: "var(--base-a)",
  T: "var(--base-t)",
  C: "var(--base-c)",
  G: "var(--base-g)",
};

export interface RegenResult {
  /** The region sequence BEFORE regeneration (from the old full sequence). */
  oldRegion: string;
  mutation: RegenerationMutation;
}

/**
 * Result card for a Helio `regenerate_region` action. Shows which region
 * changed, a compact inline diff of old vs regenerated bases, the honest
 * constraint report, and — ONLY when the engine returned real Evo 2
 * probabilities — a per-base confidence strip visually distinct from the
 * heuristic 4D scores. In mock/mock_fallback it shows an honest note instead.
 */
export default function RegenResultCard({ result }: { result: RegenResult }) {
  const { oldRegion, mutation: m } = result;
  const newRegion = m.regenerated ?? "";
  const cr = m.constraint_report;

  const diff = useMemo(
    () => computeDiff(oldRegion, newRegion),
    [oldRegion, newRegion],
  );
  const changeCount = diff.length;
  const identity =
    Math.max(oldRegion.length, newRegion.length) > 0
      ? 1 - changeCount / Math.max(oldRegion.length, newRegion.length)
      : 1;

  const realConfidence = hasRealConfidence(m);

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        background: "var(--surface-base)",
        border: "1px solid var(--ghost-border)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2 px-3.5 py-2.5 flex-wrap"
        style={{ borderBottom: "1px solid var(--ghost-border)" }}
      >
        <RefreshCw size={13} style={{ color: "var(--accent)" }} />
        <span
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-primary)" }}
        >
          Region regenerated
        </span>
        <span className="flex-1" />
        <ProvenanceBadge
          engine={m.engine}
          method={m.method}
          prefixOnlyConditioning={m.prefix_only_conditioning}
        />
      </div>

      <div className="px-3.5 py-3 space-y-3">
        {/* Region coordinates */}
        <div className="text-[11px] font-mono" style={{ color: "var(--text-secondary)" }}>
          positions{" "}
          <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
            {m.start}–{m.end}
          </span>
          {m.new_region_end !== m.end && (
            <>
              {" "}→ new end{" "}
              <span style={{ color: "var(--base-t)", fontWeight: 600 }}>
                {m.new_region_end}
              </span>
            </>
          )}
          {"  ·  "}
          {changeCount} base{changeCount !== 1 ? "s" : ""} changed ·{" "}
          {(identity * 100).toFixed(0)}% identity
          {typeof m.candidates_evaluated === "number" && m.candidates_evaluated > 0 && (
            <>
              {"  ·  "}
              {m.candidates_evaluated} sampled
            </>
          )}
        </div>

        {/* Real Evo 2 confidence strip — VISUALLY DISTINCT from 4D heuristics */}
        {realConfidence ? (
          <ConfidenceStrip probs={m.sampled_probs} />
        ) : (
          <div
            className="text-[10.5px] leading-relaxed rounded-lg px-2.5 py-2"
            style={{
              background: "color-mix(in oklch, var(--base-t), transparent 92%)",
              color: "var(--text-muted)",
              border: "1px solid color-mix(in oklch, var(--base-t), transparent 82%)",
            }}
          >
            No real Evo 2 per-base confidence for this region — it came from the{" "}
            <span style={{ fontWeight: 600 }}>{m.engine}</span> path, which does
            not return genuine model probabilities. Confidence is intentionally
            not shown rather than fabricated.
          </div>
        )}

        {/* Compact inline diff: old region over regenerated */}
        <InlineDiff oldRegion={oldRegion} newRegion={newRegion} diffPositions={new Set(diff.filter((d) => d.kind === "snp").map((d) => d.position))} />

        {/* Constraint report */}
        <ConstraintReportView report={cr} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Real per-base Evo 2 confidence strip (0..1). Deliberately uses an indigo
// ramp so it never reads like the honey/green heuristic 4D score bars.
// ---------------------------------------------------------------------------
function ConfidenceStrip({ probs }: { probs: number[] }) {
  const mean = probs.reduce((a, b) => a + b, 0) / probs.length;
  const min = Math.min(...probs);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span
          className="text-[9px] font-semibold uppercase tracking-wider inline-flex items-center gap-1"
          style={{ color: "var(--regen-conf, #6366f1)" }}
        >
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: "var(--regen-conf, #6366f1)" }}
          />
          Evo 2 model confidence (real)
        </span>
        <span className="text-[9px] font-mono" style={{ color: "var(--text-muted)" }}>
          mean {mean.toFixed(2)} · min {min.toFixed(2)}
        </span>
      </div>
      <div
        className="flex items-end gap-px h-8 rounded-md overflow-hidden px-1 py-0.5"
        style={{ background: "color-mix(in oklch, #6366f1, transparent 94%)" }}
      >
        {probs.map((p, i) => {
          const h = Math.max(6, Math.min(100, p * 100));
          return (
            <div
              key={i}
              className="flex-1 rounded-[1px]"
              title={`base +${i}: p=${p.toFixed(3)}`}
              style={{
                height: `${h}%`,
                minWidth: "1px",
                background: `color-mix(in oklch, #6366f1, transparent ${Math.round(
                  (1 - p) * 70,
                )}%)`,
              }}
            />
          );
        })}
      </div>
      <div className="text-[9px] mt-1" style={{ color: "var(--text-faint)" }}>
        Per-base probability the model assigned to each regenerated base. Higher =
        more confident. This is the real Evo 2 signal, separate from the heuristic
        4D scores.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compact inline diff: OLD region above the NEW (regenerated) region, changed
// bases highlighted. Wraps; scrolls if long.
// ---------------------------------------------------------------------------
function InlineDiff({
  oldRegion,
  newRegion,
  diffPositions,
}: {
  oldRegion: string;
  newRegion: string;
  diffPositions: Set<number>;
}) {
  const renderRow = (seq: string, highlight: string) => {
    const cells = [];
    const len = Math.max(oldRegion.length, newRegion.length);
    for (let i = 0; i < len; i++) {
      const base = i < seq.length ? seq[i] : "·";
      const isDiff = diffPositions.has(i) || i >= oldRegion.length || i >= newRegion.length;
      cells.push(
        <span
          key={i}
          className="inline-block text-center"
          style={{
            width: "1ch",
            color: base === "·" ? "var(--text-faint)" : BC[base] ?? "var(--text-muted)",
            background: isDiff ? highlight : "transparent",
            borderRadius: isDiff ? "2px" : "0",
          }}
        >
          {base}
        </span>,
      );
    }
    return cells;
  };

  return (
    <div>
      <div
        className="text-[9px] font-medium uppercase tracking-wider mb-1"
        style={{ color: "var(--text-faint)" }}
      >
        Old → regenerated
      </div>
      <div
        className="font-mono text-[11px] leading-5 overflow-x-auto rounded-lg px-2 py-1.5 space-y-0.5"
        style={{ background: "var(--surface-raised)", border: "1px solid var(--ghost-border)" }}
      >
        <div className="flex items-start gap-1.5 whitespace-nowrap">
          <span className="text-[9px] w-8 shrink-0 select-none pt-0.5" style={{ color: "var(--text-faint)" }}>
            old
          </span>
          <div className="flex flex-nowrap">
            {renderRow(oldRegion, "color-mix(in oklch, var(--base-t), transparent 65%)")}
          </div>
        </div>
        <div className="flex items-start gap-1.5 whitespace-nowrap">
          <span className="text-[9px] w-8 shrink-0 select-none pt-0.5" style={{ color: "var(--accent)" }}>
            new
          </span>
          <div className="flex flex-nowrap">
            {renderRow(newRegion, "color-mix(in oklch, var(--accent), transparent 65%)")}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Honest constraint report
// ---------------------------------------------------------------------------
function ConstraintReportView({ report }: { report?: RegenerationMutation["constraint_report"] }) {
  if (!report) return null;
  const rows: Array<{ label: string; value: string; ok: boolean | null }> = [];

  if (report.gc_target !== null && report.gc_target !== undefined) {
    rows.push({
      label: "GC content",
      value: `${(report.achieved_gc * 100).toFixed(1)}% (target ${(report.gc_target * 100).toFixed(0)}%)`,
      ok: report.gc_within_tolerance,
    });
  } else {
    rows.push({
      label: "GC content",
      value: `${(report.achieved_gc * 100).toFixed(1)}% (no target)`,
      ok: null,
    });
  }

  if (report.length_delta_requested !== 0) {
    rows.push({
      label: "Length",
      value: `${report.region_length_before} → ${report.region_length_after} bp (requested Δ ${report.length_delta_requested > 0 ? "+" : ""}${report.length_delta_requested})`,
      ok: null,
    });
  }

  if (Array.isArray(report.avoid_motifs) && report.avoid_motifs.length > 0) {
    const stillPresent = report.avoid_motifs_still_present ?? [];
    rows.push({
      label: "Avoid motifs",
      value:
        stillPresent.length === 0
          ? `${report.avoid_motifs.join(", ")} — all removed`
          : `still present: ${stillPresent.join(", ")}`,
      ok: stillPresent.length === 0,
    });
  }

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span
          className="text-[9px] font-medium uppercase tracking-wider"
          style={{ color: "var(--text-faint)" }}
        >
          Constraint report
        </span>
        <StatusPill satisfied={report.satisfied} />
      </div>
      <div className="space-y-1">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center gap-2 text-[10.5px]">
            <span className="shrink-0" style={{ width: 84, color: "var(--text-muted)" }}>
              {r.label}
            </span>
            <span className="font-mono flex-1" style={{ color: "var(--text-secondary)" }}>
              {r.value}
            </span>
            {r.ok === true && <Check size={11} style={{ color: "var(--accent)" }} />}
            {r.ok === false && <X size={11} style={{ color: "var(--base-t)" }} />}
          </div>
        ))}
      </div>
      {report.note && (
        <div className="text-[9.5px] mt-1.5" style={{ color: "var(--text-faint)" }}>
          {report.note}
        </div>
      )}
    </div>
  );
}

function StatusPill({ satisfied }: { satisfied: boolean }) {
  const color = satisfied ? "var(--accent)" : "var(--base-t)";
  const Icon = satisfied ? Check : TriangleAlert;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-semibold"
      style={{
        background: `color-mix(in oklch, ${color}, transparent 88%)`,
        color,
      }}
    >
      <Icon size={9} />
      {satisfied ? "constraints met" : "partially met"}
    </span>
  );
}
