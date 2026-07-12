"""PCR / sequencing primer design (primer3).

Thin, honest wrapper over primer3-py (`primer3.bindings.design_primers`). Given
a template DNA sequence it returns primer pairs with the standard primer3
metrics: sequence, position, length, melting temperature, GC%, and the
thermodynamic self/hetero-dimer and hairpin penalties primer3 computes.

No fabrication: every value comes directly from primer3's thermodynamic model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import primer3


@dataclass(frozen=True)
class Primer:
    sequence: str
    start: int          # 0-based start on the template (5' end of the oligo)
    length: int
    tm_celsius: float
    gc_percent: float
    self_any_th: float  # self-dimer alignment score (thermodynamic)
    self_end_th: float  # 3'-end self-dimer score
    hairpin_th: float   # hairpin melting temperature


@dataclass(frozen=True)
class PrimerPair:
    left: Primer
    right: Primer
    product_size: int
    product_tm: float | None
    pair_penalty: float
    compl_any_th: float  # heterodimer (left vs right) alignment score
    compl_end_th: float  # 3'-end heterodimer score


@dataclass(frozen=True)
class PrimerDesignResult:
    sequence_length: int
    pairs: list[PrimerPair]
    explain_left: str
    explain_right: str
    explain_pair: str
    method: str = "primer3"
    note: str = ""
    settings: dict[str, object] = field(default_factory=dict)


def _primer(res: dict, side: str, idx: int) -> Primer:
    loc = res[f"PRIMER_{side}_{idx}"]  # [start, length]
    return Primer(
        sequence=res[f"PRIMER_{side}_{idx}_SEQUENCE"],
        start=int(loc[0]),
        length=int(loc[1]),
        tm_celsius=round(float(res[f"PRIMER_{side}_{idx}_TM"]), 2),
        gc_percent=round(float(res[f"PRIMER_{side}_{idx}_GC_PERCENT"]), 1),
        self_any_th=round(float(res.get(f"PRIMER_{side}_{idx}_SELF_ANY_TH", 0.0)), 2),
        self_end_th=round(float(res.get(f"PRIMER_{side}_{idx}_SELF_END_TH", 0.0)), 2),
        hairpin_th=round(float(res.get(f"PRIMER_{side}_{idx}_HAIRPIN_TH", 0.0)), 2),
    )


def design_primers(
    sequence: str,
    product_size_min: int = 100,
    product_size_max: int = 1000,
    opt_tm: float = 60.0,
    min_tm: float = 57.0,
    max_tm: float = 63.0,
    opt_size: int = 20,
    min_size: int = 18,
    max_size: int = 25,
    num_return: int = 5,
) -> PrimerDesignResult:
    """Design PCR/sequencing primer pairs for ``sequence`` with primer3.

    Args:
        sequence: Template DNA (A/C/G/T; other symbols are left to primer3).
        product_size_min/max: Allowed amplicon size window in bp.
        opt/min/max_tm: Target melting-temperature window (Celsius).
        opt/min/max_size: Primer length window in nucleotides.
        num_return: Maximum number of primer pairs to return.

    Returns:
        PrimerDesignResult with the ranked primer pairs and primer3's own
        "explain" strings describing how the candidate space was filtered.

    Raises:
        ValueError: If the sequence is shorter than the minimum product size or
            the size/Tm windows are inconsistent.
    """
    seq = sequence.upper().strip()
    if len(seq) < 2 * min_size:
        raise ValueError(
            f"Sequence too short ({len(seq)} bp) to place a primer pair "
            f"(need at least {2 * min_size} bp)."
        )
    if product_size_min > product_size_max:
        raise ValueError("product_size_min must be <= product_size_max")
    if not (min_tm <= opt_tm <= max_tm):
        raise ValueError("Tm window inconsistent: require min_tm <= opt_tm <= max_tm")
    if not (min_size <= opt_size <= max_size):
        raise ValueError("Size window inconsistent: require min_size <= opt_size <= max_size")

    # primer3 cannot make a product longer than the template; clamp the upper
    # bound so a short template still yields pairs instead of an empty result.
    upper = min(product_size_max, len(seq))
    lower = min(product_size_min, upper)

    global_args = {
        "PRIMER_OPT_SIZE": opt_size,
        "PRIMER_MIN_SIZE": min_size,
        "PRIMER_MAX_SIZE": max_size,
        "PRIMER_OPT_TM": opt_tm,
        "PRIMER_MIN_TM": min_tm,
        "PRIMER_MAX_TM": max_tm,
        "PRIMER_MIN_GC": 20.0,
        "PRIMER_MAX_GC": 80.0,
        "PRIMER_PRODUCT_SIZE_RANGE": [[lower, upper]],
        "PRIMER_NUM_RETURN": num_return,
    }
    seq_args = {"SEQUENCE_ID": "template", "SEQUENCE_TEMPLATE": seq}

    res = primer3.bindings.design_primers(seq_args=seq_args, global_args=global_args)

    n = int(res.get("PRIMER_PAIR_NUM_RETURNED", 0))
    pairs: list[PrimerPair] = []
    for i in range(n):
        product_tm = res.get(f"PRIMER_PAIR_{i}_PRODUCT_TM")
        pairs.append(
            PrimerPair(
                left=_primer(res, "LEFT", i),
                right=_primer(res, "RIGHT", i),
                product_size=int(res[f"PRIMER_PAIR_{i}_PRODUCT_SIZE"]),
                product_tm=round(float(product_tm), 2) if product_tm is not None else None,
                pair_penalty=round(float(res[f"PRIMER_PAIR_{i}_PENALTY"]), 3),
                compl_any_th=round(float(res.get(f"PRIMER_PAIR_{i}_COMPL_ANY_TH", 0.0)), 2),
                compl_end_th=round(float(res.get(f"PRIMER_PAIR_{i}_COMPL_END_TH", 0.0)), 2),
            )
        )

    note = (
        f"primer3 returned {n} pair(s). Tm is the nearest-neighbor melting "
        f"temperature; SELF/COMPL/HAIRPIN values are primer3 thermodynamic "
        f"alignment scores (higher = stronger, more problematic secondary "
        f"structure)."
    )
    if n == 0:
        note = (
            "primer3 found no primer pair under these constraints. See the "
            "explain fields; try widening the Tm or product-size window."
        )

    return PrimerDesignResult(
        sequence_length=len(seq),
        pairs=pairs,
        explain_left=str(res.get("PRIMER_LEFT_EXPLAIN", "")),
        explain_right=str(res.get("PRIMER_RIGHT_EXPLAIN", "")),
        explain_pair=str(res.get("PRIMER_PAIR_EXPLAIN", "")),
        method="primer3",
        note=note,
        settings={
            "product_size_range": [lower, upper],
            "tm_window": [min_tm, opt_tm, max_tm],
            "size_window": [min_size, opt_size, max_size],
            "num_return": num_return,
        },
    )
