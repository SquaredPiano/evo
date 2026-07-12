"use client";

import { useMemo, useRef, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { useEvoStore } from "@/lib/store";
import {
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Box,
  ArrowLeftRight,
  ChevronUp,
  ChevronDown,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { diffCandidates, type DiffHunk, type DiffPosition } from "@/lib/seqDiff";
import { ScienceTooltip } from "@/components/ui/ScienceTooltip";
import type { AnalysisResult } from "@/types";

const ProteinViewer = dynamic(() => import("@/components/structure/ProteinViewer"), { ssr: false });

const BC: Record<string, string> = { A: "var(--base-a)", T: "var(--base-t)", C: "var(--base-c)", G: "var(--base-g)" };
const BASES_PER_LINE = 60;
const BASES_PER_BLOCK = 10;

interface CandidateLike {
  id: number;
  sequence: string;
  scores: { functional: number; tissue: number; offTarget: number; novelty: number };
  overall: number;
  perPositionScores?: Array<{ position: number; score: number }>;
}

/**
 * Resolve the best HONEST per-candidate PDB. Priority:
 *  1. The active candidate's live-folded structure (activePdb).
 *  2. A predicted protein whose region length uniquely matches this candidate.
 * Anything ambiguous or absent returns null — we never show another candidate's
 * fold under the wrong label, and we never fabricate a structure.
 */
function pdbForCandidate(
  cand: CandidateLike,
  analysisResult: AnalysisResult | null,
  activeCandidateId: number | null,
  activePdb: string | null,
): string | null {
  if (cand.id === activeCandidateId && activePdb) return activePdb;
  const proteins = (analysisResult?.predictedProteins ?? []).filter((p) => p.pdbData);
  const matches = proteins.filter((p) => p.regionEnd === cand.sequence.length);
  const unique = Array.from(new Set(matches.map((m) => m.pdbData)));
  if (unique.length === 1 && unique[0]) return unique[0];
  return null;
}

export default function CompareView() {
  const candidates = useEvoStore((s) => s.candidates);
  const regions = useEvoStore((s) => s.regions);
  const setViewMode = useEvoStore((s) => s.setViewMode);
  const setActiveCandidateId = useEvoStore((s) => s.setActiveCandidateId);
  const analysisResult = useEvoStore((s) => s.analysisResult);
  const activePdb = useEvoStore((s) => s.activePdb);
  const activeCandidateId = useEvoStore((s) => s.activeCandidateId);
  const theme = useEvoStore((s) => s.theme);
  const setChatOpen = useEvoStore((s) => s.setChatOpen);
  const setChatDraft = useEvoStore((s) => s.setChatDraft);

  const compareLeftId = useEvoStore((s) => s.compareLeftId);
  const compareRightId = useEvoStore((s) => s.compareRightId);
  const setCompareLeftId = useEvoStore((s) => s.setCompareLeftId);
  const setCompareRightId = useEvoStore((s) => s.setCompareRightId);

  // Effective selection with sensible fallbacks (top two ranked candidates).
  const leftId = compareLeftId ?? candidates[0]?.id ?? null;
  const rightId =
    compareRightId ?? candidates.find((c) => c.id !== leftId)?.id ?? null;

  const candA = candidates.find((c) => c.id === leftId) ?? candidates[0];
  const candB = candidates.find((c) => c.id === rightId) ?? candidates[1];

  const rankOf = (id: number) => candidates.findIndex((c) => c.id === id) + 1;

  const diff = useMemo(() => {
    if (!candA || !candB) return null;
    return diffCandidates(
      candA.sequence,
      candB.sequence,
      candA.perPositionScores,
      candB.perPositionScores,
    );
  }, [candA, candB]);

  const [hunkIndex, setHunkIndex] = useState(0);
  const [showDiff, setShowDiff] = useState(false);
  const hunkRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const gotoHunk = (next: number) => {
    if (!diff || diff.hunks.length === 0) return;
    const clamped = Math.max(0, Math.min(diff.hunks.length - 1, next));
    setHunkIndex(clamped);
    hunkRefs.current[clamped]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  if (candidates.length < 2) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ background: "var(--surface-base)" }}>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Need at least 2 candidates to compare.</p>
      </div>
    );
  }

  if (!candA || !candB) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ background: "var(--surface-base)" }}>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Select two candidates to compare.</p>
      </div>
    );
  }

  const sameCandidate = candA.id === candB.id;

  const regionAt = (pos: number) => regions.find((r) => pos >= r.start && pos < r.end);

  const pdbA = pdbForCandidate(candA, analysisResult, activeCandidateId, activePdb);
  const pdbB = pdbForCandidate(candB, analysisResult, activeCandidateId, activePdb);

  // ── Score delta table rows ──
  type Row = { label: string; a: number; b: number; lowerBetter?: boolean; pct?: boolean };
  const metricRows: Row[] = [
    { label: "Functional", a: candA.scores.functional, b: candB.scores.functional, pct: true },
    { label: "Tissue", a: candA.scores.tissue, b: candB.scores.tissue, pct: true },
    { label: "Off-target", a: candA.scores.offTarget, b: candB.scores.offTarget, lowerBetter: true, pct: true },
    { label: "Novelty", a: candA.scores.novelty, b: candB.scores.novelty, pct: true },
    { label: "Overall", a: candA.overall, b: candB.overall },
  ];

  const winnerOf = (r: Row): "A" | "B" | "tie" => {
    const eps = r.pct ? 0.005 : 0.05;
    const diffVal = r.a - r.b;
    if (Math.abs(diffVal) < eps) return "tie";
    const aWins = r.lowerBetter ? r.a < r.b : r.a > r.b;
    return aWins ? "A" : "B";
  };

  const cardBg = "var(--surface-raised)";
  const nameA = `Candidate_${candA.id.toString().padStart(3, "0")}`;
  const nameB = `Candidate_${candB.id.toString().padStart(3, "0")}`;

  // ── Plain-language "What changed" summary (derived from data already shown) ──
  const changedBases = diff?.changes.length ?? 0;
  const totalBases = diff ? Math.max(diff.lengthA, diff.lengthB) : candA.sequence.length;
  const identityPct = diff ? diff.identity * 100 : 100;

  // Which candidate is stronger on each metric, in plain-English terms.
  const friendlyMetric: Record<string, string> = {
    Functional: "function",
    Tissue: "tissue fit",
    "Off-target": "off-target safety",
    Novelty: "novelty",
  };
  const aWins: string[] = [];
  const bWins: string[] = [];
  for (const r of metricRows) {
    if (r.label === "Overall") continue;
    const w = winnerOf(r);
    if (w === "A") aWins.push(friendlyMetric[r.label] ?? r.label.toLowerCase());
    else if (w === "B") bWins.push(friendlyMetric[r.label] ?? r.label.toLowerCase());
  }
  const overallRow = metricRows[metricRows.length - 1];
  const overallWinner = winnerOf(overallRow);

  const listAnd = (arr: string[]) =>
    arr.length === 0
      ? ""
      : arr.length === 1
        ? arr[0]
        : arr.length === 2
          ? `${arr[0]} and ${arr[1]}`
          : `${arr.slice(0, -1).join(", ")}, and ${arr[arr.length - 1]}`;

  const changeSentence = sameCandidate
    ? "You picked the same candidate on both sides, so there is nothing to compare yet."
    : changedBases === 0
      ? `${nameA} and ${nameB} are identical over their shared length.`
      : `${nameA} and ${nameB} differ at ${changedBases} of ${totalBases} bases (${identityPct.toFixed(1)}% similar).`;

  const strengthParts: string[] = [];
  if (aWins.length) strengthParts.push(`${nameA} scores higher on ${listAnd(aWins)}`);
  if (bWins.length) strengthParts.push(`${nameB} scores higher on ${listAnd(bWins)}`);
  const strengthSentence = sameCandidate
    ? ""
    : strengthParts.length
      ? `${strengthParts.join("; ")}.`
      : "The two score about the same across every metric.";

  const overallLeaderLabel =
    overallWinner === "tie" ? "Even overall" : `${overallWinner} leads overall`;

  const explainInHelio = () => {
    const aStrong = aWins.length ? `${nameA} scores higher on ${listAnd(aWins)}` : "";
    const bStrong = bWins.length ? `${nameB} scores higher on ${listAnd(bWins)}` : "";
    const strengths = [aStrong, bStrong].filter(Boolean).join("; ");
    const prompt =
      `Explain this candidate comparison in plain English for a non-biologist. ` +
      `I'm comparing two DNA design variants: ${nameA} (rank #${rankOf(candA.id)}) and ${nameB} (rank #${rankOf(candB.id)}). ` +
      (sameCandidate
        ? `They are the same candidate. `
        : `They differ at ${changedBases} of ${totalBases} bases (${identityPct.toFixed(1)}% similar). `) +
      (strengths ? `${strengths}. ` : "They score about the same across every metric. ") +
      `Off-target is a safety metric where lower is better. ${overallLeaderLabel}. ` +
      `Explain what these differences mean and which candidate looks better and why. ` +
      `These are composition and motif heuristics, not clinical scores.`;
    setChatOpen(true);
    setChatDraft(prompt);
  };

  return (
    <div className="flex-1 overflow-auto" style={{ background: "var(--surface-base)" }}>
      <div className="max-w-6xl mx-auto px-8 py-6">
        {/* Header */}
        <div className="flex items-start justify-between mb-5 gap-4">
          <div>
            <h2 className="text-xl font-semibold tracking-tight mb-1">Candidate comparison</h2>
            <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
              See how two design variants stack up. The summary below says what changed and
              which one is stronger; the table scores each metric head-to-head, and you can open
              the base-level view for exact positions.
            </p>
          </div>
          <button onClick={() => { setActiveCandidateId(candA.id); setViewMode("explorer"); }}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all hover:scale-[1.02] shrink-0"
            style={{ background: "var(--accent)", color: "var(--ink)" }}>
            Edit in Studio <ArrowRight size={14} />
          </button>
        </div>

        {/* ── CANDIDATE PICKERS ── */}
        <div className="rounded-xl p-4 mb-6 grid grid-cols-[1fr_auto_1fr] items-center gap-3" style={{ background: cardBg }}>
          <CandidatePicker
            label="A"
            value={candA.id}
            candidates={candidates}
            onChange={(id) => setCompareLeftId(id)}
            accent="var(--accent)"
          />
          <button
            onClick={() => { setCompareLeftId(candB.id); setCompareRightId(candA.id); }}
            title="Swap A and B"
            className="p-2 rounded-full transition-colors hover:bg-black/[0.05]"
            style={{ color: "var(--text-secondary)", border: "1px solid var(--ghost-border)" }}>
            <ArrowLeftRight size={15} />
          </button>
          <CandidatePicker
            label="B"
            value={candB.id}
            candidates={candidates}
            onChange={(id) => setCompareRightId(id)}
            accent="var(--base-c)"
          />
        </div>

        {sameCandidate && (
          <div className="rounded-xl p-4 mb-6 text-[13px]" style={{ background: cardBg, color: "var(--text-muted)" }}>
            A and B are the same candidate — pick two different variants to see a diff.
          </div>
        )}

        {/* ── PLAIN-LANGUAGE "WHAT CHANGED" SUMMARY (always visible, primary) ── */}
        <div className="rounded-xl p-5 mb-6" style={{ background: cardBg }}>
          <span className="text-[11px] font-medium uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
            What changed
          </span>
          <p className="text-[14px] leading-relaxed mb-1" style={{ color: "var(--text-primary)" }}>
            {changeSentence}
          </p>
          {strengthSentence && (
            <p className="text-[13px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {strengthSentence}
            </p>
          )}
          {!sameCandidate && (
            <div className="flex flex-wrap items-center gap-2 mt-4">
              <SummaryChip tone="neutral">
                <ScienceTooltip term="identity">{identityPct.toFixed(1)}% similar</ScienceTooltip>
              </SummaryChip>
              <SummaryChip tone="neutral">
                {changedBases} changed base{changedBases !== 1 ? "s" : ""}
              </SummaryChip>
              {diff && diff.lengthA !== diff.lengthB && (
                <SummaryChip tone="neutral">
                  length {diff.lengthA} → {diff.lengthB}
                </SummaryChip>
              )}
              <SummaryChip tone={overallWinner === "A" ? "a" : overallWinner === "B" ? "b" : "neutral"}>
                {overallLeaderLabel}
              </SummaryChip>
            </div>
          )}
          <div className="mt-4">
            <button
              onClick={explainInHelio}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-[13px] font-medium transition-all hover:scale-[1.02]"
              style={{ background: "var(--surface-base)", color: "var(--text-primary)", border: "1px solid var(--ghost-border)" }}>
              <Sparkles size={14} style={{ color: "var(--accent)" }} />
              Explain this comparison in plain English
            </button>
          </div>
        </div>

        {/* ── BASE-LEVEL DIFF (collapsed by default — simple first) ── */}
        {!sameCandidate && diff && (
          <div className="rounded-xl overflow-hidden mb-6" style={{ background: cardBg }}>
            <button
              onClick={() => setShowDiff((v) => !v)}
              aria-expanded={showDiff}
              className="w-full flex items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-black/[0.02]"
              style={{ borderBottom: showDiff ? "1px solid var(--ghost-border)" : "none" }}>
              {showDiff ? <ChevronDown size={15} style={{ color: "var(--text-muted)" }} /> : <ChevronRight size={15} style={{ color: "var(--text-muted)" }} />}
              <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Show base-level diff
              </span>
              <span className="text-[12px] font-mono" style={{ color: "var(--text-secondary)" }}>
                {diff.hunks.length} changed region{diff.hunks.length !== 1 ? "s" : ""}
              </span>
              <span className="flex-1" />
            </button>

            {showDiff && (
            <>
            <div className="flex items-center gap-3 px-5 py-3 flex-wrap" style={{ borderBottom: "1px solid var(--ghost-border)" }}>
              <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Changed regions
              </span>
              <span className="text-[12px] font-mono" style={{ color: "var(--text-secondary)" }}>
                {diff.changes.length} changed base{diff.changes.length !== 1 ? "s" : ""} ·{" "}
                <ScienceTooltip term="identity">{(diff.identity * 100).toFixed(2)}% similar</ScienceTooltip>
              </span>
              {diff.lengthA !== diff.lengthB && (
                <span className="text-[11px] font-mono" style={{ color: "var(--base-t)" }}>
                  length {diff.lengthA} → {diff.lengthB}
                </span>
              )}
              <span className="flex-1" />
              {diff.hunks.length > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono tabular-nums" style={{ color: "var(--text-muted)" }}>
                    region {hunkIndex + 1}/{diff.hunks.length}
                  </span>
                  <button onClick={() => gotoHunk(hunkIndex - 1)} disabled={hunkIndex === 0}
                    className="p-1 rounded transition-colors hover:bg-black/[0.05] disabled:opacity-30"
                    style={{ border: "1px solid var(--ghost-border)" }} title="Previous region">
                    <ChevronUp size={13} />
                  </button>
                  <button onClick={() => gotoHunk(hunkIndex + 1)} disabled={hunkIndex === diff.hunks.length - 1}
                    className="p-1 rounded transition-colors hover:bg-black/[0.05] disabled:opacity-30"
                    style={{ border: "1px solid var(--ghost-border)" }} title="Next region">
                    <ChevronDown size={13} />
                  </button>
                </div>
              )}
            </div>

            {/* Legend row */}
            <div className="flex items-center gap-4 px-5 py-2 text-[11px] font-mono" style={{ borderBottom: "1px solid var(--ghost-border)", color: "var(--text-muted)" }}>
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: "color-mix(in oklch, var(--base-t), transparent 70%)" }} /> A ({rankOf(candA.id) > 0 ? `#${rankOf(candA.id)} · ` : ""}{nameA})
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: "color-mix(in oklch, var(--accent), transparent 70%)" }} /> B ({rankOf(candB.id) > 0 ? `#${rankOf(candB.id)} · ` : ""}{nameB})
              </span>
            </div>

            {diff.hunks.length === 0 ? (
              <div className="px-5 py-8 text-center text-[13px]" style={{ color: "var(--text-muted)" }}>
                Sequences are identical over their common length.
              </div>
            ) : (
              <div className="max-h-[520px] overflow-y-auto">
                {diff.hunks.map((hunk, hi) => (
                  <div
                    key={hi}
                    ref={(el) => { hunkRefs.current[hi] = el; }}
                    style={{ borderBottom: hi < diff.hunks.length - 1 ? "1px solid var(--ghost-border)" : "none" }}
                  >
                    <HunkBlock
                      hunk={hunk}
                      seqA={candA.sequence}
                      seqB={candB.sequence}
                      hasScoreDeltas={diff.hasScoreDeltas}
                      regionLabel={(pos) => regionAt(pos)?.type}
                    />
                  </div>
                ))}
              </div>
            )}
            </>
            )}
          </div>
        )}

        {/* ── SCORE DELTA TABLE ── */}
        <div className="rounded-xl p-5 mb-6" style={{ background: cardBg }}>
          <span className="text-[11px] font-medium uppercase tracking-wider block mb-1" style={{ color: "var(--text-muted)" }}>Score comparison</span>
          <p className="text-[11px] mb-4" style={{ color: "var(--text-faint)" }}>
            Head-to-head metrics. Off-target is inverted, so lower is better. These are composition and motif heuristics, not clinical scores.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                  <th className="text-left font-medium pb-2">Metric</th>
                  <th className="text-right font-medium pb-2 w-20">A</th>
                  <th className="text-right font-medium pb-2 w-20">B</th>
                  <th className="text-center font-medium pb-2 w-40">Δ (B − A)</th>
                  <th className="text-right font-medium pb-2 w-24">Winner</th>
                </tr>
              </thead>
              <tbody>
                {metricRows.map((r) => {
                  const winner = winnerOf(r);
                  const delta = r.b - r.a;
                  const fmt = (v: number) => (r.pct ? `${(v * 100).toFixed(r.label === "Off-target" ? 1 : 0)}%` : v.toFixed(1));
                  const deltaFmt = r.pct ? `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)}` : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`;
                  const isOverall = r.label === "Overall";
                  return (
                    <tr key={r.label} style={{ borderTop: isOverall ? "1px solid var(--ghost-border)" : "1px solid color-mix(in oklch, var(--ghost-border), transparent 55%)" }}>
                      <td className={`py-2.5 ${isOverall ? "font-semibold" : ""}`} style={{ color: "var(--text-primary)" }}>
                        {r.label}
                        {r.lowerBetter && <span className="text-[10px] ml-1.5" style={{ color: "var(--text-faint)" }}>(lower better)</span>}
                      </td>
                      <td className="text-right font-mono tabular-nums" style={{ color: winner === "A" ? "var(--accent)" : "var(--text-secondary)", fontWeight: winner === "A" ? 600 : 400 }}>{fmt(r.a)}</td>
                      <td className="text-right font-mono tabular-nums" style={{ color: winner === "B" ? "var(--base-c)" : "var(--text-secondary)", fontWeight: winner === "B" ? 600 : 400 }}>{fmt(r.b)}</td>
                      <td className="py-2.5">
                        <DeltaCell delta={delta} lowerBetter={r.lowerBetter} pct={r.pct} label={deltaFmt} />
                      </td>
                      <td className="text-right">
                        {winner === "tie" ? (
                          <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>tie</span>
                        ) : (
                          <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
                            style={{
                              background: winner === "A" ? "color-mix(in oklch, var(--accent), transparent 88%)" : "color-mix(in oklch, var(--base-c), transparent 88%)",
                              color: winner === "A" ? "var(--accent)" : "var(--base-c)",
                            }}>
                            {winner}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── STRUCTURE COMPARISON: candidate A vs candidate B ── */}
        <div className="rounded-xl overflow-hidden" style={{ background: cardBg }}>
          <div className="flex items-center gap-2 px-5 py-3" style={{ borderBottom: "1px solid var(--ghost-border)" }}>
            <Box size={14} style={{ color: "var(--accent)" }} />
            <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              3D Structure — Candidate A vs Candidate B
            </span>
          </div>
          <div className="grid grid-cols-2" style={{ borderBottom: "1px solid var(--ghost-border)" }}>
            <div className="px-4 py-2 text-center" style={{ borderRight: "1px solid var(--ghost-border)" }}>
              <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--accent)" }}>A · {nameA}</span>
            </div>
            <div className="px-4 py-2 text-center">
              <span className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--base-c)" }}>B · {nameB}</span>
            </div>
          </div>
          <div className="grid grid-cols-2">
            <StructurePane pdb={pdbA} theme={theme} bordered />
            <StructurePane pdb={pdbB} theme={theme} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small pill used in the "What changed" summary
// ---------------------------------------------------------------------------
function SummaryChip({ children, tone }: { children: ReactNode; tone: "neutral" | "a" | "b" }) {
  const accent = tone === "a" ? "var(--accent)" : tone === "b" ? "var(--base-c)" : null;
  return (
    <span
      className="inline-flex items-center text-[11px] font-medium px-2.5 py-1 rounded-full"
      style={
        accent
          ? { background: `color-mix(in oklch, ${accent}, transparent 88%)`, color: accent }
          : { background: "var(--surface-base)", color: "var(--text-secondary)", border: "1px solid var(--ghost-border)" }
      }
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Candidate picker dropdown
// ---------------------------------------------------------------------------
function CandidatePicker({
  label, value, candidates, onChange, accent,
}: {
  label: string;
  value: number;
  candidates: CandidateLike[];
  onChange: (id: number) => void;
  accent: string;
}) {
  return (
    <label className="flex items-center gap-3">
      <span className="text-xs font-mono font-semibold px-2 py-1 rounded-full shrink-0"
        style={{ background: `color-mix(in oklch, ${accent}, transparent 88%)`, color: accent }}>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 min-w-0 text-[13px] rounded-lg px-3 py-2 font-mono cursor-pointer transition-colors"
        style={{ background: "var(--surface-base)", color: "var(--text-primary)", border: "1px solid var(--ghost-border)" }}
      >
        {candidates.map((c, i) => (
          <option key={c.id} value={c.id}>
            #{i + 1} · Candidate_{c.id.toString().padStart(3, "0")} · {c.overall.toFixed(1)} · {c.sequence.length} bp
          </option>
        ))}
      </select>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Centered delta bar cell (MutationDiff-style)
// ---------------------------------------------------------------------------
function DeltaCell({
  delta, lowerBetter, pct, label,
}: {
  delta: number;
  lowerBetter?: boolean;
  pct?: boolean;
  label: string;
}) {
  // "Good" direction: positive delta is an improvement unless lowerBetter.
  const improved = lowerBetter ? delta < 0 : delta > 0;
  const eps = pct ? 0.005 : 0.05;
  const neutral = Math.abs(delta) < eps;
  const color = neutral ? "var(--text-muted)" : improved ? "var(--accent)" : "var(--base-t)";
  const maxAbs = pct ? 0.5 : 30; // scaling reference for the bar
  const frac = Math.min(Math.abs(delta) / maxAbs, 1);
  const barPercent = frac * 50;
  const isNegative = delta < 0;

  return (
    <div className="flex items-center gap-2 justify-center">
      <div className="relative h-1.5 rounded-full overflow-hidden flex-1 max-w-[110px]" style={{ background: "var(--ghost-border)" }}>
        <div className="absolute left-1/2 top-0 bottom-0 w-px" style={{ background: "var(--text-faint)" }} />
        <div className="absolute top-0 bottom-0 rounded-full"
          style={{
            background: color,
            opacity: neutral ? 0.4 : 0.85,
            left: isNegative ? `${50 - barPercent}%` : "50%",
            width: `${barPercent}%`,
          }} />
      </div>
      <span className="inline-flex items-center gap-0.5 w-14 justify-end font-mono text-[11px]" style={{ color }}>
        {neutral ? <Minus size={11} /> : improved ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// One git-diff hunk: sequence lines (A over B) + per-change annotation strip
// ---------------------------------------------------------------------------
function HunkBlock({
  hunk, seqA, seqB, hasScoreDeltas, regionLabel,
}: {
  hunk: DiffHunk;
  seqA: string;
  seqB: string;
  hasScoreDeltas: boolean;
  regionLabel: (pos: number) => string | undefined;
}) {
  const diffSet = useMemo(() => new Set(hunk.changes.map((c) => c.position)), [hunk.changes]);

  // Break the hunk window into 60bp lines aligned to absolute boundaries.
  const lineStart = Math.floor(hunk.start / BASES_PER_LINE) * BASES_PER_LINE;
  const lines: number[] = [];
  for (let p = lineStart; p < hunk.end; p += BASES_PER_LINE) lines.push(p);

  const renderRow = (seq: string, from: number, sideAccent: string) => {
    const to = Math.min(from + BASES_PER_LINE, hunk.end);
    const cells = [];
    for (let pos = from; pos < to; pos++) {
      const inWindow = pos >= hunk.start;
      const base = pos < seq.length ? seq[pos] : "·";
      const isDiff = diffSet.has(pos);
      cells.push(
        <span key={pos} className="inline-block w-[1ch] text-center"
          style={{
            marginLeft: pos > from && pos % BASES_PER_BLOCK === 0 ? "6px" : "0",
            color: inWindow ? (BC[base] ?? "var(--text-faint)") : "var(--text-faint)",
            opacity: inWindow ? 1 : 0.3,
            background: isDiff ? sideAccent : "transparent",
            borderRadius: isDiff ? "2px" : "0",
          }}>
          {base}
        </span>,
      );
    }
    return cells;
  };

  return (
    <div className="px-5 py-3">
      {/* Region header */}
      <div className="text-[11px] font-mono mb-2" style={{ color: "var(--text-faint)" }}>
        Bases {hunk.start}–{hunk.end} · {hunk.changes.length} changed base{hunk.changes.length !== 1 ? "s" : ""}
      </div>

      {/* Sequence lines */}
      <div className="font-mono text-[13px] leading-5 overflow-x-auto space-y-2">
        {lines.map((from) => (
          <div key={from} className="flex flex-col gap-0.5">
            <div className="flex items-start gap-2">
              <span className="text-[10px] w-4 text-right shrink-0 tabular-nums select-none pt-0.5" style={{ color: "var(--text-faint)" }}>A</span>
              <span className="text-[10px] w-12 text-right shrink-0 tabular-nums select-none pt-0.5" style={{ color: "var(--text-faint)" }}>{from}</span>
              <div className="flex flex-nowrap">{renderRow(seqA, from, "color-mix(in oklch, var(--base-t), transparent 65%)")}</div>
            </div>
            <div className="flex items-start gap-2">
              <span className="text-[10px] w-4 text-right shrink-0 tabular-nums select-none pt-0.5" style={{ color: "var(--text-faint)" }}>B</span>
              <span className="text-[10px] w-12 text-right shrink-0 tabular-nums select-none pt-0.5" style={{ color: "var(--text-faint)" }}>{from}</span>
              <div className="flex flex-nowrap">{renderRow(seqB, from, "color-mix(in oklch, var(--accent), transparent 65%)")}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Per-change annotations */}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
        {hunk.changes.map((c: DiffPosition) => {
          const region = regionLabel(c.position);
          return (
            <div key={c.position} className="inline-flex items-center gap-1.5 text-[11px] font-mono">
              <span style={{ color: "var(--text-muted)" }}>{c.position}</span>
              <span className="font-semibold" style={{ color: BC[c.ref] ?? "var(--text-muted)" }}>{c.ref}</span>
              <span className="text-[10px]" style={{ color: "var(--text-faint)" }}>→</span>
              <span className="font-semibold" style={{ color: BC[c.alt] ?? "var(--text-muted)" }}>{c.alt}</span>
              {region && (
                <span className="text-[9px] px-1 py-0.5 rounded" style={{ background: "var(--ghost-border)", color: "var(--text-muted)" }}>{region}</span>
              )}
              {/* Only show a real per-position score delta — never a fake 0. */}
              {hasScoreDeltas && c.scoreDelta !== undefined && (
                <span style={{ color: c.scoreDelta > 0 ? "var(--accent)" : c.scoreDelta < 0 ? "var(--base-t)" : "var(--text-muted)" }}>
                  <ScienceTooltip term="log-likelihood">
                    confidence {c.scoreDelta > 0 ? "+" : ""}{c.scoreDelta.toFixed(2)}
                  </ScienceTooltip>
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Structure pane — real fold or honest empty state
// ---------------------------------------------------------------------------
function StructurePane({ pdb, theme, bordered }: { pdb: string | null; theme: "dark" | "light"; bordered?: boolean }) {
  const bg = theme === "dark" ? "var(--surface-void)" : "var(--surface-base)";
  return (
    <div className="h-[320px] flex items-center justify-center" style={{ background: bg, borderRight: bordered ? "1px solid var(--ghost-border)" : undefined }}>
      {pdb ? (
        <ProteinViewer pdbData={pdb} theme={theme} />
      ) : (
        <div className="text-center px-4">
          <Box size={20} className="mx-auto mb-2" style={{ color: "var(--text-faint)" }} />
          <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>No predicted structure for this candidate.</p>
          <p className="text-[10px] mt-1" style={{ color: "var(--text-faint)" }}>Fold it from the Structure view to compare here.</p>
        </div>
      )}
    </div>
  );
}
