"""RNA/DNA secondary-structure prediction (ViennaRNA).

Computes the minimum free energy (MFE) secondary structure of a sequence with
ViennaRNA (`RNA.fold`), returning the MFE value, the dot-bracket structure, and
the set of hairpin loops parsed from that structure.

Honest labeling: ViennaRNA folds RNA. A DNA input is folded as its
transcribed RNA (T -> U) under the RNA energy model, so for DNA this is an
RNA-model approximation, not a DNA-duplex thermodynamics calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import RNA


@dataclass(frozen=True)
class Hairpin:
    stem_start: int   # 0-based index of the first paired base (5' side)
    stem_end: int     # 0-based index of the last paired base (3' side)
    loop_start: int   # 0-based index of the first unpaired base in the loop
    loop_size: int    # number of unpaired bases in the loop


@dataclass(frozen=True)
class SecondaryStructureResult:
    sequence: str          # the folded sequence (RNA alphabet, T converted to U)
    length: int
    mfe_kcal_mol: float
    dot_bracket: str
    paired_fraction: float
    hairpins: list[Hairpin]
    input_was_dna: bool
    method: str = "ViennaRNA MFE (RNA.fold)"
    note: str = ""


def _pair_table(dot_bracket: str) -> list[int]:
    """Map each position to its partner index, or -1 if unpaired."""
    table = [-1] * len(dot_bracket)
    stack: list[int] = []
    for i, ch in enumerate(dot_bracket):
        if ch == "(":
            stack.append(i)
        elif ch == ")":
            if stack:
                j = stack.pop()
                table[i] = j
                table[j] = i
    return table


def _find_hairpins(dot_bracket: str) -> list[Hairpin]:
    """Identify hairpin loops: a run of unpaired bases closed by a base pair.

    A hairpin is a `(` immediately (ignoring nested structure) enclosing a
    stretch of `.` that is then closed by the matching `)` with no intervening
    pairs. Detected by scanning for `(....)` patterns via the pair table.
    """
    table = _pair_table(dot_bracket)
    hairpins: list[Hairpin] = []
    n = len(dot_bracket)
    for i in range(n):
        j = table[i]
        if j <= i:
            continue
        # positions i (open) .. j (close). A hairpin loop has all bases between
        # i and j unpaired.
        if all(table[k] == -1 for k in range(i + 1, j)):
            hairpins.append(
                Hairpin(
                    stem_start=i,
                    stem_end=j,
                    loop_start=i + 1,
                    loop_size=(j - i - 1),
                )
            )
    return hairpins


def fold_sequence(sequence: str) -> SecondaryStructureResult:
    """Fold ``sequence`` and return its MFE secondary structure.

    Args:
        sequence: RNA or DNA sequence. DNA is folded as transcribed RNA
            (T -> U) under the ViennaRNA RNA energy model.

    Returns:
        SecondaryStructureResult with MFE, dot-bracket structure, and hairpins.

    Raises:
        ValueError: If the sequence is empty.
    """
    raw = sequence.upper().strip()
    if not raw:
        raise ValueError("Sequence must not be empty")

    input_was_dna = "T" in raw and "U" not in raw
    rna = raw.replace("T", "U")

    dot_bracket, mfe = RNA.fold(rna)

    paired = sum(1 for ch in dot_bracket if ch in "()")
    paired_fraction = paired / len(dot_bracket) if dot_bracket else 0.0
    hairpins = _find_hairpins(dot_bracket)

    if input_was_dna:
        note = (
            "Input contained T and was folded as transcribed RNA (T converted "
            "to U). This is a ViennaRNA RNA-model approximation, not a "
            "DNA-duplex thermodynamics calculation."
        )
    else:
        note = "ViennaRNA minimum free energy structure for the RNA sequence."

    return SecondaryStructureResult(
        sequence=rna,
        length=len(rna),
        mfe_kcal_mol=round(float(mfe), 2),
        dot_bracket=dot_bracket,
        paired_fraction=round(paired_fraction, 4),
        hairpins=hairpins,
        input_was_dna=input_was_dna,
        method="ViennaRNA MFE (RNA.fold)",
        note=note,
    )
