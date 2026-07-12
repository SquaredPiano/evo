"""Tests for the improved restriction-site scan.

Covers the additions over the old forward-strand exact-match scan:
both-strand scanning, IUPAC ambiguity expansion, cut coordinates, and
cutter multiplicity (single vs multi cutter).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.agent.tools import (
    _is_palindrome,
    _iupac_find,
    _iupac_revcomp,
    tool_restriction_sites,
)


class TestIupacHelpers:
    def test_revcomp_plain(self) -> None:
        assert _iupac_revcomp("GAATTC") == "GAATTC"  # palindrome
        assert _iupac_revcomp("GGGAAA") == "TTTCCC"

    def test_revcomp_ambiguity(self) -> None:
        # W = A/T (self-complementary code); R=A/G -> Y=C/T.
        assert _iupac_revcomp("GAWTC") == "GAWTC"
        assert _iupac_revcomp("ARC") == "GYT"

    def test_iupac_find_exact(self) -> None:
        assert _iupac_find("ATCGGAATTCATCG", "GAATTC") == [4]

    def test_iupac_find_degenerate(self) -> None:
        # GAWTC matches both GAATC and GATTC.
        hits = _iupac_find("GAATCXGATTC".replace("X", "A"), "GAWTC")
        assert hits == [0, 6]

    def test_iupac_find_overlapping(self) -> None:
        assert _iupac_find("AAAA", "AA") == [0, 1, 2]

    def test_palindrome_detection(self) -> None:
        assert _is_palindrome("GAATTC") is True
        assert _is_palindrome("GGGAAA") is False


class TestRestrictionScan:
    @pytest.mark.asyncio
    async def test_reports_cut_position(self) -> None:
        # EcoRI G^AATTC at index 4 -> top-strand cut at 4 + 1 = 5.
        result = await tool_restriction_sites(
            candidate_id=0, sequence="ATCGGAATTCATCG", enzymes=["EcoRI"],
        )
        sites = result.structured_result["sites"]
        assert len(sites) == 1
        ecori = sites[0]
        assert ecori["positions"] == [4]
        assert ecori["cut_offset"] == 1
        assert ecori["cut_positions"] == [5]

    @pytest.mark.asyncio
    async def test_single_cutter_multiplicity(self) -> None:
        result = await tool_restriction_sites(
            candidate_id=0, sequence="ATCGGAATTCATCGTTTT", enzymes=["EcoRI"],
        )
        ecori = result.structured_result["sites"][0]
        assert ecori["multiplicity"] == "single"
        assert ecori["is_single_cutter"] is True
        assert result.structured_result["single_cutters"] == ["EcoRI"]

    @pytest.mark.asyncio
    async def test_multi_cutter_multiplicity(self) -> None:
        result = await tool_restriction_sites(
            candidate_id=0, sequence="GAATTCAAAGAATTC", enzymes=["EcoRI"],
        )
        ecori = result.structured_result["sites"][0]
        assert ecori["count"] == 2
        assert ecori["multiplicity"] == "multi"
        assert ecori["is_single_cutter"] is False
        assert result.structured_result["single_cutters"] == []

    @pytest.mark.asyncio
    async def test_palindrome_not_double_counted(self) -> None:
        # EcoRI is palindromic: one physical site must count once, not twice.
        result = await tool_restriction_sites(
            candidate_id=0, sequence="AAAGAATTCAAA", enzymes=["EcoRI"],
        )
        ecori = result.structured_result["sites"][0]
        assert ecori["palindromic"] is True
        assert ecori["count"] == 1

    @pytest.mark.asyncio
    async def test_note_mentions_both_strands(self) -> None:
        result = await tool_restriction_sites(
            candidate_id=0, sequence="ATCGGAATTCATCG",
        )
        assert "both strands" in result.note

    @pytest.mark.asyncio
    async def test_backward_compatible_fields_present(self) -> None:
        # The ToolResultCard contract fields must still be present.
        result = await tool_restriction_sites(
            candidate_id=0, sequence="ATCGGAATTCATCG",
        )
        sr = result.structured_result
        assert sr["tool"] == "restriction_sites"
        assert {"sequence_length", "enzymes_checked", "total_sites", "sites"} <= sr.keys()
        for site in sr["sites"]:
            assert {"enzyme", "recognition_site", "positions", "count"} <= site.keys()
