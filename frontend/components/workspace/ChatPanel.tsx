"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { useProteusStore } from "@/lib/store";
import { X, Send, Sparkles, Check, Loader2, AlertCircle, RefreshCw, PenLine, MapPin } from "lucide-react";
import { buildEvidenceLinks } from "@/lib/evidence";
import { getCandidateDisplay } from "@/lib/candidateDisplay";
import { useDesignPipeline } from "@/hooks/useDesignPipeline";
import { isRegenerationMutation } from "@/lib/regen";
import RegenResultCard, { type RegenResult } from "./RegenResultCard";
import RegionExplanationCard from "./RegionExplanationCard";
import SuggestedActionButton from "./SuggestedActionButton";
import ToolResultCard from "./ToolResultCard";
import {
  isRegionExplanation,
  isSuggestedAction,
  messageForSuggestedAction,
  type RegionExplanation,
  type SuggestedAction,
  type ToolResult,
} from "@/lib/agentTypes";

/** Window (bp) regenerated around a single selected base when no range exists. */
const REGEN_WINDOW = 30;

const SCREEN_PROMPTS: Record<string, string[]> = {
  analyze: [
    "What do these scores mean?",
    "Cite the NCBI / PubMed / ClinVar sources for this run",
    "Rescore the sequence",
  ],
  leaderboard: [
    "Compare candidate #1 and #2",
    "Which candidate is safest?",
    "Optimize for tissue specificity",
  ],
  explorer: [
    "What is this base's annotation?",
    "Mutate position 12 to C",
    "Make this safer by reducing off-target risk",
  ],
  ide: [
    "Mutate position 20 to G",
    "Change all A's to T's",
    "Optimize for functional score",
  ],
  compare: [
    "Why does Candidate A outperform B?",
    "Compare all candidates",
    "Suggest an improvement",
  ],
  structure: [
    "Explain this fold in plain English",
    "Cite the literature used for this design",
    "What does pLDDT tell me here?",
  ],
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL?.trim() || "http://localhost:8000";

/**
 * Detect a request for a FULL redesign (new candidate set), as opposed to a
 * single-region regeneration. Kept conservative so region-level prompts
 * ("regenerate positions 40-80", "raise GC here") still route to the agent's
 * regenerate_region tool. A redesign needs an explicit "new/fresh candidates"
 * or "redesign"/"start over" intent.
 */
function isRedesignRequest(lc: string): boolean {
  if (/\b(redesign|re-design|start over|start from scratch)\b/.test(lc)) return true;
  // "new/fresh/more/different candidates", "candidates that are shorter", etc.
  if (/\b(new|fresh|more|another|different|shorter|longer)\s+(set of\s+)?candidates?\b/.test(lc)) return true;
  if (/\bcandidates?\s+that\s+are\b/.test(lc)) return true;
  if (/\bgenerate\s+(new|fresh|more|another)\b/.test(lc)) return true;
  return false;
}

interface ToolCallEntry {
  tool: string;
  status: string;
  summary: string;
}

interface GuidedPrompt {
  label: string;
  prompt: string;
  why: string;
}

export default function ChatPanel() {
  const chatMessages = useProteusStore((s) => s.chatMessages);
  const addChatMessage = useProteusStore((s) => s.addChatMessage);
  const clearChat = useProteusStore((s) => s.clearChat);
  const toggleChat = useProteusStore((s) => s.toggleChat);
  const rawSequence = useProteusStore((s) => s.rawSequence);
  const { startDesign } = useDesignPipeline();
  const viewMode = useProteusStore((s) => s.viewMode);
  const candidates = useProteusStore((s) => s.candidates);
  const activeCandidateId = useProteusStore((s) => s.activeCandidateId);
  const selectedPosition = useProteusStore((s) => s.selectedPosition);
  const selectedRegion = useProteusStore((s) => s.selectedRegion);
  const editHistoryLength = useProteusStore((s) => s.editHistory.length);
  const chatDraft = useProteusStore((s) => s.chatDraft);
  const setChatDraft = useProteusStore((s) => s.setChatDraft);
  const retrievalStatuses = useProteusStore((s) => s.retrievalStatuses);
  const seedSource = useProteusStore((s) => s.seedSource);
  const scoringNote = useProteusStore((s) => s.scoringNote);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [agentPhase, setAgentPhase] = useState<"idle" | "thinking" | "executing" | "reflecting">("idle");
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCallEntry[]>([]);
  const [reasoningSteps, setReasoningSteps] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Record<string, any>[]>([]);
  const [regenResults, setRegenResults] = useState<RegenResult[]>([]);
  const [regionExplanation, setRegionExplanation] = useState<RegionExplanation | null>(null);
  const [suggestedAction, setSuggestedAction] = useState<SuggestedAction | null>(null);
  const [toolResults, setToolResults] = useState<ToolResult[]>([]);
  const [iterations, setIterations] = useState(0);
  const [streamingText, setStreamingText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const evidenceLinks = useMemo(() => {
    const map = Object.fromEntries(
      retrievalStatuses
        .filter((r) => r.status === "complete" && r.result)
        .map((r) => [r.source, r.result])
    );
    return buildEvidenceLinks(map);
  }, [retrievalStatuses]);

  // Gene symbol from NCBI retrieval - enables ClinVar gene context in region
  // evidence. Same derivation used in analyze/page.tsx; read from the shared
  // store state so ChatPanel can thread `gene` into the agent context.
  const activeGene = useMemo(() => {
    const ncbi = retrievalStatuses.find((r) => r.source === "ncbi")?.result as
      | Record<string, unknown>
      | undefined;
    const sym = ncbi?.symbol ?? ncbi?.gene;
    return typeof sym === "string" && sym && sym !== "Gene" ? sym : null;
  }, [retrievalStatuses]);

  // Human-readable target of an "Explain this region" ask, for the button hint.
  const explainTargetLabel = useMemo(() => {
    if (selectedRegion) return `positions ${selectedRegion.start}–${selectedRegion.end}`;
    if (selectedPosition !== null) return `a ±20 bp window around base ${selectedPosition}`;
    return "the current selection";
  }, [selectedRegion, selectedPosition]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chatMessages.length, isTyping, activeToolCalls.length, agentPhase]);

  useEffect(() => {
    if (!chatDraft) return;
    setInput(chatDraft);
    inputRef.current?.focus();
    setChatDraft(null);
  }, [chatDraft, setChatDraft]);

  const prompts = SCREEN_PROMPTS[viewMode] ?? SCREEN_PROMPTS.analyze;
  const guidedPrompts = useMemo(() => {
    const active =
      candidates.find((c) => c.id === (activeCandidateId ?? -1)) ??
      candidates[0];
    const items: GuidedPrompt[] = [];

    if (active) {
      items.push({
        label: "Explain Like I’m New",
        prompt: "Explain this candidate in plain English for a beginner. What does each score mean? Do not edit or mutate the sequence.",
        why: "Fast orientation for first-time users",
      });
      if (active.scores.offTarget > 0.02) {
        items.push({
          label: "Make It Safer",
          prompt: "Make this safer by reducing off-target risk, apply the best edit, and explain the tradeoff simply.",
          why: "Reduces unwanted effects",
        });
      }
      if (active.scores.tissue < 0.6) {
        items.push({
          label: "Improve Tissue Fit",
          prompt: "Optimize this candidate for tissue specificity and explain what changed.",
          why: "Better targeting for intended tissue",
        });
      }
      if (active.scores.functional < 0.68) {
        items.push({
          label: "Boost Likely-To-Work",
          prompt: "Optimize for functional plausibility and show me the before/after scores.",
          why: "Raises success probability",
        });
      }
    }

    if (selectedPosition !== null) {
      items.push({
        label: "Inspect Selected Base",
        prompt: `Explain what base position ${selectedPosition} might influence and suggest one beneficial mutation.`,
        why: "Connects sequence edits to outcomes",
      });
    }
    if (editHistoryLength > 0) {
      items.push({
        label: "Undo Last Edit",
        prompt: "Undo the last edit and explain how the scores changed.",
        why: "Safe rollback when experimenting",
      });
    }
    if (candidates.length > 1) {
      items.push({
        label: "Compare Top 3",
        prompt: "Compare the top 3 candidates for a layman and recommend one with a simple reason.",
        why: "Decision support without jargon",
      });
    }

    // Ensure stable, compact list.
    const deduped: GuidedPrompt[] = [];
    const seen = new Set<string>();
    for (const item of items) {
      if (seen.has(item.label)) continue;
      seen.add(item.label);
      deduped.push(item);
      if (deduped.length >= 6) break;
    }
    return deduped;
  }, [activeCandidateId, candidates, editHistoryLength, selectedPosition, viewMode]);

  // Guided reprompt / regenerate affordances. These compose the right natural-
  // language message (using the current selection where relevant) and send it;
  // the backend regenerate_region tool / design pipeline does the real work.
  const repromptActions = useMemo(() => {
    const seqLen = rawSequence.length;
    if (seqLen === 0) return [] as Array<{ label: string; hint: string; prompt: string; disabled?: boolean }>;

    const hasSel = selectedPosition !== null;
    const pos = selectedPosition ?? 0;
    const winStart = hasSel ? Math.max(0, pos - REGEN_WINDOW) : 0;
    const winEnd = hasSel ? Math.min(seqLen, pos + REGEN_WINDOW) : seqLen;
    const regionPhrase = `positions ${winStart}-${winEnd}`;
    const windowNote = hasSel ? ` (a ±${REGEN_WINDOW} bp window around base ${pos})` : "";

    return [
      {
        label: "Regenerate selected region",
        hint: hasSel
          ? `Resample ${regionPhrase}${windowNote}`
          : "Select a base first to target a region",
        prompt: `Regenerate ${regionPhrase}${windowNote}.`,
        disabled: !hasSel,
      },
      {
        label: "Raise GC here",
        hint: hasSel ? `Increase GC in ${regionPhrase}` : "Increase GC across the sequence",
        prompt: hasSel
          ? `Raise the GC content in ${regionPhrase}${windowNote}.`
          : "Raise the GC content of this sequence.",
      },
      {
        label: "Avoid a restriction site (EcoRI)",
        hint: hasSel ? `Remove GAATTC from ${regionPhrase}` : "Remove EcoRI (GAATTC) sites",
        prompt: hasSel
          ? `Avoid the EcoRI restriction site (GAATTC) in ${regionPhrase}${windowNote}.`
          : "Avoid the EcoRI restriction site (GAATTC) in this sequence.",
      },
      {
        label: "Regenerate the whole sequence",
        hint: `Resample all ${seqLen} bp`,
        prompt: `Regenerate positions 0-${seqLen} (the whole sequence).`,
      },
      {
        label: "Give me shorter candidates",
        hint: "Fresh design run - shorter variants",
        prompt: "Give me new candidates that are shorter than the current design.",
      },
    ];
  }, [rawSequence, selectedPosition]);

  const streamAssistantText = async (text: string) => {
    setStreamingText("");
    const clean = (text || "").trim();
    if (!clean) return;
    const step = clean.length > 280 ? 6 : clean.length > 140 ? 4 : 2;
    for (let i = 0; i < clean.length; i += step) {
      setStreamingText(clean.slice(0, i + step));
      await new Promise((r) => setTimeout(r, 14));
    }
  };

  /** Apply candidate_update from the backend agent to the store */
  const applyAgentUpdate = async (update: Record<string, any>) => {
    const s = useProteusStore.getState();
    const candidateId = update.candidate_id ?? s.activeCandidateId ?? 0;

    // TRUE REGENERATION: capture the region diff BEFORE the sequence is replaced.
    // `s.rawSequence` here is still the pre-regeneration sequence.
    if (isRegenerationMutation(update.mutation)) {
      const m = update.mutation;
      const oldRegion = (s.rawSequence || "").slice(m.start, m.end);
      setRegenResults((prev) => [...prev, { oldRegion, mutation: m }]);
    }

    if (update.sequence && typeof update.sequence === "string") {
      s.setSequence(update.sequence);
      try {
        const { parseSequence } = await import("@/lib/sequenceUtils");
        const newBases = parseSequence(update.sequence, s.regions).map((b: any, i: number) => ({
          ...b,
          likelihoodScore: update.per_position_scores?.[i]?.score ?? s.scores[i]?.score,
        }));
        useProteusStore.setState({
          bases: newBases,
          scores: Array.isArray(update.per_position_scores)
            ? update.per_position_scores.map((row: any) => ({
                position: Number(row.position ?? 0),
                score: Number(row.score ?? 0),
              }))
            : s.scores,
        });
      } catch { /* parsing optional */ }
    }
    if (update.scores) {
      const scores = update.scores;
      const candidates = [...s.candidates];
      const idx = candidates.findIndex(c => c.id === candidateId);
      const nextCandidate = {
        id: candidateId,
        sequence: update.sequence ?? (idx >= 0 ? candidates[idx].sequence : s.rawSequence),
        scores: {
          functional: Number(scores.functional ?? (idx >= 0 ? candidates[idx].scores.functional : 0)),
          tissue: Number(scores.tissue_specificity ?? (idx >= 0 ? candidates[idx].scores.tissue : 0)),
          offTarget: Number(scores.off_target ?? (idx >= 0 ? candidates[idx].scores.offTarget : 0)),
          novelty: Number(scores.novelty ?? (idx >= 0 ? candidates[idx].scores.novelty : 0)),
        },
        overall: 0,
        status: "scored",
      };
      nextCandidate.overall = (
        nextCandidate.scores.functional * 0.35 +
        nextCandidate.scores.tissue * 0.30 +
        (1 - nextCandidate.scores.offTarget) * 0.20 +
        nextCandidate.scores.novelty * 0.15
      ) * 100;
      if (idx >= 0) {
        candidates[idx] = nextCandidate;
      } else {
        candidates.push(nextCandidate);
      }
      candidates.sort((a, b) => b.overall - a.overall);
      useProteusStore.getState().setCandidates(candidates);
      useProteusStore.getState().setActiveCandidateId(candidateId);
    }
    if (update.pdb_data && typeof update.pdb_data === "string" && update.pdb_data.length > 10) {
      useProteusStore.getState().setActivePdb(update.pdb_data);
    } else if (update.sequence) {
      // Backend didn't return PDB - trigger a refold on the new sequence
      try {
        const { fetchStructure } = await import("@/lib/api");
        const pdb = await fetchStructure(0, update.sequence.length, update.sequence);
        useProteusStore.getState().setActivePdb(pdb);
      } catch { /* structure optional */ }
    }
    if (update.mutation && typeof update.mutation.position === "number") {
      const mut = update.mutation;
      s.addEditEntry({
        position: mut.position,
        from: mut.reference_base ?? "?",
        to: mut.new_base ?? "?",
        delta: mut.delta_likelihood ?? 0,
      });
    }
  };

  // Intentionally start a fresh Helio conversation. The design workspace
  // (sequence, candidates, structure) stays - only the chat thread + its
  // ephemeral regen/comparison cards are cleared.
  const handleNewChat = () => {
    clearChat();
    setRegenResults([]);
    setComparison([]);
    setReasoningSteps([]);
    setActiveToolCalls([]);
    setRegionExplanation(null);
    setSuggestedAction(null);
    setToolResults([]);
    setInput("");
  };

  // Clicking Helio's suggested action fires the follow-up that triggers the
  // underlying tool (regenerate_region / optimize_candidate). We compose a
  // natural-language message the backend already routes and reuse handleSend -
  // the same path used by every other regen/agent action.
  const handleSuggestedAction = (action: SuggestedAction) => {
    if (isTyping) return;
    void handleSend(messageForSuggestedAction(action));
  };

  const handleSend = async (text?: string) => {
    const msg = text ?? input.trim();
    if (!msg || isTyping) return;
    addChatMessage({ role: "user", content: msg });
    setInput("");
    setIsTyping(true);
    setAgentPhase("thinking");
    setActiveToolCalls([]);
    setReasoningSteps([]);
    setComparison([]);
    setRegionExplanation(null);
    setSuggestedAction(null);
    setToolResults([]);
    setIterations(0);

    const s = useProteusStore.getState();
    const lc = msg.toLowerCase();

    // Ensure a backend session exists before any agent/tool work.
    let sessionId = s.sessionId;
    if ((!sessionId || sessionId === "local") && s.rawSequence) {
      try {
        const { bootstrapSession } = await import("@/lib/api");
        const boot = await bootstrapSession(s.rawSequence, {
          sessionId: sessionId ?? undefined,
          candidateId: s.activeCandidateId ?? 0,
        });
        sessionId = boot.session_id;
        useProteusStore.getState().setSessionId(sessionId);
      } catch {
        /* agent endpoint can still bootstrap via sequence body */
      }
    }

    // ── LOCAL ACTIONS: handle these directly, never send to backend agent ──

    // CITE SOURCES: surface retrieval provenance without an LLM round-trip
    if (
      /\b(cite|citation|pubmed|clinvar|ncbi|sources?|evidence|literature)\b/i.test(lc) &&
      !/\b(mutate|edit|optim|rescore|fold)\b/i.test(lc)
    ) {
      if (evidenceLinks.length > 0) {
        const lines = [
          "Here are the live database records tied to this design run:",
          ...evidenceLinks.map((l) => `${l.source.toUpperCase()}: ${l.label}\n${l.url}`),
          seedSource ? `Seed provenance: ${seedSource.replace(/_/g, " ")}` : "",
          "ClinVar/PubMed are context cards - they inform you, they do not rewrite the DNA.",
        ].filter(Boolean);
        addChatMessage({ role: "assistant", content: lines.join("\n\n") });
      } else {
        addChatMessage({
          role: "assistant",
          content:
            "No NCBI / PubMed / ClinVar links are stored for this session yet. Run a design from a gene goal so retrieval can attach real PMIDs and ClinVar IDs - then ask me again.",
        });
      }
      setIsTyping(false);
      setAgentPhase("idle");
      return;
    }

    // RESCORE: just re-analyze, no mutations
    if (/\brescore\b|\bre-score\b|\bre-analyze\b|\bscore.+again\b/i.test(lc)) {
      if (s.rawSequence) {
        setAgentPhase("executing");
        setActiveToolCalls([{ tool: "analyzeSequence", status: "running", summary: "Re-scoring..." }]);
        try {
          const { analyzeSequence } = await import("@/lib/api");
          const result = await analyzeSequence(s.rawSequence);
          useProteusStore.getState().setAnalysisResult(result);
          setActiveToolCalls([{ tool: "analyzeSequence", status: "ok", summary: `Rescored ${result.perPositionScores.length} positions` }]);
          addChatMessage({ role: "assistant", content: `Rescored ${result.perPositionScores.length} positions. ${result.predictedProteins.length} protein(s) predicted. Check the Overview for updated results.` });
        } catch {
          setActiveToolCalls([{ tool: "analyzeSequence", status: "failed", summary: "Backend unavailable" }]);
          addChatMessage({ role: "assistant", content: "Couldn't rescore - backend may be unavailable." });
        }
      } else {
        addChatMessage({ role: "assistant", content: "No sequence loaded. Submit a sequence first." });
      }
      setIsTyping(false);
      setAgentPhase("idle");
      return;
    }

    // REFOLD: just re-predict structure, no mutations
    if (/\brefold\b|\bre-fold\b|\bpredict structure\b|\bfold again\b/i.test(lc)) {
      if (s.rawSequence) {
        setAgentPhase("executing");
        setActiveToolCalls([{ tool: "fetchStructure", status: "running", summary: "Re-folding protein with ESMFold..." }]);
        try {
          const { fetchStructure } = await import("@/lib/api");
          const pdb = await fetchStructure(0, s.rawSequence.length, s.rawSequence);
          useProteusStore.getState().setActivePdb(pdb);
          setActiveToolCalls([{ tool: "fetchStructure", status: "ok", summary: "ESMFold structure ready" }]);
          addChatMessage({ role: "assistant", content: "Structure re-folded with ESMFold. Open the Structure view to inspect it - drag to orbit, scroll to zoom, click a residue only after a short tap (drags won't select)." });
        } catch {
          setActiveToolCalls([{ tool: "fetchStructure", status: "failed", summary: "Prediction failed" }]);
          addChatMessage({ role: "assistant", content: "Structure prediction failed. Confirm STRUCTURE_MODE=esmfold and that the backend can reach api.esmatlas.com." });
        }
      } else {
        addChatMessage({ role: "assistant", content: "No sequence to fold." });
      }
      setIsTyping(false);
      setAgentPhase("idle");
      return;
    }

    // FULL REDESIGN from chat: a request for NEW candidates (optionally
    // constrained - shorter / higher GC / avoid motif) runs the design
    // pipeline. startDesign() resets the workspace but PRESERVES this
    // conversation (see store.reset), so the scientist never loses context.
    if (isRedesignRequest(lc)) {
      addChatMessage({
        role: "assistant",
        content:
          "Launching a fresh design run with your constraints. New candidates will stream into the workspace - I'm keeping this conversation intact.",
      });
      setIsTyping(false);
      setAgentPhase("idle");
      startDesign(msg);
      return;
    }

    // ── BACKEND AGENT: send everything else to the agentic copilot ──
    try {
      setAgentPhase("thinking");
      const historyPayload = useProteusStore
        .getState()
        .chatMessages
        .slice(-64)
        .map((m) => ({ role: m.role, content: m.content }));

      const activeCand =
        candidates.find((c) => c.id === (s.activeCandidateId ?? -1)) ?? candidates[0];

      if (!s.rawSequence && !sessionId) {
        addChatMessage({
          role: "assistant",
          content: "Load or design a sequence first - I need DNA in the workspace before I can edit, score, or explain.",
        });
        setIsTyping(false);
        setAgentPhase("idle");
        return;
      }

      const res = await fetch(`${API_BASE}/api/agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId ?? s.sessionId ?? "local",
          candidate_id: s.activeCandidateId ?? 0,
          message: msg,
          history: historyPayload,
          sequence: s.rawSequence || undefined,
          context: {
            view_mode: s.viewMode,
            selected_position: s.selectedPosition ?? undefined,
            // Region-aware ask: an explicit half-open range when one is
            // selected; otherwise the backend derives a ±20bp window from
            // selected_position. `gene` enables ClinVar gene context.
            selected_region: s.selectedRegion ?? undefined,
            gene: activeGene ?? undefined,
            scores: activeCand
              ? {
                  functional: activeCand.scores.functional,
                  tissue_specificity: activeCand.scores.tissue,
                  off_target: activeCand.scores.offTarget,
                  novelty: activeCand.scores.novelty,
                  combined: activeCand.overall / 100,
                }
              : undefined,
            evidence_links: evidenceLinks.map((l) => ({
              source: l.source,
              label: l.label,
              url: l.url,
              ...(l.detail ? { detail: l.detail } : {}),
            })),
            seed_source: seedSource ?? undefined,
            scoring_note: scoringNote ?? undefined,
          },
        }),
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`Agent request failed (${res.status}): ${errText || "unknown error"}`);
      }

      const data = await res.json();
      if (data.tool_calls && Array.isArray(data.tool_calls)) {
        setAgentPhase("executing");
        // Progressive tool trail so the wait feels alive (API is still one JSON response).
        setActiveToolCalls([]);
        for (const tc of data.tool_calls as ToolCallEntry[]) {
          setActiveToolCalls((prev) => [
            ...prev,
            { tool: tc.tool, status: "running", summary: "Running…" },
          ]);
          await new Promise((r) => setTimeout(r, 120));
          setActiveToolCalls((prev) =>
            prev.map((row) =>
              row.tool === tc.tool && row.status === "running"
                ? { tool: tc.tool, status: tc.status, summary: tc.summary }
                : row
            )
          );
        }
      }

      if (data.reasoning_steps && Array.isArray(data.reasoning_steps)) {
        setReasoningSteps(data.reasoning_steps);
      }
      if (typeof data.iterations === "number") {
        setIterations(data.iterations);
      }

      if (data.candidate_update) {
        setAgentPhase("reflecting");
        useProteusStore.getState().saveVersion();
        await applyAgentUpdate(data.candidate_update);
      }

      if (data.comparison && Array.isArray(data.comparison) && data.comparison.length > 0) {
        setComparison(data.comparison);
        setActiveToolCalls((prev) => [
          ...prev,
          { tool: "compare", status: "ok", summary: `Ranked ${data.comparison.length} candidates` },
        ]);
      }

      // Region-aware payloads (all nullable - guard every field).
      if (isRegionExplanation(data.region_explanation)) {
        setRegionExplanation(data.region_explanation);
      }
      if (isSuggestedAction(data.suggested_action)) {
        setSuggestedAction(data.suggested_action);
      }
      if (Array.isArray(data.tool_results) && data.tool_results.length > 0) {
        setToolResults(
          data.tool_results.filter(
            (t: unknown): t is ToolResult =>
              Boolean(t) && typeof (t as { tool?: unknown }).tool === "string",
          ),
        );
      }

      const assistantText = data.assistant_message ?? "I couldn't process that.";
      // Stream the reply into the transcript so it doesn't appear as a cold dump.
      setStreamingText("");
      const chunk = 12;
      for (let i = 0; i < assistantText.length; i += chunk) {
        setStreamingText(assistantText.slice(0, i + chunk));
        await new Promise((r) => setTimeout(r, 16));
      }
      setStreamingText("");
      addChatMessage({ role: "assistant", content: assistantText });
    } catch (err) {
      addChatMessage({
        role: "assistant",
        content:
          err instanceof Error
            ? `Agent backend error: ${err.message}`
            : "Agent backend error: request failed.",
      });
      setStreamingText("");
    } finally {
      setIsTyping(false);
      setAgentPhase("idle");
    }
  };

  // Helio edits the active candidate - say which one, honestly.
  const helioDisplay = getCandidateDisplay(candidates, activeCandidateId);
  const helioSubtitle = helioDisplay.hasCandidate ? helioDisplay.label : "Agent · tools · explain";
  const helioSubtitleTitle = helioDisplay.hasCandidate ? helioDisplay.subtitle : "Agent · tools · explain";

  return (
    <div className="w-full sm:w-[380px] shrink-0 flex flex-col h-full"
      style={{ background: "var(--surface-raised)", borderLeft: "1px solid var(--ghost-border)" }}
      role="complementary"
      aria-label="Proteus copilot">

      {/* Header */}
      <div className="flex items-center justify-between px-5 h-16 shrink-0"
        style={{ borderBottom: "1px solid var(--ghost-border)" }}>
        <div className="flex items-center gap-2.5">
          <span className="inline-flex items-center justify-center w-8 h-8 rounded-2xl" style={{ background: "var(--honey-500)", color: "var(--ink)", boxShadow: "0 6px 16px -4px rgba(245,158,11,0.4)" }}>
            <Sparkles size={14} aria-hidden="true" />
          </span>
          <div className="leading-tight">
            <span className="text-sm font-bold block" style={{ color: "var(--text-primary)" }}>Helio</span>
            <span className="label-caps" style={{ fontSize: "8px" }} title={helioSubtitleTitle}>
              {helioSubtitle}
            </span>
          </div>
          {iterations > 1 && (
            <span className="chip-honey" style={{ fontSize: "9px" }}>
              {iterations} iters
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleNewChat}
            disabled={isTyping || (chatMessages.length === 0 && regenResults.length === 0)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium transition-colors hover:bg-white/[0.04] disabled:opacity-40"
            style={{ color: "var(--text-muted)", border: "1px solid var(--ghost-border)" }}
            title="Start a fresh Helio conversation (keeps your design in the workspace)"
            aria-label="Start a new chat"
          >
            <PenLine size={11} aria-hidden="true" /> New Chat
          </button>
          <button onClick={toggleChat} className="p-1.5 rounded-full transition-colors" style={{ color: "var(--text-muted)" }} aria-label="Close chat panel">
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-5 space-y-5" aria-live="polite" aria-label="Chat messages">
        {chatMessages.length === 0 && (
          <div>
            <p className="text-[13px] mb-4 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              I can transform sequences, mutate bases, optimize scores, compare candidates, and explain any metric. Everything runs through the agentic pipeline.
            </p>
            <div className="space-y-1.5">
              {prompts.map((q) => (
                <button key={q} onClick={() => handleSend(q)}
                  className="block w-full text-left text-[12px] px-3 py-2.5 rounded-full transition-colors hover:bg-white/[0.04]"
                  style={{ color: "var(--text-secondary)", lineHeight: 1.4 }}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {/* Region-aware STAR affordance: explain the selected region in plain
            English. Uses selected_region (explicit range) or selected_position
            (backend derives a ±20bp window). */}
        {rawSequence.length > 0 && (
          <button
            onClick={() =>
              handleSend(
                "Explain the selected region in plain English - what it does, why it matters, and how confident the model is."
              )
            }
            disabled={isTyping}
            className="w-full text-left rounded-2xl px-3.5 py-2.5 transition-all hover:brightness-105 disabled:opacity-50"
            style={{
              background: "color-mix(in oklch, var(--accent), transparent 90%)",
              border: "1px solid color-mix(in oklch, var(--accent), transparent 62%)",
            }}
          >
            <div className="flex items-center gap-2">
              <MapPin size={14} style={{ color: "var(--accent)" }} />
              <span className="text-[12.5px] font-semibold" style={{ color: "var(--text-primary)" }}>
                Explain this region
              </span>
            </div>
            <div className="text-[10.5px] mt-1 leading-snug" style={{ color: "var(--text-secondary)" }}>
              What it does &amp; why it matters - for {explainTargetLabel}.
            </div>
          </button>
        )}
        {guidedPrompts.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--text-faint)" }}>
              Guided Experiments
            </div>
            {guidedPrompts.map((item) => (
              <button
                key={item.label}
                onClick={() => handleSend(item.prompt)}
                disabled={isTyping}
                className="w-full text-left px-3 py-2 rounded-full transition-colors hover:bg-white/[0.04] disabled:opacity-50"
                style={{ background: "var(--surface-base)" }}
              >
                <div className="text-[12px] font-medium" style={{ color: "var(--text-primary)" }}>{item.label}</div>
                <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>{item.why}</div>
              </button>
            ))}
          </div>
        )}
        {repromptActions.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-medium uppercase tracking-wider flex items-center gap-1.5" style={{ color: "var(--text-faint)" }}>
              <RefreshCw size={10} /> Reprompt &amp; Regenerate
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {repromptActions.map((item) => (
                <button
                  key={item.label}
                  onClick={() => handleSend(item.prompt)}
                  disabled={isTyping || item.disabled}
                  title={item.hint}
                  className="text-left px-2.5 py-2 rounded-xl transition-colors hover:bg-white/[0.04] disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{ background: "var(--surface-base)", border: "1px solid var(--ghost-border)" }}
                >
                  <div className="text-[11px] font-medium leading-tight" style={{ color: "var(--text-primary)" }}>{item.label}</div>
                  <div className="text-[9px] mt-0.5 leading-tight" style={{ color: "var(--text-muted)" }}>{item.hint}</div>
                </button>
              ))}
            </div>
          </div>
        )}
        {chatMessages.map((msg, i) => (
          <div key={i} className={msg.role === "user" ? "flex flex-col items-end" : "flex flex-col items-start"}>
            <div className="label-caps mb-1" style={{ fontSize: "9px", color: msg.role === "user" ? "var(--text-faint)" : "var(--accent-bright)" }}>
              {msg.role === "user" ? "You" : "Helio"}
            </div>
            <div className="text-[13px] leading-relaxed px-3.5 py-2.5 max-w-[92%]"
              style={
                msg.role === "user"
                  ? { color: "var(--ink)", background: "var(--honey-200)", borderRadius: "14px 14px 4px 14px" }
                  : { color: "var(--text-primary)", background: "var(--surface-elevated)", borderRadius: "14px 14px 14px 4px", borderLeft: "2px solid var(--accent)" }
              }>
              {msg.role === "assistant" ? <ChatMessageBody text={msg.content} /> : msg.content}
            </div>
          </div>
        ))}

        {/* Regeneration result cards (region regenerated via regenerate_region) */}
        {regenResults.length > 0 && (
          <div className="space-y-2">
            <div className="label-caps" style={{ fontSize: "9px" }}>Regeneration Results</div>
            {regenResults.slice(-4).map((r, i) => (
              <RegenResultCard key={`regen-${i}-${r.mutation.start}-${r.mutation.end}`} result={r} />
            ))}
          </div>
        )}

        {/* Region explanation - the STAR card for a non-biologist */}
        {regionExplanation && (
          <RegionExplanationCard explanation={regionExplanation} />
        )}

        {/* Helio's proactive one-click follow-up */}
        {suggestedAction && (
          <SuggestedActionButton
            action={suggestedAction}
            onClick={() => handleSuggestedAction(suggestedAction)}
            disabled={isTyping}
          />
        )}

        {/* Read-only tool result cards (off-target scan, restriction sites) */}
        {toolResults.length > 0 && (
          <div className="space-y-2">
            {toolResults.map((tr, i) => (
              <ToolResultCard key={`tool-${i}-${tr.tool}`} result={tr} />
            ))}
          </div>
        )}

        {/* Comparison table */}
        {comparison.length > 0 && (
          <div className="space-y-1.5">
            <div className="label-caps" style={{ fontSize: "9px" }}>Candidate Ranking</div>
            <div className="overflow-hidden rounded-2xl" style={{ border: "1px solid var(--ghost-border)" }}>
              {comparison.slice(0, 6).map((row, i) => {
                const combined = Number(row.combined ?? row.scores?.combined ?? row.overall ?? 0);
                const cid = row.candidate_id ?? row.id ?? i;
                return (
                  <div key={`cmp-${i}`} className="flex items-center justify-between px-3 py-2 text-[11px]"
                    style={{ background: i === 0 ? "rgba(245,158,11,0.12)" : "var(--surface-base)", borderTop: i > 0 ? "1px solid var(--ghost-border)" : "none" }}>
                    <span className="font-mono font-bold" style={{ color: "var(--text-primary)" }}>
                      {i === 0 ? "★ " : `${i + 1}. `}#{cid}
                    </span>
                    <span className="font-mono" style={{ color: combined >= 0.6 ? "var(--base-a)" : combined >= 0.4 ? "var(--base-g)" : "var(--base-t)" }}>
                      {combined.toFixed(3)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Agent thinking/executing indicator */}
        {isTyping && (
          <div>
            <div className="text-[10px] font-medium uppercase tracking-wider mb-1" style={{ color: "var(--accent)" }}>Helio</div>
            {agentPhase === "thinking" && (
              <div className="flex items-center gap-2 py-1.5 px-3 rounded-full text-[12px]"
                style={{ background: "rgba(var(--accent-rgb, 9,212,156), 0.08)", border: "1px solid rgba(var(--accent-rgb, 9,212,156), 0.2)", color: "var(--accent)" }}>
                <div className="flex gap-1">
                  {[0, 1, 2].map(i => (
                    <div key={i} className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "var(--accent)", animationDelay: `${i * 0.2}s` }} />
                  ))}
                </div>
                <span>Planning actions...</span>
              </div>
            )}
            {agentPhase === "executing" && (
              <div className="flex items-center gap-2 py-1.5 px-3 rounded-full text-[12px]"
                style={{ background: "rgba(246,193,77, 0.08)", border: "1px solid rgba(246,193,77, 0.2)", color: "#ffd990" }}>
                <Loader2 size={12} className="animate-spin" />
                <span>Executing tools...</span>
              </div>
            )}
            {agentPhase === "reflecting" && (
              <div className="flex items-center gap-2 py-1.5 px-3 rounded-full text-[12px]"
                style={{ background: "rgba(114,182,255, 0.08)", border: "1px solid rgba(114,182,255, 0.2)", color: "#72b6ff" }}>
                <Sparkles size={12} />
                <span>Reflecting on results...</span>
              </div>
            )}
            {streamingText && (
              <div
                className="mt-2 text-[13px] leading-relaxed px-3 py-2 rounded-full"
                style={{ background: "var(--surface-base)", color: "var(--text-primary)" }}
              >
                {streamingText}
                <span className="ml-1 inline-block w-2 h-4 align-middle animate-pulse" style={{ background: "var(--accent)" }} />
              </div>
            )}
          </div>
        )}

        {/* Tool call trail */}
        {activeToolCalls.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-medium uppercase tracking-wider"
              style={{ color: "var(--text-faint)" }}>
              Tool Execution
            </div>
            {activeToolCalls.map((tc, i) => (
              <div key={`tc-${i}`}
                className="flex items-start gap-2 px-3 py-2 rounded-full text-[11px] transition-all"
                style={{
                  background: "var(--surface-base)",
                  border: `1px solid ${tc.status === "ok" ? "rgba(var(--accent-rgb, 9,212,156), 0.3)" : tc.status === "failed" ? "rgba(255,90,111, 0.3)" : "rgba(246,193,77, 0.3)"}`,
                  animation: "fadeSlideIn 0.3s ease-out",
                }}>
                <div className="mt-0.5 shrink-0">
                  {tc.status === "ok" ? (
                    <Check size={12} style={{ color: "var(--accent)" }} />
                  ) : tc.status === "failed" ? (
                    <AlertCircle size={12} style={{ color: "#ff5a6f" }} />
                  ) : (
                    <Loader2 size={12} className="animate-spin" style={{ color: "#f6c14d" }} />
                  )}
                </div>
                <div>
                  <div className="font-medium" style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono, monospace)", fontSize: "11px" }}>
                    {tc.tool}
                  </div>
                  <div style={{ color: "var(--text-muted)" }}>{tc.summary}</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Reasoning steps */}
        {reasoningSteps.length > 0 && (
          <div className="space-y-1">
            <div className="text-[10px] font-medium uppercase tracking-wider"
              style={{ color: "var(--text-faint)" }}>
              Agent Reasoning
            </div>
            {reasoningSteps.slice(-4).map((step, i) => (
              <div key={`rs-${i}`} className="text-[11px] px-3 py-1.5 rounded"
                style={{ color: "var(--text-muted)", background: "var(--surface-base)" }}>
                {step}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-4 py-3 shrink-0" style={{ borderTop: "1px solid var(--ghost-border)" }}>
        <div className="flex gap-2 items-center rounded-2xl px-3 py-2.5 border"
          style={{ background: "rgba(255,255,255,0.7)", borderColor: "var(--ghost-border)", boxShadow: "var(--shadow-soft)" }}>
          <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Ask Helio to edit, optimize, or explain..."
            aria-label="Message Helio"
            className="flex-1 text-[13px] outline-none bg-transparent"
            style={{ color: "var(--text-primary)" }}
            disabled={isTyping} />
          <button onClick={() => handleSend()} disabled={!input.trim() || isTyping}
            aria-label="Send message"
            className="p-1.5 rounded transition-colors hover:bg-white/5 disabled:opacity-30"
            style={{ color: input.trim() ? "var(--accent)" : "var(--text-faint)" }}>
            <Send size={14} aria-hidden="true" />
          </button>
        </div>
      </div>

      <style jsx>{`
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateX(-6px); }
          to { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}

const URL_RE = /(https?:\/\/[^\s]+)/g;

function ChatMessageBody({ text }: { text: string }) {
  const blocks = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  return (
    <div className="space-y-2">
      {blocks.map((line, i) => {
        const parts = line.split(URL_RE);
        return (
          <p key={i} className="m-0">
            {parts.map((part, j) =>
              /^https?:\/\//.test(part) ? (
                <a
                  key={j}
                  href={part.replace(/[.,;:)]+$/, "")}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline break-all"
                  style={{ color: "var(--honey-700)" }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {part.replace(/[.,;:)]+$/, "")}
                </a>
              ) : (
                <span key={j}>{part}</span>
              )
            )}
          </p>
        );
      })}
    </div>
  );
}
