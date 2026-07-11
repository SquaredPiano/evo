"use client";

import { useCallback } from "react";
import { analyzeSequence, bootstrapSession } from "@/lib/api";
import { useEvoStore } from "@/lib/store";

export function useSequenceAnalysis() {
  const pipelineStatus = useEvoStore((s) => s.pipelineStatus);
  const error = useEvoStore((s) => s.error);
  const analysisResult = useEvoStore((s) => s.analysisResult);
  const setAnalysisResult = useEvoStore((s) => s.setAnalysisResult);
  const setPipelineStatus = useEvoStore((s) => s.setPipelineStatus);
  const setViewMode = useEvoStore((s) => s.setViewMode);
  const setError = useEvoStore((s) => s.setError);

  const analyze = useCallback(
    async (sequence: string) => {
      setViewMode("pipeline");
      setPipelineStatus("analyzing");

      try {
        const result = await analyzeSequence(sequence);

        setAnalysisResult(result);

        // Bind the analyzed sequence to a backend session so the agent edits the right DNA.
        try {
          const boot = await bootstrapSession(sequence);
          useEvoStore.getState().setSessionId(boot.session_id);
        } catch {
          // Agent can still bootstrap via sequence on first chat message.
        }

        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Analysis failed";
        setError(message);
        return null;
      }
    },
    [setAnalysisResult, setPipelineStatus, setViewMode, setError]
  );

  const reset = useCallback(() => {
    useEvoStore.getState().reset();
  }, []);

  return {
    result: analysisResult,
    isLoading: pipelineStatus === "analyzing",
    error,
    analyze,
    reset,
  };
}
