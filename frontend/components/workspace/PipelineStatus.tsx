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
  const seedSource = useEvoStore((s) => s.seedSource);
  const retrievalStatuses = useEvoStore((s) => s.retrievalStatuses);
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
            ? generationTokenCount === 0 && pipelineStage === "generation"
              ? "Calling Evo 2… bases will stream here as soon as NIM responds."
              : "Evo 2 is streaming DNA. NCBI seeds identity when available; scores stay labeled as heuristics under NIM."
            : "Scoring your sequence and preparing structure."}
        </p>

        {(seedSource || retrievalStatuses.some((r) => r.status !== "pending")) && (
          <div className="flex flex-wrap gap-2 mb-6">
            {seedSource && (
              <span
                className="inline-flex px-3 py-1 rounded-full text-[11px] font-medium"
                style={{ background: "var(--wax)", color: "var(--ink)" }}
              >
                Seed: {seedSource.replace(/_/g, " ")}
              </span>
            )}
            {retrievalStatuses.map((r) => (
              <span
                key={r.source}
                className="inline-flex px-3 py-1 rounded-full text-[11px] font-medium"
                style={{
                  background: r.status === "complete" ? "rgba(22,163,74,0.1)" : r.status === "failed" ? "rgba(220,38,38,0.08)" : "var(--wax)",
                  color: r.status === "complete" ? "#16A34A" : r.status === "failed" ? "#B91C1C" : "var(--text-muted)",
                }}
              >
                {r.source.toUpperCase()} · {r.status}
                {r.source === "clinvar" && r.status === "complete" ? " (context)" : ""}
              </span>
            ))}
          </div>
        )}

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
                    <Loader2 size={14} className="animate-spin spinner-keep" style={{ color: "var(--honey-600)" }} />
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

        {isStreaming && (generatingSequence.length > 0 || (pipelineStage === "generation" && generationTokenCount === 0)) && (
          <div className="mb-6 px-1">
            <p className="text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-faint)" }}>
              {generationTokenCount === 0 ? "Evo 2 · waiting" : "Evo 2 · live DNA"}
            </p>
            <p
              className="font-mono text-[12px] leading-relaxed break-all max-h-28 overflow-y-auto rounded-2xl px-3 py-3"
              style={{ color: "var(--text-secondary)", background: "var(--wax)" }}
            >
              {generationTokenCount === 0
                ? "········ awaiting first base ········"
                : generatingSequence.slice(-320)}
              {pipelineStage === "generation" && (
                <span className="inline-block w-2 h-3 ml-0.5 align-middle animate-pulse" style={{ background: "var(--honey-600)" }} />
              )}
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
            <Loader2 size={14} className="animate-spin spinner-keep ml-auto" style={{ color: "var(--honey-600)" }} />
          </motion.div>
        )}
      </div>
    </div>
  );
}
