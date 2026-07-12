"use client";

import { useMemo } from "react";
import { MapPin, FlaskConical, ExternalLink, Info } from "lucide-react";
import ProvenanceBadge from "./ProvenanceBadge";
import type {
  RegionExplanation,
  RegionExplanationEvidence,
} from "@/lib/agentTypes";

const INDIGO = "#6366f1"; // real Evo 2 confidence - deliberately NOT honey/green.

/** Real external link only - never fabricate. Require http(s). */
function safeUrl(url?: string | null): string | null {
  if (!url) return null;
  const u = url.trim();
  return u.startsWith("http://") || u.startsWith("https://") ? u : null;
}

const SOURCE_BADGE: Record<string, { label: string; color: string }> = {
  clinvar: { label: "ClinVar", color: "var(--annotation-exon, #d97757)" },
  regulatory: { label: "Regulatory", color: "var(--annotation-orf, #6aa6c9)" },
  literature: { label: "Paper", color: "var(--accent, #7c9885)" },
};

function badgeFor(source: string) {
  return SOURCE_BADGE[source] ?? { label: source, color: "var(--text-muted)" };
}

/**
 * The STAR card: a plain-English, non-biologist-friendly breakdown of ONE
 * region using real Evo 2 signals + evidence. The narrative lead lives in the
 * assistant message above; this renders the honest structured evidence beneath.
 *
 * HONESTY: the per-position mini-chart is a composition signal (honey) unless
 * the backend flags real model confidence, in which case an indigo strip labeled
 * "Evo 2 model confidence (real)" is shown. The two are never conflated.
 */
export default function RegionExplanationCard({
  explanation: e,
}: {
  explanation: RegionExplanation;
}) {
  const region = e.region ?? { start: 0, end: 0, length: 0 };
  const perPos = Array.isArray(e.per_position_scores) ? e.per_position_scores : [];
  const summary = e.signal_summary;
  const mc = e.model_confidence;
  const prov = e.provenance;
  const evidence = Array.isArray(e.evidence) ? e.evidence : [];
  const whole = e.scores_whole_candidate;

  const realConfidence =
    Boolean(mc?.is_real_model_confidence) &&
    Array.isArray(mc?.sampled_probs) &&
    (mc?.sampled_probs?.length ?? 0) > 0;

  const lowConfSet = useMemo(
    () => new Set(summary?.low_confidence_positions ?? []),
    [summary],
  );

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        background: "var(--surface-base)",
        border: "1px solid var(--ghost-border)",
        boxShadow: "var(--shadow-soft)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2 px-3.5 py-2.5 flex-wrap"
        style={{ borderBottom: "1px solid var(--ghost-border)" }}
      >
        <MapPin size={13} style={{ color: "var(--accent)" }} />
        <span
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-primary)" }}
        >
          What this region does
        </span>
        <span className="flex-1" />
        <span className="text-[10.5px] font-mono" style={{ color: "var(--text-muted)" }}>
          {region.start}–{region.end} · {region.length} bp
        </span>
      </div>

      <div className="px-3.5 py-3 space-y-4">
        {/* Region bases preview */}
        {typeof e.bases === "string" && e.bases.length > 0 && (
          <div
            className="font-mono text-[10.5px] leading-4 rounded-lg px-2 py-1.5 overflow-x-auto whitespace-nowrap"
            style={{
              background: "var(--surface-raised)",
              border: "1px solid var(--ghost-border)",
              color: "var(--text-secondary)",
            }}
          >
            {e.bases.length > 240 ? `${e.bases.slice(0, 240)}…` : e.bases}
          </div>
        )}

        {/* Per-position mini-chart (composition signal) */}
        {perPos.length > 0 && (
          <PerPositionChart
            perPos={perPos}
            lowConfSet={lowConfSet}
            note={prov?.per_position_signal}
          />
        )}

        {/* Signal summary */}
        {summary && (
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10.5px]" style={{ color: "var(--text-muted)" }}>
            <span>
              mean signal{" "}
              <span className="font-mono" style={{ color: "var(--text-secondary)" }}>
                {fmt(summary.mean_score)}
              </span>
            </span>
            <span>
              weakest{" "}
              <span className="font-mono" style={{ color: "var(--base-t)" }}>
                {fmt(summary.min_score)}
              </span>{" "}
              @ pos {summary.min_position}
            </span>
            {Array.isArray(summary.low_confidence_positions) &&
              summary.low_confidence_positions.length > 0 && (
                <span>
                  {summary.low_confidence_positions.length} low-confidence base
                  {summary.low_confidence_positions.length !== 1 ? "s" : ""}
                </span>
              )}
          </div>
        )}

        {/* Model confidence - REAL (indigo) vs honest heuristic note */}
        {realConfidence && mc?.sampled_probs ? (
          <ConfidenceStrip probs={mc.sampled_probs} meanProb={mc.mean_sampled_prob} />
        ) : (
          <div
            className="rounded-lg px-2.5 py-2 text-[10.5px] leading-relaxed space-y-1.5"
            style={{
              background: "color-mix(in oklch, var(--base-t), transparent 93%)",
              border: "1px solid color-mix(in oklch, var(--base-t), transparent 84%)",
              color: "var(--text-muted)",
            }}
          >
            <div className="flex items-center gap-1.5">
              <ProvenanceBadge engine={mc?.engine ?? "unknown"} compact />
              <span className="font-semibold" style={{ color: "var(--text-secondary)" }}>
                Composition signal, not model confidence
              </span>
            </div>
            <p className="m-0">
              {prov?.per_position_signal ??
                "The per-position bars above are a composition signal along the sequence, not Evo 2 model confidence. Regenerate this region to get genuine per-base model confidence."}
            </p>
          </div>
        )}

        {/* Evidence */}
        {evidence.length > 0 && (
          <EvidenceList items={evidence} clinvarNote={prov?.clinvar} />
        )}

        {/* GC + whole-candidate scores (heuristic 4D) */}
        <WholeCandidate
          gcContent={e.gc_content}
          whole={whole}
          note={prov?.four_d_scores}
        />
      </div>
    </div>
  );
}

function fmt(n: number | undefined): string {
  return typeof n === "number" && Number.isFinite(n) ? n.toFixed(2) : "–";
}

// ---------------------------------------------------------------------------
// Per-position composition mini-chart. Honey bars (composition signal),
// low-confidence positions marked with a warm dot + tinted bar so the eye finds
// the weak spots.
// ---------------------------------------------------------------------------
function PerPositionChart({
  perPos,
  lowConfSet,
  note,
}: {
  perPos: { position: number; score: number }[];
  lowConfSet: Set<number>;
  note?: string;
}) {
  const scores = perPos.map((p) => p.score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const span = max - min || 1;

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span
          className="text-[9px] font-semibold uppercase tracking-wider inline-flex items-center gap-1"
          style={{ color: "var(--honey-700, #b45309)" }}
        >
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: "var(--honey-500, #f59e0b)" }}
          />
          Per-position signal (composition)
        </span>
        <span className="text-[9px]" style={{ color: "var(--text-faint)" }}>
          {perPos.length} bases
        </span>
      </div>
      <div
        className="flex items-end gap-px h-9 rounded-md overflow-hidden px-1 py-0.5"
        style={{ background: "color-mix(in oklch, var(--honey-500, #f59e0b), transparent 94%)" }}
      >
        {perPos.map((p, i) => {
          const norm = (p.score - min) / span; // 0..1
          const h = Math.max(6, Math.min(100, norm * 100));
          const low = lowConfSet.has(p.position);
          return (
            <div
              key={i}
              className="flex-1 rounded-[1px] relative"
              title={`pos ${p.position}: ${p.score.toFixed(3)}${low ? " · low confidence" : ""}`}
              style={{
                height: `${h}%`,
                minWidth: "1px",
                background: low
                  ? "var(--base-t, #ef4444)"
                  : `color-mix(in oklch, var(--honey-500, #f59e0b), transparent ${Math.round((1 - norm) * 55)}%)`,
              }}
            />
          );
        })}
      </div>
      {note && (
        <div className="text-[9px] mt-1" style={{ color: "var(--text-faint)" }}>
          {note}
        </div>
      )}
      {lowConfSet.size > 0 && (
        <div className="text-[9px] mt-0.5 flex items-center gap-1" style={{ color: "var(--base-t)" }}>
          <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: "var(--base-t)" }} />
          Red bars = positions the signal flags as low-confidence.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// REAL Evo 2 per-base confidence strip (0..1). Indigo - distinct from honey.
// ---------------------------------------------------------------------------
function ConfidenceStrip({
  probs,
  meanProb,
}: {
  probs: number[];
  meanProb: number | null;
}) {
  const mean =
    typeof meanProb === "number" && Number.isFinite(meanProb)
      ? meanProb
      : probs.reduce((a, b) => a + b, 0) / probs.length;
  const min = Math.min(...probs);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span
          className="text-[9px] font-semibold uppercase tracking-wider inline-flex items-center gap-1"
          style={{ color: INDIGO }}
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: INDIGO }} />
          Evo 2 model confidence (real)
        </span>
        <span className="text-[9px] font-mono" style={{ color: "var(--text-muted)" }}>
          mean {mean.toFixed(2)} · min {min.toFixed(2)}
        </span>
      </div>
      <div
        className="flex items-end gap-px h-9 rounded-md overflow-hidden px-1 py-0.5"
        style={{ background: `color-mix(in oklch, ${INDIGO}, transparent 94%)` }}
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
                background: `color-mix(in oklch, ${INDIGO}, transparent ${Math.round((1 - p) * 70)}%)`,
              }}
            />
          );
        })}
      </div>
      <div className="text-[9px] mt-1" style={{ color: "var(--text-faint)" }}>
        Real per-base probability from a live Evo 2 pass. Higher = more confident.
        Separate from the heuristic 4D scores.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Evidence list - source badges + real links only. ClinVar framed as context.
// ---------------------------------------------------------------------------
function EvidenceList({
  items,
  clinvarNote,
}: {
  items: RegionExplanationEvidence[];
  clinvarNote?: string;
}) {
  const hasClinvar = items.some((i) => i.source === "clinvar");
  return (
    <div>
      <div className="text-[9px] font-semibold uppercase tracking-wider mb-1.5" style={{ color: "var(--text-faint)" }}>
        Evidence for this region
      </div>
      <div className="space-y-1.5">
        {items.map((item, i) => {
          const badge = badgeFor(item.source);
          const href = safeUrl(item.url);
          return (
            <div
              key={`${item.source}-${i}`}
              className="rounded-lg px-2.5 py-1.5"
              style={{ background: "var(--surface-raised)", border: "1px solid var(--ghost-border)" }}
            >
              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                <span
                  className="uppercase"
                  style={{
                    fontSize: "8.5px",
                    fontWeight: 700,
                    letterSpacing: "0.06em",
                    padding: "1px 5px",
                    borderRadius: "3px",
                    color: badge.color,
                    backgroundColor: `color-mix(in oklch, ${badge.color}, transparent 86%)`,
                  }}
                >
                  {badge.label}
                </span>
                <span className="text-[9px] font-mono" style={{ color: "var(--text-faint)" }}>
                  {item.start}–{item.end}
                </span>
                {item.confidence && (
                  <span className="text-[9px]" style={{ color: "var(--text-faint)" }}>
                    · {item.confidence}
                  </span>
                )}
              </div>
              {href ? (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] font-medium inline-flex items-center gap-1"
                  style={{ color: "var(--accent)" }}
                >
                  {item.title}
                  <ExternalLink size={9} />
                </a>
              ) : (
                <span className="text-[11px] font-medium" style={{ color: "var(--text-primary)" }}>
                  {item.title}
                </span>
              )}
              {item.detail && (
                <div className="text-[10px] mt-0.5 leading-snug" style={{ color: "var(--text-muted)" }}>
                  {item.detail}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {hasClinvar && clinvarNote && (
        <div
          className="text-[9.5px] mt-1.5 flex items-start gap-1 leading-snug"
          style={{ color: "var(--text-faint)" }}
        >
          <Info size={10} className="mt-px shrink-0" />
          <span>{clinvarNote}</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// GC + whole-candidate heuristic 4D scores, compactly labeled heuristic.
// ---------------------------------------------------------------------------
function WholeCandidate({
  gcContent,
  whole,
  note,
}: {
  gcContent: number;
  whole?: RegionExplanation["scores_whole_candidate"];
  note?: string;
}) {
  const pct = (v: number | undefined) =>
    typeof v === "number" && Number.isFinite(v) ? `${Math.round(v * 100)}%` : "–";
  const gcPct =
    typeof gcContent === "number" && Number.isFinite(gcContent)
      ? `${Math.round(gcContent * (gcContent <= 1 ? 100 : 1))}%`
      : "–";

  const tiles: { label: string; value: string }[] = [
    { label: "GC content", value: gcPct },
    ...(whole
      ? [
          { label: "Functional", value: pct(whole.functional) },
          { label: "Tissue", value: pct(whole.tissue_specificity) },
          { label: "Off-target", value: pct(whole.off_target) },
          { label: "Novelty", value: pct(whole.novelty) },
          { label: "Combined", value: pct(whole.combined) },
        ]
      : []),
  ];

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <FlaskConical size={10} style={{ color: "var(--text-faint)" }} />
        <span className="text-[9px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-faint)" }}>
          Whole-candidate context (heuristic)
        </span>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        {tiles.map((t) => (
          <div
            key={t.label}
            className="rounded-lg px-2 py-1.5"
            style={{ background: "var(--surface-raised)", border: "1px solid var(--ghost-border)" }}
          >
            <div className="text-[8.5px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              {t.label}
            </div>
            <div className="text-[12px] font-mono font-semibold" style={{ color: "var(--text-primary)" }}>
              {t.value}
            </div>
          </div>
        ))}
      </div>
      {note && (
        <div className="text-[9px] mt-1" style={{ color: "var(--text-faint)" }}>
          {note}
        </div>
      )}
    </div>
  );
}
