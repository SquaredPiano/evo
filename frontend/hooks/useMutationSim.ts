"use client";

import { useCallback } from "react";
import { editBase, fetchStructure, predictMutation } from "@/lib/api";
import { useEvoStore } from "@/lib/store";
import { parseSequence } from "@/lib/sequenceUtils";

export function useMutationSim() {
  const mutationEffect = useEvoStore((s) => s.mutationEffect);
  const mutationLoading = useEvoStore((s) => s.mutationLoading);
  const setMutationEffect = useEvoStore((s) => s.setMutationEffect);
  const setMutationLoading = useEvoStore((s) => s.setMutationLoading);

  const simulate = useCallback(
    async (sequence: string, position: number, alternateBase: string) => {
      setMutationLoading(true);
      setMutationEffect(null);

      try {
        const store = useEvoStore.getState();
        store.saveVersion();

        let effect;
        // Whether a background protein refold is worth running, and any
        // per-position score patch the backend sent back for the heatmap.
        let refold = true;
        let perPositionPatch: { position: number; score: number }[] | null = null;
        if (store.sessionId && store.activeCandidateId !== null) {
          const response = await editBase(store.sessionId, store.activeCandidateId, position, alternateBase);
          effect = {
            position: response.position,
            referenceBase: response.reference_base,
            alternateBase: response.new_base,
            deltaLikelihood: response.delta_likelihood,
            predictedImpact: response.predicted_impact,
          };
          // Default to refolding unless the backend says the coding region is unchanged.
          refold = response.refold_recommended !== false;
          perPositionPatch = response.per_position_scores ?? null;
          const candidates = [...store.candidates];
          const idx = candidates.findIndex((c) => c.id === store.activeCandidateId);
          if (idx >= 0) {
            const functional = Number(response.updated_scores.functional ?? candidates[idx].scores.functional);
            const tissue = Number(response.updated_scores.tissue_specificity ?? candidates[idx].scores.tissue);
            const offTarget = Number(response.updated_scores.off_target ?? candidates[idx].scores.offTarget);
            const novelty = Number(response.updated_scores.novelty ?? candidates[idx].scores.novelty);
            candidates[idx] = {
              ...candidates[idx],
              scores: { functional, tissue, offTarget, novelty },
              overall:
                (functional * 0.35 + tissue * 0.3 + (1 - offTarget) * 0.2 + novelty * 0.15) *
                100,
              sequence:
                sequence.slice(0, position) + alternateBase + sequence.slice(position + 1),
            };
            candidates.sort((a, b) => b.overall - a.overall);
            store.setCandidates(candidates);
          }
        } else {
          effect = await predictMutation(sequence, position, alternateBase);
        }

        setMutationEffect(effect);

        // Apply the mutation to the sequence, patching in the per-position score
        // window from the backend so the heatmap (LikelihoodGraph / SequenceEditor)
        // updates immediately instead of showing stale colors.
        const mutated = sequence.slice(0, position) + alternateBase + sequence.slice(position + 1);
        const latest = useEvoStore.getState();
        let nextScores = latest.scores;
        if (perPositionPatch && perPositionPatch.length) {
          nextScores = [...latest.scores];
          for (const p of perPositionPatch) {
            if (p.position >= 0 && p.position < nextScores.length) {
              nextScores[p.position] = { position: p.position, score: p.score };
            }
          }
        }
        const newBases = parseSequence(mutated, latest.regions).map((base, i) => ({
          ...base,
          likelihoodScore: nextScores[i]?.score,
        }));
        store.setSequence(mutated);
        useEvoStore.setState({ bases: newBases, scores: nextScores });

        // Scores are in - release the blocking spinner NOW. A single-base edit
        // should feel instant instead of waiting ~10-90s on protein folding.
        setMutationLoading(false);

        // Re-fold the protein structure in the BACKGROUND. Keep the previous PDB
        // visible meanwhile; only swap it in once the new fold lands.
        if (refold) {
          void (async () => {
            useEvoStore.getState().setStructureRefolding(true);
            try {
              const pdb = await fetchStructure(0, mutated.length, mutated);
              useEvoStore.getState().setActivePdb(pdb);
            } catch {
              // Structure prediction may fail - keep old PDB
            } finally {
              useEvoStore.getState().setStructureRefolding(false);
            }
          })();
        }
      } catch {
        // Mutation prediction failed
        setMutationLoading(false);
      }
    },
    [setMutationEffect, setMutationLoading]
  );

  const reset = useCallback(() => {
    setMutationEffect(null);
    setMutationLoading(false);
  }, [setMutationEffect, setMutationLoading]);

  return { effect: mutationEffect, isLoading: mutationLoading, simulate, reset };
}
