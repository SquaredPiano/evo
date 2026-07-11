"use client";

import { motion } from "framer-motion";
import { useEvoStore } from "@/lib/store";
import { Check, Loader2, AlertCircle } from "lucide-react";

const STAGES = [
  { id: "intent", label: "Understanding your goal" },
  { id: "retrieval", label: "Gathering context" },
  { id: "generation", label: "Writing DNA candidates" },
  { id: "scoring", label: "Scoring quality" },
  { id: "structure", label: "Folding structure" },
  { id: "explanation", label: "Explaining results" },
];

export default function PipelineStatus() {
  const pipelineStatus = useEvoStore((s) => s.pipelineStatus);
  const completedStages = useEvoStore((s) => s.completedStages);
  const pipelineStage = useEvoStore((s) => s.pipelineStage);
  const sessionId = useEvoStore((s) => s.sessionId);
  const generationTokenCount = useEvoStore((s) => s.generationTokenCount);
  const generatingSequence = useEvoStore((s) => s.generatingSequence);
  const candidates = useEvoStore((s) => s.candidates);
  const error = useEvoStore((s) => s.error);

  if (pipelineStatus !== "analyzing") return null;

  const isStreaming = sessionId !== null;
  const allDone = completedStages.length >= STAGES.length;
  const progress = allDone ? 100 : (completedStages.length / STAGES.length) * 100;
  const activeStageIdx = STAGES.findIndex((s) => s.id === pipelineStage);
  const failedCount = candidates.filter((c) => c.status === "failed").length;
  const readyCount = candidates.filter((c) =>
    ["scored", "structured", "complete"].includes(c.status)
  ).length;

  return (
    <div
      className="flex-1 flex items-center justify-center px-6 py-10"
      style={{ background: "var(--surface-base)" }}
      role="status"
      aria-live="polite"
      aria-label="Pipeline progress"
    >
      <div className="max-w-md w-full">
        <h2 className="text-2xl font-serif italic tracking-tight mb-2" style={{ color: "var(--ink)" }}>
          {isStreaming ? "Designing…" : "Analyzing…"}
        </h2>
        <p className="text-[14px] mb-8 leading-relaxed" style={{ color: "var(--text-muted)" }}>
          {isStreaming
            ? "Evo 2 is generating a few candidates, then scoring and folding them."
            : "Scoring your sequence and preparing structure."}
        </p>

        <div
          className="h-1.5 rounded-full mb-8 overflow-hidden"
          style={{ background: "var(--wax)" }}
          role="progressbar"
          aria-valuenow={Math.round(progress)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <motion.div
            className="h-full rounded-full"
            style={{ background: "var(--honey-500)" }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.35 }}
          />
        </div>

        <div className="space-y-0.5 mb-8">
          {STAGES.map((stage, i) => {
            const isComplete = completedStages.includes(stage.id);
            const isActive = i === activeStageIdx && !isComplete;
            return (
              <div
                key={stage.id}
                className="flex items-center gap-3 py-2 px-2 rounded-full"
                style={{
                  background: isActive ? "rgba(245,158,11,0.08)" : "transparent",
                }}
              >
                <div className="w-5 h-5 flex items-center justify-center">
                  {isComplete ? (
                    <Check size={14} style={{ color: "var(--honey-600)" }} />
                  ) : isActive ? (
                    <Loader2 size={14} className="animate-spin" style={{ color: "var(--honey-600)" }} />
                  ) : (
                    <div className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--wax-deep)" }} />
                  )}
                </div>
                <span
                  className="text-[13px] flex-1 font-medium"
                  style={{
                    color: isComplete || isActive ? "var(--ink)" : "var(--text-faint)",
                  }}
                >
                  {stage.label}
                </span>
                {isActive && stage.id === "generation" && generationTokenCount > 0 && (
                  <span className="text-[11px] font-medium" style={{ color: "var(--honey-600)" }}>
                    {generationTokenCount} bases
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {isStreaming && generatingSequence.length > 0 && (
          <div className="mb-6 px-1">
            <p className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-faint)" }}>
              Live DNA
            </p>
            <p
              className="font-mono text-[11px] leading-relaxed break-all max-h-16 overflow-hidden"
              style={{ color: "var(--text-secondary)" }}
            >
              {generatingSequence.slice(-200)}
            </p>
          </div>
        )}

        {isStreaming && candidates.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {candidates.slice(0, 6).map((c) => (
              <span
                key={c.id}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-medium"
                style={{
                  background:
                    c.status === "failed"
                      ? "rgba(220,38,38,0.08)"
                      : ["scored", "structured"].includes(c.status)
                        ? "rgba(22,163,74,0.1)"
                        : "var(--wax)",
                  color:
                    c.status === "failed"
                      ? "#DC2626"
                      : ["scored", "structured"].includes(c.status)
                        ? "#16A34A"
                        : "var(--text-muted)",
                }}
              >
                #{c.id}
                {c.status === "failed" ? " failed" : c.sequence?.length ? ` · ${c.sequence.length} bp` : ` · ${c.status}`}
              </span>
            ))}
          </div>
        )}

        {failedCount > 0 && readyCount === 0 && (
          <div
            className="flex items-start gap-2.5 px-4 py-3 rounded-2xl text-[13px]"
            style={{ background: "rgba(220,38,38,0.06)", color: "#B91C1C" }}
          >
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span>
              Generation hit an error before candidates finished. Try again — shorter designs usually succeed on the first pass.
              {candidates.find((c) => c.error)?.error ? ` (${candidates.find((c) => c.error)?.error})` : ""}
            </span>
          </div>
        )}

        {error && (
          <div className="mt-3 text-[13px]" style={{ color: "#B91C1C" }}>
            {error}
          </div>
        )}

        {allDone && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-6 flex items-center gap-3 px-4 py-3 rounded-full"
            style={{ background: "rgba(245,158,11,0.12)" }}
          >
            <Check size={16} style={{ color: "var(--honey-700)" }} />
            <span className="text-[13px] font-medium" style={{ color: "var(--honey-700)" }}>
              Done — opening results
            </span>
            <Loader2 size={14} className="animate-spin ml-auto" style={{ color: "var(--honey-600)" }} />
          </motion.div>
        )}
      </div>
    </div>
  );
}
