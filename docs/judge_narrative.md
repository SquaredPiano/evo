# Evo — Judge Cheat-Sheet

Printable one-pager. The stance across the whole product: **the wow is the closed
loop + live engines + honesty, not the numbers.** Every score on screen is a
hypothesis or a ranking heuristic — never a clinical claim.

---

## 1. ~60-second spoken demo script

> "Evo is a genomic design IDE. The wow here is the **closed loop with live
> engines, and radical honesty about what each number means** — not the scores
> themselves.
>
> I type a design goal. **Evo 2 — Arc Institute's DNA foundation model — streams
> real DNA, base by base.** While it generates, we pull **live context from NCBI,
> PubMed and ClinVar**: NCBI seeds the sequence identity; PubMed and ClinVar are
> context only — they never rewrite the DNA.
>
> Then **ESMFold folds the candidate into a 3D structure** you can rotate, with
> per-residue confidence (pLDDT).
>
> Every score is labeled for what it actually is. Under our default engine,
> generation is real, but the per-base scores are **calibrated heuristics — we
> say so, right on the screen** — a true forward pass needs local Evo 2. There's
> a one-click **Story Mode** glossary so you can check any term yourself.
>
> So: goal in → real generation → live evidence → structure → edit and re-score.
> A closed loop, honest about its limits."

Keep it to the loop. If asked "is this pathogenic / safe / drug-ready?" — say no,
and point at the honesty labels.

---

## 2. Plain-English glossary

- **Log-likelihood ("model surprise")** — Evo 2 is autocomplete for DNA.
  Log-likelihood scores how *expected* each base was. High = looks like real gene
  DNA; low = unusual. **NOT** a prediction the therapy works. Under the default
  engine (NIM), generation is real but per-base scores are **calibrated
  heuristics**, not a true forward pass — real LL needs `EVO2_MODE=local`.
- **Per-position score** — one number per base along the sequence; same caveat as
  log-likelihood (real values only in local mode, otherwise labeled heuristics).
- **pLDDT** — ESMFold's confidence in the predicted 3D shape, per amino acid
  (0–100). Confidence of the **shape**, not proof of function.
- **ORF (open reading frame)** — a start→stop stretch that could be a gene. A
  hint, **not** a validated gene.
- **Off-target** — overlap with a small built-in panel of bad sequences; lower is
  better. **NOT** a genome-wide scan.
- **Functional / Tissue / Novelty (the 4D scores)** — ranking heuristics built
  from composition, motifs, and panel overlap. Used only to sort candidates in
  the IDE — **not clinical assays**.
- **Evo 2** — Arc Institute's genomic foundation model; writes the candidate DNA.
  Generation and scoring are separate steps.
- **ESMFold** — Meta's model (Lin et al., Science 2023) that predicts 3D protein
  structure from an amino-acid sequence; produces the structure preview and pLDDT.

---

## 3. Kill phrases — NEVER say these

- ❌ "Evo 2 scored this **pathogenic**." (We do not predict pathogenicity; ClinVar
  labels are reference data, not our model's verdict.)
- ❌ "This is **safe in patients**." (No safety claim of any kind.)
- ❌ "High **tissue score = expressed in brain**." (It's a motif-count heuristic,
  not an expression measurement.)
- ❌ "**pLDDT 85 = drug-ready**." (pLDDT is shape confidence, not function or
  developability.)
- ❌ "The model **proved** this works / is functional." (Scores are hypotheses and
  ranking heuristics.)
- ❌ "These are **real Evo 2 log-likelihoods**." (Only true under local mode; the
  default engine uses labeled heuristics — check the scoring note.)
- ❌ "We did a **genome-wide off-target scan**." (It's a small built-in panel.)

When in doubt, downgrade the claim and point to Story Mode.
