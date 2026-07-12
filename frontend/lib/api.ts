/**
 * API client for the Evo backend.
 *
 * INTEGRATION GUIDE:
 * - Set NEXT_PUBLIC_API_URL env var to point to the GPU-hosted backend
 *   (e.g., NEXT_PUBLIC_API_URL=http://192.168.1.100:8000)
 * - All functions throw on HTTP errors. Callers (hooks) catch and fall
 *   back to mock data when the backend is unreachable.
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
 * When the backend is running on the GX10, just set the env var and
 * all mock fallbacks in the hooks will be bypassed automatically.
 */

import type { AnalysisResult, MutationEffect } from "@/types";

// Default to the real local backend to avoid silently hitting mock Next routes.
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
  predicted_impact: "benign" | "moderate" | "deleterious";
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
 *  Structure is NOT folded here — the caller refolds out of band when
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
}

/** POST /api/agent/chat - Run the agentic copilot for one turn. */
export async function agentChat(
  sessionId: string,
  candidateId: number,
  message: string,
  options: { history?: Array<{ role: string; content: string }>; sequence?: string } = {}
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

/** POST /api/export/fasta - Export sequences as FASTA text. */
export async function exportFasta(
  sequences: Array<{ header: string; sequence: string }>
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
}

/** POST /api/optimize/codons - Organism-specific codon optimization. */
export async function optimizeCodons(
  sequence: string,
  organism: string,
  preserveMotifs: string[] = []
): Promise<CodonOptimizationResult> {
  const res = await fetch(`${API_BASE}/api/optimize/codons`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sequence, organism, preserve_motifs: preserveMotifs }),
  });
  if (!res.ok) throw new Error(`Codon optimization failed: ${res.status}`);
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
