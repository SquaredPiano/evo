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
    """PWM-motif match: does the sequence carry transcription-factor binding
    sites linked to the requested tissue?

    This is a REAL position weight matrix (PWM) motif match score. It scans the
    sequence on both strands against curated JASPAR CORE 2024 vertebrate
    matrices (see ``services.motifs``) grouped into neuronal, cardiac/muscle,
    and general-regulatory transcription factors, then derives a [0, 1] score
    from confidence-weighted hit density.

    It remains a heuristic PROXY for tissue specificity, not an expression-level
    prediction or a measured binding assay: a strong PWM hit means the local
    sequence resembles a TF's known preference, not that the factor is expressed
    in the target tissue or that the element is active there.

    Tissue-relevant matrix subsets:
    - Neuronal: REST/NRSF, NEUROD1, ASCL1, OLIG2, SOX2, PAX6, CREB1, POU2F1
    - Cardiac/muscle: MEF2A/C, GATA1/2/3, MYOD1, NFATC1/2, TEAD1
    - General regulatory: TBP (TATA), SP1 (GC box), NRF1, YY1, CTCF, NFKB1,
      STAT3, TP53, E2F1
    """
    from services.motifs import (
        CARDIAC_MATRICES,
        GENERIC_MATRICES,
        NEURONAL_MATRICES,
    )

    neuronal_d = _pwm_density(sequence, NEURONAL_MATRICES)
    cardiac_d = _pwm_density(sequence, CARDIAC_MATRICES)
    generic_d = _pwm_density(sequence, GENERIC_MATRICES)

    # If target tissues specified, reward the matching subset and apply a modest
    # penalty when the competing lineage's sites dominate instead.
    if target_tissues:
        target_lower = [t.lower() for t in target_tissues]
        has_neural = any(
            "neuron" in t or "hippocamp" in t or "brain" in t or "neural" in t
            for t in target_lower
        )
        has_cardiac = any(
            "cardiac" in t or "heart" in t or "muscle" in t for t in target_lower
        )

        if has_neural:
            return _clamp(
                0.45
                + 0.35 * _saturate(neuronal_d, 2.0)
                - 0.15 * _saturate(cardiac_d, 2.0)
                + 0.05 * _saturate(generic_d, 3.0)
            )
        if has_cardiac:
            return _clamp(
                0.45
                + 0.35 * _saturate(cardiac_d, 2.0)
                - 0.15 * _saturate(neuronal_d, 2.0)
                + 0.05 * _saturate(generic_d, 3.0)
            )

    # Default: overall regulatory-element richness across all subsets.
    total_d = neuronal_d + cardiac_d + generic_d
    return _clamp(0.3 + 0.5 * _saturate(total_d, 4.0))


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

def _pwm_density(sequence: str, matrix_ids: tuple[str, ...]) -> float:
    """Confidence-weighted PWM hit density (per kb) for a matrix subset.

    Scans both strands at a relative-score threshold of 0.8 and sums each hit's
    excess above threshold, so only well-matched sites contribute. Normalised
    per 1000 bp with the denominator floored at 200 bp so a single strong hit in
    a very short test sequence does not read as an implausibly high density.
    """
    from services.motifs import scan_sequence

    hits = scan_sequence(sequence, threshold=0.8, matrix_ids=list(matrix_ids))
    # relative_score is in [0.8, 1.0]; map to [0, 1] "how far above threshold".
    strength = sum((h.relative_score - 0.8) / 0.2 for h in hits)
    denom = max(len(sequence), 200)
    return strength / denom * 1000.0


def _saturate(x: float, scale: float) -> float:
    """Saturating map of a non-negative signal to [0, 1): 1 - exp(-x/scale)."""
    if x <= 0.0:
        return 0.0
    return 1.0 - math.exp(-x / scale)


def _sigmoid(x: float, center: float = 0.0, steepness: float = 1.0) -> float:
    """Sigmoid normalization to [0, 1]."""
    return 1.0 / (1.0 + math.exp(-steepness * (x - center)))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
