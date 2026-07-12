/**
 * Types for the region-aware Helio agent payloads.
 *
 * These mirror the NULLABLE top-level fields the backend `POST /api/agent/chat`
 * response now carries: `region_explanation`, `suggested_action`, `tool_results`.
 *
 * HONESTY CONTRACT (enforced by the UI that renders these):
 *  - `model_confidence.sampled_probs` are REAL Evo 2 confidence ONLY when
 *    `is_real_model_confidence === true`. Otherwise the per-position scores are
 *    heuristic proxies (see `provenance.per_position_signal`) and no confidence
 *    strip may be rendered.
 *  - ClinVar evidence is GENE CONTEXT, framed per `provenance.clinvar` — never a
 *    verdict on the candidate.
 *  - Links are rendered only when the backend supplies a real http(s) url.
 */

export interface RegionPerPositionScore {
  position: number;
  score: number;
}

export interface RegionSignalSummary {
  mean_score: number;
  min_score: number;
  min_position: number;
  /** Absolute positions the signal flags as low-confidence within the region. */
  low_confidence_positions: number[];
}

export interface RegionModelConfidence {
  engine: string;
  /** Gate: sampled_probs are genuine Evo 2 probabilities only when true. */
  is_real_model_confidence: boolean;
  mean_sampled_prob: number | null;
  sampled_probs: number[] | null;
}

export interface RegionExplanationEvidence {
  start: number;
  end: number;
  source: "regulatory" | "clinvar" | "literature" | string;
  kind: string;
  title: string;
  detail?: string | null;
  url?: string | null;
  identifier?: string | null;
  score?: number | null;
  confidence?: string | null;
}

export interface RegionExplanationProvenance {
  per_position_signal: string;
  four_d_scores: string;
  clinvar: string;
}

export interface RegionWholeCandidateScores {
  functional: number;
  tissue_specificity: number;
  off_target: number;
  novelty: number;
  combined: number;
}

export interface RegionExplanation {
  candidate_id: number;
  region: { start: number; end: number; length: number };
  bases: string;
  gc_content: number;
  per_position_scores: RegionPerPositionScore[];
  signal_summary: RegionSignalSummary;
  model_confidence: RegionModelConfidence;
  evidence: RegionExplanationEvidence[];
  provenance: RegionExplanationProvenance;
  scores_whole_candidate: RegionWholeCandidateScores;
}

/** Proactive one-click follow-up Helio suggests after explaining a region. */
export interface SuggestedAction {
  label: string;
  tool: "regenerate_region" | "optimize_candidate" | string;
  args: Record<string, unknown>;
  objective?: string | null;
  rationale?: string | null;
}

// --- Read-only tool result cards ------------------------------------------

export interface OffTargetHit {
  region_name: string;
  category: string;
  risk_level: string;
  similarity_score: number;
  shared_kmers: number;
  description: string;
}

export interface OffTargetScanResult {
  tool: "offtarget_scan";
  query_length: number;
  k: number;
  repeat_fraction: number;
  gc_balance_risk: string | number | boolean | null;
  total_hits: number;
  high_risk: number;
  medium_risk: number;
  hits: OffTargetHit[];
}

export interface RestrictionSite {
  enzyme: string;
  recognition_site: string;
  positions: number[];
  count: number;
}

export interface RestrictionSitesResult {
  tool: "restriction_sites";
  sequence_length: number;
  enzymes_checked: number;
  total_sites: number;
  sites: RestrictionSite[];
}

export type ToolResult =
  | OffTargetScanResult
  | RestrictionSitesResult
  | { tool: string; [key: string]: unknown };

// --- Narrowing helpers (defensive against partial/legacy payloads) --------

export function isRegionExplanation(x: unknown): x is RegionExplanation {
  if (!x || typeof x !== "object") return false;
  const r = x as Record<string, unknown>;
  return (
    typeof r.region === "object" &&
    r.region !== null &&
    Array.isArray(r.per_position_scores) &&
    typeof r.model_confidence === "object"
  );
}

export function isSuggestedAction(x: unknown): x is SuggestedAction {
  if (!x || typeof x !== "object") return false;
  const a = x as Record<string, unknown>;
  return typeof a.label === "string" && typeof a.tool === "string";
}

export function isOffTargetScan(r: ToolResult): r is OffTargetScanResult {
  return r.tool === "offtarget_scan";
}

export function isRestrictionSites(r: ToolResult): r is RestrictionSitesResult {
  return r.tool === "restriction_sites";
}

/**
 * Build a natural-language message that triggers a SuggestedAction's tool.
 * The backend routes these phrasings to `regenerate_region` /
 * `optimize_candidate`; we compose from args where present and fall back to the
 * human label so the send never becomes a no-op.
 */
export function messageForSuggestedAction(action: SuggestedAction): string {
  const args = action.args ?? {};
  const num = (v: unknown): number | null =>
    typeof v === "number" && Number.isFinite(v) ? v : null;

  if (action.tool === "regenerate_region") {
    const start = num(args.start);
    const end = num(args.end);
    const parts: string[] = [];
    if (start !== null && end !== null) {
      parts.push(`Regenerate positions ${start}-${end}.`);
    } else {
      parts.push("Regenerate the selected region.");
    }
    const gc = num(args.gc_target ?? args.target_gc);
    if (gc !== null) {
      parts.push(`Target a GC content of ${Math.round(gc * (gc <= 1 ? 100 : 1))}%.`);
    }
    const motifs = Array.isArray(args.avoid_motifs) ? args.avoid_motifs : [];
    if (motifs.length > 0) parts.push(`Avoid the motif(s) ${motifs.join(", ")}.`);
    if (action.objective) parts.push(`Objective: ${action.objective}.`);
    return parts.join(" ");
  }

  if (action.tool === "optimize_candidate") {
    return action.objective
      ? `Optimize this candidate for ${action.objective} and show the before/after scores.`
      : "Optimize this candidate and show the before/after scores.";
  }

  // Unknown tool — the label is already imperative in practice.
  return action.label;
}
