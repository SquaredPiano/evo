"use client";

import { useEvoStore } from "@/lib/store";
import { ChevronRight, ArrowRight, GitCompare } from "lucide-react";
import { motion } from "framer-motion";
import { ScienceTooltip } from "@/components/ui/ScienceTooltip";
import ProvenanceBadge from "@/components/workspace/ProvenanceBadge";

function strengthLabel(value: number): "Strong" | "Promising" | "Weak" {
  if (value >= 0.75) return "Strong";
  if (value >= 0.55) return "Promising";
  return "Weak";
}

function safetyLabel(offTarget: number): "Strong" | "Moderate" | "Risky" {
  if (offTarget <= 0.03) return "Strong";
  if (offTarget <= 0.08) return "Moderate";
  return "Risky";
}

export default function CandidateLeaderboard() {
  const candidates = useEvoStore((s) => s.candidates);
  const activeCandidateId = useEvoStore((s) => s.activeCandidateId);
  const setActiveCandidateId = useEvoStore((s) => s.setActiveCandidateId);
  const setViewMode = useEvoStore((s) => s.setViewMode);
  const setChatOpen = useEvoStore((s) => s.setChatOpen);
  const setChatDraft = useEvoStore((s) => s.setChatDraft);
  const compareLeftId = useEvoStore((s) => s.compareLeftId);
  const setCompareLeftId = useEvoStore((s) => s.setCompareLeftId);
  const setCompareRightId = useEvoStore((s) => s.setCompareRightId);

  // Two-click compare: first row picks A, a different second row picks B and
  // jumps to the compare view.
  const handleCompare = (id: number) => {
    if (compareLeftId !== null && id !== compareLeftId) {
      setCompareRightId(id);
      setViewMode("compare");
    } else {
      setCompareLeftId(id);
      setCompareRightId(null);
    }
  };

  const topCandidate = candidates[0];
  const laySummary = topCandidate
    ? `Best variant #${topCandidate.id}: function ${strengthLabel(topCandidate.scores.functional)}, tissue-motif ${strengthLabel(topCandidate.scores.tissue)}, panel safety ${safetyLabel(topCandidate.scores.offTarget)}. These are demo heuristics, not clinical scores.`
    : "No design variants have finished scoring yet.";
  const expertSummary = topCandidate
    ? `Functional ${topCandidate.scores.functional.toFixed(3)}, tissue ${topCandidate.scores.tissue.toFixed(3)}, panel off-target ${topCandidate.scores.offTarget.toFixed(3)}, novelty ${topCandidate.scores.novelty.toFixed(3)}.`
    : "";

  const queuePrompt = (prompt: string) => {
    setChatOpen(true);
    setChatDraft(prompt);
  };

  return (
    <div className="flex-1 overflow-auto px-4 lg:px-8 py-6" style={{ background: "var(--surface-base)" }}
      role="region" aria-label="Design variants">
      <div className="max-w-5xl mx-auto">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
          <div>
            <h2 className="text-xl font-semibold tracking-tight mb-1">Design variants</h2>
            <p className="text-[13px]" style={{ color: "var(--text-muted)" }}>
              {candidates.length} alternative DNA sequences from this run, ranked by a <ScienceTooltip term="overall-viability">combined demo score</ScienceTooltip>. Pick one to inspect or edit.
            </p>
          </div>
          <button onClick={() => setViewMode("explorer")}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all hover:scale-[1.02]"
            style={{ background: "var(--accent)", color: "var(--ink)" }}>
            Inspect top variant <ArrowRight size={14} aria-hidden="true" />
          </button>
        </div>

        <div className="mb-5 rounded-xl p-4" style={{ background: "var(--surface-elevated)" }}>
          <div className="text-[11px] font-medium uppercase tracking-wider mb-2" style={{ color: "var(--accent)" }}>
            Plain-Language Translation
          </div>
          <p className="text-[13px] leading-relaxed mb-1" style={{ color: "var(--text-primary)" }}>
            {laySummary}
          </p>
          {expertSummary && (
            <p className="text-[12px] font-mono mb-3" style={{ color: "var(--text-muted)" }}>
              {expertSummary}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => queuePrompt("Explain the top candidate for a clinician and a layman in 5 bullet points.")}
              className="px-3 py-1.5 rounded-full text-[11px] transition-colors hover:bg-white/[0.06]"
              style={{ background: "var(--surface-base)", color: "var(--text-secondary)" }}
            >
              Explain Top Candidate
            </button>
            <button
              onClick={() => queuePrompt("Compare top 3 candidates and recommend one for safety-sensitive use.")}
              className="px-3 py-1.5 rounded-full text-[11px] transition-colors hover:bg-white/[0.06]"
              style={{ background: "var(--surface-base)", color: "var(--text-secondary)" }}
            >
              Compare Top 3
            </button>
            <button
              onClick={() => queuePrompt("Improve the active candidate for tissue specificity and explain tradeoffs.")}
              className="px-3 py-1.5 rounded-full text-[11px] transition-colors hover:bg-white/[0.06]"
              style={{ background: "var(--surface-base)", color: "var(--text-secondary)" }}
            >
              Improve Tissue Fit
            </button>
          </div>
        </div>

        {/* Ranking table */}
        <div className="rounded-xl overflow-hidden" style={{ background: "var(--surface-elevated)" }}>
          <div className="flex items-center gap-3 px-5 py-2.5 text-[11px] font-medium uppercase tracking-wider"
            style={{ color: "var(--text-muted)" }}>
            <span className="w-10">Rank</span>
            <span className="flex-1">Candidate</span>
            <span className="w-20 text-right"><ScienceTooltip term="functional-plausibility">Functional</ScienceTooltip></span>
            <span className="w-20 text-right"><ScienceTooltip term="tissue-specificity">Tissue</ScienceTooltip></span>
            <span className="w-20 text-right"><ScienceTooltip term="off-target-risk">Off-target</ScienceTooltip></span>
            <span className="w-20 text-right"><ScienceTooltip term="novelty">Novelty</ScienceTooltip></span>
            <span className="w-20 text-right"><ScienceTooltip term="overall-viability">Overall</ScienceTooltip></span>
            <span className="w-8" />
          </div>
          {candidates.map((c, i) => (
            <motion.div key={c.id}
              onClick={() => { setActiveCandidateId(c.id); setViewMode("explorer"); }}
              role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setActiveCandidateId(c.id); setViewMode("explorer"); } }}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.08 + i * 0.06, type: "spring" as const, stiffness: 300, damping: 26 }}
              whileHover={{ scale: 1.005, x: 2 }}
              className="w-full flex items-center gap-3 px-5 py-3.5 text-left transition-colors hover:bg-black/[0.03] rounded-full mx-1 cursor-pointer"
              style={{
                background: activeCandidateId === c.id ? "rgba(245,158,11,0.12)" : "transparent",
              }}>
              <span className="text-base font-semibold w-10 font-mono" style={{ color: i === 0 ? "var(--accent)" : "var(--text-muted)" }}>
                #{i + 1}
              </span>
              <span className="flex-1">
                <span className="text-[13px] font-medium" style={{ color: "var(--text-primary)" }}>Candidate_{c.id.toString().padStart(3, "0")}</span>
                {activeCandidateId === c.id && (
                  <span className="text-[9px] font-semibold uppercase tracking-wider ml-2 px-1.5 py-0.5 rounded-full align-middle"
                    style={{ background: "color-mix(in oklch, var(--accent), transparent 82%)", color: "var(--accent)" }}>
                    Editing
                  </span>
                )}
                <span className="text-[11px] font-mono ml-2" style={{ color: "var(--text-faint)" }}>{c.sequence.length} bp</span>
                {c.provenance?.engine && (
                  <span className="ml-2 align-middle inline-flex">
                    <ProvenanceBadge
                      engine={c.provenance.engine}
                      method={c.provenance.method}
                      prefixOnlyConditioning={c.provenance.prefix_only_conditioning}
                      compact
                    />
                  </span>
                )}
                {c.status !== "scored" && (
                  <span className="text-[10px] font-mono ml-2" style={{ color: c.status === "failed" ? "var(--base-t)" : "var(--text-faint)" }}>
                    {c.status}
                  </span>
                )}
              </span>
              <span className="w-20 text-right text-[13px] font-mono" style={{ color: "var(--accent)" }}>{(c.scores.functional * 100).toFixed(0)}%</span>
              <span className="w-20 text-right text-[13px] font-mono" style={{ color: "var(--base-c)" }}>{(c.scores.tissue * 100).toFixed(0)}%</span>
              <span className="w-20 text-right text-[13px] font-mono" style={{ color: c.scores.offTarget > 0.03 ? "var(--base-t)" : "var(--accent)" }}>{(c.scores.offTarget * 100).toFixed(1)}%</span>
              <span className="w-20 text-right text-[13px] font-mono" style={{ color: "var(--base-g)" }}>{(c.scores.novelty * 100).toFixed(0)}%</span>
              <span className="w-20 text-right text-base font-semibold font-mono" style={{ color: "var(--text-primary)" }}>{c.overall.toFixed(1)}</span>
              <button
                onClick={(e) => { e.stopPropagation(); handleCompare(c.id); }}
                title={compareLeftId === c.id ? "Pinned as A — pick another to compare" : compareLeftId !== null ? "Compare against A" : "Pick as A to compare"}
                aria-label="Compare this candidate"
                className="w-8 shrink-0 flex items-center justify-center rounded-full py-1 transition-colors hover:bg-black/[0.06]"
                style={{ color: compareLeftId === c.id ? "var(--accent)" : "var(--text-faint)" }}>
                {compareLeftId === c.id
                  ? <span className="text-[11px] font-mono font-semibold">A</span>
                  : <GitCompare size={14} aria-hidden="true" />}
              </button>
              <ChevronRight size={14} className="w-6 shrink-0" style={{ color: "var(--text-faint)" }} aria-hidden="true" />
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}
