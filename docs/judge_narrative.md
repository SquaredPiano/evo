# Evo - Judge Cheat-Sheet

Printable one-pager. The stance across the whole product: **the wow is the closed
loop + live engines + honesty, not the numbers.** Every score on screen is a
hypothesis or a ranking heuristic - never a clinical claim.

---

## 1. ~60-second spoken demo script

> "Evo is a genomic design IDE. The wow here is the **closed loop with live
> engines, and radical honesty about what each number means** - not the scores
> themselves.
>
> I type a design goal. **Evo 2 - Arc Institute's DNA foundation model - streams
> real DNA, base by base.** While it generates, we pull **live context from NCBI,
> PubMed and ClinVar**: NCBI seeds the sequence identity; PubMed and ClinVar are
> context only - they never rewrite the DNA.
>
> Then **ESMFold folds the candidate into a 3D structure** you can rotate, with
> per-residue confidence (pLDDT).
>
> Every score is labeled for what it actually is. Generation is real Evo 2, and
> generated candidates carry the model's own confidence. The 4D scores are
> **composition and motif signals, not clinical assays, and we say so right on
> the screen.** There's a one-click **Story Mode** glossary so you can check any
> term yourself.
>
> So: goal in → real generation → live evidence → structure → edit and re-score.
> A closed loop, honest about its limits."

Keep it to the loop. If asked "is this pathogenic / safe / drug-ready?" - say no,
and point at the honesty labels.

---

## 2. Plain-English glossary

- **Log-likelihood ("model surprise")** - Evo 2 is autocomplete for DNA.
  Log-likelihood scores how *expected* each base was. High = looks like real gene
  DNA; low = unusual. **NOT** a prediction the therapy works. Generated candidates
  carry Evo 2's real model confidence (`sampled_probs`); the per-position 4D view
  shows **composition and motif signals**.
- **Per-position score** - one number per base along the sequence; real Evo 2
  model confidence for a generated candidate, or composition and motif signals of
  the same length in the 4D view.
- **pLDDT** - ESMFold's confidence in the predicted 3D shape, per amino acid
  (0–100). Confidence of the **shape**, not proof of function.
- **ORF (open reading frame)** - a start→stop stretch that could be a gene. A
  hint, **not** a validated gene.
- **Off-target** - overlap with a small built-in panel of bad sequences; lower is
  better. **NOT** a genome-wide scan.
- **Functional / Tissue / Novelty (the 4D scores)** - ranking heuristics built
  from composition, motifs, and panel overlap. Used only to sort candidates in
  the IDE - **not clinical assays**.
- **Evo 2** - Arc Institute's genomic foundation model; writes the candidate DNA.
  Generation and scoring are separate steps.
- **ESMFold** - Meta's model (Lin et al., Science 2023) that predicts 3D protein
  structure from an amino-acid sequence; produces the structure preview and pLDDT.

---

## 3. Kill phrases - NEVER say these

- ❌ "Evo 2 scored this **pathogenic**." (We do not predict pathogenicity; ClinVar
  labels are reference data, not our model's verdict.)
- ❌ "This is **safe in patients**." (No safety claim of any kind.)
- ❌ "High **tissue score = expressed in brain**." (It's a motif-count heuristic,
  not an expression measurement.)
- ❌ "**pLDDT 85 = drug-ready**." (pLDDT is shape confidence, not function or
  developability.)
- ❌ "The model **proved** this works / is functional." (Scores are hypotheses and
  ranking heuristics.)
- ❌ "The 4D scores are **real Evo 2 log-likelihoods**." (They are composition and
  motif signals, not forward-pass log-likelihoods; generated candidates do carry
  real Evo 2 confidence via `sampled_probs`. Check the scoring note.)
- ❌ "We did a **genome-wide off-target scan**." (It's a small built-in panel.)

When in doubt, downgrade the claim and point to Story Mode.
