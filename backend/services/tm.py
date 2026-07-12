"""DNA melting temperature (Tm) calculation.

Pure-Python implementation of two standard, deterministic methods:

  * Nearest-neighbor (SantaLucia 1998 unified parameters) - the accepted
    reference method for oligo duplex stability. Accounts for stacking
    thermodynamics, initiation, salt, and strand concentration.
  * Wallace rule (2xAT + 4xGC) - the simple approximation for very short
    oligos (<= 14 nt), kept as an honest fallback / cross-check.

No external dependencies: the thermodynamic table is hardcoded from the
published unified parameter set.

References:
  SantaLucia J Jr. "A unified view of polymer, dumbbell, and oligonucleotide
  DNA nearest-neighbor thermodynamics." PNAS 95(4):1460-1465 (1998).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Gas constant, cal/(mol*K).
_R = 1.987

# Unified nearest-neighbor parameters (SantaLucia 1998, Table 1).
# Key = 5'->3' dinucleotide of the top strand. dH in kcal/mol, dS in cal/(mol*K).
_NN: dict[str, tuple[float, float]] = {
    "AA": (-7.9, -22.2),
    "AT": (-7.2, -20.4),
    "TA": (-7.2, -21.3),
    "CA": (-8.5, -22.7),
    "GT": (-8.4, -22.4),
    "CT": (-7.8, -21.0),
    "GA": (-8.2, -22.2),
    "CG": (-10.6, -27.2),
    "GC": (-9.8, -24.4),
    "GG": (-8.0, -19.9),
    # Complements (reverse-complement dinucleotides share the same parameters).
    "TT": (-7.9, -22.2),
    "AG": (-7.8, -21.0),
    "TC": (-8.2, -22.2),
    "AC": (-8.4, -22.4),
    "TG": (-8.5, -22.7),
    "CC": (-8.0, -19.9),
}

# Initiation corrections (dH kcal/mol, dS cal/(mol*K)).
_INIT_GC = (0.1, -2.8)   # helix initiation with a terminal G*C pair
_INIT_AT = (2.3, 4.1)    # helix initiation with a terminal A*T pair

_DNA = frozenset("ACGT")


@dataclass
class TmResult:
    """Structured melting-temperature report."""

    sequence: str
    length: int
    gc_fraction: float
    method: str            # which value is the headline: "nearest-neighbor" | "wallace"
    tm_celsius: float      # headline Tm
    tm_nn_celsius: float | None      # nearest-neighbor Tm (None if not computable)
    tm_wallace_celsius: float        # Wallace-rule Tm
    na_molar: float
    oligo_molar: float
    delta_h_kcal: float | None       # total enthalpy (kcal/mol), NN only
    delta_s_cal: float | None        # total entropy incl. salt (cal/mol/K), NN only
    note: str


def _clean(sequence: str) -> str:
    return "".join(sequence.upper().split())


def gc_fraction(sequence: str) -> float:
    seq = _clean(sequence)
    if not seq:
        return 0.0
    gc = sum(1 for b in seq if b in ("G", "C"))
    return gc / len(seq)


def wallace_tm(sequence: str) -> float:
    """Wallace ("2+4") rule Tm in Celsius. Best for oligos <= 14 nt."""
    seq = _clean(sequence)
    at = sum(1 for b in seq if b in ("A", "T"))
    gc = sum(1 for b in seq if b in ("G", "C"))
    return 2.0 * at + 4.0 * gc


def nearest_neighbor_tm(
    sequence: str,
    *,
    na_molar: float = 0.05,
    oligo_molar: float = 0.25e-6,
) -> tuple[float, float, float]:
    """Nearest-neighbor Tm (SantaLucia 1998).

    Returns (tm_celsius, delta_h_kcal, delta_s_cal_with_salt).

    Assumes a non-self-complementary duplex with both strands present at
    ``oligo_molar`` total strand concentration (the x=4 case). Salt correction
    is applied to the entropy term per the 1998 unified treatment.
    """
    seq = _clean(sequence)
    if len(seq) < 2:
        raise ValueError("Nearest-neighbor Tm needs at least 2 nucleotides.")
    if any(b not in _DNA for b in seq):
        raise ValueError("Nearest-neighbor Tm requires only A/C/G/T (no N/ambiguity).")

    dh = 0.0
    ds = 0.0
    for i in range(len(seq) - 1):
        h, s = _NN[seq[i : i + 2]]
        dh += h
        ds += s

    # Terminal initiation corrections.
    for terminal in (seq[0], seq[-1]):
        h, s = _INIT_GC if terminal in ("G", "C") else _INIT_AT
        dh += h
        ds += s

    # Salt correction on entropy (SantaLucia 1998):
    #   dS[Na+] = dS[1M] + 0.368 * (N - 1) * ln[Na+]
    n = len(seq)
    ds_salt = ds + 0.368 * (n - 1) * math.log(na_molar)

    # Non-self-complementary duplex, equal strand concentrations => x = 4.
    tm_kelvin = (dh * 1000.0) / (ds_salt + _R * math.log(oligo_molar / 4.0))
    return tm_kelvin - 273.15, dh, ds_salt


def compute_tm(
    sequence: str,
    *,
    na_molar: float = 0.05,
    oligo_molar: float = 0.25e-6,
) -> TmResult:
    """Compute Tm with the appropriate headline method and both cross-checks."""
    seq = _clean(sequence)
    if not seq:
        raise ValueError("Sequence must not be empty.")

    wallace = wallace_tm(seq)
    gc = gc_fraction(seq)

    nn_tm: float | None = None
    dh: float | None = None
    ds: float | None = None
    if len(seq) >= 2 and all(b in _DNA for b in seq):
        nn_tm, dh, ds = nearest_neighbor_tm(seq, na_molar=na_molar, oligo_molar=oligo_molar)

    if nn_tm is not None:
        method = "nearest-neighbor"
        headline = nn_tm
        note = (
            "Tm (nearest-neighbor, SantaLucia 1998) at "
            f"[Na+]={na_molar * 1000:.0f} mM, [oligo]={oligo_molar * 1e6:.2f} uM. "
            "Wallace rule shown for cross-check."
        )
    else:
        method = "wallace"
        headline = wallace
        note = (
            "Tm (Wallace 2+4 rule). Nearest-neighbor not computable "
            "(sequence too short or contains ambiguous bases)."
        )

    return TmResult(
        sequence=seq,
        length=len(seq),
        gc_fraction=gc,
        method=method,
        tm_celsius=round(headline, 2),
        tm_nn_celsius=None if nn_tm is None else round(nn_tm, 2),
        tm_wallace_celsius=round(wallace, 2),
        na_molar=na_molar,
        oligo_molar=oligo_molar,
        delta_h_kcal=None if dh is None else round(dh, 2),
        delta_s_cal=None if ds is None else round(ds, 2),
        note=note,
    )
