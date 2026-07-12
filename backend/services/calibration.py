"""Scoring calibration against ClinVar ground truth.

The Evo2 delta-log-likelihood score is only meaningful if it actually
separates known-pathogenic mutations from known-benign ones. Rather than
asserting that it does, this module *measures* it: it pulls labeled variants
from ClinVar, scores each with whatever Evo2 engine is currently configured,
and reports a real AUROC.

Directionality: the Evo2 paper reports that deleterious variants receive a
*lower* (more negative) log-likelihood than the reference. So the pathogenicity
score we rank on is ``-delta_likelihood`` — higher means "looks more broken".

Honesty note baked into the output: the hosted NIM endpoint has no per-position
forward pass, so under ``nim_api`` (and the offline dev engine) the scores here
come from a deterministic composition/motif signal rather than a true Evo2
per-sequence log-likelihood. An AUROC near 0.5 with those engines is therefore
the truthful result, not a bug. A real Evo2 discrimination signal requires the
local Evo2 checkpoint (``EVO2_MODE=local``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from services.evo2 import Evo2Service
from services.variant_annotation import VariantAnnotation, annotate_variants

logger = logging.getLogger("evo.calibration")

# ClinVar significance strings we treat as each class.
_PATHOGENIC = {"pathogenic", "likely pathogenic", "likely_pathogenic",
               "pathogenic/likely pathogenic"}
_BENIGN = {"benign", "likely benign", "likely_benign", "benign/likely benign"}


@dataclass(frozen=True)
class ScoredVariant:
    position: int
    ref_base: str
    alt_base: str
    label: str            # "pathogenic" | "benign"
    delta_likelihood: float
    pathogenicity_score: float  # -delta_likelihood


@dataclass
class CalibrationReport:
    gene: str
    engine_mode: str
    auroc: float | None            # None when a class is empty / nothing scored
    n_pathogenic: int
    n_benign: int
    n_scored: int
    n_skipped_unaligned: int       # variant ref base did not match the sequence
    mean_delta_pathogenic: float | None
    mean_delta_benign: float | None
    note: str
    scored: list[ScoredVariant] = field(default_factory=list)


def compute_auroc(labels: list[int], scores: list[float]) -> float | None:
    """AUROC via the rank-sum (Mann–Whitney U) identity, tie-aware.

    ``labels`` are 1 for the positive class, 0 for the negative class.
    Returns None if either class is empty.
    """
    if len(labels) != len(scores):
        raise ValueError("labels and scores must be the same length")
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    # Average ranks (1-based), splitting ties evenly.
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # +1 for 1-based ranks
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    sum_pos_ranks = sum(ranks[i] for i in range(len(labels)) if labels[i] == 1)
    auroc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return round(auroc, 4)


async def calibrate_variants(
    service: Evo2Service,
    sequence: str,
    variants: list[VariantAnnotation],
) -> list[ScoredVariant]:
    """Score each aligned SNV. Variants whose ref base doesn't match the
    sequence at their position are skipped by the caller (see calibrate_gene);
    this scores exactly what it's given."""
    scored: list[ScoredVariant] = []
    for v in variants:
        label = _classify(v.clinical_significance)
        if label is None or not v.ref_base or not v.alt_base:
            continue
        try:
            result = await service.score_mutation(sequence, v.position, v.alt_base)
        except ValueError:
            continue
        scored.append(ScoredVariant(
            position=v.position,
            ref_base=v.ref_base,
            alt_base=v.alt_base,
            label=label,
            delta_likelihood=result.delta_likelihood,
            pathogenicity_score=-result.delta_likelihood,
        ))
    return scored


def _classify(significance: str) -> str | None:
    s = significance.strip().lower()
    if s in _PATHOGENIC or "pathogenic" in s and "benign" not in s:
        return "pathogenic"
    if s in _BENIGN or "benign" in s and "pathogenic" not in s:
        return "benign"
    return None


def _aligned(variant: VariantAnnotation, sequence: str) -> bool:
    """Keep only SNVs whose reference base matches the provided sequence."""
    if not variant.ref_base or not variant.alt_base:
        return False
    if variant.position < 0 or variant.position >= len(sequence):
        return False
    return sequence[variant.position].upper() == variant.ref_base.upper()


def _engine_mode() -> str:
    """Active Evo2 engine from config — read directly to avoid a network
    health check (nim_api's health() call would hit the live API)."""
    try:
        from config import settings
        mode = settings.evo2_mode
        return getattr(mode, "value", str(mode))
    except Exception:
        return "unknown"


async def calibrate_gene(
    service: Evo2Service,
    gene: str,
    sequence: str,
    max_per_class: int = 40,
) -> CalibrationReport:
    """Fetch pathogenic + benign ClinVar SNVs for a gene, align them to the
    provided sequence, score them, and report a real AUROC."""
    engine_mode = _engine_mode()

    if not sequence:
        return CalibrationReport(
            gene=gene, engine_mode=engine_mode, auroc=None,
            n_pathogenic=0, n_benign=0, n_scored=0, n_skipped_unaligned=0,
            mean_delta_pathogenic=None, mean_delta_benign=None,
            note="No sequence provided; supply a CDS-aligned sequence to calibrate.",
        )

    patho, benign = await asyncio.gather(
        annotate_variants(gene, sequence=sequence, max_variants=max_per_class,
                          significance="pathogenic"),
        annotate_variants(gene, sequence=sequence, max_variants=max_per_class,
                          significance="benign"),
    )

    candidates = list(patho.annotations) + list(benign.annotations)
    aligned = [v for v in candidates if _aligned(v, sequence)]
    skipped = len(candidates) - len(aligned)

    scored = await calibrate_variants(service, sequence, aligned)
    labels = [1 if s.label == "pathogenic" else 0 for s in scored]
    scores = [s.pathogenicity_score for s in scored]
    auroc = compute_auroc(labels, scores)

    n_p = sum(labels)
    n_b = len(labels) - n_p
    dp = [s.delta_likelihood for s in scored if s.label == "pathogenic"]
    db = [s.delta_likelihood for s in scored if s.label == "benign"]

    return CalibrationReport(
        gene=gene,
        engine_mode=engine_mode,
        auroc=auroc,
        n_pathogenic=n_p,
        n_benign=n_b,
        n_scored=len(scored),
        n_skipped_unaligned=skipped,
        mean_delta_pathogenic=round(sum(dp) / len(dp), 6) if dp else None,
        mean_delta_benign=round(sum(db) / len(db), 6) if db else None,
        note=_build_note(engine_mode, auroc, n_p, n_b),
        scored=scored,
    )


def _build_note(engine_mode: str, auroc: float | None, n_p: int, n_b: int) -> str:
    if n_p == 0 or n_b == 0:
        return ("Need both pathogenic and benign variants aligned to the sequence "
                "to compute AUROC. Provide a CDS-aligned reference sequence.")
    if engine_mode in {"mock", "nim_api"}:
        return (f"AUROC measured with the '{engine_mode}' engine, whose scores derive from a "
                "deterministic composition/motif signal rather than a true Evo2 per-sequence "
                "log-likelihood, so an AUROC near 0.5 is expected and honest. Run "
                "EVO2_MODE=local for a real Evo2 discrimination signal.")
    return (f"AUROC measured with the '{engine_mode}' engine over {n_p} pathogenic and "
            f"{n_b} benign ClinVar SNVs aligned to the sequence.")
