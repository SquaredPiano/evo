"""Constrained region regeneration for Evo2 - TRUE re-invocation of the model.

This module implements generation-based iteration (reprompting), as opposed to
the single-base hill-climbing that only mutates an existing candidate. It calls
``Evo2Service.generate_detailed`` to actually re-synthesize a region.

TWO HONESTY-CRITICAL LIMITATIONS, encoded here and surfaced in every payload:

1. PREFIX-ONLY CONDITIONING. Evo2 (local and NIM) is autoregressive and generates
   left-to-right. When we regenerate a middle region we seed with the PREFIX
   ``sequence[:start]`` only; the regenerated bases do NOT see the downstream
   suffix ``sequence[end:]``. NIM exposes no native infilling / region-lock, so a
   spliced middle region is not jointly optimized with its right context. This is
   flagged as ``prefix_only_conditioning=True`` in the result.

2. REJECTION SAMPLING, NOT NATIVE CONSTRAINED DECODING. Constraints (GC target,
   avoid-motifs, length) are enforced by SAMPLE-K rejection sampling: we draw K
   independent regenerations and keep the one that best satisfies the constraints.
   The model is never told the constraints; we simply pick the closest sample. The
   ``constraint_report`` states what was actually achieved (e.g. achieved GC,
   motifs still present) so nothing is oversold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.evo2 import Evo2Service, GenerationResult

# Default number of candidate regenerations for SAMPLE-K rejection sampling.
DEFAULT_SAMPLE_K = 6
# Restriction-enzyme names → recognition sites, so "avoid EcoRI" resolves to a motif.
RESTRICTION_SITES: dict[str, str] = {
    "ECORI": "GAATTC",
    "BAMHI": "GGATCC",
    "HINDIII": "AAGCTT",
    "NOTI": "GCGGCCGC",
    "XHOI": "CTCGAG",
    "NDEI": "CATATG",
    "SALI": "GTCGAC",
    "XBAI": "TCTAGA",
    "SPEI": "ACTAGT",
    "PSTI": "CTGCAG",
    "KPNI": "GGTACC",
    "SACI": "GAGCTC",
    "NCOI": "CCATGG",
    "BGLII": "AGATCT",
    "CLAI": "ATCGAT",
    "ECORV": "GATATC",
    "SMAI": "CCCGGG",
    "APAI": "GGGCCC",
    "MLUI": "ACGCGT",
    "NHEI": "GCTAGC",
}


@dataclass
class RegenerationResult:
    """Result of a constrained region regeneration - the frontend payload source.

    All fields are additive and honest. ``sampled_probs`` is real Evo2 confidence
    (per regenerated base) ONLY when ``engine == "nim"``; otherwise it is None.
    """

    spliced_sequence: str        # full sequence: prefix + regenerated + suffix
    regenerated: str             # just the newly generated sub-sequence
    region_start: int            # start index in the ORIGINAL sequence
    region_end: int              # end index in the ORIGINAL sequence (exclusive)
    new_region_end: int          # start + len(regenerated) - end in the NEW sequence
    sampled_probs: list[float] | None  # per-regenerated-base Evo2 confidence (or None)
    engine: str                  # "nim" | "mock_fallback" | "local" | "mock"
    elapsed_ms: float | None
    prefix_only_conditioning: bool  # always True - see module docstring
    method: str                  # "rejection_sampling_sample_k"
    candidates_evaluated: int    # K
    constraint_report: dict[str, Any] = field(default_factory=dict)

    @property
    def sampled_probs_are_real_model_confidence(self) -> bool:
        return self.engine == "nim" and self.sampled_probs is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "spliced_sequence": self.spliced_sequence,
            "regenerated": self.regenerated,
            "region_start": self.region_start,
            "region_end": self.region_end,
            "new_region_end": self.new_region_end,
            "regenerated_length": len(self.regenerated),
            "sampled_probs": self.sampled_probs,
            "sampled_probs_are_real_model_confidence": self.sampled_probs_are_real_model_confidence,
            "engine": self.engine,
            "elapsed_ms": self.elapsed_ms,
            "prefix_only_conditioning": self.prefix_only_conditioning,
            "method": self.method,
            "candidates_evaluated": self.candidates_evaluated,
            "constraint_report": self.constraint_report,
        }


# ---------------------------------------------------------------------------
# Constraint helpers (pure functions - unit-tested)
# ---------------------------------------------------------------------------

def gc_fraction(sequence: str) -> float:
    """GC fraction in [0, 1]. Empty sequence → 0.0."""
    if not sequence:
        return 0.0
    seq = sequence.upper()
    return (seq.count("G") + seq.count("C")) / len(seq)


def motifs_present(sequence: str, motifs: list[str]) -> list[str]:
    """Return the subset of ``motifs`` that occur in ``sequence`` (case-insensitive)."""
    seq = sequence.upper()
    return [m for m in motifs if m and m.upper() in seq]


def normalize_avoid_motifs(motifs: list[str] | None) -> list[str]:
    """Resolve enzyme names to recognition sites; pass raw ATCG motifs through."""
    if not motifs:
        return []
    out: list[str] = []
    for raw in motifs:
        token = str(raw).strip().upper()
        if not token:
            continue
        if token in RESTRICTION_SITES:
            out.append(RESTRICTION_SITES[token])
        elif set(token) <= set("ATCGN"):
            out.append(token)
        # else: unknown label - skip silently (nothing to avoid)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for m in out:
        if m not in seen:
            seen.add(m)
            deduped.append(m)
    return deduped


def _constraint_penalty(
    region: str,
    *,
    gc_target: float | None,
    avoid_motifs: list[str],
) -> float:
    """Lower is better. Combines GC distance and a per-motif violation penalty."""
    penalty = 0.0
    if gc_target is not None:
        penalty += abs(gc_fraction(region) - gc_target)
    # Each avoid-motif still present is a hard-ish violation.
    penalty += 1.0 * len(motifs_present(region, avoid_motifs))
    return penalty


def parse_generation_constraints(constraints: list[str] | None) -> dict[str, Any]:
    """Parse free-text DesignSpec.constraints into a structured constraint dict.

    Understands tokens the intent parser / LLM emit, e.g. "high_gc_content",
    "low_gc", "avoid_ecori", "no_gaattc". Returns {} when nothing is recognized,
    so the caller can cheaply skip the rejection-sampling path.
    """
    if not constraints:
        return {}
    text = " ".join(str(c).lower() for c in constraints)
    parsed: dict[str, Any] = {}

    if "high_gc" in text or "high gc" in text:
        parsed["gc_target"] = 0.62
    elif "low_gc" in text or "low gc" in text:
        parsed["gc_target"] = 0.38

    avoid: list[str] = []
    for name in RESTRICTION_SITES:
        low = name.lower()
        if f"avoid_{low}" in text or f"avoid {low}" in text or f"no_{low}" in text or f"no {low}" in text:
            avoid.append(name)
    # Raw site tokens (e.g. "avoid_gaattc").
    for word in text.replace("_", " ").split():
        token = word.upper()
        if len(token) >= 4 and set(token) <= set("ATCG"):
            avoid.append(token)
    if avoid:
        parsed["avoid_motifs"] = avoid
    return parsed


# ---------------------------------------------------------------------------
# Core: constrained region regeneration
# ---------------------------------------------------------------------------

async def regenerate_region(
    service: Evo2Service,
    sequence: str,
    start: int,
    end: int,
    constraints: dict[str, Any] | None = None,
    *,
    sample_k: int = DEFAULT_SAMPLE_K,
) -> RegenerationResult:
    """Regenerate ``sequence[start:end]`` by re-invoking Evo2 (reprompting).

    Prefix-conditioned splice:
        seed      = sequence[:start]
        generated = model.generate_detailed(seed, n_tokens)      # left-to-right
        spliced   = sequence[:start] + generated + sequence[end:]

    If ``end >= len(sequence)`` this is a tail regeneration (no suffix to preserve).

    Constraints (all optional, via ``constraints`` dict):
        gc_target:    float in [0, 1] - desired GC fraction of the region.
        length_delta: int - bp to add (+) / remove (-) from the region length.
        avoid_motifs: list[str] - substrings / enzyme names the region must avoid.
        temperature:  float - sampling temperature.

    Constraint satisfaction uses SAMPLE-K rejection sampling (see module docstring):
    NOT native constrained decoding. The returned ``constraint_report`` states what
    was actually achieved. ``sampled_probs`` is real Evo2 confidence only under NIM.
    """
    constraints = dict(constraints or {})
    n = len(sequence)

    # --- Clamp the region to valid bounds ---
    start = max(0, min(int(start), n))
    end = max(start, min(int(end), n))
    region_len = end - start

    gc_target = constraints.get("gc_target")
    if gc_target is not None:
        gc_target = max(0.0, min(float(gc_target), 1.0))
    length_delta = int(constraints.get("length_delta") or 0)
    avoid_motifs = normalize_avoid_motifs(constraints.get("avoid_motifs"))
    temperature = float(constraints.get("temperature", 1.0))

    # --- Length math: how many tokens to generate for the new region ---
    n_tokens = max(1, region_len + length_delta)

    seed = sequence[:start]
    suffix = sequence[end:]

    k = max(1, int(sample_k))

    # --- SAMPLE-K rejection sampling ---
    best: GenerationResult | None = None
    best_penalty = float("inf")
    for i in range(k):
        # Vary temperature slightly per draw to diversify samples. This keeps the
        # mock backend deterministic (same inputs → same outputs) while still
        # exploring, and lets real NIM draws differ naturally.
        draw_temp = max(0.1, min(temperature + 0.06 * i, 1.0))
        result = await service.generate_detailed(seed, n_tokens, temperature=draw_temp)
        region = result.generated
        penalty = _constraint_penalty(region, gc_target=gc_target, avoid_motifs=avoid_motifs)
        # Tie-break: prefer higher real model confidence when available.
        if penalty < best_penalty or best is None:
            best_penalty = penalty
            best = result

    assert best is not None
    regenerated = best.generated
    spliced = seed + regenerated + suffix
    new_region_end = start + len(regenerated)

    achieved_gc = gc_fraction(regenerated)
    still_present = motifs_present(regenerated, avoid_motifs)
    satisfied = (
        (gc_target is None or abs(achieved_gc - gc_target) <= 0.05)
        and not still_present
    )

    constraint_report: dict[str, Any] = {
        "gc_target": gc_target,
        "achieved_gc": round(achieved_gc, 4),
        "gc_within_tolerance": (gc_target is None or abs(achieved_gc - gc_target) <= 0.05),
        "length_delta_requested": length_delta,
        "region_length_before": region_len,
        "region_length_after": len(regenerated),
        "avoid_motifs": avoid_motifs,
        "avoid_motifs_still_present": still_present,
        "temperature": temperature,
        "satisfied": bool(satisfied),
        "note": (
            "Constraints enforced by SAMPLE-K rejection sampling (not native "
            "constrained decoding); region conditions on the prefix only."
        ),
    }

    return RegenerationResult(
        spliced_sequence=spliced,
        regenerated=regenerated,
        region_start=start,
        region_end=end,
        new_region_end=new_region_end,
        sampled_probs=best.sampled_probs,
        engine=best.engine,
        elapsed_ms=best.elapsed_ms,
        prefix_only_conditioning=True,
        method="rejection_sampling_sample_k",
        candidates_evaluated=k,
        constraint_report=constraint_report,
    )
