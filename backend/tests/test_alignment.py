"""Tests for the pure-Python pairwise aligner (services.alignment).

Covers global (Needleman-Wunsch) and local (Smith-Waterman) alignment plus the
coordinate lift map: identity, a single SNP, a single insertion, a single
deletion, and lifting a coordinate across an indel (the case that motivated the
module - reference variant coordinates landing in a candidate frame).
"""

from __future__ import annotations

import pytest

from services.alignment import (
    AlignmentTooLargeError,
    MAX_MATRIX_CELLS,
    needleman_wunsch,
    smith_waterman,
    lift_position,
)


# ---------------------------------------------------------------------------
# Global alignment: structure of the aligned strings
# ---------------------------------------------------------------------------

class TestGlobalAlignmentShape:
    def test_identity(self):
        aln = needleman_wunsch("ACGTACGT", "ACGTACGT")
        assert aln.aligned_a == "ACGTACGT"
        assert aln.aligned_b == "ACGTACGT"
        assert "-" not in aln.aligned_a and "-" not in aln.aligned_b
        # Every position maps to itself.
        assert list(aln.a_to_b) == list(range(8))
        assert list(aln.b_to_a) == list(range(8))

    def test_single_snp(self):
        aln = needleman_wunsch("ACGTACGT", "ACGAACGT")
        # No gaps for a single substitution.
        assert "-" not in aln.aligned_a and "-" not in aln.aligned_b
        assert len(aln.aligned_a) == 8
        # Identity coordinate mapping is preserved across a mismatch.
        assert list(aln.a_to_b) == list(range(8))

    def test_single_insertion_in_b(self):
        # B has one extra base in the middle -> gap in A.
        aln = needleman_wunsch("ACGTACGT", "ACGTTACGT")
        assert len(aln.aligned_a) == len(aln.aligned_b)
        assert aln.aligned_a.count("-") == 1
        assert aln.aligned_b.count("-") == 0

    def test_single_deletion_in_b(self):
        # B is missing one base -> gap in B.
        aln = needleman_wunsch("ACGTTACGT", "ACGTACGT")
        assert len(aln.aligned_a) == len(aln.aligned_b)
        assert aln.aligned_b.count("-") == 1
        assert aln.aligned_a.count("-") == 0

    def test_empty_inputs(self):
        aln = needleman_wunsch("", "")
        assert aln.aligned_a == "" and aln.aligned_b == ""
        aln2 = needleman_wunsch("ACGT", "")
        assert aln2.aligned_b == "----"
        assert all(x is None for x in aln2.a_to_b)


# ---------------------------------------------------------------------------
# Coordinate lifting
# ---------------------------------------------------------------------------

class TestCoordinateLift:
    def test_identity_lift(self):
        aln = needleman_wunsch("ACGTACGT", "ACGTACGT")
        for i in range(8):
            assert aln.lift_a_to_b(i) == i

    def test_lift_across_insertion(self):
        # candidate (B) has 2 extra bases ("TT") inserted between the C-run and
        # the G-run of the reference (A). The insertion is flanked by distinct
        # bases so the gap placement (and thus the lift) is unambiguous.
        ref = "AAACCCGGG"
        cand = "AAACCCTTGGG"  # "TT" inserted between CCC and GGG
        aln = needleman_wunsch(ref, cand)
        # Before the insertion, coordinates are unchanged.
        assert aln.lift_a_to_b(0) == 0
        assert aln.lift_a_to_b(5) == 5
        # After the insertion, reference positions shift by +2.
        assert aln.lift_a_to_b(6) == 8
        assert aln.lift_a_to_b(8) == 10

    def test_lift_across_deletion(self):
        # candidate (B) is missing 2 bases ("TT") that exist in the reference.
        ref = "AAACCCTTGGG"
        cand = "AAACCCGGG"  # "TT" deleted between CCC and GGG
        aln = needleman_wunsch(ref, cand)
        assert aln.lift_a_to_b(5) == 5
        # The two deleted reference bases have no candidate counterpart.
        assert aln.lift_a_to_b(6) is None
        assert aln.lift_a_to_b(7) is None
        # Position after the deletion resumes, shifted by -2.
        assert aln.lift_a_to_b(8) == 6

    def test_lift_position_convenience(self):
        ref = "AAACCCGGG"
        cand = "AAACCCTTGGG"
        assert lift_position(ref, cand, 6) == 8
        assert lift_position(ref, cand, 0) == 0

    def test_lift_out_of_range(self):
        aln = needleman_wunsch("ACGT", "ACGT")
        assert aln.lift_a_to_b(-1) is None
        assert aln.lift_a_to_b(99) is None


# ---------------------------------------------------------------------------
# Local alignment (Smith-Waterman)
# ---------------------------------------------------------------------------

class TestLocalAlignment:
    def test_local_finds_common_core(self):
        # Shared core "ACGTACGT" flanked by unrelated ends.
        a = "TTTTACGTACGTTTTT"
        b = "GGGACGTACGTGG"
        aln = smith_waterman(a, b)
        assert "ACGTACGT" in aln.aligned_a.replace("-", "")
        assert aln.score > 0
        # The aligned block is a proper sub-range, not the whole sequence.
        assert aln.a_start > 0
        assert aln.a_end <= len(a)

    def test_local_lift_within_block(self):
        a = "TTTTACGTACGT"
        b = "GGGACGTACGT"
        aln = smith_waterman(a, b)
        # A position inside the shared core lifts; a flanking one does not.
        core_pos = a.index("ACGTACGT")
        assert aln.lift_a_to_b(core_pos) is not None
        assert aln.lift_a_to_b(0) is None  # in the "TTTT" flank, unaligned


# ---------------------------------------------------------------------------
# Length guard
# ---------------------------------------------------------------------------

class TestLengthGuard:
    def test_oversized_raises(self):
        big = "A" * (MAX_MATRIX_CELLS // 1000 + 1)
        other = "C" * 1001
        with pytest.raises(AlignmentTooLargeError):
            needleman_wunsch(big, other)

    def test_lift_position_falls_back_to_none_when_too_large(self):
        big = "A" * (MAX_MATRIX_CELLS // 1000 + 1)
        other = "C" * 1001
        # Convenience helper degrades gracefully instead of raising.
        assert lift_position(big, other, 0) is None
