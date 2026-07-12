"""Unit tests for PWM motif scanning against the bundled JASPAR matrices."""

from __future__ import annotations

import random

import pytest

from services.motifs import (
    CARDIAC_MATRICES,
    DEFAULT_THRESHOLD,
    MATRICES,
    MotifHit,
    NEURONAL_MATRICES,
    available_matrices,
    scan_sequence,
)


def test_matrices_loaded():
    # The curated JASPAR CORE 2024 set is bundled and parsed at import.
    assert len(MATRICES) >= 20
    # Every loaded matrix exposes an ID and a TF name.
    for mid, tf in available_matrices():
        assert mid and tf
    # A couple of anchor matrices we rely on downstream.
    assert "MA0108.3" in MATRICES  # TBP / TATA
    assert "MA0035.5" in MATRICES  # GATA1


def test_canonical_tata_hits_tbp():
    # A canonical TATA box embedded in neutral flanks yields a TBP hit.
    seq = "CGACTGCAGT" + "TATAAAA" + "GGCCTTAGCA"
    hits = scan_sequence(seq, threshold=DEFAULT_THRESHOLD, matrix_ids=["MA0108.3"])
    assert hits, "expected at least one TBP PWM hit on a canonical TATA box"
    assert all(isinstance(h, MotifHit) for h in hits)
    assert any(h.tf_name.upper() == "TBP" for h in hits)
    # The exact-consensus window should be a very strong (near-max) match.
    best = max(hits, key=lambda h: h.relative_score)
    assert best.relative_score >= 0.9
    # Coordinates point at the embedded motif and stay within bounds.
    assert best.end - best.start == MATRICES["MA0108.3"].length
    assert 0 <= best.start < best.end <= len(seq)


def test_gata_core_hits_gata_matrix():
    # Tandem GATA cores yield GATA-family hits on the cardiac subset.
    seq = "C" * 10 + "AGATAAGATAAG" + "C" * 10
    hits = scan_sequence(seq, threshold=DEFAULT_THRESHOLD, matrix_ids=list(CARDIAC_MATRICES))
    assert hits
    assert any("GATA" in h.tf_name.upper() for h in hits)


def test_both_strands_scanned():
    # The scanner must report hits on BOTH strands. The TATA consensus reads on
    # the + strand for TBP, while a forward GATA core reads on the - strand for
    # MA0035.5 (the JASPAR matrix is stored in reverse orientation).
    plus = scan_sequence("CGT" + "TATAAAA" + "CGT", matrix_ids=["MA0108.3"])
    assert any(h.strand == "+" for h in plus)
    minus = scan_sequence(
        "C" * 10 + "AGATAAGATAAG" + "C" * 10, matrix_ids=list(CARDIAC_MATRICES)
    )
    assert any(h.strand == "-" for h in minus)


def test_random_sequence_has_few_hits():
    # A random sequence yields far fewer hits than a motif-dense one, and hit
    # density stays low relative to the number of windows scanned.
    rng = random.Random(20240711)
    rand_seq = "".join(rng.choice("ACGT") for _ in range(300))
    hits = scan_sequence(rand_seq, threshold=0.85)
    # Both-strand scan over ~300 windows x >20 matrices is tens of thousands of
    # windows; a strict threshold should keep confident hits sparse.
    assert len(hits) < 40


def test_handles_n_and_empty():
    # N / ambiguity codes never crash and never produce a hit for their window.
    assert scan_sequence("") == []
    assert scan_sequence("NNNNNNNNNNNNNN") == []
    # A clean TATA flanked by Ns still resolves on the clean window.
    hits = scan_sequence("NNNN" + "TATAAAA" + "NNNN", matrix_ids=["MA0108.3"])
    assert any(h.tf_name.upper() == "TBP" for h in hits)
    for h in hits:
        # No hit window may overlap the N runs (positions 0-3 and 11-14).
        assert h.start >= 4 and h.end <= 11


def test_relative_score_bounds():
    seq = "GCGCGCCAATCAGGGGCGGGGCGGGGCTATAAAAGGCGCGCAGATAAGATAAG"
    for h in scan_sequence(seq):
        assert DEFAULT_THRESHOLD <= h.relative_score <= 1.0 + 1e-9
        assert h.strand in ("+", "-")


def test_threshold_monotonic():
    seq = "GCGCGCCAATCAGGGGCGGGGCGGGGCTATAAAAGGCGCGCAGATAAGATAAG"
    lenient = scan_sequence(seq, threshold=0.75)
    strict = scan_sequence(seq, threshold=0.9)
    assert len(strict) <= len(lenient)


def test_subsets_are_bundled():
    for subset in (NEURONAL_MATRICES, CARDIAC_MATRICES):
        assert all(mid in MATRICES for mid in subset)
