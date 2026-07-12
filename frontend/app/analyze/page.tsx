"use client";

import dynamic from "next/dynamic";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import {
  Dna, FlaskConical, BarChart3, Search, Home, Sun, Moon, LogOut,
  ChevronRight, Pencil, ArrowRight, Sparkles, Target,
  Box, Maximize2, Minimize2, HelpCircle, RotateCcw, Menu, X, BookOpen, Cpu,
} from "lucide-react";
import ErrorBoundary from "@/components/ui/ErrorBoundary";
import { useEvoStore } from "@/lib/store";
import { getSession } from "@/lib/api";
import { useSessionAutosave } from "@/hooks/useSessionAutosave";
import { useSequenceAnalysis } from "@/hooks/useSequenceAnalysis";
import { useDesignPipeline } from "@/hooks/useDesignPipeline";
import { useMutationSim } from "@/hooks/useMutationSim";
import SequenceInput from "@/components/sequence/SequenceInput";
import SequenceViewer from "@/components/sequence/SequenceViewer";
import SequenceEditor from "@/components/sequence/SequenceEditor";
import WorkspaceSidebar from "@/components/layout/WorkspaceSidebar";
import ToolsPanel from "@/components/workspace/ToolsPanel";
import ExperimentHistory from "@/components/workspace/ExperimentHistory";
import AnnotationTrack from "@/components/annotation/AnnotationTrack";
import AnnotationLegend from "@/components/annotation/AnnotationLegend";
import LikelihoodGraph from "@/components/annotation/LikelihoodGraph";
import MutationPanel from "@/components/mutation/MutationPanel";
import CandidateLeaderboard from "@/components/workspace/CandidateLeaderboard";
import ChatPanel from "@/components/workspace/ChatPanel";
import PipelineStatus from "@/components/workspace/PipelineStatus";
import CompareView from "@/components/workspace/CompareView";
import MutationDiff from "@/components/mutation/MutationDiff";
import RelatedWorkPanel from "@/components/workspace/RelatedWorkPanel";
import StoryMode from "@/components/analysis/StoryMode";
import SequenceScrubber from "@/components/sequence/SequenceScrubber";
import EditingCandidateChrome from "@/components/workspace/EditingCandidateChrome";

import { ScienceTooltip, ScienceInfo } from "@/components/ui/ScienceTooltip";
import TutorialOverlay, { isTutorialCompleted } from "@/components/ui/TutorialOverlay";

const ProteinViewer = dynamic(() => import("@/components/structure/ProteinViewer"), { ssr: false });

/* ─── Constants ──────────────────────────────────────────────────────── */

const SIDEBAR_ITEMS = [
  { icon: Dna, label: "Overview", viewMode: "analyze" as const },
  { icon: Search, label: "Sequence", viewMode: "explorer" as const },
  { icon: Box, label: "Structure", viewMode: "structure" as const },
  { icon: BarChart3, label: "Variants", viewMode: "leaderboard" as const },
];

const VIEW_LABELS = {
  input: "Start", pipeline: "Working", analyze: "Overview",
  structure: "Structure", leaderboard: "Variants",
  explorer: "Sequence", ide: "Sequence", compare: "Compare",
} as const;

const VALID_VIEWS = ["input", "pipeline", "analyze", "structure", "leaderboard", "explorer", "ide", "compare"];

// Views where edits actually apply to the active candidate — these get the
// "Editing candidate #N" pill. Read-only surfaces (overview, variants grid,
// compare, pipeline, input) deliberately do not.
const EDIT_CAPABLE_VIEWS: string[] = ["explorer", "ide", "structure"];

/* ─── Motion presets ─────────────────────────────────────────────────── */

const springTransition = { type: "spring" as const, stiffness: 300, damping: 28, mass: 0.8 };
const smoothTransition = { duration: 0.35, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] };

const fadeSlide = {
  initial: { opacity: 1 },
  animate: { opacity: 1 },
  exit: { opacity: 1 },
  transition: { duration: 0.01 },
};

const staggerContainer = {
  animate: { transition: { staggerChildren: 0.02, delayChildren: 0 } },
};

const staggerItem = {
  initial: { opacity: 1, y: 0 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.01 },
};

const slideInRight = {
  initial: { opacity: 1, x: 0 },
  animate: { opacity: 1, x: 0 },
  transition: { duration: 0.01 },
};

const scaleIn = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1 },
  transition: springTransition,
};

/* ─── Score bar that animates width on mount ─────────────────────────── */

function AnimatedScoreBar({ value, color, delay = 0 }: { value: number; color: string; delay?: number }) {
  return (
    <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--wax)" }}>
      <motion.div
        className="h-full rounded-full"
        initial={{ width: 0 }}
        animate={{ width: `${value * 100}%` }}
        transition={{ duration: 0.8, delay, ease: [0.16, 1, 0.3, 1] }}
        style={{ background: color, opacity: 0.8 }}
      />
    </div>
  );
}

/* ─── Main page ──────────────────────────────────────────────────────── */

export default function AnalyzePage() {
  return (
    <Suspense fallback={<div className="h-screen" style={{ background: "var(--surface-base)" }} />}>
      <AnalyzePageInner />
    </Suspense>
  );
}

function AnalyzePageInner() {
  const viewMode = useEvoStore((s) => s.viewMode);
  const rawSequence = useEvoStore((s) => s.rawSequence);
  const bases = useEvoStore((s) => s.bases);
  const regions = useEvoStore((s) => s.regions);
  const scores = useEvoStore((s) => s.scores);
  const analysisResult = useEvoStore((s) => s.analysisResult);
  const retrievalStatuses = useEvoStore((s) => s.retrievalStatuses);
  // Gene symbol from NCBI retrieval — scopes ClinVar region-evidence in AnnotationTrack.
  const activeGene = (() => {
    const ncbi = retrievalStatuses.find((r) => r.source === "ncbi")?.result as
      | Record<string, unknown>
      | undefined;
    const sym = ncbi?.symbol ?? ncbi?.gene;
    return typeof sym === "string" && sym && sym !== "Gene" ? sym : null;
  })();
  const selectedPosition = useEvoStore((s) => s.selectedPosition);
  const activePdb = useEvoStore((s) => s.activePdb);
  const highlightResidues = useEvoStore((s) => s.highlightResidues);
  const mutationEffect = useEvoStore((s) => s.mutationEffect);
  const mutationLoading = useEvoStore((s) => s.mutationLoading);
  const editHistory = useEvoStore((s) => s.editHistory);
  const setViewMode = useEvoStore((s) => s.setViewMode);
  const setSelectedPosition = useEvoStore((s) => s.setSelectedPosition);
  const setActivePdb = useEvoStore((s) => s.setActivePdb);
  const setHighlightResidues = useEvoStore((s) => s.setHighlightResidues);
  const addEditEntry = useEvoStore((s) => s.addEditEntry);
  const saveVersion = useEvoStore((s) => s.saveVersion);
  const revertVersion = useEvoStore((s) => s.revertVersion);
  const candidates = useEvoStore((s) => s.candidates);
  const activeCandidateId = useEvoStore((s) => s.activeCandidateId);
  const chatOpen = useEvoStore((s) => s.chatOpen);
  const toggleChat = useEvoStore((s) => s.toggleChat);
  const setChatOpen = useEvoStore((s) => s.setChatOpen);
  const setChatDraft = useEvoStore((s) => s.setChatDraft);
  const setComposerPrefill = useEvoStore((s) => s.setComposerPrefill);
  const hydrateFromSnapshot = useEvoStore((s) => s.hydrateFromSnapshot);
  const theme = "light" as const;

  // Debounced, best-effort autosave of the current session to the durable store.
  useSessionAutosave();
  const wsStatus = useEvoStore((s) => s.wsStatus);
  const seedSource = useEvoStore((s) => s.seedSource);
  const scoringNote = useEvoStore((s) => s.scoringNote);
  const structureModel = useEvoStore((s) => s.structureModel);
  const explanation = useEvoStore((s) => s.explanation);
  const toggleStoryMode = useEvoStore((s) => s.toggleStoryMode);

  const searchParams = useSearchParams();
  const router = useRouter();

  // Tutorial state
  const [showTutorial, setShowTutorial] = useState(false);
  useEffect(() => {
    if (!isTutorialCompleted()) {
      const timer = setTimeout(() => setShowTutorial(true), 800);
      return () => clearTimeout(timer);
    }
  }, []);

  // Collapse legacy Edit (ide) into Sequence (explorer).
  useEffect(() => {
    if (viewMode === "ide") setViewMode("explorer");
  }, [viewMode, setViewMode]);

  // Structure fullscreen state
  const [structureFullscreen, setStructureFullscreen] = useState(false);
  const urlHydratedRef = useRef(false);

  // Hydrate view from URL once on mount — never fight sidebar clicks afterward.
  useEffect(() => {
    if (urlHydratedRef.current) return;
    urlHydratedRef.current = true;
    const urlView = searchParams.get("view");
    if (urlView && VALID_VIEWS.includes(urlView) && urlView !== viewMode) {
      setViewMode(urlView as typeof viewMode);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Store → URL only (one direction).
  useEffect(() => {
    const current = searchParams.get("view");
    if (viewMode === "input") {
      if (current) router.replace("/analyze", { scroll: false });
      return;
    }
    if (current !== viewMode) {
      router.replace(`/analyze?view=${viewMode}`, { scroll: false });
    }
  }, [viewMode, router, searchParams]);

  const { isLoading, error, analyze } = useSequenceAnalysis();
  const { startDesign } = useDesignPipeline();
  const { simulate } = useMutationSim();

  useEffect(() => {
    if (analysisResult?.predictedProteins?.[0]?.pdbData && !activePdb) {
      setActivePdb(analysisResult.predictedProteins[0].pdbData);
      return;
    }
    // Analyze may return ORF metadata without PDB — fold via /api/structure (ESMFold).
    if (analysisResult && !activePdb && rawSequence && rawSequence.length >= 30) {
      let cancelled = false;
      (async () => {
        try {
          const { fetchStructure } = await import("@/lib/api");
          const pdb = await fetchStructure(0, rawSequence.length, rawSequence);
          if (!cancelled && pdb) setActivePdb(pdb);
        } catch {
          /* structure optional until user opens Structure tab */
        }
      })();
      return () => {
        cancelled = true;
      };
    }
  }, [analysisResult, activePdb, setActivePdb, rawSequence]);

  const handleSequenceSubmit = useCallback((seq: string) => { analyze(seq); }, [analyze]);
  const handleDesignSubmit = useCallback((goal: string) => { startDesign(goal); }, [startDesign]);
  const handleBaseClick = useCallback((pos: number) => { setSelectedPosition(pos); }, [setSelectedPosition]);
  const handleMutationSubmit = useCallback((pos: number, alt: string) => {
    if (rawSequence) {
      simulate(rawSequence, pos, alt);
      addEditEntry({ position: pos, from: rawSequence[pos], to: alt, delta: 0 });
    }
  }, [rawSequence, simulate, addEditEntry]);

  // Inline editor: local (optimistic) sequence edits — insert/delete/typing.
  const handleSequenceChange = useCallback((next: string) => {
    useEvoStore.getState().setEditedSequence(next);
  }, []);
  // Inline editor: single-base mutate that hits the backend instant-rescore path.
  const handleRescoreBase = useCallback((pos: number, base: string) => {
    setSelectedPosition(pos);
    handleMutationSubmit(pos, base);
  }, [setSelectedPosition, handleMutationSubmit]);

  // Rescore: re-analyze the current sequence with the backend
  const [rescoring, setRescoring] = useState(false);
  const handleRescore = useCallback(async () => {
    if (!rawSequence || rescoring) return;
    setRescoring(true);
    try {
      const result = await import("@/lib/api").then(m => m.analyzeSequence(rawSequence));
      useEvoStore.getState().setAnalysisResult(result);
    } catch { /* keep current data */ }
    setRescoring(false);
  }, [rawSequence, rescoring]);

  // 3D ↔ sequence linking
  const [clickedResidue, setClickedResidue] = useState<number | null>(null);
  const [hoveredResidue, setHoveredResidue] = useState<number | null>(null);
  const inspectedResidue = hoveredResidue ?? clickedResidue;

  const queueGuidedPrompt = useCallback((prompt: string) => {
    setChatOpen(true);
    setChatDraft(prompt);
  }, [setChatDraft, setChatOpen]);

  const handleResidueClick = useCallback((residueSeq: number) => {
    const basePos = (residueSeq - 1) * 3;
    if (basePos >= 0 && basePos < (bases.length || rawSequence.length)) {
      setSelectedPosition(basePos);
    }
    setClickedResidue(residueSeq);
    setHighlightResidues([residueSeq]);
  }, [bases.length, rawSequence.length, setSelectedPosition, setHighlightResidues]);

  const handleResidueHover = useCallback((residueSeq: number | null) => {
    setHoveredResidue(residueSeq);
    // Live highlight on hover so you don't need to click every residue.
    if (residueSeq !== null) {
      setHighlightResidues([residueSeq]);
    } else if (clickedResidue !== null) {
      setHighlightResidues([clickedResidue]);
    } else {
      setHighlightResidues([]);
    }
  }, [clickedResidue, setHighlightResidues]);

  // One source of truth: when the playhead (selectedPosition) moves — from the
  // scrubber, the LikelihoodGraph, the editor caret, or a region jump — mirror
  // it onto the 3D residue highlight so the structure tracks the sequence.
  // Uses the same residue↔base mapping as handleResidueClick ((resi-1)*3).
  useEffect(() => {
    if (selectedPosition === null) return;
    const residue = Math.floor(selectedPosition / 3) + 1;
    setHighlightResidues([residue]);
  }, [selectedPosition, setHighlightResidues]);

  // Mobile sidebar collapse
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="h-screen flex overflow-hidden" style={{ background: "var(--surface-base)", color: "var(--text-primary)" }}>

      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ── TUTORIAL OVERLAY ── */}
      <TutorialOverlay
        isOpen={showTutorial}
        onClose={() => setShowTutorial(false)}
        onViewChange={(view) => setViewMode(view as typeof viewMode)}
        currentView={viewMode}
      />

      <WorkspaceSidebar
        viewMode={viewMode}
        analysisResult={analysisResult}
        sidebarOpen={sidebarOpen}
        onNavigate={(v) => setViewMode(v as typeof viewMode)}
        onCloseMobile={() => setSidebarOpen(false)}
        onShowTutorial={() => setShowTutorial(true)}
        onNewDesign={() => {
          setViewMode("input");
        }}
        onSelectSession={(session) => {
          setComposerPrefill({
            mode: session.kind,
            value: session.payload,
          });
          setViewMode("input");
        }}
        onResumeSession={(sessionId) => {
          // RESUME a durable session: restore full state, don't re-run.
          getSession(sessionId)
            .then((snap) => {
              if (snap) {
                hydrateFromSnapshot(snap);
                setViewMode("analyze");
              }
            })
            .catch(() => {
              // Persistence unavailable — leave the workspace untouched.
            });
        }}
        wsStatus={wsStatus}
        navItems={SIDEBAR_ITEMS}
      />

      <div className="flex-1 flex flex-col overflow-hidden" id="main-content">
        {/* ── HEADER (glassmorphic) ── */}
        <motion.header
          className="h-14 shrink-0 flex items-center justify-between px-4 lg:px-6"
          style={{ background: "rgba(250,249,246,0.9)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--ghost-border)" }}
          initial={false}
        >
          <div className="flex items-center gap-3">
            {/* Mobile menu toggle */}
            <button
              className="lg:hidden p-2 -ml-2 rounded-full transition-colors hover:bg-white/[0.06]"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              aria-label={sidebarOpen ? "Close navigation menu" : "Open navigation menu"}
              aria-expanded={sidebarOpen}
            >
              {sidebarOpen ? <X size={18} aria-hidden="true" /> : <Menu size={18} aria-hidden="true" />}
            </button>
            {viewMode !== "input" && viewMode !== "pipeline" && (
              <span className="text-[13px] font-medium" style={{ color: "var(--text-secondary)" }}>
                {VIEW_LABELS[viewMode]}
              </span>
            )}
            {EDIT_CAPABLE_VIEWS.includes(viewMode) && (
              <EditingCandidateChrome variant="pill" />
            )}
          </div>
          <div className="flex items-center gap-1 lg:gap-3 overflow-x-auto">
            {viewMode !== "input" && viewMode !== "pipeline" && (
              <>
                <div className="hidden md:flex gap-1 lg:hidden" role="tablist" aria-label="View tabs">
                  {(["analyze", "explorer", "structure", "leaderboard", "compare"] as const).map((m) => (
                    <motion.button key={m} onClick={() => setViewMode(m)}
                      role="tab"
                      aria-selected={viewMode === m}
                      whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}
                      className="px-3.5 py-1.5 text-[12px] font-medium transition-colors"
                      style={{
                        background: viewMode === m ? "var(--ink)" : "transparent",
                        color: viewMode === m ? "var(--cream)" : "var(--text-muted)",
                        borderRadius: "999px",
                        boxShadow: viewMode === m ? "0 8px 20px -6px rgba(15,15,15,0.25)" : "none",
                      }}>
                      {VIEW_LABELS[m]}
                    </motion.button>
                  ))}
                </div>
                <button onClick={toggleChat}
                  aria-label={chatOpen ? "Close Helio" : "Open Helio"}
                  aria-pressed={chatOpen}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-[12px] font-medium transition-all duration-300"
                  style={{
                    color: chatOpen ? "var(--ink)" : "var(--honey-700)",
                    background: chatOpen ? "var(--honey-100)" : "rgba(245,158,11,0.1)",
                  }}>
                  <Sparkles size={13} /> Helio
                </button>
              </>
            )}
          </div>
        </motion.header>

        <AnimatePresence mode="popLayout" initial={false}>
          {/* ═══ INPUT ═══ */}
          {viewMode === "input" && (
            <motion.div key="input" className="flex-1 flex overflow-hidden" data-tutorial="sequence-input"
              role="main"
              {...fadeSlide}>
              <ErrorBoundary>
                <SequenceInput onSubmit={handleSequenceSubmit} onDesign={handleDesignSubmit} isLoading={isLoading} error={error} />
              </ErrorBoundary>
            </motion.div>
          )}

          {/* ═══ PIPELINE: running ═══ */}
          {viewMode === "pipeline" && (
            <motion.div key="pipeline" className="flex-1" role="main" aria-live="polite"
              {...fadeSlide}>
              <ErrorBoundary>
                <PipelineStatus />
              </ErrorBoundary>
            </motion.div>
          )}

          {/* ═══ ANALYZE: understand ═══ */}
          {viewMode === "analyze" && analysisResult && (() => {
            const topRegion = regions.reduce((best, r) => (r.score && (!best.score || Math.abs(r.score) < Math.abs(best.score))) ? r : best, regions[0]);
            const codingRegions = regions.filter(r => r.type === "exon" || r.type === "orf");
            const avgScore = scores.length > 0 ? (scores.reduce((a, s) => a + Math.abs(s.score), 0) / scores.length) : 0;
            const scoresAreHeuristic = Boolean(scoringNote);
            const engineChips: { label: string; value: string; term?: string }[] = [
              { label: "Generation", value: "Evo 2", term: "evo2" },
              { label: "Scoring", value: scoresAreHeuristic ? "labeled heuristic" : "Evo 2 log-likelihood", term: "log-likelihood" },
              ...(seedSource ? [{ label: "Seed", value: seedSource.replace(/_/g, " ") }] : []),
              ...(analysisResult.predictedProteins.length > 0
                ? [{ label: "Structure", value: structureModel ?? "ESMFold", term: "esmfold" }]
                : []),
            ];
            const summaryTiles = [
              { label: "Coding regions", value: String(codingRegions.length), color: "var(--accent)", term: "exon" },
              { label: "Mean confidence", value: avgScore.toFixed(2), color: "var(--base-c)", term: "log-likelihood" },
              { label: "Proteins predicted", value: String(analysisResult.predictedProteins.length), color: "var(--base-g)", term: "protein-structure" },
              { label: "Sequence length", value: `${rawSequence.length} bp`, color: "var(--text-secondary)", term: "base-pair" },
            ];
            return (
            <motion.div key="analyze" className="flex-1 overflow-auto"
              {...fadeSlide}>

              {/* ── Run-report header ─────────────────────────────────── */}
              <div className="px-8 pt-8 pb-6" style={{ background: "var(--surface-raised)" }}>
                <div className="max-w-6xl mx-auto">
                  <div className="flex items-start justify-between gap-6">
                    <motion.div {...staggerItem} className="min-w-0">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-[10px] font-semibold uppercase tracking-[0.14em]" style={{ color: "var(--accent)" }}>
                          Design report
                        </span>
                        <span className="text-[10px]" style={{ color: "var(--text-faint)" }}>·</span>
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-faint)" }}>
                          {rawSequence.length} bp · {scores.length} scores
                        </span>
                      </div>
                      <h2 className="text-2xl font-semibold tracking-tight mb-2">
                        {codingRegions.length > 0
                          ? `Candidate with ${codingRegions.length} coding region${codingRegions.length !== 1 ? "s" : ""}`
                          : "Generated candidate"}
                      </h2>
                      {explanation && (
                        <p className="text-[13px] max-w-2xl leading-relaxed line-clamp-3" style={{ color: "var(--text-secondary)" }}>
                          {explanation.length > 320 ? `${explanation.slice(0, 317)}…` : explanation}
                        </p>
                      )}
                      {/* Engine provenance chips */}
                      <div className="flex flex-wrap items-center gap-1.5 mt-3">
                        {engineChips.map((chip) => (
                          <span key={chip.label}
                            className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full"
                            style={{ background: "var(--surface-elevated)", color: "var(--text-secondary)" }}>
                            <Cpu size={11} style={{ color: "var(--accent)" }} />
                            <span style={{ color: "var(--text-faint)" }}>{chip.label}</span>
                            {chip.term ? (
                              <ScienceTooltip term={chip.term}><span className="font-medium" style={{ color: "var(--ink)" }}>{chip.value}</span></ScienceTooltip>
                            ) : (
                              <span className="font-medium" style={{ color: "var(--ink)" }}>{chip.value}</span>
                            )}
                          </span>
                        ))}
                      </div>
                    </motion.div>
                    <div className="flex flex-col items-end gap-2 shrink-0">
                      <div className="flex gap-2">
                        <motion.button onClick={() => setViewMode("structure")}
                          whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}
                          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium transition-all"
                          style={{ background: "var(--surface-elevated)", color: "var(--text-primary)" }}>
                          <Box size={15} /> View Structure
                        </motion.button>
                        <motion.button onClick={() => setViewMode("explorer")}
                          whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}
                          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium transition-all"
                          style={{ background: "var(--accent)", color: "var(--ink)" }}>
                          Open Explorer <ArrowRight size={15} />
                        </motion.button>
                      </div>
                      <button onClick={toggleStoryMode}
                        className="inline-flex items-center gap-1.5 text-[11px] font-medium transition-colors hover:underline"
                        style={{ color: "var(--text-muted)" }}>
                        <BookOpen size={12} /> How to read this (Story Mode)
                      </button>
                    </div>
                  </div>

                  {scoringNote && (
                    <p className="text-[12px] mt-4 max-w-3xl leading-relaxed px-3 py-2 rounded-lg"
                      style={{ color: "var(--text-muted)", background: "color-mix(in oklch, var(--base-t), transparent 94%)" }}>
                      {scoringNote}
                    </p>
                  )}

                  {/* Scannable summary strip */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
                    {summaryTiles.map(({ label, value, color, term }) => (
                      <div key={label} className="rounded-xl px-4 py-3" style={{ background: "var(--surface-elevated)" }}>
                        <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>
                          <ScienceTooltip term={term}>{label}</ScienceTooltip>
                        </div>
                        <div className="text-xl font-semibold font-mono" style={{ color }}>{value}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="px-8 py-6 max-w-6xl mx-auto">
                {/* Annotation track full-width */}
                <motion.div className="mb-6" {...scaleIn}>
                  <AnnotationTrack regions={regions} sequenceLength={rawSequence.length} gene={activeGene} />
                  <AnnotationLegend regions={regions} />
                </motion.div>

                {/* Three-column: structure preview + regions + insights */}
                <motion.div className="grid grid-cols-1 lg:grid-cols-4 gap-6" variants={staggerContainer} initial="initial" animate="animate">
                  {/* Left: Structure preview card */}
                  <motion.div className="lg:col-span-1" variants={staggerItem}>
                    <div className="rounded-xl overflow-hidden" style={{ background: "var(--surface-elevated)" }}>
                      <div className="p-4 pb-2">
                        <div className="flex items-center gap-2 mb-2">
                          <Box size={14} style={{ color: "var(--accent)" }} />
                          <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--accent)" }}>
                            <ScienceTooltip term="protein-structure">Protein Structure</ScienceTooltip>
                          </span>
                        </div>
                      </div>
                      <div className="h-[220px] cursor-pointer flex items-center justify-center" onClick={() => setViewMode("structure")}
                        style={{ background: "var(--surface-base)" }}>
                        <div className="text-center">
                          <Box size={40} style={{ color: "var(--accent)", margin: "0 auto 8px", opacity: 0.5 }} />
                          <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>Click to view 3D structure</span>
                        </div>
                      </div>
                      <div className="p-3">
                        <button onClick={() => setViewMode("structure")}
                          className="w-full text-xs font-medium flex items-center justify-center gap-1 py-2.5 rounded-full transition-colors hover:bg-white/[0.04]"
                          style={{ color: "var(--accent)" }}>
                          Explore in 3D <ArrowRight size={12} />
                        </button>
                      </div>
                    </div>
                  </motion.div>

                  {/* Middle 2/4: Region list */}
                  <motion.div className="lg:col-span-2" variants={staggerItem}>
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Identified regions</h3>
                      <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>{regions.length} total</span>
                    </div>
                    <div className="rounded-xl overflow-hidden" style={{ background: "var(--surface-elevated)" }}>
                      <div className="flex items-center gap-4 px-5 py-2.5 text-[11px] font-medium uppercase tracking-wider"
                        style={{ color: "var(--text-muted)" }}>
                        <span className="w-6">#</span>
                        <span className="flex-1">Region</span>
                        <span className="w-20 text-right">Type</span>
                        <span className="w-24 text-right">Position</span>
                        <span className="w-16 text-right"><ScienceTooltip term="base-pair">Length</ScienceTooltip></span>
                        <span className="w-16 text-right"><ScienceTooltip term="log-likelihood">Score</ScienceTooltip></span>
                        <span className="w-8" />
                      </div>
                      {regions.slice(0, 10).map((r, i) => (
                        <motion.button key={i}
                          onClick={() => { setSelectedPosition(r.start); setViewMode("explorer"); }}
                          initial={{ opacity: 0, x: -12 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: 0.1 + i * 0.04, ...springTransition }}
                          className="w-full flex items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-white/[0.04]"
                          style={{ borderBottom: i < Math.min(regions.length, 10) - 1 ? "1px solid rgba(255,255,255,0.04)" : "none" }}>
                          <span className="text-xs font-mono w-6" style={{ color: "var(--text-muted)" }}>{i + 1}</span>
                          <span className="text-[13px] font-medium flex-1" style={{ color: "var(--text-primary)" }}>{r.label ?? `${r.type} ${i + 1}`}</span>
                          <span className="text-[11px] font-mono w-20 text-right px-1.5 py-0.5 rounded"
                            style={{
                              color: r.type === "exon" || r.type === "orf" ? "var(--accent)" : "var(--text-muted)",
                              background: r.type === "exon" || r.type === "orf" ? "color-mix(in oklch, var(--accent), transparent 92%)" : "transparent",
                            }}>
                            <ScienceTooltip term={r.type}>{r.type}</ScienceTooltip>
                          </span>
                          <span className="text-xs font-mono w-24 text-right" style={{ color: "var(--text-secondary)" }}>{r.start}-{r.end}</span>
                          <span className="text-xs font-mono w-16 text-right" style={{ color: "var(--text-muted)" }}>{r.end - r.start} bp</span>
                          <span className="text-xs font-mono w-16 text-right" style={{ color: r.score && Math.abs(r.score) < 2 ? "var(--accent)" : "var(--base-t)" }}>
                            {r.score?.toFixed(1) ?? "-"}
                          </span>
                          <ChevronRight size={14} className="w-8 shrink-0" style={{ color: "var(--text-faint)" }} />
                        </motion.button>
                      ))}
                    </div>
                  </motion.div>

                  {/* Right 1/4: Insights */}
                  <motion.div className="space-y-4" variants={staggerItem}>
                    {topRegion && (
                      <div className="p-5 rounded-xl" style={{ background: "var(--surface-elevated)" }}>
                        <div className="flex items-center gap-2 mb-3">
                          <Target size={14} style={{ color: "var(--accent)" }} />
                          <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--accent)" }}>Top region</span>
                        </div>
                        <div className="text-base font-semibold mb-1">{topRegion.label ?? topRegion.type}</div>
                        <div className="text-xs font-mono mb-3" style={{ color: "var(--text-secondary)" }}>{topRegion.start}-{topRegion.end} ({topRegion.end - topRegion.start} bp)</div>
                        <button onClick={() => { setSelectedPosition(topRegion.start); setViewMode("explorer"); }}
                          className="text-xs font-medium flex items-center gap-1 transition-colors hover:text-white"
                          style={{ color: "var(--accent)" }}>
                          Inspect this region <ArrowRight size={12} />
                        </button>
                      </div>
                    )}

                    <div className="p-5 rounded-xl" style={{ background: "var(--surface-elevated)" }}>
                      <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Engines</span>
                      <p className="text-xs mt-2 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                        DNA generated by <ScienceTooltip term="evo2">Evo 2</ScienceTooltip>. Per-position <ScienceTooltip term="log-likelihood">log-likelihood</ScienceTooltip> scores how gene-like each base looks — {scoresAreHeuristic ? "labeled heuristics under the default engine, not a real forward pass" : "a real Evo 2 forward pass"}. Structure by <ScienceTooltip term="esmfold">ESMFold</ScienceTooltip>.
                      </p>
                      <button onClick={toggleStoryMode}
                        className="mt-3 inline-flex items-center gap-1.5 text-[11px] font-medium transition-colors hover:underline"
                        style={{ color: "var(--accent)" }}>
                        <BookOpen size={12} /> Open Story Mode glossary
                      </button>
                    </div>
                  </motion.div>
                </motion.div>

                {/* ── Related work & evidence (full width) ─────────────── */}
                <motion.div className="mt-8 pt-6" style={{ borderTop: "1px solid var(--ghost-border)" }} {...scaleIn}>
                  <h3 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>Related work &amp; evidence</h3>
                  <RelatedWorkPanel />
                </motion.div>
              </div>
            </motion.div>
            );
          })()}

          {/* ═══ STRUCTURE: 3D protein centerpiece ═══ */}
          {viewMode === "structure" && (
            <motion.div key="structure" className="flex-1 flex overflow-hidden"
              {...fadeSlide}>
              {/* Main 3D viewer area */}
              <div className={`flex-1 flex flex-col overflow-hidden ${structureFullscreen ? "" : ""}`}>
                {/* Toolbar */}
                <motion.div className="shrink-0 flex items-center justify-between px-6 py-3"
                  style={{ background: "var(--surface-raised)" }}
                  initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1, ...springTransition }}>
                  <div className="flex items-center gap-3">
                    <Box size={14} style={{ color: "var(--accent)" }} />
                    <span className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
                      <ScienceTooltip term="protein-structure">3D Protein Structure</ScienceTooltip> — hover residues for details, click to inspect
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <motion.button
                      whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                      onClick={() => setStructureFullscreen(!structureFullscreen)}
                      className="px-3 py-1.5 rounded-full text-[10px] font-medium uppercase tracking-wider transition-all font-label flex items-center gap-1.5"
                      style={{ color: "var(--text-muted)" }}>
                      {structureFullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
                      {structureFullscreen ? "Exit fullscreen" : "Fullscreen"}
                    </motion.button>
                    <motion.button
                      whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                      onClick={() => setHighlightResidues([])}
                      className="px-3 py-1.5 rounded-full text-[10px] font-medium uppercase tracking-wider transition-all font-label flex items-center gap-1.5"
                      style={{ color: "var(--text-muted)" }}>
                      <RotateCcw size={12} /> Reset
                    </motion.button>
                    <motion.button onClick={() => setViewMode("explorer")}
                      whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                      className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-[10px] font-medium uppercase tracking-wider font-label transition-all"
                      style={{ background: "var(--accent)", color: "var(--ink)" }}>
                      <Search size={12} /> Explore Sequence
                    </motion.button>
                  </div>
                </motion.div>

                {/* Viewer */}
                <motion.div
                  className="flex-1 relative"
                  style={{ background: "var(--surface-base)" }}
                  initial={false}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.01 }}
                >
                  <ProteinViewer
                    pdbData={activePdb || undefined}
                    highlightResidues={highlightResidues}
                    onResidueClick={handleResidueClick}
                    onResidueHover={handleResidueHover}
                    isFullscreen={structureFullscreen}
                    theme={theme}
                    structureModel={structureModel}
                  />

                  {/* An uploaded PDB is not model-predicted: show an honest badge
                      instead of a pLDDT legend, since its B-factors are not pLDDT. */}
                  {structureModel === "user_pdb" ? (
                    <motion.div
                      className="absolute top-14 left-4 flex items-center gap-2 px-3 py-2 rounded-2xl pointer-events-none max-w-[min(100%,360px)] z-10"
                      style={{
                        background: "rgba(255,255,255,0.86)",
                        backdropFilter: "blur(12px)",
                        border: "1px solid var(--ghost-border)",
                        boxShadow: "var(--shadow-soft)",
                      }}
                      initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.3, ...springTransition }}
                    >
                      <span className="text-[10px] leading-snug" style={{ color: "#B45309" }}>
                        Uploaded structure — not model-predicted; not linked to a DNA sequence. Colors are not pLDDT.
                      </span>
                    </motion.div>
                  ) : (
                  /* pLDDT legend — top-left so it never collides with view-mode buttons */
                  <motion.div
                    className="absolute top-14 left-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2 rounded-2xl pointer-events-none max-w-[min(100%,340px)] z-10"
                    style={{
                      background: "rgba(255,255,255,0.82)",
                      backdropFilter: "blur(12px)",
                      border: "1px solid var(--ghost-border)",
                      boxShadow: "var(--shadow-soft)",
                    }}
                    initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3, ...springTransition }}
                  >
                    <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                      <ScienceTooltip term="plddt">pLDDT</ScienceTooltip>
                    </span>
                    {[
                      { color: "#5bb5a2", label: "≥90" },
                      { color: "#6b9fd4", label: "≥70" },
                      { color: "#c9a855", label: "≥50" },
                      { color: "#d47a7a", label: "<50" },
                    ].map(({ color, label }) => (
                      <div key={label} className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>{label}</span>
                      </div>
                    ))}
                  </motion.div>
                  )}
                </motion.div>
              </div>

              {/* Side panel (hidden in fullscreen and on mobile) */}
              {!structureFullscreen && (
                <motion.div className="hidden lg:flex w-[320px] shrink-0 flex-col overflow-y-auto"
                  style={{ background: "var(--surface-elevated)" }}
                  {...slideInRight}>

                  {/* Selected residue info */}
                  <div className="p-5 pb-4">
                    <span className="text-[11px] font-medium uppercase tracking-wider block mb-4" style={{ color: "var(--accent)" }}>
                      <ScienceTooltip term="residue">Residue Inspector</ScienceTooltip>
                    </span>
                    {inspectedResidue !== null ? (
                      <motion.div className="space-y-3" initial={{ opacity: 0 }} animate={{ opacity: 1 }} key={inspectedResidue}>
                        <div>
                          <span className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                            {hoveredResidue !== null && hoveredResidue !== clickedResidue ? "Hovering" : "Residue"}
                          </span>
                          <div className="text-lg font-semibold font-mono" style={{ color: "var(--text-primary)" }}>
                            #{inspectedResidue}
                          </div>
                        </div>
                        {selectedPosition !== null && clickedResidue === inspectedResidue && (
                          <div>
                            <span className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Linked base position</span>
                            <div className="text-sm font-mono" style={{ color: "var(--accent)" }}>{selectedPosition}</div>
                          </div>
                        )}
                        {hoveredResidue !== null && (
                          <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-faint)" }}>
                            Click to pin this residue and jump to its codon in the sequence.
                          </p>
                        )}
                      </motion.div>
                    ) : (
                      <p className="text-[13px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
                        Hover the ribbon to preview residues — click once to pin and link the DNA codon.
                      </p>
                    )}
                  </div>

                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />

                  {/* Sequence context (only when analysis has run) */}
                  {bases.length > 0 && (
                    <>
                      <div className="p-5">
                        <span className="text-[11px] font-medium uppercase tracking-wider block mb-3" style={{ color: "var(--text-muted)" }}>
                          Sequence Preview
                        </span>
                        <div className="h-[180px] overflow-auto rounded-lg" style={{ background: "var(--surface-base)" }}>
                          <div className="p-2">
                            <SequenceViewer bases={bases.slice(0, 300)} regions={regions}
                              highlightedPosition={selectedPosition ?? undefined} onBaseClick={handleBaseClick} />
                          </div>
                        </div>
                      </div>
                      <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />
                    </>
                  )}

                  {/* Quick scores */}
                  <div className="p-5">
                    <span className="text-[11px] font-medium uppercase tracking-wider block mb-3" style={{ color: "var(--text-muted)" }}>
                      <ScienceTooltip term="overall-viability">Candidate Scores</ScienceTooltip>
                    </span>
                    {candidates.length > 0 && (() => {
                      const c = candidates.find(c => c.id === (activeCandidateId ?? 0)) ?? candidates[0];
                      return (
                        <div className="space-y-2.5">
                          {[
                            { label: "Functional", val: c.scores.functional, color: "var(--accent)", term: "functional-plausibility" },
                            { label: "Tissue", val: c.scores.tissue, color: "var(--base-c)", term: "tissue-specificity" },
                            { label: "Off-target", val: c.scores.offTarget, color: "var(--base-t)", term: "off-target-risk" },
                            { label: "Novelty", val: c.scores.novelty, color: "var(--base-g)", term: "novelty" },
                          ].map(({ label, val, color, term }, i) => (
                            <div key={label} className="flex items-center gap-3">
                              <span className="text-[11px] w-16" style={{ color: "var(--text-muted)" }}>
                                <ScienceTooltip term={term}>{label}</ScienceTooltip>
                              </span>
                              <AnimatedScoreBar value={val} color={color} delay={0.15 + i * 0.08} />
                              <span className="text-[11px] font-mono w-10 text-right" style={{ color }}>{(val * 100).toFixed(0)}%</span>
                            </div>
                          ))}
                        </div>
                      );
                    })()}
                  </div>

                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />

                  {/* Confidence summary */}
                  <div className="p-5">
                    <span className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
                      About this view
                    </span>
                    <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                      {structureModel === "user_pdb" ? (
                        <>
                          This is a structure file you uploaded, rendered exactly as provided.
                          It is <strong>not model-predicted</strong> and <strong>not linked</strong> to a DNA sequence,
                          so residue colors are not <ScienceTooltip term="plddt">pLDDT</ScienceTooltip> and codon linking is disabled.
                        </>
                      ) : structureModel === "esmfold" || (!structureModel && activePdb) ? (
                        <>
                          This fold is from live <ScienceTooltip term="esmfold">ESMFold</ScienceTooltip> (Meta ESM Atlas) of a coding ORF translated from your DNA.
                          Colors are per-residue <ScienceTooltip term="plddt">pLDDT</ScienceTooltip>.
                        </>
                      ) : activePdb ? (
                        <>Structure source: <strong>{structureModel ?? "unknown"}</strong>. Treat this as illustrative unless labeled ESMFold live.</>
                      ) : (
                        <>No structure yet. ESMFold needs an ORF of at least ~40 amino acids. Short or non-coding designs will not fold.</>
                      )}
                    </p>
                  </div>

                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />

                  <div className="p-5">
                    <span className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--accent)" }}>
                      Guided Next Steps
                    </span>
                    {(() => {
                      const active = candidates.find((c) => c.id === (activeCandidateId ?? -1)) ?? candidates[0];
                      if (!active) return null;
                      const likely = active.scores.functional >= 0.7 ? "Promising" : active.scores.functional >= 0.55 ? "Moderate" : "Weak";
                      const tissueFit = active.scores.tissue >= 0.7 ? "Strong" : active.scores.tissue >= 0.55 ? "Moderate" : "Weak";
                      const safety = active.scores.offTarget <= 0.03 ? "Strong" : active.scores.offTarget <= 0.08 ? "Moderate" : "Risky";
                      return (
                        <>
                          <p className="text-[12px] leading-relaxed mb-3" style={{ color: "var(--text-primary)" }}>
                            Candidate #{active.id}: function heuristic <strong>{likely}</strong>, tissue-motif <strong>{tissueFit}</strong>, panel safety <strong>{safety}</strong>. Demo metrics only.
                          </p>
                          <div className="space-y-2">
                            <button
                              onClick={() => queueGuidedPrompt("Explain this structure and candidate in plain English for a patient-facing clinician and for a biotech researcher.")}
                              className="w-full text-left px-3 py-2 rounded-full text-[11px] transition-colors hover:bg-white/[0.05]"
                              style={{ background: "var(--surface-base)", color: "var(--text-secondary)" }}
                            >
                              Explain this candidate for layman + clinician
                            </button>
                            <button
                              onClick={() => queueGuidedPrompt("Improve this candidate for tissue specificity and show exact score changes.")}
                              className="w-full text-left px-3 py-2 rounded-full text-[11px] transition-colors hover:bg-white/[0.05]"
                              style={{ background: "var(--surface-base)", color: "var(--text-secondary)" }}
                            >
                              Improve tissue specificity
                            </button>
                            <button
                              onClick={() => queueGuidedPrompt("Reduce off-target risk and explain the tradeoffs in one concise paragraph.")}
                              className="w-full text-left px-3 py-2 rounded-full text-[11px] transition-colors hover:bg-white/[0.05]"
                              style={{ background: "var(--surface-base)", color: "var(--text-secondary)" }}
                            >
                              Make it safer
                            </button>
                          </div>
                        </>
                      );
                    })()}
                  </div>

                  <div className="flex-1" />
                </motion.div>
              )}

              {chatOpen && <ChatPanel />}
            </motion.div>
          )}

          {/* ═══ LEADERBOARD: rank/triage ═══ */}
          {viewMode === "leaderboard" && analysisResult && (
            <motion.div key="leaderboard" className="flex-1 flex overflow-hidden"
              {...fadeSlide}>
              <CandidateLeaderboard />
              {chatOpen && <ChatPanel />}
            </motion.div>
          )}

          {/* ═══ COMPARE: diff ═══ */}
          {viewMode === "compare" && analysisResult && (
            <motion.div key="compare" className="flex-1 flex overflow-hidden"
              {...fadeSlide}>
              <CompareView />
              {chatOpen && <ChatPanel />}
            </motion.div>
          )}


          {/* ═══ SEQUENCE: inspect + edit (merged Sequence / Edit) ═══ */}
          {(viewMode === "explorer" || viewMode === "ide") && analysisResult && (
            <motion.div key="sequence-workspace" className="flex-1 flex flex-col overflow-hidden"
              {...fadeSlide}>
              {/* IDE toolbar */}
              <div className="h-10 shrink-0 flex items-center justify-between px-5"
                style={{ background: "var(--surface-raised)" }}>
                <div className="flex items-center gap-3">
                  <EditingCandidateChrome variant="pill" />
                  <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>
                    <ScienceTooltip term="base-pair">{rawSequence.length} bp</ScienceTooltip> · {editHistory.length} <ScienceTooltip term="mutation">edit{editHistory.length !== 1 ? "s" : ""}</ScienceTooltip>
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={saveVersion} className="text-[10px] px-2.5 py-1 rounded-full font-medium transition-colors hover:bg-white/[0.04]"
                    style={{ color: "var(--text-muted)" }}>Save version</button>
                  <button onClick={() => { revertVersion(); setClickedResidue(null); }} className="text-[10px] px-2.5 py-1 rounded-full font-medium transition-colors hover:bg-white/[0.04]"
                    style={{ color: "var(--text-muted)" }}>Revert</button>
                  <button onClick={() => setViewMode("compare")}
                    className="text-[10px] px-2.5 py-1 rounded-full font-medium transition-colors hover:bg-white/[0.04]"
                    style={{ color: "var(--text-muted)" }}>Compare</button>
                  <button onClick={handleRescore} disabled={rescoring}
                    className="text-[10px] px-2.5 py-1 rounded-full font-medium transition-colors disabled:opacity-50"
                    style={{ background: "var(--accent)", color: "var(--ink)" }}>
                    {rescoring ? "Rescoring..." : "Rescore"}
                  </button>
                </div>
              </div>
              <div className="flex-1 flex overflow-hidden min-h-0">
                {/* Editable workspace */}
                <div className="flex-1 flex flex-col overflow-hidden min-w-0">
                  <div className="px-5 py-2 shrink-0" style={{ background: "var(--surface-raised)" }}>
                    <AnnotationTrack regions={regions} sequenceLength={rawSequence.length} gene={activeGene} />
                  </div>
                  <div className="flex-1 overflow-auto px-5 py-3">
                    <SequenceEditor
                      sequence={rawSequence}
                      regions={regions}
                      perPositionScores={scores}
                      selectedPosition={selectedPosition}
                      onSequenceChange={handleSequenceChange}
                      onRescoreBase={handleRescoreBase}
                      onSelectPosition={setSelectedPosition}
                    />
                  </div>
                  {/* Playhead: scrubs selectedPosition across the whole sequence */}
                  <div className="shrink-0 px-5 py-2.5" style={{ background: "var(--surface-raised)", borderTop: "1px solid var(--ghost-border)" }}>
                    <SequenceScrubber
                      length={rawSequence.length}
                      position={selectedPosition}
                      onChange={setSelectedPosition}
                    />
                  </div>
                  <div className="h-36 shrink-0 px-5 py-3" style={{ background: "var(--surface-raised)" }}>
                    <LikelihoodGraph scores={scores}
                      highlightedPosition={selectedPosition ?? undefined} onPositionHover={setSelectedPosition} />
                  </div>
                </div>
                {/* IDE right panel */}
                <motion.div className="hidden lg:flex w-[380px] shrink-0 flex-col overflow-y-auto"
                  style={{ background: "var(--surface-elevated)" }}
                  {...slideInRight}>
                  {/* Mutation editor */}
                  <div className="p-5">
                    <span className="text-[11px] font-medium uppercase tracking-wider block mb-3" style={{ color: "var(--accent)" }}>
                      <ScienceTooltip term="mutation">Mutation Editor</ScienceTooltip>
                    </span>
                    <MutationPanel sequence={rawSequence} onMutationSubmit={handleMutationSubmit}
                      mutationEffect={mutationEffect ?? undefined} isLoading={mutationLoading} />
                    {mutationEffect && (
                      <motion.div className="mt-4" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                        <MutationDiff effect={mutationEffect} />
                      </motion.div>
                    )}
                  </div>
                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />
                  {/* Scoring summary */}
                  <div className="p-5">
                    <span className="text-[11px] font-medium uppercase tracking-wider block mb-3" style={{ color: "var(--text-muted)" }}>
                      <ScienceTooltip term="overall-viability">Candidate scores</ScienceTooltip>
                    </span>
                    {candidates.length > 0 && (() => {
                      const c = candidates.find(c => c.id === (activeCandidateId ?? 0)) ?? candidates[0];
                      return (
                        <div className="space-y-2.5">
                          {[
                            { label: "Functional", val: c.scores.functional, color: "var(--accent)", term: "functional-plausibility" },
                            { label: "Tissue", val: c.scores.tissue, color: "var(--base-c)", term: "tissue-specificity" },
                            { label: "Off-target", val: c.scores.offTarget, color: "var(--base-t)", term: "off-target-risk" },
                            { label: "Novelty", val: c.scores.novelty, color: "var(--base-g)", term: "novelty" },
                          ].map(({ label, val, color, term }, i) => (
                            <div key={label} className="flex items-center gap-3">
                              <span className="text-[11px] w-16" style={{ color: "var(--text-muted)" }}>
                                <ScienceTooltip term={term}>{label}</ScienceTooltip>
                              </span>
                              <AnimatedScoreBar value={val} color={color} delay={i * 0.06} />
                              <span className="text-[11px] font-mono w-10 text-right" style={{ color }}>{(val * 100).toFixed(0)}%</span>
                            </div>
                          ))}
                        </div>
                      );
                    })()}
                  </div>
                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />
                  {/* Research tools: off-target, codon opt, variants, export */}
                  <ToolsPanel />
                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />
                  {/* Related work: foundational + run-specific evidence */}
                  <div className="p-5">
                    <span className="text-[11px] font-medium uppercase tracking-wider block mb-3" style={{ color: "var(--accent)" }}>
                      Related work
                    </span>
                    <RelatedWorkPanel compact />
                  </div>
                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />
                  {/* Live 3D structure preview */}
                  <div className="p-5">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                        <ScienceTooltip term="protein-structure">Live Structure</ScienceTooltip>
                      </span>
                      <button onClick={() => setViewMode("structure")} className="text-[10px] font-medium" style={{ color: "var(--accent)" }}>
                        Fullscreen <Maximize2 size={10} className="inline ml-0.5" />
                      </button>
                    </div>
                    <div className="rounded-lg overflow-hidden h-[200px]" style={{ background: "var(--surface-void)" }}>
                      <ProteinViewer pdbData={activePdb || undefined} highlightResidues={highlightResidues}
                        onResidueClick={handleResidueClick} theme={theme} structureModel={structureModel} />
                    </div>
                    {mutationEffect && (
                      <div className="mt-2 text-center">
                        <span className="text-[10px]" style={{ color: "var(--accent)" }}>
                          Structure re-folded after {editHistory.length} edit{editHistory.length !== 1 ? "s" : ""}
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />
                  {/* Edit history */}
                  <div className="p-5">
                    <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                      Edit history ({editHistory.length})
                    </span>
                    {editHistory.length === 0 ? (
                      <p className="text-xs mt-2" style={{ color: "var(--text-faint)" }}>
                        Click a base, select a target, and run <ScienceTooltip term="mutation">simulation</ScienceTooltip> to begin editing.
                      </p>
                    ) : (
                      <div className="mt-2 space-y-1">
                        {editHistory.slice(-8).reverse().map((e, i) => (
                          <motion.div key={i}
                            className="flex items-center gap-2 text-xs font-mono py-1"
                            style={{ color: "var(--text-secondary)" }}
                            initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: i * 0.04 }}>
                            <span style={{ color: "var(--text-faint)" }}>pos {e.position}</span>
                            <span style={{ color: "var(--base-t)" }}>{e.from}</span>
                            <span style={{ color: "var(--text-faint)" }}>&rarr;</span>
                            <span style={{ color: "var(--accent)" }}>{e.to}</span>
                          </motion.div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="h-px mx-5" style={{ background: "var(--ghost-border)" }} />
                  <ExperimentHistory />
                </motion.div>
                {chatOpen && <ChatPanel />}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Helio opens from the header only — no duplicate floating button */}

      {/* Story Mode: judge-facing plain-English glossary (opens from Overview) */}
      <StoryMode />
    </div>
  );
}
