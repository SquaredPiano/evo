"""Tests for protein physicochemical parameters."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.protein_params import (
    compute_protein_params,
    gravy,
    molecular_weight,
    theoretical_pi,
)


class TestMolecularWeight:
    def test_met_enkephalin(self) -> None:
        # YGGFM (Met-enkephalin): ExPASy ProtParam average MW = 573.67 Da.
        assert molecular_weight("YGGFM") == pytest.approx(573.66, abs=0.05)

    def test_single_alanine(self) -> None:
        # Ala residue (71.0788) + water (18.01524).
        assert molecular_weight("A") == pytest.approx(89.09, abs=0.01)


class TestGravy:
    def test_met_enkephalin_gravy(self) -> None:
        # (Y -1.3, G -0.4, G -0.4, F 2.8, M 1.9) / 5 = 0.52.
        assert gravy("YGGFM") == pytest.approx(0.52, abs=0.001)

    def test_hydrophobic_positive(self) -> None:
        assert gravy("IIVV") > 0

    def test_hydrophilic_negative(self) -> None:
        assert gravy("RRKK") < 0


class TestPI:
    def test_acidic_peptide_low_pi(self) -> None:
        assert theoretical_pi("DDEE") < 4.5

    def test_basic_peptide_high_pi(self) -> None:
        assert theoretical_pi("KKRR") > 9.5


class TestComputeProteinParams:
    def test_full_report(self) -> None:
        r = compute_protein_params("YGGFM")
        assert r.length == 5
        assert r.molecular_weight == pytest.approx(573.66, abs=0.05)
        assert r.gravy == pytest.approx(0.52, abs=0.001)
        assert r.aromaticity == pytest.approx(0.4, abs=0.001)  # Y + F of 5
        assert abs(sum(r.composition.values()) - 1.0) < 1e-6

    def test_ignores_non_standard(self) -> None:
        r = compute_protein_params("YGGFMX")
        assert r.unknown_residues == 1
        assert r.length == 5

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_protein_params("   ")
