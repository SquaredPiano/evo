"""Core domain types - source of truth for the backend.

Frontend types in /types mirror these. API responses in responses.py
serialize from these. Components never see raw model tensors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel, Field


class AnnotationType(str, Enum):
    EXON = "exon"
    INTRON = "intron"
    ORF = "orf"
    PROPHAGE = "prophage"
    TRNA = "trna"
    RRNA = "rrna"
    INTERGENIC = "intergenic"
    UNKNOWN = "unknown"


# Neutral half-band for the SUM-based windowed delta (see
# evo2._windowed_mutation_delta). delta is now the SUM of per-position
# log-likelihood differences over the +/-10 bp window around the edit, not the
# old sequence-wide mean, so it lives on a much larger scale: a single
# transition change alone shifts the local sum by ~0.3-0.9 nats. A pure
# GC-content swap that changes no dinucleotide transition contributes only
# ~0.02-0.04, so 0.05 marks the floor below which the local composition signal
# is within heuristic noise. (The old +/-0.001 band was tuned for the mean and
# would flag that noise as directional.)
# NOTE: this band is calibrated for the shipped heuristic engines (nim_api /
# mock composition signal). Under EVO2_MODE=local (real Evo2 forward pass, not
# deployed) the summed real log-likelihood scale differs and would want a
# per-engine band; revisit if local is ever enabled.
IMPACT_NEUTRAL_BAND = 0.05


class Impact(str, Enum):
    """How a single-base edit shifts sequence likelihood under the model.

    This is a model-likelihood label, NOT a clinical pathogenicity call. A
    de-novo candidate has no wild-type reference, so ClinVar vocabulary
    (benign/deleterious) does not apply here.
    """

    MORE_LIKELY = "more_likely"
    NEUTRAL = "neutral"
    LESS_LIKELY = "less_likely"

    @staticmethod
    def from_delta(delta: float) -> Impact:
        """Classify a single-base edit from its SIGNED delta log-likelihood.

        delta = sum over a +/-10 bp window of [ LL(alt) - LL(ref) ]. The SIGN
        carries the meaning:
          delta >  IMPACT_NEUTRAL_BAND   -> MORE_LIKELY  (edit more expected locally)
          |delta| <= IMPACT_NEUTRAL_BAND -> NEUTRAL       (little change)
          delta < -IMPACT_NEUTRAL_BAND   -> LESS_LIKELY  (edit less expected locally)

        A model-likelihood score, not a clinical assay.
        """
        if delta > IMPACT_NEUTRAL_BAND:
            return Impact.MORE_LIKELY
        if delta < -IMPACT_NEUTRAL_BAND:
            return Impact.LESS_LIKELY
        return Impact.NEUTRAL


@dataclass(frozen=True)
class LikelihoodScore:
    position: int
    score: float  # per-position log-likelihood under Evo2


@dataclass(frozen=True)
class MutationScore:
    position: int
    reference_base: str
    alternate_base: str
    delta_likelihood: float
    predicted_impact: Impact


@dataclass(frozen=True)
class SequenceRegion:
    start: int  # 0-indexed inclusive
    end: int  # exclusive
    type: AnnotationType
    label: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class CandidateScores:
    """Four heuristic signals from the Evo2 scoring pipeline."""

    functional: float  # 0-1, composition + ORF + motif plausibility heuristic
    tissue_specificity: float  # 0-1, tissue-motif match heuristic
    off_target: float  # 0-1, panel k-mer homology + repeat-content heuristic (lower = better); NOT a genome-wide scan
    novelty: float  # 0-1, composition divergence from human genomic averages + optional edit distance from a reference

    @property
    def combined(self) -> float:
        """Combined score: weighted blend of the four signals for ranking. Higher is better."""
        return (
            0.40 * self.functional
            + 0.25 * self.tissue_specificity
            + 0.20 * (1.0 - self.off_target)  # invert so lower risk = higher score
            + 0.15 * self.novelty
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "functional": self.functional,
            "tissue_specificity": self.tissue_specificity,
            "off_target": self.off_target,
            "novelty": self.novelty,
            "combined": self.combined,
        }

    def to_ws_event(self, candidate_id: int) -> dict[str, object]:
        return {
            "event": "candidate_scored",
            "data": {
                "candidate_id": candidate_id,
                "scores": self.to_dict(),
            },
        }


@dataclass
class Candidate:
    id: int
    sequence: str
    scores: CandidateScores | None = None
    per_position_scores: list[LikelihoodScore] = field(default_factory=list)
    regions: list[SequenceRegion] = field(default_factory=list)
    pdb_data: str | None = None
    plddt_score: float | None = None


@dataclass(frozen=True)
class ForwardResult:
    """Result from an Evo2 forward pass."""

    logits: list[float]  # per-position log-likelihoods
    sequence_score: float  # mean log-likelihood across positions
    embeddings: list[list[float]] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "logits": self.logits,
            "sequence_score": self.sequence_score,
        }
        if self.embeddings is not None:
            payload["embeddings"] = self.embeddings
        return payload

    def to_ws_event(self, candidate_id: int) -> dict[str, object]:
        return {
            "event": "forward_pass_complete",
            "data": {
                "candidate_id": candidate_id,
                **self.to_dict(),
            },
        }

class TissueSpec(BaseModel):
    high_expression: list[str] = Field(default_factory=list)
    low_expression: list[str] = Field(default_factory=list)


class DesignSpec(BaseModel):
    design_type: str
    target_gene: str | None = None
    organism: str | None = None
    tissue_specificity: TissueSpec | None = None
    therapeutic_context: str | None = None
    constraints: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)
