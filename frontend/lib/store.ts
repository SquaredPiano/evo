import { create } from "zustand";
import type {
  AnalysisResult,
  MutationEffect,
  LikelihoodScore,
  SequenceRegion,
  RegionEvidence,
  Base,
} from "@/types";
import { parseSequence } from "@/lib/sequenceUtils";
import type { CandidateProvenance } from "@/lib/regen";
import { fetchRegionEvidence, putSession, type SessionSnapshot } from "@/lib/api";

type PipelineStatus = "idle" | "input" | "analyzing" | "complete" | "error";

/**
 * Product view states within /analyze:
 * - input: paste a sequence
 * - pipeline: analysis running, live streaming
 * - analyze: candidate overview (understand)
 * - structure: 3D protein structure centerpiece
 * - leaderboard: candidate ranking/triage
 * - explorer: sequence inspection (inspect)
 * - ide: full editing (manipulate)
 * - compare: diff/compare view
 */
type ViewMode = "input" | "pipeline" | "analyze" | "structure" | "leaderboard" | "explorer" | "ide" | "compare";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

interface EditEntry {
  position: number;
  from: string;
  to: string;
  delta: number;
  timestamp: number;
}

interface Candidate {
  id: number;
  sequence: string;
  scores: { functional: number; tissue: number; offTarget: number; novelty: number };
  overall: number;
  status: string;
  perPositionScores?: LikelihoodScore[];
  error?: string | null;
  /** Provenance for a constrained full redesign (engine, method, real-confidence flag). */
  provenance?: CandidateProvenance | null;
}

interface RetrievalStatus {
  source: string;
  status: "pending" | "running" | "complete" | "failed";
  result?: Record<string, unknown> | null;
}

/** Provenance for a sequence imported from a FASTA/GenBank file. */
interface ImportSource {
  format: "fasta" | "genbank";
  id: string;
  organism?: string;
  definition?: string;
  featureCount?: number;
}

interface EvoState {
  viewMode: ViewMode;
  pipelineStatus: PipelineStatus;
  pipelineStage: string;
  error: string | null;

  rawSequence: string;
  bases: Base[];
  regions: SequenceRegion[];
  scores: LikelihoodScore[];
  analysisResult: AnalysisResult | null;

  selectedPosition: number | null;
  selectedRegionIndex: number | null;
  activePdb: string | null;
  originalPdb: string | null;
  /** Provenance: esmfold | mock | unavailable | user_pdb | null.
   * "user_pdb" = a structure file the user uploaded — NOT a model prediction. */
  structureModel: string | null;
  highlightResidues: number[];

  mutationEffect: MutationEffect | null;
  mutationLoading: boolean;
  /** True while the protein structure refolds in the background after an edit.
   *  Independent of mutationLoading (which only covers fast scoring). */
  structureRefolding: boolean;

  editHistory: EditEntry[];
  chatMessages: ChatMessage[];
  chatOpen: boolean;
  chatDraft: string | null;
  /** Prefill the home composer when restoring a recent session. */
  composerPrefill: { mode: "design" | "paste"; value: string } | null;
  /** Metadata for a sequence brought in via FASTA/GenBank import (if any). */
  importSource: ImportSource | null;
  candidates: Candidate[];
  activeCandidateId: number | null;
  /** Candidate comparison: which two candidates are pinned in CompareView. */
  compareLeftId: number | null;
  compareRightId: number | null;

  // Streaming pipeline state
  sessionId: string | null;
  generatingSequence: string;
  explanation: string;
  retrievalStatuses: RetrievalStatus[];
  generationTokenCount: number;
  completedStages: string[];
  /** Where generation seeds came from: ncbi_cds | retrieval_context | fallback_seed | … */
  seedSource: string | null;
  /** Honest note about score provenance (heuristic vs real Evo2 LL). */
  scoringNote: string | null;

  /** Story Mode: judge-facing plain-English glossary drawer. */
  storyModeOpen: boolean;
  setStoryModeOpen: (open: boolean) => void;
  toggleStoryMode: () => void;

  // Connection
  wsStatus: "disconnected" | "connecting" | "connected";
  setWsStatus: (status: "disconnected" | "connecting" | "connected") => void;

  // Theme
  theme: "dark" | "light";
  toggleTheme: () => void;

  // Auth (mock)
  user: { id: string; name: string; email: string } | null;
  signIn: () => void;
  signOut: () => void;

  // Actions
  setViewMode: (mode: ViewMode) => void;
  setSequence: (seq: string) => void;
  setEditedSequence: (seq: string) => void;
  setAnalysisResult: (result: AnalysisResult) => void;
  setSelectedPosition: (pos: number | null) => void;
  setSelectedRegionIndex: (idx: number | null) => void;
  setActivePdb: (pdb: string | null) => void;
  setStructureModel: (model: string | null) => void;
  setHighlightResidues: (residues: number[]) => void;
  setMutationEffect: (effect: MutationEffect | null) => void;
  setMutationLoading: (loading: boolean) => void;
  setStructureRefolding: (refolding: boolean) => void;
  setPipelineStatus: (status: PipelineStatus) => void;
  setPipelineStage: (stage: string) => void;
  setError: (error: string | null) => void;
  addEditEntry: (entry: Omit<EditEntry, "timestamp">) => void;
  addChatMessage: (msg: Omit<ChatMessage, "timestamp">) => void;
  /** Intentionally start a fresh Helio conversation (in-memory only).
   *  Distinct from reset()/startDesign, which now PRESERVE the conversation. */
  clearChat: () => void;
  toggleChat: () => void;
  setChatOpen: (open: boolean) => void;
  setChatDraft: (draft: string | null) => void;
  setComposerPrefill: (prefill: { mode: "design" | "paste"; value: string } | null) => void;
  setImportSource: (source: ImportSource | null) => void;
  setCandidates: (candidates: Candidate[]) => void;
  setActiveCandidateId: (id: number | null) => void;
  setCompareLeftId: (id: number | null) => void;
  setCompareRightId: (id: number | null) => void;
  setSessionId: (id: string | null) => void;
  appendGeneratingToken: (token: string) => void;
  appendExplanation: (text: string) => void;
  setRetrievalStatuses: (statuses: RetrievalStatus[]) => void;
  updateRetrievalStatus: (
    source: string,
    status: RetrievalStatus["status"],
    result?: Record<string, unknown> | null,
  ) => void;
  addCompletedStage: (stage: string) => void;
  setSeedSource: (source: string | null) => void;
  setScoringNote: (note: string | null) => void;
  savedSnapshot: { sequence: string; editHistory: EditEntry[]; pdb?: string | null } | null;
  saveVersion: () => void;
  revertVersion: () => void;

  // --- Region → evidence binding (additive; hover-a-region → supporting research) ---
  // Coordinate-bound evidence for the current sequence. `regionEvidenceKey` is the
  // sequence the evidence was fetched for (dedup guard). Populated via the
  // /api/region-evidence endpoint; the pipeline also emits `region_evidence_ready`.
  regionEvidence: RegionEvidence[];
  regionEvidenceKey: string | null;
  setRegionEvidence: (items: RegionEvidence[], key?: string | null) => void;
  loadRegionEvidence: (sequence: string, gene?: string | null) => Promise<void>;

  // --- Durable session persistence (MongoDB via /api/sessions) ---
  /** Serialize the documented resumable fields into a SessionSnapshot. */
  snapshotFromStore: () => SessionSnapshot;
  /** Restore full workspace state from a snapshot (RESUME, not re-run). */
  hydrateFromSnapshot: (snap: SessionSnapshot) => void;

  reset: () => void;
}

const initialState = {
  viewMode: "input" as ViewMode,
  pipelineStatus: "idle" as PipelineStatus,
  pipelineStage: "",
  error: null as string | null,
  rawSequence: "",
  bases: [] as Base[],
  regions: [] as SequenceRegion[],
  scores: [] as LikelihoodScore[],
  analysisResult: null as AnalysisResult | null,
  selectedPosition: null as number | null,
  selectedRegionIndex: null as number | null,
  activePdb: null as string | null,
  originalPdb: null as string | null,
  structureModel: null as string | null,
  highlightResidues: [] as number[],
  mutationEffect: null as MutationEffect | null,
  mutationLoading: false,
  structureRefolding: false,
  editHistory: [] as EditEntry[],
  chatMessages: [] as ChatMessage[],
  chatOpen: false,
  chatDraft: null as string | null,
  composerPrefill: null as { mode: "design" | "paste"; value: string } | null,
  importSource: null as ImportSource | null,
  candidates: [] as Candidate[],
  activeCandidateId: null as number | null,
  compareLeftId: null as number | null,
  compareRightId: null as number | null,
  sessionId: null as string | null,
  generatingSequence: "",
  explanation: "",
  retrievalStatuses: [] as RetrievalStatus[],
  generationTokenCount: 0,
  completedStages: [] as string[],
  seedSource: null as string | null,
  scoringNote: null as string | null,
  storyModeOpen: false,
  wsStatus: "disconnected" as "disconnected" | "connecting" | "connected",
  theme: "light" as "dark" | "light",
  savedSnapshot: null as { sequence: string; editHistory: EditEntry[]; pdb?: string | null } | null,
  user: null as { id: string; name: string; email: string } | null,
  regionEvidence: [] as RegionEvidence[],
  regionEvidenceKey: null as string | null,
};

export const useEvoStore = create<EvoState>((set, get) => ({
  ...initialState,

  toggleTheme: () => {
    // Light-only product — ignore dark mode requests.
    set({ theme: "light" });
    if (typeof document !== "undefined") {
      document.documentElement.classList.remove("dark");
    }
  },
  setViewMode: (mode) => set({ viewMode: mode }),
  setSequence: (seq) => set({ rawSequence: seq }),

  // Local (client-side) sequence edit from the inline editor: recompute bases,
  // preserve per-position likelihood scores where positions still line up, and
  // mirror the change onto the active candidate so Rescore/Compare stay in sync.
  setEditedSequence: (seq) => {
    const state = get();
    const cleaned = seq.toUpperCase().replace(/[^ATCGN]/g, "");
    const nextBases = parseSequence(cleaned, state.regions).map((base, i) => ({
      ...base,
      likelihoodScore: state.scores[i]?.score,
    }));
    const candidates = state.candidates.map((c) =>
      c.id === (state.activeCandidateId ?? c.id) ? { ...c, sequence: cleaned } : c
    );
    set({ rawSequence: cleaned, bases: nextBases, candidates });
  },

  setAnalysisResult: (result) => {
    const state = get();
    const regions = result.regions;
    const bases = parseSequence(result.rawSequence, regions).map((base, i) => ({
      ...base,
      likelihoodScore: result.perPositionScores[i]?.score,
    }));

    let candidates = [...state.candidates];
    if (candidates.length === 0) {
      // For direct /api/analyze path (non-pipeline), create one deterministic candidate.
      const meanAbs = result.perPositionScores.length
        ? result.perPositionScores.reduce((sum, row) => sum + Math.abs(row.score), 0) / result.perPositionScores.length
        : 0.5;
      const normalized = Math.max(0, Math.min(1, meanAbs / 2.5));
      const baseCandidate: Candidate = {
        id: 0,
        sequence: result.rawSequence,
        scores: {
          functional: Math.max(0.35, Math.min(0.92, 0.45 + normalized * 0.4)),
          tissue: Math.max(0.2, Math.min(0.9, 0.4 + normalized * 0.3)),
          offTarget: Math.max(0.0, Math.min(0.35, 0.18 - normalized * 0.12)),
          novelty: Math.max(0.2, Math.min(0.9, 0.35 + normalized * 0.35)),
        },
        overall: 0,
        status: "scored",
        perPositionScores: result.perPositionScores,
        error: null,
      };
      baseCandidate.overall =
        (baseCandidate.scores.functional * 0.35 +
          baseCandidate.scores.tissue * 0.3 +
          (1 - baseCandidate.scores.offTarget) * 0.2 +
          baseCandidate.scores.novelty * 0.15) *
        100;
      candidates = [baseCandidate];
    }

    const activeCandidateId = state.activeCandidateId ?? candidates[0]?.id ?? null;

    // A fresh run arrives from the pipeline/input screens. Anything else
    // (Rescore from Sequence/Edit) is an in-place update of the same session.
    const freshRun = state.viewMode === "pipeline" || state.viewMode === "input";

    // Only leave the pipeline/input screens — never yank Sequence/Edit → Structure.
    const nextView = freshRun ? "analyze" : state.viewMode;

    set({
      analysisResult: result,
      rawSequence: result.rawSequence,
      regions, bases,
      scores: result.perPositionScores,
      pipelineStatus: "complete",
      viewMode: nextView,
      candidates,
      activeCandidateId,
      error: null,
      // Stale compare pins from a previous run must not carry into a new one.
      ...(freshRun ? { compareLeftId: null, compareRightId: null } : {}),
    });
  },

  setSelectedPosition: (pos) => set({ selectedPosition: pos }),
  setSelectedRegionIndex: (idx) => set({ selectedRegionIndex: idx }),
  setActivePdb: (pdb) => {
    const state = get();
    // Save the first PDB as the original for comparison
    if (!state.originalPdb && pdb) {
      set({ activePdb: pdb, originalPdb: pdb });
    } else {
      set({ activePdb: pdb });
    }
  },
  setStructureModel: (model) => set({ structureModel: model }),
  setHighlightResidues: (residues) => set({ highlightResidues: residues }),
  setMutationEffect: (effect) => set({ mutationEffect: effect }),
  setMutationLoading: (loading) => set({ mutationLoading: loading }),
  setStructureRefolding: (refolding) => set({ structureRefolding: refolding }),
  setPipelineStatus: (status) => set({ pipelineStatus: status }),
  setPipelineStage: (stage) => set({ pipelineStage: stage }),
  setError: (error) => set({ error, pipelineStatus: "error" }),
  addEditEntry: (entry) => set({ editHistory: [...get().editHistory, { ...entry, timestamp: Date.now() }] }),
  addChatMessage: (msg) => set({ chatMessages: [...get().chatMessages, { ...msg, timestamp: Date.now() }] }),
  clearChat: () => {
    // New Chat: archive the outgoing session to the durable store BEFORE wiping
    // the in-memory thread, so it appears in the sidebar and can be resumed.
    // Best-effort + silent: never block or error the UI when Mongo is off.
    const s = get();
    const hasContent = Boolean(s.sessionId) && (s.rawSequence.length > 0 || s.candidates.length > 0);
    if (hasContent) {
      try {
        void putSession(s.snapshotFromStore()).catch(() => {});
      } catch {
        // ignore — persistence is additive
      }
    }
    set({ chatMessages: [], chatDraft: null });
  },
  toggleChat: () => set({ chatOpen: !get().chatOpen }),
  setChatOpen: (open) => set({ chatOpen: open }),
  setChatDraft: (draft) => set({ chatDraft: draft }),
  setComposerPrefill: (prefill) => set({ composerPrefill: prefill }),
  setImportSource: (source) => set({ importSource: source }),
  setCandidates: (candidates) => set({ candidates }),
  setCompareLeftId: (id) => set({ compareLeftId: id }),
  setCompareRightId: (id) => set({ compareRightId: id }),
  setActiveCandidateId: (id) => {
    const state = get();
    const candidate = state.candidates.find((c) => c.id === id);
    if (!candidate) {
      set({ activeCandidateId: id });
      return;
    }
    const regions = state.regions;
    const perPosition = candidate.perPositionScores ?? state.scores;
    const nextBases = parseSequence(candidate.sequence, regions).map((base, i) => ({
      ...base,
      likelihoodScore: perPosition[i]?.score,
    }));
    set({
      activeCandidateId: id,
      rawSequence: candidate.sequence,
      scores: perPosition,
      bases: nextBases,
    });
  },
  setSessionId: (id) => set({ sessionId: id }),
  setWsStatus: (status) => set({ wsStatus: status }),
  appendGeneratingToken: (token) => set((s) => ({
    generatingSequence: s.generatingSequence + token,
    generationTokenCount: s.generationTokenCount + 1,
  })),
  appendExplanation: (text) => set((s) => ({ explanation: s.explanation + text })),
  setRetrievalStatuses: (statuses) => set({ retrievalStatuses: statuses }),
  updateRetrievalStatus: (source, status, result) => set((s) => ({
    retrievalStatuses: s.retrievalStatuses.map((r) =>
      r.source === source
        ? { ...r, status, ...(result !== undefined ? { result } : {}) }
        : r
    ),
  })),
  addCompletedStage: (stage) => set((s) => ({
    completedStages: s.completedStages.includes(stage) ? s.completedStages : [...s.completedStages, stage],
  })),
  setSeedSource: (source) => set({ seedSource: source }),
  setScoringNote: (note) => set({ scoringNote: note }),
  setStoryModeOpen: (open) => set({ storyModeOpen: open }),
  toggleStoryMode: () => set((s) => ({ storyModeOpen: !s.storyModeOpen })),
  signIn: () => set({}),
  signOut: () => set({ user: null }),
  saveVersion: () => set((s) => ({
    savedSnapshot: { sequence: s.rawSequence, editHistory: [...s.editHistory], pdb: s.activePdb },
  })),
  revertVersion: () => {
    const snap = get().savedSnapshot;
    if (snap) {
      const regions = get().regions;
      const scores = get().scores;
      const newBases = parseSequence(snap.sequence, regions).map((b, i) => ({
        ...b,
        likelihoodScore: scores[i]?.score,
      }));
      set({
        rawSequence: snap.sequence,
        bases: newBases,
        editHistory: snap.editHistory,
        activePdb: snap.pdb ?? get().originalPdb ?? get().activePdb,
        mutationEffect: null,
        highlightResidues: [],
        selectedPosition: null,
      });
    }
  },
  // --- Region → evidence binding (additive) ---
  setRegionEvidence: (items, key = null) =>
    set({ regionEvidence: items, regionEvidenceKey: key }),

  // Fetch coordinate-bound evidence for a sequence, deduped by sequence so the
  // two AnnotationTrack instances don't double-fetch. Silently no-ops on error
  // (evidence is additive context; never blocks the main flow).
  loadRegionEvidence: async (sequence, gene) => {
    const cleaned = (sequence ?? "").trim();
    if (!cleaned) {
      set({ regionEvidence: [], regionEvidenceKey: null });
      return;
    }
    const key = `${cleaned.length}:${gene ?? ""}:${cleaned.slice(0, 32)}`;
    if (get().regionEvidenceKey === key) return; // already loaded / in flight
    set({ regionEvidenceKey: key });
    try {
      const res = await fetchRegionEvidence({
        sequence: cleaned,
        gene: gene ?? undefined,
        includeClinvar: Boolean(gene),
      });
      // Guard against races: only apply if this is still the latest request.
      if (get().regionEvidenceKey === key) {
        set({ regionEvidence: res.items });
      }
    } catch {
      if (get().regionEvidenceKey === key) set({ regionEvidence: [] });
    }
  },

  // --- Durable session persistence (additive; safe no-ops when Mongo is off) ---
  snapshotFromStore: () => {
    const s = get();
    // Derive a human title: design goal from first user chat, else a seq label.
    const firstUser = s.chatMessages.find((m) => m.role === "user");
    const title =
      (firstUser?.content ?? "").trim().slice(0, 80) ||
      (s.rawSequence ? `Sequence (${s.rawSequence.length} bp)` : "Untitled session");
    const kind: string = s.importSource
      ? "paste"
      : s.structureModel === "user_pdb"
        ? "pdb"
        : "design";
    return {
      sessionId: s.sessionId,
      title,
      kind,
      rawSequence: s.rawSequence,
      candidates: s.candidates,
      activeCandidateId: s.activeCandidateId,
      analysisResult: s.analysisResult,
      scores: s.scores,
      regions: s.regions,
      activePdb: s.activePdb,
      structureModel: s.structureModel,
      chatMessages: s.chatMessages,
      editHistory: s.editHistory,
      retrievalStatuses: s.retrievalStatuses,
      seedSource: s.seedSource,
      scoringNote: s.scoringNote,
      compareLeftId: s.compareLeftId,
      compareRightId: s.compareRightId,
      regionEvidence: s.regionEvidence,
    } as SessionSnapshot;
  },

  hydrateFromSnapshot: (snap) => {
    // Restore stored fields; recompute derived `bases` from the sequence so the
    // viewer renders without re-running the pipeline. Everything is defensive:
    // missing/renamed fields fall back to sensible empties.
    const rawSequence = typeof snap.rawSequence === "string" ? snap.rawSequence : "";
    const regions = (Array.isArray(snap.regions) ? snap.regions : []) as SequenceRegion[];
    const scores = (Array.isArray(snap.scores) ? snap.scores : []) as LikelihoodScore[];
    const bases = parseSequence(rawSequence, regions).map((base, i) => ({
      ...base,
      likelihoodScore: scores[i]?.score,
    }));
    set({
      ...initialState,
      // Preserve theme/user across a resume.
      theme: get().theme,
      user: get().user,
      sessionId: typeof snap.sessionId === "string" ? snap.sessionId : get().sessionId,
      rawSequence,
      regions,
      scores,
      bases,
      candidates: (Array.isArray(snap.candidates) ? snap.candidates : []) as Candidate[],
      activeCandidateId:
        typeof snap.activeCandidateId === "number" ? snap.activeCandidateId : null,
      analysisResult: (snap.analysisResult ?? null) as AnalysisResult | null,
      activePdb: typeof snap.activePdb === "string" ? snap.activePdb : null,
      originalPdb: typeof snap.activePdb === "string" ? snap.activePdb : null,
      structureModel: typeof snap.structureModel === "string" ? snap.structureModel : null,
      chatMessages: (Array.isArray(snap.chatMessages) ? snap.chatMessages : []) as ChatMessage[],
      editHistory: (Array.isArray(snap.editHistory) ? snap.editHistory : []) as EditEntry[],
      retrievalStatuses: (Array.isArray(snap.retrievalStatuses)
        ? snap.retrievalStatuses
        : []) as RetrievalStatus[],
      seedSource: typeof snap.seedSource === "string" ? snap.seedSource : null,
      scoringNote: typeof snap.scoringNote === "string" ? snap.scoringNote : null,
      compareLeftId: typeof snap.compareLeftId === "number" ? snap.compareLeftId : null,
      compareRightId: typeof snap.compareRightId === "number" ? snap.compareRightId : null,
      regionEvidence: (Array.isArray(snap.regionEvidence)
        ? snap.regionEvidence
        : []) as RegionEvidence[],
      // A resumed session lands on the candidate overview, fully restored.
      viewMode: "analyze",
      pipelineStatus: "complete",
    });
  },

  // reset() clears the design workspace but INTENTIONALLY preserves the Helio
  // conversation (chatMessages/chatOpen). Regenerating or launching a fresh
  // design must not destroy the scientist's chat history. Use clearChat() to
  // explicitly start a new conversation ("New Chat").
  reset: () =>
    set((s) => ({
      ...initialState,
      chatMessages: s.chatMessages,
      chatOpen: s.chatOpen,
    })),

}));
