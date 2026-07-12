"use client";

import { useCallback } from "react";
import { analyzeSequence, bootstrapSession } from "@/lib/api";
import { useProteusStore } from "@/lib/store";

export function useSequenceAnalysis() {
  const pipelineStatus = useProteusStore((s) => s.pipelineStatus);
  const error = useProteusStore((s) => s.error);
  const analysisResult = useProteusStore((s) => s.analysisResult);
  const setAnalysisResult = useProteusStore((s) => s.setAnalysisResult);
  const setPipelineStatus = useProteusStore((s) => s.setPipelineStatus);
  const setViewMode = useProteusStore((s) => s.setViewMode);
  const setError = useProteusStore((s) => s.setError);

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
          useProteusStore.getState().setSessionId(boot.session_id);
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
    useProteusStore.getState().reset();
  }, []);

  return {
    result: analysisResult,
    isLoading: pipelineStatus === "analyzing",
    error,
    analyze,
    reset,
  };
}
