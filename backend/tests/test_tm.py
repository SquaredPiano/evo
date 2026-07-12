"""Tests for melting-temperature (Tm) calculation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.tm import compute_tm, nearest_neighbor_tm, wallace_tm


class TestWallace:
    def test_wallace_rule(self) -> None:
        # 2*(A+T) + 4*(G+C); 20-mer, 50% GC -> 2*10 + 4*10 = 60.
        assert wallace_tm("ATGCATGCATGCATGCATGC") == 60.0

    def test_all_gc(self) -> None:
        assert wallace_tm("GCGCGCGC") == 32.0  # 4 * 8


class TestNearestNeighbor:
    def test_20mer_in_expected_range(self) -> None:
        # A well-behaved ~50% GC 20-mer should land around 55-60 C at
        # default 50 mM Na+ / 0.25 uM oligo (SantaLucia 1998).
        tm, dh, ds = nearest_neighbor_tm("ATGCATGCATGCATGCATGC")
        assert 53.0 <= tm <= 62.0
        assert dh < 0  # duplex formation is enthalpically favorable

    def test_gc_rich_is_hotter(self) -> None:
        gc_rich, _, _ = nearest_neighbor_tm("GCGCGCGCGCGCGCGCGCGC")
        at_rich, _, _ = nearest_neighbor_tm("ATATATATATATATATATAT")
        assert gc_rich > at_rich

    def test_higher_salt_raises_tm(self) -> None:
        low, _, _ = nearest_neighbor_tm("ATGCATGCATGCATGCATGC", na_molar=0.01)
        high, _, _ = nearest_neighbor_tm("ATGCATGCATGCATGCATGC", na_molar=1.0)
        assert high > low

    def test_rejects_ambiguous(self) -> None:
        with pytest.raises(ValueError):
            nearest_neighbor_tm("ATGCNNATGC")


class TestComputeTm:
    def test_headline_is_nn_for_normal_oligo(self) -> None:
        r = compute_tm("GTAAAACGACGGCCAGTGCCA")
        assert r.method == "nearest-neighbor"
        assert r.tm_nn_celsius is not None
        assert 55.0 <= r.tm_celsius <= 65.0
        assert r.tm_wallace_celsius > 0

    def test_falls_back_to_wallace_on_ambiguity(self) -> None:
        r = compute_tm("ATGCNNNNATGC")
        assert r.method == "wallace"
        assert r.tm_nn_celsius is None
        assert r.tm_celsius == r.tm_wallace_celsius

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_tm("   ")
