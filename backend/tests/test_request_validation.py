"""Request-layer sequence validation: IUPAC acceptance + genuine rejection."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.requests import (
    VALID_BASES,
    VALID_EDIT_BASES,
    AnalyzeRequest,
    BaseEditRequest,
    _validate_sequence,
)


class TestIUPACAcceptance:
    def test_full_iupac_alphabet_accepted(self):
        # A/C/G/T + N + ambiguity codes must all validate.
        seq = "ATCGNRYSWKMBDHV"
        assert _validate_sequence(seq) == seq
        assert VALID_BASES == frozenset("ATCGNRYSWKMBDHV")

    def test_ambiguous_imported_sequence_analyzes(self):
        # A legitimately-ambiguous sequence must not be rejected at /api/analyze.
        req = AnalyzeRequest(sequence="ATCGRYSWKMBDHVN")
        assert req.sequence == "ATCGRYSWKMBDHVN"

    def test_lowercase_and_whitespace_normalized(self):
        assert AnalyzeRequest(sequence="  atcgryn  ").sequence == "ATCGRYN"


class TestGenuineRejection:
    def test_invalid_characters_rejected(self):
        with pytest.raises(ValueError, match="Invalid nucleotides"):
            _validate_sequence("ATCGZ")

    def test_analyze_rejects_junk(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest(sequence="XYZ123")

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            _validate_sequence("   ")


class TestEditBaseStaysUnambiguous:
    def test_edit_base_rejects_ambiguity_code(self):
        # Point edits must resolve to a concrete base, not an IUPAC ambiguity.
        assert VALID_EDIT_BASES == frozenset("ATCGN")
        with pytest.raises(ValidationError):
            BaseEditRequest(session_id="s", candidate_id=0, position=0, new_base="R")

    def test_edit_base_accepts_concrete_base(self):
        req = BaseEditRequest(session_id="s", candidate_id=0, position=0, new_base="a")
        assert req.new_base == "A"
