/**
 * API client for the Proteus backend.
 *
 * INTEGRATION GUIDE:
 * - Set NEXT_PUBLIC_API_URL env var to point to the GPU-hosted backend
 *   (e.g., NEXT_PUBLIC_API_URL=http://192.168.1.100:8000)
 * - All functions throw on HTTP errors. Callers surface an honest error
 *   state when the backend is unreachable; there is no mock fallback.
 * - Response shapes are mapped to frontend domain types here at the
 *   boundary. Components never see raw API shapes.
 *
 * STUB STATUS:
 * - analyzeSequence:  Calls POST /api/analyze. Backend implemented.
 * - predictMutation:  Calls POST /api/mutations. Backend implemented.
 * - fetchStructure:   Calls POST /api/structure. Returns live ESMFold when configured; errors instead of silent mock.
 * - submitDesign:     Calls POST /api/design. Backend implemented.
 *                     Returns session_id + ws_url for streaming.
 * - editBase:         Calls POST /api/edit/base. Backend implemented.
 * - editFollowup:     Calls POST /api/edit/followup. Backend implemented.
 *
 * Set NEXT_PUBLIC_API_URL to the backend host. There are no mock fallbacks;
 * failures surface as honest error states.
 */

import type { AnalysisResult, MutationEffect } from "@/types";

// Default to the real local backend.
// Override with NEXT_PUBLIC_API_URL when backend runs on another machine.
const API_BASE = process.env.NEXT_PUBLIC_API_URL?.trim() || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Response mappers (API shape -> domain type)
// ---------------------------------------------------------------------------

interface ApiAnalysisResponse {
  sequence: string;
  regions?: Array<{
    start: number;
    end: number;
    type: string;
    label?: string;
    score?: number;
  }>;
  scores: Array<{ position: number; score: number }>;
  proteins: Array<{
    region_start: number;
    region_end: number;
    pdb_data?: string;
    sequence_identity?: number;
  }>;
}

function mapAnalysisResponse(data: ApiAnalysisResponse): AnalysisResult {
  return {
    rawSequence: data.sequence ?? "",
    regions: (data.regions ?? []).map((r) => ({
      start: r.start,
      end: r.end,
      type: (r.type ?? "unknown") as AnalysisResult["regions"][number]["type"],
      label: r.label,
      score: r.score,
    })),
    perPositionScores: (data.scores ?? []).map((s) => ({
      position: s.position,
      score: s.score,
    })),
    predictedProteins: (data.proteins ?? []).map((p) => ({
      regionStart: p.region_start,
      regionEnd: p.region_end,
      pdbData: p.pdb_data,
      sequenceIdentity: p.sequence_identity,
    })),
  };
}

// ---------------------------------------------------------------------------
// Path A: Non-streaming analysis endpoints (currently used by frontend)
// ---------------------------------------------------------------------------

/** POST /api/analyze - Submit sequence for Evo2 analysis */
export async function analyzeSequence(
  sequence: string
): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequence }),
  });
  if (!res.ok) throw new Error(`Analysis failed: ${res.status}`);
  const data = await res.json();
  return mapAnalysisResponse(data);
}

/** POST /api/mutations - Predict mutation effect */
export async function predictMutation(
  sequence: string,
  position: number,
  alternateBase: string
): Promise<MutationEffect> {
  const res = await fetch(`${API_BASE}/api/mutations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequence, position, alternate_base: alternateBase }),
  });
  if (!res.ok) throw new Error(`Mutation prediction failed: ${res.status}`);
  const data = await res.json();
  return {
    position: data.position,
    referenceBase: data.reference_base,
    alternateBase: data.alternate_base,
    deltaLikelihood: data.delta_likelihood,
    predictedImpact: data.predicted_impact,
  };
}

/** POST /api/structure - Fetch protein structure prediction */
export async function fetchStructure(
  regionStart: number,
  regionEnd: number,
  sequence: string
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/structure`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sequence,
      region_start: regionStart,
      region_end: regionEnd,
    }),
  });
  if (!res.ok) throw new Error(`Structure prediction failed: ${res.status}`);
  const data = await res.json();
  return data.pdb_data;
}

// ---------------------------------------------------------------------------
// Path B: Streaming design pipeline (backend built, frontend integration TBD)
// ---------------------------------------------------------------------------

export interface DesignSession {
  sessionId: string;
  wsUrl: string;
}

export interface SubmitDesignOptions {
  sessionId?: string;
  numCandidates?: number;
  runProfile?: "demo" | "live";
  truthMode?: "demo_fallback" | "real_only";
  targetLength?: number;
  seedSequence?: string;
}

/** POST /api/session/bootstrap - Bind a sequence to a session (no pipeline). */
export async function bootstrapSession(
  sequence: string,
  options: { sessionId?: string; candidateId?: number } = {}
): Promise<{ session_id: string; candidate_id: number; length: number }> {
  const res = await fetch(`${API_BASE}/api/session/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sequence,
      session_id: options.sessionId,
      candidate_id: options.candidateId ?? 0,
    }),
  });
  if (!res.ok) throw new Error(`Session bootstrap failed: ${res.status}`);
  return res.json();
}

/** POST /api/design - Start a full design pipeline. Returns WS URL for streaming. */
export async function submitDesign(
  goal: string,
  options: SubmitDesignOptions = {}
): Promise<DesignSession> {
  const {
    sessionId,
    numCandidates = 10,
    // Default to live, real-data runs: real Evo 2 generation, live NCBI/PubMed/ClinVar
    // retrieval, and live ESMFold folding. No synthesized "demo" papers or mock structures.
    runProfile = "live",
    truthMode = "real_only",
    targetLength,
    seedSequence,
  } = options;
  const body: Record<string, unknown> = {
    goal,
    session_id: sessionId,
    num_candidates: numCandidates,
    run_profile: runProfile,
    truth_mode: truthMode,
  };
  if (targetLength !== undefined) {
    body.target_length = targetLength;
  }
  if (seedSequence) {
    body.seed_sequence = seedSequence;
  }
  const res = await fetch(`${API_BASE}/api/design`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Design submission failed: ${res.status}`);
  const data = await res.json();
  return { sessionId: data.session_id, wsUrl: data.ws_url };
}

export interface BaseEditResult {
  position: number;
  reference_base: string;
  new_base: string;
  delta_likelihood: number;
  predicted_impact: "more_likely" | "neutral" | "less_likely";
  updated_scores: {
    functional: number;
    tissue_specificity: number;
    off_target: number;
    novelty: number;
    combined?: number | null;
  };
  /** Full mutated sequence, so the client need not reconstruct it. */
  sequence?: string | null;
  /** Per-position log-likelihoods for a window around the edit (heatmap patch). */
  per_position_scores?: { position: number; score: number }[] | null;
  /** True only when the edit changes the translated coding region. */
  refold_recommended?: boolean;
}

/** POST /api/edit/base - Single base pair edit, re-score only. Must respond < 2s.
 *  Structure is NOT folded here - the caller refolds out of band when
 *  `refold_recommended` is true. */
export async function editBase(
  sessionId: string,
  candidateId: number,
  position: number,
  newBase: string
): Promise<BaseEditResult> {
  const res = await fetch(`${API_BASE}/api/edit/base`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      candidate_id: candidateId,
      position,
      new_base: newBase,
    }),
  });
  if (!res.ok) throw new Error(`Base edit failed: ${res.status}`);
  return res.json();
}

/** POST /api/edit/followup - NL follow-up, triggers partial pipeline re-run. */
export async function editFollowup(
  sessionId: string,
  message: string,
  candidateId: number
) {
  const res = await fetch(`${API_BASE}/api/edit/followup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      candidate_id: candidateId,
    }),
  });
  if (!res.ok) throw new Error(`Followup failed: ${res.status}`);
  return res.json();
}

/** GET /api/health - Check backend status */
export async function checkHealth(): Promise<{
  status: string;
  model: string;
  gpu_available: boolean;
  inference_mode: string;
  structure_mode?: string;
  llm_available?: boolean;
  evo2_mode?: string;
}> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Agent copilot
// ---------------------------------------------------------------------------

/** Region-aware context the agent request may carry. All fields optional. */
export interface AgentChatContext {
  view_mode?: string;
  selected_position?: number;
  /** Half-open [start, end) candidate frame; enables region_explanation. */
  selected_region?: { start: number; end: number };
  /** Gene symbol - enables ClinVar gene context in region evidence. */
  gene?: string;
  scores?: Record<string, number>;
  evidence_links?: Array<Record<string, unknown>>;
  seed_source?: string;
  scoring_note?: string;
  [key: string]: unknown;
}

export interface AgentChatResult {
  assistant_message: string;
  tool_calls: Array<{ tool: string; status: string; summary: string }>;
  candidate_update: {
    candidate_id: number;
    sequence: string;
    scores: Record<string, number>;
    mutation?: Record<string, unknown> | null;
    per_position_scores?: Array<{ position: number; score: number }> | null;
    pdb_data?: string | null;
    confidence?: number | null;
  } | null;
  comparison?: unknown;
  iterations?: number;
  reasoning_steps?: string[] | null;
  // Region-aware payloads (nullable). See lib/agentTypes.ts for full shapes.
  region_explanation?: unknown | null;
  suggested_action?: unknown | null;
  tool_results?: unknown[] | null;
}

/** POST /api/agent/chat - Run the agentic copilot for one turn. */
export async function agentChat(
  sessionId: string,
  candidateId: number,
  message: string,
  options: {
    history?: Array<{ role: string; content: string }>;
    sequence?: string;
    context?: AgentChatContext;
  } = {}
): Promise<AgentChatResult> {
  const res = await fetch(`${API_BASE}/api/agent/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      candidate_id: candidateId,
      message,
      history: options.history ?? [],
      sequence: options.sequence,
      ...(options.context ? { context: options.context } : {}),
    }),
  });
  if (!res.ok) throw new Error(`Agent chat failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Import / export
// ---------------------------------------------------------------------------

export interface ImportedSequence {
  id: string;
  sequence: string;
  length: number;
  organism?: string;
  definition?: string;
  description?: string;
  features?: Array<{ type: string; start: number; end: number; strand: string }>;
}

/** POST /api/import - Parse a FASTA or GenBank file into sequences. */
export async function importSequenceFile(
  file: File
): Promise<{ format: string; count: number; sequences: ImportedSequence[] }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/import`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Import failed: ${res.status}`);
  return res.json();
}

/** POST /api/export/fasta - Export sequences as FASTA text.
 * Backend keys the header off `id` (+ optional `description`); sending `header`
 * silently produces ">sequence". Keep this field name in sync with the backend. */
export async function exportFasta(
  sequences: Array<{ id: string; sequence: string; description?: string }>
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/export/fasta`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequences }),
  });
  if (!res.ok) throw new Error(`FASTA export failed: ${res.status}`);
  return res.text();
}

/** POST /api/export/genbank - Export a single sequence as GenBank text. */
export async function exportGenbank(payload: {
  sequence: string;
  locus?: string;
  definition?: string;
  organism?: string;
  scores?: Record<string, number>;
}): Promise<string> {
  const res = await fetch(`${API_BASE}/api/export/genbank`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`GenBank export failed: ${res.status}`);
  return res.text();
}

// ---------------------------------------------------------------------------
// Research-grade analysis
// ---------------------------------------------------------------------------

export interface CodonOptimizationResult {
  original_sequence: string;
  optimized_sequence: string;
  organism: string;
  original_cai: number;
  optimized_cai: number;
  amino_acid_sequence: string;
  codons_changed: number;
  total_codons: number;
  gc_content_before: number;
  gc_content_after: number;
  preserved_motif_count: number;
  // Constraint-based (DNAChisel) reporting.
  method: string;
  gc_min: number;
  gc_max: number;
  max_homopolymer: number;
  avoided_sites: string[];
  constraints_satisfied: boolean;
  longest_homopolymer_before: number;
  longest_homopolymer_after: number;
}

export interface CodonOptimizationOptions {
  preserveMotifs?: string[];
  gcMin?: number;
  gcMax?: number;
  avoidSites?: string[];
  maxHomopolymer?: number;
}

/**
 * POST /api/optimize/codons - Constraint-based codon optimization (DNAChisel:
 * EnforceTranslation + match_codon_usage + GC window + homopolymer/repeat caps).
 */
export async function optimizeCodons(
  sequence: string,
  organism: string,
  opts: CodonOptimizationOptions = {}
): Promise<CodonOptimizationResult> {
  const body: Record<string, unknown> = {
    sequence,
    organism,
    preserve_motifs: opts.preserveMotifs ?? [],
  };
  if (opts.gcMin != null) body.gc_min = opts.gcMin;
  if (opts.gcMax != null) body.gc_max = opts.gcMax;
  if (opts.avoidSites != null) body.avoid_sites = opts.avoidSites;
  if (opts.maxHomopolymer != null) body.max_homopolymer = opts.maxHomopolymer;
  const res = await fetch(`${API_BASE}/api/optimize/codons`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Codon optimization failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Primer design (primer3) - POST /api/primers
// ---------------------------------------------------------------------------

export interface Primer {
  sequence: string;
  start: number;
  length: number;
  tm_celsius: number;
  gc_percent: number;
  self_any_th: number;
  self_end_th: number;
  hairpin_th: number;
}

export interface PrimerPair {
  left: Primer;
  right: Primer;
  product_size: number;
  product_tm: number | null;
  pair_penalty: number;
  compl_any_th: number;
  compl_end_th: number;
}

export interface PrimerDesignResult {
  sequence_length: number;
  method: string;                 // "primer3"
  pairs: PrimerPair[];
  count: number;
  explain_left: string;
  explain_right: string;
  explain_pair: string;
  note: string;
  settings: Record<string, unknown>;
}

export interface PrimerDesignOptions {
  productSizeMin?: number;
  productSizeMax?: number;
  optTm?: number;
  minTm?: number;
  maxTm?: number;
  numReturn?: number;
}

/** POST /api/primers - Design PCR/sequencing primer pairs (primer3). */
export async function designPrimers(
  sequence: string,
  opts: PrimerDesignOptions = {}
): Promise<PrimerDesignResult> {
  const body: Record<string, unknown> = { sequence };
  if (opts.productSizeMin != null) body.product_size_min = opts.productSizeMin;
  if (opts.productSizeMax != null) body.product_size_max = opts.productSizeMax;
  if (opts.optTm != null) body.opt_tm = opts.optTm;
  if (opts.minTm != null) body.min_tm = opts.minTm;
  if (opts.maxTm != null) body.max_tm = opts.maxTm;
  if (opts.numReturn != null) body.num_return = opts.numReturn;
  const res = await fetch(`${API_BASE}/api/primers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Primer design failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// RNA/DNA secondary structure (ViennaRNA) - POST /api/secondary-structure
// ---------------------------------------------------------------------------

export interface Hairpin {
  stem_start: number;
  stem_end: number;
  loop_start: number;
  loop_size: number;
}

export interface SecondaryStructureResult {
  sequence: string;
  length: number;
  method: string;                 // "ViennaRNA MFE (RNA.fold)"
  mfe_kcal_mol: number;
  dot_bracket: string;
  paired_fraction: number;
  hairpins: Hairpin[];
  hairpin_count: number;
  input_was_dna: boolean;
  note: string;
}

/** POST /api/secondary-structure - ViennaRNA MFE secondary structure. */
export async function foldSecondaryStructure(
  sequence: string
): Promise<SecondaryStructureResult> {
  const res = await fetch(`${API_BASE}/api/secondary-structure`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequence }),
  });
  if (!res.ok) throw new Error(`Secondary-structure prediction failed: ${res.status}`);
  return res.json();
}

export interface VariantAnnotation {
  position: number;
  ref_base: string;
  alt_base: string;
  clinical_significance: string;
  condition: string;
  variant_id: string;
  variant_title: string;
  variation_type: string;
  review_stars: number;
  allele_frequency: number | null;
}

/** POST /api/variants - Annotate a gene/region with ClinVar pathogenic variants. */
export async function annotateVariants(payload: {
  gene: string;
  sequence?: string;
  regionStart?: number;
  regionEnd?: number;
  maxVariants?: number;
}): Promise<{ gene: string; total_variants_in_gene: number; annotations: VariantAnnotation[]; count: number }> {
  const res = await fetch(`${API_BASE}/api/variants`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      gene: payload.gene,
      sequence: payload.sequence,
      region_start: payload.regionStart ?? 0,
      region_end: payload.regionEnd,
      max_variants: payload.maxVariants ?? 25,
    }),
  });
  if (!res.ok) throw new Error(`Variant annotation failed: ${res.status}`);
  return res.json();
}

import type { RegionEvidence } from "@/types";

/** POST /api/region-evidence - Assemble coordinate-bound evidence for a sequence.
 *  Binds coordinates → ClinVar variants (gene context), regulatory motifs, and
 *  semantically-retrieved literature (source="literature", on by default server-side
 *  via include_literature) - no UI change needed, the backend just returns more items. */
export async function fetchRegionEvidence(payload: {
  sequence: string;
  gene?: string;
  regionStart?: number;
  regionEnd?: number;
  maxVariants?: number;
  includeClinvar?: boolean;
  includeLiterature?: boolean;
  // Session id enables edit-history-gated literature: papers attach to the
  // regions Evo2 actually made novel (edited/regenerated spans). Without it the
  // backend returns no literature by design.
  sessionId?: string | null;
  // Which candidate's edit history to gate on - the backend's candidate_id is
  // a plain (non-nullable) int defaulting to 0, so this must be a real number,
  // never null/undefined in the request body.
  candidateId?: number | null;
}): Promise<{
  gene: string | null;
  region_start: number;
  region_end: number;
  items: RegionEvidence[];
  count: number;
}> {
  const res = await fetch(`${API_BASE}/api/region-evidence`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sequence: payload.sequence,
      gene: payload.gene ?? null,
      region_start: payload.regionStart ?? 0,
      region_end: payload.regionEnd,
      max_variants: payload.maxVariants ?? 25,
      include_clinvar: payload.includeClinvar ?? true,
      include_literature: payload.includeLiterature ?? true,
      session_id: payload.sessionId ?? null,
      candidate_id: payload.candidateId ?? 0,
    }),
  });
  if (!res.ok) throw new Error(`Region evidence failed: ${res.status}`);
  return res.json();
}

export interface OffTargetHit {
  region_name: string;
  similarity_score: number;
  shared_kmers: number;
  category: string;
  risk_level: string;
  description: string;
}

/** POST /api/offtarget - Local k-mer off-target scan against known genomic elements. */
export async function scanOffTargets(
  sequence: string,
  k = 12
): Promise<{
  query_length: number;
  repeat_fraction: number;
  gc_balance_risk: "low" | "medium" | "high";
  hit_count: number;
  hits: OffTargetHit[];
}> {
  const res = await fetch(`${API_BASE}/api/offtarget`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequence, k }),
  });
  if (!res.ok) throw new Error(`Off-target scan failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// CRISPR off-target scoring (CFD + MIT) against a supplied reference
// ---------------------------------------------------------------------------

export interface CrisprMismatch {
  position: number;   // 1..20 (20 = PAM-proximal)
  guide_base: string;
  target_base: string;
}

export interface CrisprOffTargetSite {
  position: number;   // 0-based start of protospacer on the forward strand
  strand: "+" | "-";
  protospacer: string;
  pam: string;
  mismatch_count: number;
  mismatches: CrisprMismatch[];
  cfd_score: number;  // 0..1 (Doench 2016)
  mit_score: number;  // 0..100 (Hsu 2013 single-guide hit score)
}

export interface CrisprOffTargetResult {
  guide: string;
  pam_pattern: string;
  reference_length: number;
  max_mismatches: number;
  strands_searched: string;
  total_sites: number;
  off_target_count: number;
  specificity_score: number;   // MIT-style aggregate, 0..100 (100 = most specific)
  sites: CrisprOffTargetSite[];
  method: string;
  note: string;
}

/**
 * POST /api/crispr-offtarget - CFD (Doench 2016) + MIT (Hsu 2013) off-target
 * scoring against the SUPPLIED reference only (both strands). Not a genome-wide scan.
 */
export async function analyzeCrisprOffTargets(
  guide: string,
  reference: string,
  opts?: { pam?: string; maxMismatches?: number; maxSites?: number }
): Promise<CrisprOffTargetResult> {
  const body: Record<string, unknown> = { guide, reference };
  if (opts?.pam != null) body.pam = opts.pam;
  if (opts?.maxMismatches != null) body.max_mismatches = opts.maxMismatches;
  if (opts?.maxSites != null) body.max_sites = opts.maxSites;
  const res = await fetch(`${API_BASE}/api/crispr-offtarget`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep status */
    }
    throw new Error(`CRISPR off-target analysis failed: ${detail}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Melting temperature (Tm) and protein parameters (deterministic primitives)
// ---------------------------------------------------------------------------

export interface TmResult {
  sequence: string;
  length: number;
  gc_fraction: number;
  method: string;                 // "nearest-neighbor" | "wallace"
  tm_celsius: number;
  tm_nn_celsius: number | null;
  tm_wallace_celsius: number;
  na_molar: number;
  oligo_molar: number;
  delta_h_kcal: number | null;
  delta_s_cal: number | null;
  note: string;
}

/** POST /api/tm - Nearest-neighbor (SantaLucia 1998) Tm + Wallace cross-check. */
export async function computeTm(
  sequence: string,
  opts?: { naMolar?: number; oligoMolar?: number }
): Promise<TmResult> {
  const body: Record<string, unknown> = { sequence };
  if (opts?.naMolar != null) body.na_molar = opts.naMolar;
  if (opts?.oligoMolar != null) body.oligo_molar = opts.oligoMolar;
  const res = await fetch(`${API_BASE}/api/tm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Tm calculation failed: ${res.status}`);
  return res.json();
}

export interface ProteinParamsResult {
  sequence: string;
  length: number;
  molecular_weight: number;       // Da
  theoretical_pi: number;
  aromaticity: number;
  gravy: number;
  positively_charged: number;
  negatively_charged: number;
  composition: Record<string, number>;
  unknown_residues: number;
  note: string;
}

/** POST /api/protein-params - MW, pI, aromaticity, GRAVY, composition (ProtParam-style). */
export async function computeProteinParams(sequence: string): Promise<ProteinParamsResult> {
  const res = await fetch(`${API_BASE}/api/protein-params`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequence }),
  });
  if (!res.ok) throw new Error(`Protein parameter calculation failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Scoring calibration (ClinVar ground-truth validation)
// ---------------------------------------------------------------------------

export interface CalibrationReport {
  gene: string;
  engine_mode: string;
  auroc: number | null;
  n_pathogenic: number;
  n_benign: number;
  n_scored: number;
  n_skipped_unaligned: number;
  mean_delta_pathogenic: number | null;
  mean_delta_benign: number | null;
  note: string;
}

/** POST /api/calibration - Measure real AUROC of the active scoring engine vs ClinVar. */
export async function runCalibration(payload: {
  gene: string;
  sequence: string;
  maxPerClass?: number;
}): Promise<CalibrationReport> {
  const res = await fetch(`${API_BASE}/api/calibration`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      gene: payload.gene,
      sequence: payload.sequence,
      max_per_class: payload.maxPerClass ?? 40,
    }),
  });
  if (!res.ok) throw new Error(`Calibration failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Experiment history (version tracking)
// ---------------------------------------------------------------------------

export interface ExperimentVersion {
  version_id: string;
  candidate_id: number;
  sequence: string;
  scores: Record<string, number>;
  operation: string;
  operation_details: Record<string, unknown>;
  parent_version_id: string | null;
  created_at: number | string;
}

/** GET /api/experiments/{sessionId} - List all recorded versions for a session. */
export async function listExperiments(
  sessionId: string,
  candidateId?: number
): Promise<{ session_id: string; count: number; versions: ExperimentVersion[] }> {
  const url = new URL(`${API_BASE}/api/experiments/${encodeURIComponent(sessionId)}`);
  if (candidateId !== undefined) url.searchParams.set("candidate_id", String(candidateId));
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`List experiments failed: ${res.status}`);
  return res.json();
}

/** POST /api/experiments/revert - Revert a candidate to a previous version. */
export async function revertExperiment(
  sessionId: string,
  versionId: string
): Promise<{ reverted: boolean; new_version_id: string; restored_sequence_length: number }> {
  const res = await fetch(`${API_BASE}/api/experiments/revert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, version_id: versionId }),
  });
  if (!res.ok) throw new Error(`Revert failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Durable session snapshots (MongoDB-backed; safe no-ops when disabled)
// ---------------------------------------------------------------------------
//
// Matches docs/session_persistence_interface.md + backend/models/sessions.py.
// A snapshot is the serialized useProteusStore state per session id, so a session
// can be *resumed* (state restored) rather than re-run. Everything degrades:
// when the backend has no Mongo URI, list -> [], get -> 404, put/delete succeed
// as no-ops. Callers treat network errors as "persistence unavailable".

/** Lightweight row for the resume list (no heavy payload). */
export interface SessionSummary {
  sessionId: string;
  title?: string | null;
  kind?: string | null;
  updatedAt?: string | null;
  candidateCount: number;
  length: number;
  userId?: string | null;
}

/** Full resumable snapshot. Permissive by design: the backend stores unknown
 *  fields verbatim so the store shape can evolve without a backend change. */
export interface SessionSnapshot {
  sessionId?: string | null;
  title?: string | null;
  kind?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  userId?: string | null;
  rawSequence?: string | null;
  candidates?: unknown[] | null;
  activeCandidateId?: number | null;
  analysisResult?: unknown;
  scores?: unknown[] | null;
  regions?: unknown[] | null;
  activePdb?: string | null;
  structureModel?: string | null;
  chatMessages?: unknown[] | null;
  editHistory?: unknown[] | null;
  retrievalStatuses?: unknown[] | null;
  seedSource?: string | null;
  scoringNote?: string | null;
  compareLeftId?: number | null;
  compareRightId?: number | null;
  regionEvidence?: unknown[] | null;
  [key: string]: unknown;
}

/** GET /api/sessions - Durable session summaries for the resume list. */
export async function listSessions(userId?: string): Promise<SessionSummary[]> {
  const url = new URL(`${API_BASE}/api/sessions`);
  if (userId) url.searchParams.set("user_id", userId);
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`List sessions failed: ${res.status}`);
  const data = await res.json();
  return (data.sessions ?? []) as SessionSummary[];
}

/** GET /api/sessions/{id} - Full snapshot for resume, or null when absent. */
export async function getSession(sessionId: string): Promise<SessionSnapshot | null> {
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Get session failed: ${res.status}`);
  return (await res.json()) as SessionSnapshot;
}

/** PUT /api/sessions/{id} - Upsert (autosave) a snapshot. Returns the summary. */
export async function putSession(snapshot: SessionSnapshot): Promise<SessionSummary> {
  const sessionId = snapshot.sessionId;
  if (!sessionId) throw new Error("putSession requires snapshot.sessionId");
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(snapshot),
  });
  if (!res.ok) throw new Error(`Put session failed: ${res.status}`);
  return (await res.json()) as SessionSummary;
}

/** DELETE /api/sessions/{id} - Remove a durable snapshot. */
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Delete session failed: ${res.status}`);
}

/** Trigger a browser download of text content. */
export function downloadText(filename: string, content: string, mime = "text/plain") {
  if (typeof document === "undefined") return;
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
