"""CRISPR off-target scoring against a SUPPLIED reference sequence.

This module scores candidate off-target sites for an SpCas9-style guide RNA
using two published models:

  1. **CFD (Cutting Frequency Determination)** - Doench, Fusi, Sullender et al.,
     Nature Biotechnology 34, 184-191 (2016). Per-position rNA:dDNA mismatch
     weights plus a PAM weight, multiplied together. The weight tables are the
     ones distributed with the Doench 2016 calculator, bundled under
     ``backend/data/crispr/`` (see SOURCE.txt for provenance).

  2. **MIT specificity (single-guide hit) score** - Hsu, Scott, Weinstein et al.,
     Nature Biotechnology 31, 827-832 (2013). Position-weighted mismatch penalty
     with mean-pairwise-distance and mismatch-count terms. The aggregate guide
     specificity is the MIT-style ``100 / (100 + sum of off-target hit scores)``.

IMPORTANT SCOPE / HONEST LABELING
---------------------------------
This searches ONLY the reference sequence you supply. It is NOT a genome-wide
off-target scan and gives NO genome-wide guarantee. To assess off-targets across
a whole genome you need a genome-wide index (e.g. Cas-OFFinder / CRISPOR against
a full assembly), which requires multi-GB data that is out of scope here. Every
score below is computed strictly against the supplied reference.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from services.translation import reverse_complement

logger = logging.getLogger(__name__)

GUIDE_LENGTH = 20  # SpCas9 spacer length that the CFD/MIT tables are defined for

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "crispr"

# IUPAC ambiguity codes -> the set of concrete bases they match.
_IUPAC: dict[str, frozenset[str]] = {
    "A": frozenset("A"), "C": frozenset("C"), "G": frozenset("G"), "T": frozenset("T"),
    "R": frozenset("AG"), "Y": frozenset("CT"), "S": frozenset("GC"), "W": frozenset("AT"),
    "K": frozenset("GT"), "M": frozenset("AC"), "B": frozenset("CGT"), "D": frozenset("AGT"),
    "H": frozenset("ACT"), "V": frozenset("ACG"), "N": frozenset("ACGT"),
}

_COMPLEMENT = {"A": "T", "C": "G", "G": "C", "T": "A", "U": "A"}

# MIT single-guide hit-score position weights (Hsu 2013). Index 0 is the
# PAM-distal position (protospacer position 1), index 19 is PAM-proximal
# (position 20, adjacent to the PAM). Higher weight = a mismatch there is more
# penalizing.
_MIT_WEIGHTS = (
    0.0, 0.0, 0.014, 0.0, 0.0, 0.395, 0.317, 0.0, 0.389, 0.079,
    0.445, 0.508, 0.613, 0.851, 0.732, 0.828, 0.615, 0.804, 0.685, 0.583,
)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Mismatch:
    """A single guide/target mismatch along the protospacer.

    ``position`` is 1..20 with 20 being the PAM-proximal end (adjacent to the
    PAM), matching the CFD table convention.
    """
    position: int
    guide_base: str   # base on the guide (spacer), 5'->3'
    target_base: str  # base on the protospacer strand of the reference


@dataclass(frozen=True)
class OffTargetSite:
    """A candidate off-target site found in the supplied reference."""
    position: int            # 0-based start of the protospacer on the forward strand
    strand: str              # "+" or "-"
    protospacer: str         # matched 20 nt protospacer, read 5'->3' on ``strand``
    pam: str                 # matched PAM, read 5'->3' on ``strand``
    mismatch_count: int
    mismatches: list[Mismatch]
    cfd_score: float         # 0..1 (Doench 2016)
    mit_score: float         # 0..100 single-guide hit score (Hsu 2013)


@dataclass
class OffTargetReport:
    """Complete off-target analysis against the supplied reference."""
    guide: str
    pam_pattern: str
    reference_length: int
    max_mismatches: int
    strands_searched: str            # always "both"
    total_sites: int                 # number of candidate sites (incl. perfect on-target matches)
    off_target_count: int            # candidate sites with >= 1 mismatch
    specificity_score: float         # MIT-style aggregate, 0..100 (100 = most specific)
    sites: list[OffTargetSite] = field(default_factory=list)
    note: str = ""
    method: str = "CFD (Doench 2016) + MIT (Hsu 2013), supplied-reference only"


# ---------------------------------------------------------------------------
# CFD data loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_cfd_tables() -> tuple[dict[str, float], dict[str, float]]:
    """Load the Doench 2016 CFD mismatch and PAM weight tables (cached)."""
    with (_DATA_DIR / "cfd_mismatch_scores.json").open() as fh:
        mm = {k: float(v) for k, v in json.load(fh).items()}
    with (_DATA_DIR / "cfd_pam_scores.json").open() as fh:
        pam = {k: float(v) for k, v in json.load(fh).items()}
    return mm, pam


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def cfd_score(guide: str, protospacer: str, pam: str) -> float:
    """CFD score (Doench 2016) for a guide against a 20 nt protospacer + PAM.

    ``guide`` and ``protospacer`` are the spacer and the matched off-target
    protospacer (same sense/strand), both 20 nt. ``pam`` is the PAM as it
    appears 3' of the protospacer (e.g. "AGG"); only its last two nucleotides
    are scored, matching the Doench convention.

    A perfect match with a canonical GG PAM returns 1.0.
    """
    if len(guide) != GUIDE_LENGTH or len(protospacer) != GUIDE_LENGTH:
        raise ValueError("CFD requires a 20 nt guide and a 20 nt protospacer")
    mm_scores, pam_scores = _load_cfd_tables()

    guide_rna = guide.upper().replace("T", "U")
    proto_rna = protospacer.upper().replace("T", "U")

    score = 1.0
    for i in range(GUIDE_LENGTH):
        g = guide_rna[i]
        o = proto_rna[i]
        if g == o:
            continue
        # dDNA base is the base on the target strand = complement of the
        # protospacer-strand (off-target) base.
        d_base = _COMPLEMENT.get(o, "N")
        key = f"r{g}:d{d_base},{i + 1}"
        # Any base we cannot resolve (e.g. an N in the reference) is treated as
        # a fully disruptive mismatch (weight 0) rather than silently ignored.
        score *= mm_scores.get(key, 0.0)

    pam_key = pam.upper().replace("U", "T")[-2:]
    score *= pam_scores.get(pam_key, 0.0)
    return score


def mit_hit_score(mismatch_positions: list[int]) -> float:
    """MIT single-guide off-target hit score (Hsu 2013), 0..100.

    ``mismatch_positions`` are 1-based protospacer positions (20 = PAM-proximal),
    matching :class:`Mismatch`. A perfect match (no mismatches) returns 100.
    """
    # Convert to 0-based indices into the PAM-distal..PAM-proximal weight array.
    idx = sorted(p - 1 for p in mismatch_positions)
    n = len(idx)

    term1 = 1.0
    for i in idx:
        term1 *= 1.0 - _MIT_WEIGHTS[i]

    if n < 2:
        term2 = 1.0
    else:
        dists = [idx[k] - idx[k - 1] for k in range(1, n)]
        mean_dist = sum(dists) / len(dists)
        term2 = 1.0 / (((19.0 - mean_dist) / 19.0) * 4.0 + 1.0)

    term3 = 1.0 if n == 0 else 1.0 / (n * n)
    return term1 * term2 * term3 * 100.0


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _pam_matches(pam_pattern: str, candidate: str) -> bool:
    """True when ``candidate`` satisfies the IUPAC ``pam_pattern``."""
    if len(candidate) != len(pam_pattern):
        return False
    for pat, base in zip(pam_pattern, candidate):
        allowed = _IUPAC.get(pat)
        if allowed is None or base not in allowed:
            return False
    return True


def _scan_strand(
    guide: str,
    pam_pattern: str,
    ref: str,
    strand: str,
    ref_len: int,
    max_mismatches: int,
) -> list[OffTargetSite]:
    """Scan one strand (``ref`` already oriented 5'->3') for candidate sites."""
    g_len = len(guide)
    p_len = len(pam_pattern)
    window = g_len + p_len
    sites: list[OffTargetSite] = []

    for i in range(len(ref) - window + 1):
        proto = ref[i:i + g_len]
        pam = ref[i + g_len:i + window]
        if not _pam_matches(pam_pattern, pam):
            continue

        mismatches: list[Mismatch] = []
        for j in range(g_len):
            if guide[j] != proto[j]:
                mismatches.append(Mismatch(position=j + 1, guide_base=guide[j], target_base=proto[j]))
                if len(mismatches) > max_mismatches:
                    break
        if len(mismatches) > max_mismatches:
            continue

        # Forward-strand 0-based start of the protospacer.
        if strand == "+":
            fwd_pos = i
        else:
            fwd_pos = ref_len - (i + window)

        cfd = cfd_score(guide, proto, pam)
        mit = mit_hit_score([m.position for m in mismatches])
        sites.append(OffTargetSite(
            position=fwd_pos,
            strand=strand,
            protospacer=proto,
            pam=pam,
            mismatch_count=len(mismatches),
            mismatches=mismatches,
            cfd_score=cfd,
            mit_score=mit,
        ))
    return sites


def analyze_offtargets(
    guide: str,
    reference: str,
    pam: str = "NGG",
    max_mismatches: int = 4,
    max_sites: int = 200,
) -> OffTargetReport:
    """Score CRISPR off-target sites for ``guide`` against a SUPPLIED reference.

    Args:
        guide: 20 nt spacer/protospacer (SpCas9). ACGT only.
        reference: the DNA sequence to search (both strands are scanned).
        pam: IUPAC PAM pattern located 3' of the protospacer (default "NGG").
        max_mismatches: maximum protospacer mismatches to accept (default 4).
        max_sites: maximum number of sites to return (ranked by CFD, then MIT).
            The aggregate specificity is computed over ALL off-targets found,
            not just the returned subset.

    Returns:
        OffTargetReport. ``specificity_score`` is the MIT-style aggregate
        ``100 / (100 + sum of off-target MIT hit scores)`` on a 0..100 scale,
        where the sum excludes perfect on-target (0-mismatch) matches.

    This is off-target scoring against the supplied reference ONLY. It does not
    scan a genome and makes no genome-wide claim.
    """
    guide = guide.upper().strip()
    pam = pam.upper().strip()
    reference = "".join(reference.upper().split())

    if len(guide) != GUIDE_LENGTH:
        raise ValueError(f"Guide must be exactly {GUIDE_LENGTH} nt (SpCas9 spacer); got {len(guide)}")
    bad_guide = set(guide) - set("ACGT")
    if bad_guide:
        raise ValueError(f"Guide must be unambiguous ACGT; invalid bases: {sorted(bad_guide)}")
    if not pam:
        raise ValueError("PAM pattern must not be empty")
    bad_pam = set(pam) - set(_IUPAC)
    if bad_pam:
        raise ValueError(f"PAM has invalid IUPAC codes: {sorted(bad_pam)}")
    if max_mismatches < 0:
        raise ValueError("max_mismatches must be >= 0")

    ref_len = len(reference)
    window = GUIDE_LENGTH + len(pam)
    if ref_len < window:
        return OffTargetReport(
            guide=guide,
            pam_pattern=pam,
            reference_length=ref_len,
            max_mismatches=max_mismatches,
            strands_searched="both",
            total_sites=0,
            off_target_count=0,
            specificity_score=100.0,
            sites=[],
            note=(
                f"Reference ({ref_len} nt) is shorter than one guide+PAM window "
                f"({window} nt); no sites to score. Off-target scoring against the "
                "supplied reference only, not a genome-wide scan."
            ),
        )

    rc = reverse_complement(reference)
    sites = _scan_strand(guide, pam, reference, "+", ref_len, max_mismatches)
    sites += _scan_strand(guide, pam, rc, "-", ref_len, max_mismatches)

    # Aggregate MIT specificity over off-targets (>= 1 mismatch); perfect
    # on-target matches are the intended cut site and are excluded from the sum.
    off_targets = [s for s in sites if s.mismatch_count >= 1]
    hit_sum = sum(s.mit_score for s in off_targets)
    specificity = 100.0 * (100.0 / (100.0 + hit_sum))

    # Rank by CFD then MIT (highest off-target risk first).
    sites.sort(key=lambda s: (s.cfd_score, s.mit_score), reverse=True)

    note = (
        f"CFD (Doench 2016) + MIT (Hsu 2013) off-target scoring against the "
        f"supplied {ref_len} nt reference (both strands), not a genome-wide scan. "
        f"Found {len(sites)} site(s) within {max_mismatches} mismatch(es) of "
        f"{guide}+{pam}; {len(off_targets)} are off-targets (>= 1 mismatch)."
    )

    return OffTargetReport(
        guide=guide,
        pam_pattern=pam,
        reference_length=ref_len,
        max_mismatches=max_mismatches,
        strands_searched="both",
        total_sites=len(sites),
        off_target_count=len(off_targets),
        specificity_score=round(specificity, 2),
        sites=sites[:max_sites],
        note=note,
    )
