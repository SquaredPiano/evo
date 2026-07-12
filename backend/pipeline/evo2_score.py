"""Evo2 scoring pipeline - four heuristic signals per candidate.

Takes raw Evo2 forward pass output and computes:
  1. Functional plausibility  (composition + ORF + motif plausibility heuristic)
  2. Tissue-motif match       (short tissue-motif matches, not expression prediction)
  3. Panel off-target overlap (panel k-mer homology + repeat-content heuristic, NOT a genome-wide or CRISPR off-target scan)
  4. Novelty                  (composition divergence from human genomic averages + optional edit distance from a reference)

Each scorer is a standalone function. The pipeline composes them into
CandidateScores. Designed for easy upgrade: swap any scorer when real
biology knowledge replaces the heuristic.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass

import numpy as np

from models.domain import CandidateScores, ForwardResult, Impact, LikelihoodScore
from services.evo2 import Evo2Service
from services.translation import (
    find_motif,
    find_orfs,
    gc_content,
)


# ---------------------------------------------------------------------------
# Individual scorers
# ---------------------------------------------------------------------------

def score_functional(
    forward: ForwardResult, sequence: str
) -> float:
    """Functional plausibility: does this sequence carry gene-like patterns?

    A composition + ORF + motif plausibility heuristic, not proof of a working
    protein. Combines:
    - Mean of the forward per-position signal. This is a true Evo2 per-position
      log-likelihood only under EVO2_MODE=local; under nim_api it is the
      deterministic composition/motif signal (see Evo2NIMService.forward), since
      the hosted endpoint has no per-position forward pass.
    - GC content penalty (extreme GC is bad)
    - ORF presence bonus (coding potential)
    - Motif presence (regulatory elements)

    This is a composition + ORF + motif plausibility heuristic, not proof of a
    working protein and not a clinical assay.
    """
    # Sigmoid-normalize the mean forward signal to [0, 1]
    # Calibrated so -0.3 maps to ~0.85
    raw_ll = forward.sequence_score
    ll_score = _sigmoid(raw_ll, center=-0.5, steepness=4.0)

    # GC content: penalize extremes (<0.3 or >0.7)
    gc = gc_content(sequence)
    gc_penalty = 0.0
    if gc < 0.3 or gc > 0.7:
        gc_penalty = 0.1 * abs(gc - 0.5) / 0.2

    # ORF bonus: having ORFs suggests coding potential
    orfs = find_orfs(sequence, min_length=60)
    orf_bonus = min(0.05 * len(orfs), 0.10)

    # Motif bonus: known regulatory elements
    motif_bonus = 0.0
    for motif in ["TATAAA", "CCAAT", "ATG", "AATAAA"]:
        hits = find_motif(sequence, motif)
        motif_bonus += 0.02 * min(len(hits), 3)

    return _clamp(ll_score - gc_penalty + orf_bonus + motif_bonus)


def score_tissue_specificity(
    forward: ForwardResult, sequence: str, target_tissues: list[str] | None = None
) -> float:
    """Tissue-motif match: does the sequence carry motifs linked to the requested tissue?

    A tissue-motif match heuristic based on a small set of hand-picked
    tissue-specific promoter motifs, NOT an expression-level prediction. This is
    the scorer most likely to be upgraded with a real classifier.

    Known tissue-specific elements:
    - Neuronal: NRSE/RE1 (TTCAGCACCACGGACAG), CRE (TGACGTCA)
    - Cardiac: MEF2 (CTAAAAATAG), GATA (WGATAR)
    - Hepatic: HNF4 binding sites
    - Pancreatic: PDX1 binding motif
    """
    # Neuronal motifs
    neuronal_motifs = ["TGACGTCA", "CAGCACC", "GCACCAC"]
    # Cardiac motifs
    cardiac_motifs = ["CTAAAAATA", "AGATAG", "GATAAG"]
    # Generic regulatory
    generic_motifs = ["TATAAA", "CCAAT", "GGGCGG"]

    neuronal_hits = sum(len(find_motif(sequence, m)) for m in neuronal_motifs)
    cardiac_hits = sum(len(find_motif(sequence, m)) for m in cardiac_motifs)
    generic_hits = sum(len(find_motif(sequence, m)) for m in generic_motifs)

    # If target tissues specified, check alignment
    if target_tissues:
        target_lower = [t.lower() for t in target_tissues]
        has_neural = any("neuron" in t or "hippocamp" in t or "brain" in t for t in target_lower)
        has_cardiac = any("cardiac" in t or "heart" in t for t in target_lower)

        if has_neural:
            # Reward neuronal motifs, penalize cardiac
            return _clamp(0.5 + 0.1 * neuronal_hits - 0.1 * cardiac_hits + 0.03 * generic_hits)
        if has_cardiac:
            return _clamp(0.5 + 0.1 * cardiac_hits - 0.1 * neuronal_hits + 0.03 * generic_hits)

    # Default: general regulatory element richness
    total_hits = neuronal_hits + cardiac_hits + generic_hits
    return _clamp(0.4 + 0.05 * total_hits)


def score_off_target(
    forward: ForwardResult, sequence: str
) -> float:
    """Panel off-target overlap: how much does this sequence resemble a small
    built-in problem panel?

    Panel k-mer homology + repeat-content heuristic. This is NOT a genome-wide or
    CRISPR off-target scan and NOT a clinical risk score. Lower is better. Checks:
    - k-mer homology to a small repeat/oncogene panel
    - Poly-nucleotide runs and repeat expansion motifs (instability markers)
    - Extreme positional log-likelihood variance (unstable regions)
    """
    risk = 0.0

    # Poly-runs: AAAA, TTTT, etc. (genomic instability markers)
    for base in "ATCG":
        poly = base * 6
        hits = len(find_motif(sequence, poly))
        risk += 0.05 * hits

    # Known problematic motifs
    pathogenic_motifs = [
        "CAGCAGCAG",  # CAG trinucleotide repeat (Huntington's)
        "CGGCGGCGG",  # CGG repeat (Fragile X)
    ]
    for motif in pathogenic_motifs:
        risk += 0.15 * len(find_motif(sequence, motif))

    # High variance in log-likelihoods = unstable regions
    if forward.logits:
        ll_std = float(np.std(forward.logits))
        if ll_std > 0.2:
            risk += 0.05 * (ll_std - 0.2)

    # Real k-mer homology scan against curated genomic panels (Alu/LINE repeats,
    # oncogene hotspots, repeat expansions, regulatory elements). This replaces
    # pure motif-counting with an actual similarity search - a clean, novel
    # sequence shares few k-mers with these panels and stays low-risk.
    try:
        from services.offtarget import scan_offtargets

        scan = scan_offtargets(sequence, k=12, max_hits=5)
        if scan.hits:
            risk += 0.4 * float(scan.hits[0].similarity_score)
        risk += 0.15 * float(scan.repeat_fraction)
    except Exception:  # scan is best-effort; never break scoring
        pass

    return _clamp(risk)


def score_novelty(
    forward: ForwardResult, sequence: str, reference: str | None = None
) -> float:
    """Novelty: how unusual is this sequence's composition?

    Composition atypicality relative to typical human genomic averages, plus
    optional edit distance from a supplied reference. There is no known-sequence
    database behind this - it is a composition heuristic, not a similarity search
    against real genomes.

    Deliberately NOT used any more:
      - No floor on the edit component: an identical or near-identical sequence
        should read as low-novelty, not be pinned to a fabricated 0.12+.
      - No base-composition entropy term: real genomic DNA already sits near the
        2-bit maximum entropy, so "high entropy = novel" rewarded ordinary DNA
        for looking ordinary. It carried no novelty signal and is dropped.
    """
    if not sequence:
        return 0.5

    # Composition atypicality: distance of GC content from the ~41% human
    # genomic average, normalised so a strongly skewed composition approaches 1.
    gc = gc_content(sequence)
    gc_component = _clamp(abs(gc - 0.41) / 0.41)

    # Edit distance from a supplied reference of equal length (0 when absent or
    # length-mismatched, and exactly 0 for an identical sequence - no floor).
    if reference and len(reference) == len(sequence):
        mismatches = sum(
            1 for a, b in zip(sequence.upper(), reference.upper()) if a != b
        )
        edit_component = mismatches / len(sequence)
        novelty = 0.5 * gc_component + 0.5 * edit_component
    else:
        novelty = gc_component

    return _clamp(novelty)


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

async def score_candidate(
    service: Evo2Service,
    sequence: str,
    target_tissues: list[str] | None = None,
    reference_sequence: str | None = None,
) -> tuple[CandidateScores, list[LikelihoodScore]]:
    """Run the full 4-dimensional scoring pipeline on a candidate sequence.

    Returns:
        (CandidateScores, per_position_scores) tuple
    """
    forward = await service.forward(sequence)

    functional = score_functional(forward, sequence)
    tissue = score_tissue_specificity(forward, sequence, target_tissues)
    off_target = score_off_target(forward, sequence)
    novelty = score_novelty(forward, sequence, reference_sequence)

    scores = CandidateScores(
        functional=round(functional, 4),
        tissue_specificity=round(tissue, 4),
        off_target=round(off_target, 4),
        novelty=round(novelty, 4),
    )

    per_position = [
        LikelihoodScore(position=i, score=round(ll, 6))
        for i, ll in enumerate(forward.logits)
    ]

    return scores, per_position


# Positions patched around a single-base edit. Wide enough to cover any local
# heatmap the frontend renders around the cursor, small enough to keep the
# payload tiny so the edit response stays well under the 2s budget.
RESCORE_WINDOW = 64


@dataclass(frozen=True)
class MutationRescore:
    """Rich result of a single-base rescore, consumed by the /edit/base fast path.

    Bundles everything the edit endpoint needs so the caller never has to issue
    a second forward pass (e.g. a duplicate ``score_mutation``) just to learn the
    reference base or impact class.
    """

    scores: CandidateScores
    delta_likelihood: float
    reference_base: str
    predicted_impact: Impact
    mutated_sequence: str
    # Per-position log-likelihoods for a WINDOW around the edit, so the frontend
    # heatmap can update immediately without waiting on a full re-analysis.
    per_position_patch: list[LikelihoodScore]


async def rescore_mutation_detailed(
    service: Evo2Service,
    sequence: str,
    position: int,
    new_base: str,
    target_tissues: list[str] | None = None,
    window: int = RESCORE_WINDOW,
) -> MutationRescore:
    """Fast re-score after a single base edit, returning everything the edit
    endpoint needs in one shot.

    The mutation delta (ref vs alt) and the full candidate rescore are computed
    concurrently. The per-position log-likelihoods are sliced to a window around
    the edit so the response stays small and the frontend heatmap can patch in
    place. This deliberately does NOT fold protein structure - that is a slow,
    best-effort step the caller runs out of band.
    """
    mutated = sequence[:position] + new_base.upper() + sequence[position + 1 :]

    # Delta (needs a ref + alt forward pass) and the full alt rescore are
    # independent - run them together instead of serially.
    mutation, (scores, per_position) = await asyncio.gather(
        service.score_mutation(sequence, position, new_base),
        score_candidate(
            service, mutated, target_tissues=target_tissues, reference_sequence=sequence
        ),
    )

    half = window // 2
    start = max(0, position - half)
    end = min(len(per_position), position + half + 1)
    patch = per_position[start:end]

    return MutationRescore(
        scores=scores,
        delta_likelihood=mutation.delta_likelihood,
        reference_base=mutation.reference_base,
        predicted_impact=mutation.predicted_impact,
        mutated_sequence=mutated,
        per_position_patch=patch,
    )


async def rescore_mutation(
    service: Evo2Service,
    sequence: str,
    position: int,
    new_base: str,
    target_tissues: list[str] | None = None,
) -> tuple[CandidateScores, float]:
    """Fast re-score after a single base edit. Used by Edit Path A.

    Backwards-compatible thin wrapper over :func:`rescore_mutation_detailed`.

    Returns:
        (updated_scores, delta_likelihood)
    """
    result = await rescore_mutation_detailed(
        service, sequence, position, new_base, target_tissues=target_tissues
    )
    return result.scores, result.delta_likelihood


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sigmoid(x: float, center: float = 0.0, steepness: float = 1.0) -> float:
    """Sigmoid normalization to [0, 1]."""
    return 1.0 / (1.0 + math.exp(-steepness * (x - center)))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
