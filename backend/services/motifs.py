"""Position weight matrix (PWM) motif scanning against bundled JASPAR matrices.

This module replaces chance-level short-substring motif matching with real
log-odds PWM scoring. It loads a curated set of JASPAR CORE 2024 vertebrate
matrices (see ``backend/data/jaspar/``) with Biopython, builds log-odds PSSMs
against a uniform background, and scans a sequence on BOTH strands.

Honest framing: a PWM hit means the local sequence resembles a transcription
factor's known binding preference above a relative-score threshold. It is a
sequence-pattern match, not a measured binding event, an occupancy call, or an
expression assay.

The matrices are parsed once at import and cached at module level.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass

import numpy as np
from Bio import motifs as bio_motifs
from Bio.motifs.jaspar import calculate_pseudocounts
from Bio.Seq import Seq

# ---------------------------------------------------------------------------
# Bundled matrix location
# ---------------------------------------------------------------------------

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "jaspar",
)

# Default relative-score threshold. A window's log-odds score is normalised to
# [0, 1] between the matrix's theoretical min and max; 0.8 is a common, fairly
# strict cut used for reporting confident matches without flooding on noise.
DEFAULT_THRESHOLD = 0.8


@dataclass(frozen=True)
class MotifHit:
    """A single PWM match above threshold on one strand."""

    matrix_id: str
    tf_name: str
    start: int  # 0-indexed, inclusive
    end: int  # exclusive
    strand: str  # "+" or "-"
    score: float  # log-odds bits
    relative_score: float  # score normalised to [0, 1] over [min, max]


@dataclass(frozen=True)
class _LoadedMatrix:
    matrix_id: str
    tf_name: str
    length: int
    pssm: object  # Bio.motifs PSSM for the + strand
    rpssm: object  # reverse-complement PSSM (scores - strand at each position)
    min_score: float
    max_score: float


def _load_matrices() -> dict[str, _LoadedMatrix]:
    """Parse every bundled ``.jaspar`` file into a log-odds PSSM.

    Uniform background, JASPAR-style pseudocounts (scaled to each matrix's
    total counts) so log-odds are well defined even for zero-count cells.
    """
    loaded: dict[str, _LoadedMatrix] = {}
    if not os.path.isdir(_DATA_DIR):
        return loaded

    for path in sorted(glob.glob(os.path.join(_DATA_DIR, "*.jaspar"))):
        try:
            with open(path) as fh:
                motif = bio_motifs.read(fh, "jaspar")
            motif.pseudocounts = calculate_pseudocounts(motif)
            pssm = motif.pssm
            rpssm = pssm.reverse_complement()
            mid = motif.matrix_id or os.path.splitext(os.path.basename(path))[0]
            loaded[mid] = _LoadedMatrix(
                matrix_id=mid,
                tf_name=motif.name or mid,
                length=motif.length,
                pssm=pssm,
                rpssm=rpssm,
                min_score=float(pssm.min),
                max_score=float(pssm.max),
            )
        except Exception:  # noqa: BLE001 - a malformed file must not kill the set
            continue
    return loaded


# Loaded once at import and cached for the process lifetime.
MATRICES: dict[str, _LoadedMatrix] = _load_matrices()


# ---------------------------------------------------------------------------
# Tissue / regulatory subsets (matrix IDs of the bundled set)
# ---------------------------------------------------------------------------

# Neuronal / neural lineage transcription factors.
NEURONAL_MATRICES: tuple[str, ...] = (
    "MA0138.3",  # REST / NRSF - the master neuronal silencer
    "MA1109.2",  # NEUROD1
    "MA1100.3",  # ASCL1
    "MA0678.1",  # OLIG2
    "MA0143.5",  # SOX2
    "MA0069.1",  # PAX6
    "MA0018.5",  # CREB1 (CRE - activity-dependent neuronal transcription)
    "MA0785.2",  # POU2F1
)

# Cardiac / muscle lineage transcription factors.
CARDIAC_MATRICES: tuple[str, ...] = (
    "MA0052.5",  # MEF2A
    "MA0497.2",  # MEF2C
    "MA0035.5",  # GATA1
    "MA0036.4",  # GATA2
    "MA0037.5",  # GATA3
    "MA0499.3",  # MYOD1
    "MA0624.3",  # NFATC1
    "MA0152.3",  # NFATC2
    "MA0090.4",  # TEAD1
)

# Broadly acting / core-promoter regulatory transcription factors.
GENERIC_MATRICES: tuple[str, ...] = (
    "MA0108.3",  # TBP (TATA box)
    "MA0079.5",  # SP1 (GC box)
    "MA0506.3",  # NRF1
    "MA0095.4",  # YY1
    "MA0139.2",  # CTCF
    "MA0105.4",  # NFKB1
    "MA0144.3",  # STAT3
    "MA0106.3",  # TP53
    "MA0024.3",  # E2F1
)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _clean(seq: str) -> str:
    return seq.upper().replace(" ", "").replace("\n", "").replace("\r", "")


def _scores_array(pssm, seq: Seq, n_windows: int) -> np.ndarray:
    """Run PSSM.calculate and normalise its shape to a 1-D array of length
    ``n_windows`` (Biopython returns a bare float when the sequence is exactly
    one window long)."""
    raw = pssm.calculate(seq)
    arr = np.atleast_1d(np.asarray(raw, dtype=float))
    if arr.shape[0] != n_windows:  # defensive; should not happen
        arr = arr[:n_windows]
    return arr


def scan_sequence(
    seq: str,
    threshold: float = DEFAULT_THRESHOLD,
    matrix_ids: list[str] | tuple[str, ...] | None = None,
) -> list[MotifHit]:
    """Scan ``seq`` on both strands and return PWM hits at or above threshold.

    Args:
        seq: DNA sequence. Non-ACGT symbols (N, IUPAC codes) are handled
            gracefully - any window overlapping one scores NaN and cannot hit.
        threshold: Relative-score cutoff in [0, 1]. A window is a hit when its
            log-odds score, normalised between the matrix min and max, is at or
            above this value. Default 0.8.
        matrix_ids: Restrict scanning to these matrix IDs. None scans the full
            bundled set.

    Returns:
        Hits sorted by (start, matrix_id). Empty list for a too-short or
        motif-free sequence - never raises for "no hits".
    """
    cleaned = _clean(seq)
    if not cleaned or not MATRICES:
        return []

    threshold = max(0.0, min(1.0, float(threshold)))
    ids = tuple(matrix_ids) if matrix_ids else tuple(MATRICES.keys())
    bio_seq = Seq(cleaned)
    seq_len = len(cleaned)

    hits: list[MotifHit] = []
    for mid in ids:
        m = MATRICES.get(mid)
        if m is None or m.length > seq_len:
            continue
        span = m.max_score - m.min_score
        if span <= 0:
            continue
        abs_threshold = m.min_score + threshold * span
        n_windows = seq_len - m.length + 1

        for strand, pssm in (("+", m.pssm), ("-", m.rpssm)):
            scores = _scores_array(pssm, bio_seq, n_windows)
            # NaN windows (non-ACGT content) never clear a finite threshold.
            passing = np.where(scores >= abs_threshold)[0]
            for pos in passing:
                score = float(scores[pos])
                if not np.isfinite(score):
                    continue
                rel = (score - m.min_score) / span
                hits.append(
                    MotifHit(
                        matrix_id=m.matrix_id,
                        tf_name=m.tf_name,
                        start=int(pos),
                        end=int(pos) + m.length,
                        strand=strand,
                        score=round(score, 4),
                        relative_score=round(float(rel), 4),
                    )
                )

    hits.sort(key=lambda h: (h.start, h.matrix_id))
    return hits


def available_matrices() -> list[tuple[str, str]]:
    """Return ``(matrix_id, tf_name)`` for every loaded matrix."""
    return [(m.matrix_id, m.tf_name) for m in MATRICES.values()]
