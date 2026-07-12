"use client";

/**
 * StoryMode - a self-serve, judge-facing glossary drawer.
 *
 * Plain-English + HONEST definitions of every term Proteus puts on screen. The
 * stance is deliberate: we never upgrade heuristics into clinical claims. The
 * "wow" is the closed loop + live engines + honesty, not the numbers.
 *
 * Opened from anywhere via the store (`storyModeOpen`).
 */

import { AnimatePresence, motion } from "framer-motion";
import { X, BookOpen } from "lucide-react";
import { useProteusStore } from "@/lib/store";

interface GlossaryEntry {
  term: string;
  plain: string;
  honesty?: string;
}

const GLOSSARY: GlossaryEntry[] = [
  {
    term: "Log-likelihood (“model surprise”)",
    plain:
      "Evo 2 is autocomplete for DNA. Log-likelihood scores how expected each base was. High = looks like real gene DNA; low = unusual.",
    honesty:
      "NOT a prediction the therapy works. Generation is real Evo 2, and generated candidates carry the model's own confidence. The per-position 4D view shows composition and motif signals.",
  },
  {
    term: "Per-position score",
    plain:
      "One number for each base along the sequence, so you can see which stretches look gene-like and which look off.",
    honesty:
      "Real Evo 2 model confidence for a generated candidate; the 4D view shows composition and motif signals of the same length.",
  },
  {
    term: "pLDDT",
    plain:
      "ESMFold's confidence in the predicted 3D shape, per amino acid (0–100). Higher = more sure about the shape.",
    honesty: "Confidence of the shape, not proof the protein functions.",
  },
  {
    term: "ORF (open reading frame)",
    plain: "A start→stop stretch of DNA that could be a gene.",
    honesty: "A hint about where a gene might be - not a validated gene.",
  },
  {
    term: "Off-target",
    plain:
      "Overlap with a small built-in panel of known bad sequences. Lower is better.",
    honesty: "NOT a genome-wide scan and not clinical off-target risk.",
  },
  {
    term: "Functional / Tissue / Novelty scores (the 4D scores)",
    plain:
      "Ranking heuristics built from composition, short motifs, and panel overlap - used only to sort candidates inside this IDE.",
    honesty:
      "Ranking heuristics, not clinical assays. A high tissue score does NOT mean the gene is expressed in that tissue.",
  },
  {
    term: "Evo 2",
    plain:
      "Arc Institute's genomic foundation model - the engine that writes the candidate DNA.",
    honesty:
      "Generation (writing bases) and scoring are separate steps. Generation is live Evo 2; the 4D scores are composition and motif heuristics.",
  },
  {
    term: "ESMFold",
    plain:
      "Meta's model (Lin et al., Science 2023) that folds an amino-acid sequence into a 3D structure. It produces the structure preview and pLDDT.",
    honesty: "Predicts shape from sequence - a structural hypothesis, not a functional guarantee.",
  },
];

export default function StoryMode() {
  const open = useProteusStore((s) => s.storyModeOpen);
  const setOpen = useProteusStore((s) => s.setStoryModeOpen);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-[9998]"
            style={{ background: "oklch(0 0 0 / 0.35)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setOpen(false)}
          />
          <motion.aside
            className="fixed right-0 top-0 bottom-0 z-[9999] w-full max-w-md overflow-y-auto"
            style={{ background: "var(--surface-elevated)", borderLeft: "1px solid var(--ghost-border)" }}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 32 }}
            role="dialog"
            aria-label="Story Mode glossary"
          >
            <div
              className="sticky top-0 flex items-center justify-between px-6 py-4"
              style={{ background: "var(--surface-elevated)", borderBottom: "1px solid var(--ghost-border)" }}
            >
              <div className="flex items-center gap-2">
                <BookOpen size={16} style={{ color: "var(--accent)" }} />
                <span className="text-sm font-semibold">Story Mode - plain English</span>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="p-1 rounded-full transition-colors hover:bg-white/[0.06]"
                aria-label="Close glossary"
                style={{ color: "var(--text-muted)" }}
              >
                <X size={16} />
              </button>
            </div>

            <div className="px-6 py-5">
              <div
                className="rounded-xl p-4 mb-5"
                style={{ background: "color-mix(in oklch, var(--accent), transparent 92%)" }}
              >
                <p className="text-[12px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  The wow here is the <strong>closed loop + live engines + honesty</strong>, not the
                  numbers. Every score below is a hypothesis or a ranking heuristic - never a clinical
                  claim.
                </p>
              </div>

              <div className="space-y-5">
                {GLOSSARY.map((g) => (
                  <div key={g.term}>
                    <div className="text-[13px] font-semibold mb-1" style={{ color: "var(--text-primary)" }}>
                      {g.term}
                    </div>
                    <p className="text-[12px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                      {g.plain}
                    </p>
                    {g.honesty && (
                      <p
                        className="text-[11px] leading-relaxed mt-1 pl-3"
                        style={{ color: "var(--text-muted)", borderLeft: "2px solid var(--ghost-border)" }}
                      >
                        <span className="font-semibold uppercase text-[9px] tracking-wider mr-1" style={{ color: "var(--base-t)" }}>
                          honesty
                        </span>
                        {g.honesty}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
