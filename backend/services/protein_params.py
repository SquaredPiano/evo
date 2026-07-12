"""Protein-level physicochemical parameters.

Pure-Python, dependency-free computation of standard, deterministic protein
descriptors from an amino-acid sequence:

  * Molecular weight  - sum of average residue masses + one water.
  * Theoretical pI    - pH at which net charge is zero, solved by bisection
                        over a standard pKa table.
  * Aromaticity       - relative frequency of F/W/Y (Lobry & Gautier 1994).
  * GRAVY             - grand average of hydropathy (Kyte & Doolittle 1982).
  * Composition stats - per-residue fractions plus charged-residue counts
                        (instability-index-style composition summary).

All tables are hardcoded from published values. These are plain arithmetic
descriptors, not predictions.
"""

from __future__ import annotations

from dataclasses import dataclass

# Average residue masses (Da) - monomer mass minus one water. Sum + one water
# gives the average polypeptide molecular weight.
_RESIDUE_MASS: dict[str, float] = {
    "A": 71.0788, "R": 156.1875, "N": 114.1038, "D": 115.0886,
    "C": 103.1388, "E": 129.1155, "Q": 128.1307, "G": 57.0519,
    "H": 137.1411, "I": 113.1594, "L": 113.1594, "K": 128.1741,
    "M": 131.1926, "F": 147.1766, "P": 97.1167, "S": 87.0782,
    "T": 101.1051, "W": 186.2132, "Y": 163.1760, "V": 99.1326,
}
_WATER = 18.01524

# Kyte & Doolittle (1982) hydropathy index.
_KD: dict[str, float] = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

# pKa values (textbook / EMBOSS-style set) for the ionizable groups.
_PKA_NTERM = 9.69
_PKA_CTERM = 2.34
_PKA_POS = {"K": 10.53, "R": 12.4, "H": 6.0}     # side chains that carry + charge
_PKA_NEG = {"D": 3.86, "E": 4.25, "C": 8.33, "Y": 10.07}  # side chains that carry - charge

_AROMATIC = frozenset("FWY")
_AA = frozenset(_RESIDUE_MASS)


@dataclass
class ProteinParams:
    """Structured protein-parameter report."""

    sequence: str
    length: int
    molecular_weight: float          # Da
    theoretical_pi: float
    aromaticity: float               # fraction F+W+Y
    gravy: float                     # grand average hydropathy
    positively_charged: int          # count of R + K
    negatively_charged: int          # count of D + E
    composition: dict[str, float]    # residue -> fraction of sequence
    unknown_residues: int            # non-standard characters ignored in tables
    note: str


def _clean(sequence: str) -> str:
    return "".join(sequence.upper().split())


def molecular_weight(sequence: str) -> float:
    seq = _clean(sequence)
    mass = sum(_RESIDUE_MASS[a] for a in seq if a in _RESIDUE_MASS)
    residues = sum(1 for a in seq if a in _RESIDUE_MASS)
    return (mass + _WATER) if residues else 0.0


def gravy(sequence: str) -> float:
    seq = _clean(sequence)
    scored = [_KD[a] for a in seq if a in _KD]
    if not scored:
        return 0.0
    return sum(scored) / len(scored)


def aromaticity(sequence: str) -> float:
    seq = _clean(sequence)
    known = [a for a in seq if a in _AA]
    if not known:
        return 0.0
    return sum(1 for a in known if a in _AROMATIC) / len(known)


def _net_charge(seq: str, ph: float) -> float:
    """Net charge of the peptide at a given pH (termini + ionizable side chains)."""
    pos = 1.0 / (1.0 + 10.0 ** (ph - _PKA_NTERM))
    for a, pka in _PKA_POS.items():
        n = seq.count(a)
        if n:
            pos += n * (1.0 / (1.0 + 10.0 ** (ph - pka)))

    neg = 1.0 / (1.0 + 10.0 ** (_PKA_CTERM - ph))
    for a, pka in _PKA_NEG.items():
        n = seq.count(a)
        if n:
            neg += n * (1.0 / (1.0 + 10.0 ** (pka - ph)))

    return pos - neg


def theoretical_pi(sequence: str) -> float:
    """pH where net charge crosses zero, via bisection over [0, 14]."""
    seq = _clean(sequence)
    known = [a for a in seq if a in _AA]
    if not known:
        return 7.0
    lo, hi = 0.0, 14.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        charge = _net_charge(seq, mid)
        if charge > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-4:
            break
    return (lo + hi) / 2.0


def compute_protein_params(sequence: str) -> ProteinParams:
    """Compute the full set of protein descriptors."""
    seq = _clean(sequence)
    if not seq:
        raise ValueError("Protein sequence must not be empty.")

    known = [a for a in seq if a in _AA]
    if not known:
        raise ValueError("Sequence contains no standard amino acids.")

    n_known = len(known)
    composition = {
        a: round(known.count(a) / n_known, 4)
        for a in sorted(set(known))
    }
    pos = sum(1 for a in known if a in ("R", "K"))
    neg = sum(1 for a in known if a in ("D", "E"))
    unknown = len(seq) - n_known

    note = (
        "Deterministic ProtParam-style descriptors: average-mass MW, "
        "pI by charge bisection, Kyte-Doolittle GRAVY, F/W/Y aromaticity."
    )
    if unknown:
        note += f" {unknown} non-standard residue(s) ignored."

    return ProteinParams(
        sequence=seq,
        length=n_known,
        molecular_weight=round(molecular_weight(seq), 2),
        theoretical_pi=round(theoretical_pi(seq), 2),
        aromaticity=round(aromaticity(seq), 4),
        gravy=round(gravy(seq), 4),
        positively_charged=pos,
        negatively_charged=neg,
        composition=composition,
        unknown_residues=unknown,
        note=note,
    )
