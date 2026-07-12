"use client";

import { useCallback, useRef } from "react";
import { submitDesign } from "@/lib/api";
import { useProteusStore } from "@/lib/store";
import { parseSequence } from "@/lib/sequenceUtils";
import type { LikelihoodScore } from "@/types";

/**
 * Hook for the streaming design pipeline.
 *
 * Flow: POST /api/design → open WS → receive events → update store.
 *
 * Events handled:
 *   intent_parsed       → mark stage complete
 *   retrieval_progress   → update per-source status
 *   generation_token     → append base to growing sequence
 *   candidate_scored     → store 4D scores
 *   structure_ready      → set PDB for viewer
 *   explanation_chunk    → accumulate explanation text
 *   pipeline_complete    → finalize candidates, transition to analyze view
 */
export function useDesignPipeline() {
  const wsRef = useRef<WebSocket | null>(null);
  const pipelineCompletedRef = useRef(false);
  const candidateSequenceRef = useRef<Record<number, string>>({});
  const candidateScoresRef = useRef<Record<number, LikelihoodScore[]>>({});

  const setPipelineStatus = useProteusStore((s) => s.setPipelineStatus);
  const setPipelineStage = useProteusStore((s) => s.setPipelineStage);
  const setViewMode = useProteusStore((s) => s.setViewMode);
  const setSessionId = useProteusStore((s) => s.setSessionId);
  const setError = useProteusStore((s) => s.setError);
  const addCompletedStage = useProteusStore((s) => s.addCompletedStage);
  const appendGeneratingToken = useProteusStore((s) => s.appendGeneratingToken);
  const appendExplanation = useProteusStore((s) => s.appendExplanation);
  const updateRetrievalStatus = useProteusStore((s) => s.updateRetrievalStatus);
  const setRetrievalStatuses = useProteusStore((s) => s.setRetrievalStatuses);
  const setActivePdb = useProteusStore((s) => s.setActivePdb);
  const setAnalysisResult = useProteusStore((s) => s.setAnalysisResult);

  const startDesign = useCallback(
    async (goal: string) => {
      // Reset streaming state
      const store = useProteusStore.getState();
      store.reset();

      setPipelineStatus("analyzing");
      setViewMode("pipeline");
      setPipelineStage("intent");
      useProteusStore.getState().setSeedSource(null);
      useProteusStore.getState().setScoringNote(
        "Generation is real Evo 2, and generated candidates carry the model's own confidence (sampled_probs). The 4D scores are composition and motif signals, not clinical assays. ClinVar and PubMed are context cards; they do not rewrite DNA."
      );
      setRetrievalStatuses([
        { source: "ncbi", status: "pending" },
        { source: "pubmed", status: "pending" },
        { source: "clinvar", status: "pending" },
      ]);

      try {
        // Step 1: POST /api/design → get session + WS URL
        pipelineCompletedRef.current = false;
        candidateSequenceRef.current = {};
        candidateScoresRef.current = {};
        const { sessionId, wsUrl } = await submitDesign(goal, {
          numCandidates: 4,
          runProfile: "live",
          truthMode: "real_only",
          seedSequence: useProteusStore.getState().rawSequence || undefined,
          targetLength: 480,
        });
        setSessionId(sessionId);

        // Step 2: Open WebSocket
        useProteusStore.getState().setWsStatus("connecting");
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          useProteusStore.getState().setWsStatus("connected");
        };

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data) as {
              event: string;
              data: Record<string, unknown>;
            };
            handleEvent(msg);
          } catch {
            // Ignore malformed messages
          }
        };

        ws.onerror = () => {
          useProteusStore.getState().setWsStatus("disconnected");
          useProteusStore.getState().setPipelineStatus("error");
          useProteusStore.getState().setViewMode("input");
          setError("WebSocket connection error");
          try {
            ws.close();
          } catch {
            // noop
          }
        };

        ws.onclose = () => {
          const store = useProteusStore.getState();
          if (!pipelineCompletedRef.current && store.pipelineStatus === "analyzing") {
            store.setPipelineStatus("error");
            store.setViewMode("input");
            store.setError("Pipeline stream ended unexpectedly. Please retry.");
          }
          wsRef.current = null;
          useProteusStore.getState().setWsStatus("disconnected");
        };
      } catch {
        setPipelineStatus("error");
        setViewMode("input");
        setError("Could not connect to backend pipeline at http://localhost:8000 (or NEXT_PUBLIC_API_URL).");
      }
    },
    [
      setPipelineStatus,
      setViewMode,
      setPipelineStage,
      setRetrievalStatuses,
      setSessionId,
      setError,
    ]
  );

  // ── Event dispatcher ──
  function handleEvent(msg: { event: string; data: Record<string, unknown> }) {
    const store = useProteusStore.getState();

    switch (msg.event) {
      case "intent_parsed": {
        store.addCompletedStage("intent");
        store.setPipelineStage("retrieval");
        break;
      }

      case "pipeline_manifest": {
        const candidateIds = Array.isArray(msg.data.candidate_ids)
          ? (msg.data.candidate_ids as number[])
          : [0];
        const placeholders = candidateIds.map((id) => ({
          id,
          sequence: "",
          scores: { functional: 0, tissue: 0, offTarget: 0, novelty: 0 },
          overall: 0,
          status: "queued",
          perPositionScores: [],
          error: null,
        }));
        store.setCandidates(placeholders);
        store.setActiveCandidateId(candidateIds[0] ?? 0);
        break;
      }

      case "candidate_seeded":
      case "candidate_seed": {
        const candidateId = Number(msg.data.candidate_id ?? 0);
        const sequence = String(msg.data.sequence ?? "");
        const source = typeof msg.data.source === "string" ? msg.data.source : null;
        if (source) {
          store.setSeedSource(source);
        }
        if (sequence) {
          candidateSequenceRef.current[candidateId] = sequence;
          const existing = store.candidates.find((c) => c.id === candidateId);
          const next = existing
            ? { ...existing, sequence, status: existing.status === "queued" ? "seeded" : existing.status }
            : {
                id: candidateId,
                sequence,
                scores: { functional: 0, tissue: 0, offTarget: 0, novelty: 0 },
                overall: 0,
                status: "seeded",
                perPositionScores: [],
                error: null,
              };
          const remaining = store.candidates.filter((c) => c.id !== candidateId);
          store.setCandidates([...remaining, next].sort((a, b) => b.overall - a.overall));
        }
        break;
      }

      case "stage_status": {
        const stage = String(msg.data.stage ?? "");
        const status = String(msg.data.status ?? "");
        if (status === "active") {
          store.setPipelineStage(stage);
        }
        if (status === "done" || status === "failed") {
          store.addCompletedStage(stage);
        }
        break;
      }

      case "candidate_status": {
        const candidateId = Number(msg.data.candidate_id ?? 0);
        const status = String(msg.data.status ?? "queued");
        const reason = typeof msg.data.reason === "string" ? msg.data.reason : null;
        const existing = store.candidates.find((c) => c.id === candidateId);
        const next = existing
          ? { ...existing, status, error: reason }
          : {
              id: candidateId,
              sequence: candidateSequenceRef.current[candidateId] ?? "",
              scores: { functional: 0, tissue: 0, offTarget: 0, novelty: 0 },
              overall: 0,
              status,
              perPositionScores: [],
              error: reason,
            };
        const remaining = store.candidates.filter((c) => c.id !== candidateId);
        store.setCandidates([...remaining, next].sort((a, b) => b.overall - a.overall));
        break;
      }

      case "retrieval_progress": {
        const source = msg.data.source as string;
        const status = msg.data.status as "pending" | "running" | "complete" | "failed";
        const result =
          msg.data.result && typeof msg.data.result === "object"
            ? (msg.data.result as Record<string, unknown>)
            : null;
        store.updateRetrievalStatus(source, status, result);

        // Check if all retrievals are done
        const statuses = store.retrievalStatuses.map((r) =>
          r.source === source ? { ...r, status, result: result ?? r.result } : r
        );
        const allDone = statuses.every(
          (r) => r.status === "complete" || r.status === "failed"
        );
        if (allDone) {
          store.addCompletedStage("retrieval");
          store.setPipelineStage("generation");
        }
        break;
      }

      case "generation_token": {
        const token = msg.data.token as string;
        const candidateId = Number(msg.data.candidate_id ?? 0);
        const current = candidateSequenceRef.current[candidateId] ?? "";
        candidateSequenceRef.current[candidateId] = `${current}${token}`;

        const existing = store.candidates.find((c) => c.id === candidateId);
        if (existing) {
          const updated = {
            ...existing,
            sequence: candidateSequenceRef.current[candidateId],
            status: existing.status === "queued" ? "running" : existing.status,
          };
          const rest = store.candidates.filter((c) => c.id !== candidateId);
          store.setCandidates([...rest, updated].sort((a, b) => b.overall - a.overall));
        }
        store.appendGeneratingToken(token);
        break;
      }

      case "generation_batch": {
        // Batched tokens for long sequences (>5k bp)
        const tokens = msg.data.tokens as string;
        const candidateId = Number(msg.data.candidate_id ?? 0);
        const current = candidateSequenceRef.current[candidateId] ?? "";
        candidateSequenceRef.current[candidateId] = `${current}${tokens}`;

        const existing = store.candidates.find((c) => c.id === candidateId);
        if (existing) {
          const updated = {
            ...existing,
            sequence: candidateSequenceRef.current[candidateId],
            status: existing.status === "queued" ? "running" : existing.status,
          };
          const rest = store.candidates.filter((c) => c.id !== candidateId);
          store.setCandidates([...rest, updated].sort((a, b) => b.overall - a.overall));
        }
        // Append just the last few tokens for the generating animation
        const displayTokens = tokens.slice(-4);
        for (const t of displayTokens) {
          store.appendGeneratingToken(t);
        }
        break;
      }

      case "generation_progress": {
        // Progress update for long sequence generation
        const progress = Number(msg.data.progress ?? 0);
        const generatedBp = Number(msg.data.generated_bp ?? 0);
        const targetBp = Number(msg.data.target_bp ?? 0);
        // Update stage progress via the stage_status mechanism
        // The pipeline status component already reads stage progress
        store.setPipelineStage("generation");
        break;
      }

      case "candidate_scored": {
        store.addCompletedStage("generation");
        store.addCompletedStage("scoring");
        store.setPipelineStage("structure");

        const scores = msg.data.scores as {
          functional: number;
          tissue_specificity: number;
          off_target: number;
          novelty: number;
          combined?: number;
        };
        const candidateId = (msg.data.candidate_id as number) ?? 0;
        const perPosition = Array.isArray(msg.data.per_position_scores)
          ? (msg.data.per_position_scores as Array<{ position: number; score: number }>)
          : [];
        candidateScoresRef.current[candidateId] = perPosition;
        const generatedSequence = candidateSequenceRef.current[candidateId] ?? "";

        // Update or create candidate with real scores
        const existing = store.candidates.find((c) => c.id === candidateId);
        const nextCandidate = {
          ...(existing ?? {
            id: candidateId,
            sequence: generatedSequence,
            scores: { functional: 0, tissue: 0, offTarget: 0, novelty: 0 },
            overall: 0,
            status: "running",
            perPositionScores: [],
            error: null,
          }),
          sequence: generatedSequence || existing?.sequence || "",
          scores: {
            functional: scores.functional,
            tissue: scores.tissue_specificity,
            offTarget: scores.off_target,
            novelty: scores.novelty,
          },
          overall: (scores.combined ?? 0) * 100,
          status: "scored",
          perPositionScores: perPosition,
          error: null,
        };
        const remaining = store.candidates.filter((c) => c.id !== candidateId);
        const nextCandidates = [...remaining, nextCandidate].sort((a, b) => b.overall - a.overall);
        store.setCandidates(nextCandidates);

        if (store.activeCandidateId === candidateId && perPosition.length > 0) {
          const bases = parseSequence(nextCandidate.sequence, store.regions).map((base, i) => ({
            ...base,
            likelihoodScore: perPosition[i]?.score,
          }));
          useProteusStore.setState({ scores: perPosition, bases, rawSequence: nextCandidate.sequence });
        }
        break;
      }

      case "structure_ready": {
        store.addCompletedStage("structure");
        store.setPipelineStage("explanation");
        const pdbData = msg.data.pdb_data as string;
        const model = typeof msg.data.model === "string" ? msg.data.model : "esmfold";
        if (pdbData) {
          store.setActivePdb(pdbData);
          store.setStructureModel(model);
        }
        break;
      }

      case "explanation_chunk": {
        const text = msg.data.text as string;
        store.appendExplanation(text);
        break;
      }

      case "pipeline_complete": {
        pipelineCompletedRef.current = true;
        store.addCompletedStage("explanation");

        const candidates = msg.data.candidates as Array<{
          id: number;
          sequence: string;
          status?: string;
          error?: string | null;
          scores: {
            functional: number;
            tissue_specificity: number;
            off_target: number;
            novelty: number;
            combined?: number;
          };
          pdb_data?: string;
          provenance?: import("@/lib/regen").CandidateProvenance | null;
        }>;

        if (candidates && candidates.length > 0) {
          const sortedIncoming = [...candidates].sort(
            (a, b) => (b.scores?.combined ?? -1) - (a.scores?.combined ?? -1)
          );
          const primarySeq = sortedIncoming[0].sequence;
          const regions = parseSequenceToRegions(primarySeq);
          const primaryScores =
            candidateScoresRef.current[sortedIncoming[0].id] ?? [];

          // Build AnalysisResult from pipeline data
          const result = {
            rawSequence: primarySeq,
            regions,
            perPositionScores: primaryScores,
            predictedProteins: candidates
              .filter((c) => c.pdb_data)
              .map((c) => ({
                regionStart: 0,
                regionEnd: c.sequence.length,
                pdbData: c.pdb_data,
                sequenceIdentity: undefined,
              })),
          };

          // Build frontend candidates
          const mappedCandidates = candidates.map((c) => ({
            id: c.id,
            sequence: c.sequence,
            scores: {
              functional: c.scores.functional,
              tissue: c.scores.tissue_specificity,
              offTarget: c.scores.off_target,
              novelty: c.scores.novelty,
            },
            overall: (c.scores.combined ?? 0) * 100,
            status: c.status ?? "scored",
            perPositionScores: candidateScoresRef.current[c.id] ?? [],
            error: c.error ?? null,
            provenance: c.provenance ?? null,
          }));
          mappedCandidates.sort((a, b) => b.overall - a.overall);

          store.setCandidates(mappedCandidates);
          store.setActiveCandidateId(mappedCandidates[0]?.id ?? null);

          // This will parse sequence, set bases, regions, scores, and transition to analyze view
          store.setAnalysisResult(result);
        } else {
          // Fallback: use generating sequence
          store.setPipelineStatus("complete");
          store.setViewMode("analyze");
        }

        // Clean up WS
        wsRef.current?.close();
        wsRef.current = null;
        break;
      }
    }
  }

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  return { startDesign, disconnect };
}

// ── Helpers to build analysis data from pipeline output ──

function parseSequenceToRegions(sequence: string) {
  // Simple heuristic: find ORF-like regions (ATG...TAA/TAG/TGA)
  const regions: Array<{
    start: number;
    end: number;
    type: "orf" | "intergenic" | "exon";
    label?: string;
    score?: number;
  }> = [];

  let i = 0;
  while (i < sequence.length - 2) {
    if (sequence.substring(i, i + 3) === "ATG") {
      const start = i;
      let end = i + 3;
      while (end < sequence.length - 2) {
        const codon = sequence.substring(end, end + 3);
        if (codon === "TAA" || codon === "TAG" || codon === "TGA") {
          end += 3;
          break;
        }
        end += 3;
      }
      if (end > start + 9) {
        regions.push({
          start,
          end: Math.min(end, sequence.length),
          type: "orf",
          label: `ORF ${regions.length + 1}`,
          score: -1.5 + Math.random() * 2,
        });
      }
      i = end;
    } else {
      i++;
    }
  }

  // Fill gaps as intergenic
  if (regions.length === 0) {
    regions.push({
      start: 0,
      end: sequence.length,
      type: "intergenic",
      label: "Intergenic",
      score: -2.0 + Math.random(),
    });
  }

  return regions;
}
