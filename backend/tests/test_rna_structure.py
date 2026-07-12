"""Tests for ViennaRNA secondary-structure prediction (service + endpoint)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from services.rna_structure import fold_sequence, _pair_table, _find_hairpins


# A classic stem-loop: a self-complementary stem enclosing a small loop.
HAIRPIN_RNA = "GGGGAAAACCCC"
# A longer designed hairpin.
STEM_LOOP = "GGGAAACCCUUUGGGAAACCC"


class TestFoldService:
    def test_folds_rna(self):
        result = fold_sequence(HAIRPIN_RNA)
        assert result.method == "ViennaRNA MFE (RNA.fold)"
        assert len(result.dot_bracket) == len(HAIRPIN_RNA)
        assert set(result.dot_bracket) <= set(".()")
        assert result.mfe_kcal_mol <= 0.0

    def test_hairpin_detected(self):
        result = fold_sequence(HAIRPIN_RNA)
        assert result.hairpins, "expected at least one hairpin loop"
        h = result.hairpins[0]
        assert h.loop_size >= 3
        assert h.stem_start < h.loop_start <= h.stem_end

    def test_dna_input_flagged_and_converted(self):
        # A DNA input (contains T, no U) is folded as transcribed RNA.
        result = fold_sequence("GGGGAAAATTTTCCCC")
        assert result.input_was_dna is True
        assert "T" not in result.sequence  # T was converted to U
        assert "approximation" in result.note.lower()

    def test_rna_input_not_flagged(self):
        result = fold_sequence(STEM_LOOP)
        assert result.input_was_dna is False

    def test_paired_fraction_range(self):
        result = fold_sequence(STEM_LOOP)
        assert 0.0 <= result.paired_fraction <= 1.0

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            fold_sequence("   ")


class TestStructureHelpers:
    def test_pair_table_balanced(self):
        table = _pair_table("((..))")
        assert table[0] == 5 and table[5] == 0
        assert table[1] == 4 and table[4] == 1
        assert table[2] == -1 and table[3] == -1

    def test_find_hairpins_simple(self):
        hairpins = _find_hairpins("(((...)))")
        # Innermost pair (index 2 with 6) closes a 3-base loop.
        assert any(h.loop_size == 3 for h in hairpins)


class TestSecondaryStructureAPI:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_endpoint_rna(self, client):
        res = client.post("/api/secondary-structure", json={"sequence": STEM_LOOP})
        assert res.status_code == 200
        body = res.json()
        assert body["method"] == "ViennaRNA MFE (RNA.fold)"
        assert body["hairpin_count"] == len(body["hairpins"])
        assert len(body["dot_bracket"]) == body["length"]

    def test_endpoint_dna_flagged(self, client):
        res = client.post("/api/secondary-structure", json={"sequence": "GGGGAAAATTTTCCCC"})
        assert res.status_code == 200
        body = res.json()
        assert body["input_was_dna"] is True

    def test_endpoint_invalid_422(self, client):
        res = client.post("/api/secondary-structure", json={"sequence": "XYZ123"})
        assert res.status_code == 422
