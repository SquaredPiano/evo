"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import ReactDOM from "react-dom";

// ---------------------------------------------------------------------------
// Dictionary of scientific terms with plain-English explanations.
// Keys are kebab-case identifiers used throughout the Proteus UI.
// ---------------------------------------------------------------------------

export const SCIENCE_TERMS: Record<
  string,
  { title: string; explanation: string; learnMore?: string }
> = {
  // ── Scores & metrics ─────────────────────────────────────────────────────
  plddt: {
    title: "pLDDT Score",
    explanation:
      "ESMFold\u2019s confidence in the predicted 3D shape, per amino acid (0\u2013100). Above 90 is very confident, below 50 is uncertain. It is confidence in the SHAPE \u2014 not proof the protein works.",
  },
  "functional-plausibility": {
    title: "Functional Plausibility (heuristic)",
    explanation:
      "A score from base composition, ORF presence, and short motif hits. A composition and motif heuristic, not a clinical assay. Higher means more gene-like patterns, not proof of a working protein.",
  },
  "tissue-specificity": {
    title: "Tissue Motif Score (heuristic)",
    explanation:
      "Counts a small set of hand-picked short motifs from neuronal/cardiac literature. Not GTEx/ENCODE expression prediction - does not guarantee tissue-restricted activity.",
  },
  "off-target-risk": {
    title: "Panel Off-Target Overlap (heuristic)",
    explanation:
      "Overlap with a small built-in panel of bad sequences (repeats/oncogene snippets, k-mer match). Lower is better. This is NOT a genome-wide scan or clinical off-target risk.",
  },
  novelty: {
    title: "Novelty Score (heuristic)",
    explanation:
      "How different this string looks from simple composition baselines. Higher means more unusual DNA - not validated inventiveness.",
  },
  "log-likelihood": {
    title: "Log-likelihood (“model surprise”)",
    explanation:
      "Evo 2 is autocomplete for DNA. Log-likelihood scores how EXPECTED each base was: high = looks like real gene DNA, low = unusual. It is NOT a prediction that a therapy works. Generated candidates carry Evo 2's real model confidence (sampled_probs); the per-position 4D view shows composition and motif signals.",
  },
  "per-position-score": {
    title: "Per-position Score",
    explanation:
      "One number per base along the sequence. For a generated candidate this is Evo 2's real model confidence; the per-position 4D view shows composition and motif signals of the same length. Check the scoring note.",
  },
  "gc-content": {
    title: "GC Content",
    explanation:
      "The percentage of bases that are G or C (vs A or T). Most genes have 40\u201360% GC content. Extreme values can cause problems with gene expression or stability.",
  },
  "combined-score": {
    title: "Combined Score",
    explanation:
      "Weighted blend of the four heuristic signals, used only to rank candidates inside this IDE. A ranking heuristic, not assay-backed viability.",
  },
  cai: {
    title: "CAI - Codon Adaptation Index",
    explanation:
      "How closely a coding sequence’s codon choices match a highly-expressed reference set for the chosen host (0–1). Higher can mean easier expression in that host - it is a heuristic, not a guarantee the protein will express or work.",
  },
  auroc: {
    title: "AUROC - Area Under the ROC Curve",
    explanation:
      "A 0.5–1.0 measure of how well a score separates two classes (e.g. pathogenic vs benign variants). 1.0 = perfect, 0.5 = no better than chance. Here it is a real measurement on the scored variants, not a claim.",
  },
  hgvs: {
    title: "Variant Notation (HGVS-style)",
    explanation:
      "A shorthand for a single-base change: reference base, position, then the new base (e.g. A123G means A at position 123 becomes G). A standard way to name a mutation, not a verdict on its effect.",
  },
  "gc-balance-risk": {
    title: "GC Balance Risk (composition heuristic)",
    explanation:
      "A rough flag from how evenly G/C bases are spread along the sequence. Very uneven or extreme GC can complicate synthesis or expression. This is a composition heuristic, not a clinical or safety risk score.",
  },
  "repeat-fraction": {
    title: "Repeat Fraction (composition heuristic)",
    explanation:
      "The share of the sequence made of short repeated stretches. High repeat content can make DNA harder to synthesize or less stable. A composition heuristic - not a genome-wide or clinical measure.",
  },
  identity: {
    title: "% Sequence Identity",
    explanation:
      "The percentage of positions that match between two aligned sequences. Higher means more similar. It measures similarity of the letters - not whether the two sequences behave the same biologically.",
  },
  codon: {
    title: "Codon",
    explanation:
      "A group of three DNA bases that codes for one amino acid (or a stop). Several different codons can code for the same amino acid - which is why a coding sequence can be rewritten without changing the protein it makes.",
  },
  wildtype: {
    title: "Wildtype",
    explanation:
      "The original, unedited base (or sequence) before any mutation is applied - the reference you are comparing a change against.",
  },
  "off-target": {
    title: "Off-Target (panel heuristic)",
    explanation:
      "Where a sequence resembles known problem elements (repeats/oncogene snippets) from a small built-in panel. Lower overlap is better. This is NOT a genome-wide scan or clinical off-target risk.",
  },

  // ── DNA / Genomics ───────────────────────────────────────────────────────
  adenine: {
    title: "Adenine (A)",
    explanation:
      "One of the four DNA building blocks (bases). Adenine always pairs with Thymine (T) in double-stranded DNA. It\u2019s like one half of a zipper tooth.",
  },
  thymine: {
    title: "Thymine (T)",
    explanation:
      "One of the four DNA building blocks. Thymine always pairs with Adenine (A). In RNA, Thymine is replaced by Uracil (U).",
  },
  cytosine: {
    title: "Cytosine (C)",
    explanation:
      "One of the four DNA building blocks. Cytosine always pairs with Guanine (G). The C\u2013G bond is stronger than the A\u2013T bond.",
  },
  guanine: {
    title: "Guanine (G)",
    explanation:
      "One of the four DNA building blocks. Guanine always pairs with Cytosine (C). Regions rich in G and C are more structurally stable.",
  },
  "base-pair": {
    title: "Base Pair (bp)",
    explanation:
      "A unit of measurement for DNA length. One base pair is one \u2018rung\u2019 of the DNA ladder \u2014 a single A\u2013T or C\u2013G connection.",
  },

  // ── Regions ──────────────────────────────────────────────────────────────
  exon: {
    title: "Exon",
    explanation:
      "A section of a gene that is retained in the mature mRNA after splicing. Exons include the protein-coding parts plus the untranslated ends that stay in the final transcript.",
  },
  intron: {
    title: "Intron",
    explanation:
      "A section between exons that is spliced out of the RNA transcript before the mRNA is used, so it does not appear in the mature message. Like filler pages removed before the book is read.",
  },
  orf: {
    title: "Open Reading Frame (ORF)",
    explanation:
      "A start\u2192stop stretch of DNA that could code for a protein. It is a hint about where a gene might be \u2014 not a validated gene.",
  },
  prophage: {
    title: "Prophage",
    explanation:
      "Viral DNA that has been inserted into a bacterial genome. It\u2019s like a dormant virus hiding in the bacteria\u2019s own genetic code.",
  },
  intergenic: {
    title: "Intergenic Region",
    explanation:
      "DNA between genes \u2014 not part of any known gene. May contain regulatory elements that control when nearby genes turn on or off.",
  },

  // ── Protein structure ────────────────────────────────────────────────────
  "protein-structure": {
    title: "Protein Structure",
    explanation:
      "The 3D shape a protein folds into. Shape determines function \u2014 like a key fitting a lock. AI can now predict these shapes from DNA sequence alone.",
  },
  residue: {
    title: "Residue",
    explanation:
      "A single amino acid in a protein chain. Proteins are chains of residues, typically 100\u20131000 long. Each residue\u2019s position affects the overall 3D shape.",
  },
  "alpha-helix": {
    title: "Alpha Helix",
    explanation:
      "A common protein shape \u2014 a coiled spiral, like a corkscrew. Many proteins contain multiple helices connected by loops.",
  },
  "beta-sheet": {
    title: "Beta Sheet",
    explanation:
      "A flat protein structure where strands line up side by side, like pleated fabric. Often found in structural proteins.",
  },

  // ── Models ───────────────────────────────────────────────────────────────
  evo2: {
    title: "Evo 2",
    explanation:
      "Arc Institute’s genomic foundation model, “autocomplete for DNA.” Evo writes the candidate bases (generation) and reports its own confidence for them. Generation and scoring are separate steps, so always check which engine produced your numbers.",
  },
  esmfold: {
    title: "ESMFold",
    explanation:
      "Meta’s model (Lin et al., Science 2023) that predicts a protein’s 3D structure from its amino-acid sequence. Faster than AlphaFold. The pLDDT confidence numbers come from ESMFold - confidence of shape, not proof of function.",
  },
  alphafold: {
    title: "AlphaFold",
    explanation:
      "Google DeepMind\u2019s breakthrough AI for predicting protein 3D structures. Won the 2024 Nobel Prize in Chemistry. Revolutionized structural biology.",
  },

  // ── Mutations ────────────────────────────────────────────────────────────
  mutation: {
    title: "Substitution effect",
    explanation:
      "Swapping one base for another, then re-scoring the sequence under the model. The result is graded as more likely, neutral, or less likely under the model - a model-likelihood score, not a clinical pathogenicity call.",
  },
  "more-likely": {
    title: "More Likely Under the Model",
    explanation:
      "The edited base makes the sequence more expected under Evo 2 (positive delta log-likelihood). A model-likelihood signal, not proof the edit improves function.",
  },
  "less-likely": {
    title: "Less Likely Under the Model",
    explanation:
      "The edited base makes the sequence less expected under Evo 2 (negative delta log-likelihood). A model-likelihood signal, not a clinical pathogenicity call.",
  },
  "delta-likelihood": {
    title: "Delta Likelihood (\u0394LL)",
    explanation:
      "How much a single-base edit changes the model\u2019s confidence in the sequence. Negative means the edit is less likely under the model; positive means more likely. A model-likelihood score, not a clinical verdict.",
  },
};

// ---------------------------------------------------------------------------
// Positioning helpers
// ---------------------------------------------------------------------------

type Side = "top" | "bottom" | "left" | "right";

function getTooltipStyle(
  side: Side,
  triggerRect: DOMRect | null,
): React.CSSProperties {
  if (!triggerRect) return { opacity: 0, pointerEvents: "none" };

  const gap = 8;
  const margin = 12; // min distance from viewport edge
  const tooltipW = 280;
  const tooltipH = 80; // estimated

  const base: React.CSSProperties = {
    position: "fixed",
    zIndex: 9999,
    maxWidth: tooltipW,
    pointerEvents: "none",
  };

  // Auto-flip if tooltip would go off-screen
  let effectiveSide = side;
  if (side === "top" && triggerRect.top < tooltipH + margin) effectiveSide = "bottom";
  if (side === "bottom" && triggerRect.bottom + tooltipH + gap > window.innerHeight - margin) effectiveSide = "top";
  if (side === "left" && triggerRect.left < tooltipW + margin) effectiveSide = "right";
  if (side === "right" && triggerRect.right + tooltipW + gap > window.innerWidth - margin) effectiveSide = "left";

  // Clamp horizontal center to keep tooltip in viewport
  const centerX = Math.max(tooltipW / 2 + margin, Math.min(triggerRect.left + triggerRect.width / 2, window.innerWidth - tooltipW / 2 - margin));

  switch (effectiveSide) {
    case "top":
      return { ...base, left: centerX, top: triggerRect.top - gap, transform: "translate(-50%, -100%)" };
    case "bottom":
      return { ...base, left: centerX, top: triggerRect.bottom + gap, transform: "translate(-50%, 0)" };
    case "left":
      return { ...base, left: triggerRect.left - gap, top: triggerRect.top + triggerRect.height / 2, transform: "translate(-100%, -50%)" };
    case "right":
      return { ...base, left: triggerRect.right + gap, top: triggerRect.top + triggerRect.height / 2, transform: "translate(0, -50%)" };
  }
}

// ---------------------------------------------------------------------------
// ScienceTooltip
// ---------------------------------------------------------------------------

interface ScienceTooltipProps {
  /** Key into SCIENCE_TERMS, or any string. If not found, children render as-is. */
  term: keyof typeof SCIENCE_TERMS | (string & {});
  children: React.ReactNode;
  className?: string;
  /** Which side to show the tooltip on (default "top"). */
  side?: Side;
}

export function ScienceTooltip({
  term,
  children,
  className,
  side = "top",
}: ScienceTooltipProps) {
  const entry = SCIENCE_TERMS[term];

  // If the term isn't in the dictionary, render children transparently.
  if (!entry) {
    return <>{children}</>;
  }

  return (
    <TooltipShell
      title={entry.title}
      explanation={entry.explanation}
      side={side}
      className={className}
    >
      {children}
    </TooltipShell>
  );
}

// ---------------------------------------------------------------------------
// ScienceInfo  (inline info icon variant)
// ---------------------------------------------------------------------------

interface ScienceInfoProps {
  /** Key into SCIENCE_TERMS. */
  term: keyof typeof SCIENCE_TERMS | (string & {});
  className?: string;
  side?: Side;
}

/**
 * A small info icon that shows the science tooltip on hover.
 * Drop it next to any label:  `<span>pLDDT <ScienceInfo term="plddt" /></span>`
 */
export function ScienceInfo({ term, className, side = "top" }: ScienceInfoProps) {
  const entry = SCIENCE_TERMS[term];
  if (!entry) return null;

  return (
    <TooltipShell
      title={entry.title}
      explanation={entry.explanation}
      side={side}
      className={className}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 16,
          height: 16,
          fontSize: 11,
          lineHeight: 1,
          borderRadius: "50%",
          border: "1px solid var(--ghost-border)",
          color: "var(--text-muted)",
          cursor: "help",
          verticalAlign: "middle",
          marginLeft: 4,
          transition: "color 0.15s ease, border-color 0.15s ease",
        }}
        aria-label={`Info: ${entry.title}`}
      >
        i
      </span>
    </TooltipShell>
  );
}

// ---------------------------------------------------------------------------
// Shared inner shell that manages hover state + renders the tooltip popup.
// ---------------------------------------------------------------------------

interface TooltipShellProps {
  title: string;
  explanation: string;
  side: Side;
  className?: string;
  children: React.ReactNode;
}

function TooltipShell({
  title,
  explanation,
  side,
  className,
  children,
}: TooltipShellProps) {
  const [visible, setVisible] = useState(false);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (triggerRef.current) {
      setRect(triggerRef.current.getBoundingClientRect());
    }
    setVisible(true);
  }, []);

  const hide = useCallback(() => {
    timeoutRef.current = setTimeout(() => setVisible(false), 120);
  }, []);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  return (
    <>
      <span
        ref={triggerRef}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        tabIndex={0}
        className={className}
        style={{
          borderBottom: "1px dashed var(--text-faint)",
          cursor: "help",
          display: "inline",
        }}
      >
        {children}
      </span>

      {visible && (
        <ScienceTooltipPopup
          title={title}
          explanation={explanation}
          style={getTooltipStyle(side, rect)}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// The actual floating popup element, rendered via a portal.
// ---------------------------------------------------------------------------

interface PopupProps {
  title: string;
  explanation: string;
  style: React.CSSProperties;
}

function ScienceTooltipPopup({ title, explanation, style }: PopupProps) {
  // We render into a portal so the tooltip escapes any overflow:hidden ancestors.
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const content = (
    <div
      style={{
        ...style,
        background: "var(--surface-elevated)",
        border: "1px solid var(--ghost-border)",
        borderRadius: 10,
        padding: "10px 14px",
        boxShadow:
          "0 4px 24px oklch(0 0 0 / 0.35), 0 1px 4px oklch(0 0 0 / 0.2)",
        opacity: mounted ? 1 : 0,
        transform: `${style.transform ?? ""} ${mounted ? "" : "scale(0.97)"}`.trim(),
        transition:
          "opacity 0.15s cubic-bezier(0.16,1,0.3,1), transform 0.15s cubic-bezier(0.16,1,0.3,1)",
        willChange: "opacity, transform",
      }}
      role="tooltip"
    >
      <div
        className="font-label"
        style={{
          fontSize: 12,
          fontWeight: 600,
          letterSpacing: "0.03em",
          color: "var(--accent-bright)",
          marginBottom: 4,
          lineHeight: 1.3,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontSize: 12,
          lineHeight: 1.55,
          color: "var(--text-secondary)",
        }}
      >
        {explanation}
      </div>
    </div>
  );

  // Portal into document.body so we are never clipped.
  if (typeof window === "undefined") return null;

  return ReactDOM.createPortal(content, document.body);
}

export default ScienceTooltip;
