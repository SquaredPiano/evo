"""Tests for primer3-based primer design (service + /api/primers endpoint)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from services.primer_design import design_primers, PrimerDesignResult


# A ~200 bp template with balanced composition so primer3 has room to work.
TEMPLATE = (
    "ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAGCATGCATGCGTACGTAGCTAGCT"
    "AGCATCGATCGATCGGCTAGCATCGGCTAGCGCTAGCGATCGATCGGCTAGCGCTAGCGATC"
    "GATTACGGATTCACTGGCCGTCGTTTTACAACGTCGTGACTGGGAAAACCCTGGCGTTACCC"
    "AACTTAATCGCCTTGCAGCACATCCCCCTTTCGCCA"
)


class TestPrimerDesignService:
    def test_returns_pairs(self):
        result = design_primers(TEMPLATE)
        assert isinstance(result, PrimerDesignResult)
        assert result.method == "primer3"
        assert len(result.pairs) >= 1

    def test_primer_metrics_are_sane(self):
        result = design_primers(TEMPLATE)
        pair = result.pairs[0]
        for primer in (pair.left, pair.right):
            assert set(primer.sequence) <= set("ACGT")
            assert 15 <= primer.length <= 30
            assert 40.0 <= primer.tm_celsius <= 75.0
            assert 0.0 <= primer.gc_percent <= 100.0
            assert primer.hairpin_th is not None

    def test_product_size_within_window(self):
        result = design_primers(TEMPLATE, product_size_min=100, product_size_max=200)
        for pair in result.pairs:
            # Upper bound is clamped to the template length.
            assert pair.product_size <= min(200, len(TEMPLATE))

    def test_tm_within_window(self):
        result = design_primers(TEMPLATE, min_tm=58.0, max_tm=62.0, opt_tm=60.0)
        for pair in result.pairs:
            assert 58.0 <= pair.left.tm_celsius <= 62.0
            assert 58.0 <= pair.right.tm_celsius <= 62.0

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            design_primers("ACGT")

    def test_inconsistent_tm_window_raises(self):
        with pytest.raises(ValueError, match="Tm window"):
            design_primers(TEMPLATE, min_tm=65.0, max_tm=60.0, opt_tm=62.0)


class TestPrimerDesignAPI:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_endpoint_returns_pairs(self, client):
        res = client.post("/api/primers", json={"sequence": TEMPLATE})
        assert res.status_code == 200
        body = res.json()
        assert body["method"] == "primer3"
        assert body["count"] == len(body["pairs"])
        assert body["count"] >= 1
        left = body["pairs"][0]["left"]
        assert "sequence" in left and "tm_celsius" in left and "gc_percent" in left

    def test_endpoint_short_sequence_422(self, client):
        res = client.post("/api/primers", json={"sequence": "ACGTACGT"})
        assert res.status_code == 422

    def test_endpoint_invalid_sequence_422(self, client):
        res = client.post("/api/primers", json={"sequence": "XYZXYZXYZ"})
        assert res.status_code == 422
