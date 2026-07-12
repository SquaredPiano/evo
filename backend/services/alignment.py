"""Pure-Python pairwise sequence alignment.

Implements Needleman-Wunsch (global) and Smith-Waterman (local) dynamic-
programming alignment with a linear gap penalty, plus a **coordinate lift map**
so a position in one sequence can be translated into the corresponding position
in the other across insertions and deletions.

No third-party dependencies - this deploys straight to the droplet. The DP is
O(n*m) in time and memory, which is fine for the candidate-sized sequences used
here (up to a few kb). A length guard (:data:`MAX_MATRIX_CELLS`) raises
:class:`AlignmentTooLargeError` for pathologically large inputs so callers can
fall back gracefully instead of exhausting memory.

Why this exists: ClinVar/HGVS coordinates are offsets into a *reference*
transcript or chromosome, not into a user's de-novo candidate. To honestly place
a reference variant onto a candidate we align candidate <-> reference and lift
the reference coordinate through the alignment. The same primitive makes the
version diff gap-aware so a single indel no longer corrupts every downstream
position.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default linear scoring. Chosen so a single substitution (one mismatch,
# score ``mismatch``) always beats representing that change as an
# insertion + deletion pair (two gaps, score ``2 * gap``): with these values
# ``mismatch (-1) > 2 * gap (-4)``. This keeps point mutations reported as
# substitutions rather than being split into spurious indels.
DEFAULT_MATCH = 1
DEFAULT_MISMATCH = -1
DEFAULT_GAP = -2

# Guard: refuse DP matrices larger than this many cells (~2000x2000). Callers
# should catch AlignmentTooLargeError and fall back to a cheaper strategy.
MAX_MATRIX_CELLS = 4_000_000

# Traceback pointer codes.
_DIAG = 1  # consume one base from each sequence (match / mismatch)
_UP = 2    # consume one base from A only  (gap in B)
_LEFT = 3  # consume one base from B only  (gap in A)


class AlignmentTooLargeError(ValueError):
    """Raised when an alignment would exceed :data:`MAX_MATRIX_CELLS`."""

    def __init__(self, len_a: int, len_b: int) -> None:
        super().__init__(
            f"alignment matrix {len_a}x{len_b} exceeds {MAX_MATRIX_CELLS} cells"
        )
        self.len_a = len_a
        self.len_b = len_b


@dataclass(frozen=True)
class Alignment:
    """Result of a pairwise alignment plus coordinate lift maps.

    ``aligned_a`` / ``aligned_b`` are equal-length strings with ``'-'`` marking
    gaps. ``a_to_b[i]`` is the position in B that A's position ``i`` aligns to,
    or ``None`` when A's base ``i`` is deleted in B (or lies outside the locally
    aligned block). ``b_to_a`` is the mirror. For a global alignment
    ``a_start``/``b_start`` are 0 and ``a_end``/``b_end`` are the full lengths;
    for a local alignment they bound the aligned sub-range.
    """

    aligned_a: str
    aligned_b: str
    score: int
    a_to_b: tuple[int | None, ...]
    b_to_a: tuple[int | None, ...]
    a_start: int
    b_start: int
    a_end: int
    b_end: int

    def lift_a_to_b(self, pos: int) -> int | None:
        """Position in B corresponding to position ``pos`` (0-based) in A.

        Returns ``None`` if ``pos`` is out of range, was deleted in B, or falls
        outside the aligned block (local alignment).
        """
        if 0 <= pos < len(self.a_to_b):
            return self.a_to_b[pos]
        return None

    def lift_b_to_a(self, pos: int) -> int | None:
        """Position in A corresponding to position ``pos`` (0-based) in B."""
        if 0 <= pos < len(self.b_to_a):
            return self.b_to_a[pos]
        return None


def _check_size(len_a: int, len_b: int) -> None:
    if len_a and len_b and len_a * len_b > MAX_MATRIX_CELLS:
        raise AlignmentTooLargeError(len_a, len_b)


def _build_lift_maps(
    aligned_a: str,
    aligned_b: str,
    len_a: int,
    len_b: int,
    a_offset: int,
    b_offset: int,
) -> tuple[tuple[int | None, ...], tuple[int | None, ...]]:
    """Walk an aligned column pair, recording base<->base correspondences.

    ``a_offset``/``b_offset`` are the start positions in the original
    (ungapped) sequences that ``aligned_a``/``aligned_b`` begin at - 0 for a
    global alignment, or the local start for Smith-Waterman.
    """
    a_to_b: list[int | None] = [None] * len_a
    b_to_a: list[int | None] = [None] * len_b
    ia = a_offset
    ib = b_offset
    for ca, cb in zip(aligned_a, aligned_b):
        if ca != "-" and cb != "-":
            a_to_b[ia] = ib
            b_to_a[ib] = ia
            ia += 1
            ib += 1
        elif ca != "-":  # gap in B: A base has no B counterpart
            ia += 1
        else:  # gap in A: B base has no A counterpart
            ib += 1
    return tuple(a_to_b), tuple(b_to_a)


def needleman_wunsch(
    a: str,
    b: str,
    match: int = DEFAULT_MATCH,
    mismatch: int = DEFAULT_MISMATCH,
    gap: int = DEFAULT_GAP,
) -> Alignment:
    """Global (end-to-end) alignment of ``a`` and ``b`` with a linear gap.

    Raises :class:`AlignmentTooLargeError` when the DP matrix would exceed
    :data:`MAX_MATRIX_CELLS`.
    """
    n, m = len(a), len(b)
    _check_size(n, m)

    if n == 0 or m == 0:
        aligned_a = a + "-" * m
        aligned_b = "-" * n + b
        a_to_b, b_to_a = _build_lift_maps(aligned_a, aligned_b, n, m, 0, 0)
        return Alignment(
            aligned_a=aligned_a,
            aligned_b=aligned_b,
            score=(n + m) * gap,
            a_to_b=a_to_b,
            b_to_a=b_to_a,
            a_start=0,
            b_start=0,
            a_end=n,
            b_end=m,
        )

    au = a.upper()
    bu = b.upper()

    # Score matrix with fully-penalised borders (global alignment).
    score = [[0] * (m + 1) for _ in range(n + 1)]
    ptr = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i * gap
        ptr[i][0] = _UP
    for j in range(1, m + 1):
        score[0][j] = j * gap
        ptr[0][j] = _LEFT

    for i in range(1, n + 1):
        ai = au[i - 1]
        row = score[i]
        prev = score[i - 1]
        prow = ptr[i]
        for j in range(1, m + 1):
            diag = prev[j - 1] + (match if ai == bu[j - 1] else mismatch)
            up = prev[j] + gap
            left = row[j - 1] + gap
            best = diag
            d = _DIAG
            if up > best:
                best = up
                d = _UP
            if left > best:
                best = left
                d = _LEFT
            row[j] = best
            prow[j] = d

    aligned_a, aligned_b = _traceback(a, b, ptr, n, m, stop_at_zero=False)
    a_to_b, b_to_a = _build_lift_maps(aligned_a, aligned_b, n, m, 0, 0)
    return Alignment(
        aligned_a=aligned_a,
        aligned_b=aligned_b,
        score=score[n][m],
        a_to_b=a_to_b,
        b_to_a=b_to_a,
        a_start=0,
        b_start=0,
        a_end=n,
        b_end=m,
    )


def smith_waterman(
    a: str,
    b: str,
    match: int = DEFAULT_MATCH,
    mismatch: int = DEFAULT_MISMATCH,
    gap: int = DEFAULT_GAP,
) -> Alignment:
    """Local alignment: the highest-scoring sub-region of ``a`` and ``b``.

    The lift maps only cover the aligned sub-range; positions outside it map to
    ``None``. Raises :class:`AlignmentTooLargeError` on oversized inputs.
    """
    n, m = len(a), len(b)
    _check_size(n, m)

    if n == 0 or m == 0:
        return Alignment(
            aligned_a="",
            aligned_b="",
            score=0,
            a_to_b=tuple([None] * n),
            b_to_a=tuple([None] * m),
            a_start=0,
            b_start=0,
            a_end=0,
            b_end=0,
        )

    au = a.upper()
    bu = b.upper()

    score = [[0] * (m + 1) for _ in range(n + 1)]
    ptr = [[0] * (m + 1) for _ in range(n + 1)]
    max_score = 0
    max_i = 0
    max_j = 0

    for i in range(1, n + 1):
        ai = au[i - 1]
        row = score[i]
        prev = score[i - 1]
        prow = ptr[i]
        for j in range(1, m + 1):
            diag = prev[j - 1] + (match if ai == bu[j - 1] else mismatch)
            up = prev[j] + gap
            left = row[j - 1] + gap
            best = 0
            d = 0
            if diag > best:
                best = diag
                d = _DIAG
            if up > best:
                best = up
                d = _UP
            if left > best:
                best = left
                d = _LEFT
            row[j] = best
            prow[j] = d
            if best > max_score:
                max_score = best
                max_i = i
                max_j = j

    # Traceback from the max cell until a zero-score cell (local boundary).
    i, j = max_i, max_j
    aa: list[str] = []
    bb: list[str] = []
    while i > 0 and j > 0 and ptr[i][j] != 0:
        d = ptr[i][j]
        if d == _DIAG:
            aa.append(a[i - 1])
            bb.append(b[j - 1])
            i -= 1
            j -= 1
        elif d == _UP:
            aa.append(a[i - 1])
            bb.append("-")
            i -= 1
        else:
            aa.append("-")
            bb.append(b[j - 1])
            j -= 1
    aa.reverse()
    bb.reverse()
    aligned_a = "".join(aa)
    aligned_b = "".join(bb)
    a_start, b_start = i, j
    a_to_b, b_to_a = _build_lift_maps(aligned_a, aligned_b, n, m, a_start, b_start)
    return Alignment(
        aligned_a=aligned_a,
        aligned_b=aligned_b,
        score=max_score,
        a_to_b=a_to_b,
        b_to_a=b_to_a,
        a_start=a_start,
        b_start=b_start,
        a_end=max_i,
        b_end=max_j,
    )


def _traceback(
    a: str,
    b: str,
    ptr: list[list[int]],
    i: int,
    j: int,
    stop_at_zero: bool,
) -> tuple[str, str]:
    """Reconstruct aligned strings from a pointer matrix (global path)."""
    aa: list[str] = []
    bb: list[str] = []
    while i > 0 or j > 0:
        d = ptr[i][j]
        if stop_at_zero and d == 0:
            break
        if i > 0 and j > 0 and d == _DIAG:
            aa.append(a[i - 1])
            bb.append(b[j - 1])
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or d == _UP):
            aa.append(a[i - 1])
            bb.append("-")
            i -= 1
        else:
            aa.append("-")
            bb.append(b[j - 1])
            j -= 1
    aa.reverse()
    bb.reverse()
    return "".join(aa), "".join(bb)


def lift_position(
    reference: str,
    candidate: str,
    ref_pos: int,
    *,
    local: bool = False,
) -> int | None:
    """Convenience: lift a 0-based ``ref_pos`` in ``reference`` into ``candidate``.

    Aligns ``reference`` (A) to ``candidate`` (B) and returns the candidate
    position the reference base maps to, or ``None`` if it cannot be placed
    (deleted in the candidate, outside the aligned block, or the alignment is
    too large). Global by default; pass ``local=True`` for Smith-Waterman.
    """
    try:
        aln = (
            smith_waterman(reference, candidate)
            if local
            else needleman_wunsch(reference, candidate)
        )
    except AlignmentTooLargeError:
        return None
    return aln.lift_a_to_b(ref_pos)
