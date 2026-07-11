"""Tests for the ClinVar scoring-calibration harness."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services.calibration import (
    CalibrationReport,
    ScoredVariant,
    _aligned,
    _classify,
    calibrate_gene,
    calibrate_variants,
    compute_auroc,
)
from services.variant_annotation import AnnotationResult, VariantAnnotation


# --- compute_auroc -------------------------------------------------------

class TestComputeAuroc:
    def test_perfect_separation(self):
        # positives score higher than all negatives
        labels = [1, 1, 0, 0]
        scores = [0.9, 0.8, 0.2, 0.1]
        assert compute_auroc(labels, scores) == 1.0

    def test_perfectly_wrong(self):
        labels = [1, 1, 0, 0]
        scores = [0.1, 0.2, 0.8, 0.9]
        assert compute_auroc(labels, scores) == 0.0

    def test_random_is_half(self):
        labels = [1, 0, 1, 0]
        scores = [0.5, 0.5, 0.5, 0.5]  # all ties → 0.5
        assert compute_auroc(labels, scores) == 0.5

    def test_single_class_returns_none(self):
        assert compute_auroc([1, 1, 1], [0.1, 0.2, 0.3]) is None
        assert compute_auroc([0, 0], [0.1, 0.2]) is None

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            compute_auroc([1, 0], [0.5])

    def test_tie_aware_partial(self):
        # one positive tied with one negative, one clear ordering
        labels = [1, 0, 1, 0]
        scores = [0.6, 0.6, 0.9, 0.1]
        auroc = compute_auroc(labels, scores)
        assert 0.5 < auroc <= 1.0


# --- classify / align helpers -------------------------------------------

class TestHelpers:
    def test_classify(self):
        assert _classify("Pathogenic") == "pathogenic"
        assert _classify("Likely pathogenic") == "pathogenic"
        assert _classify("Benign") == "benign"
        assert _classify("Likely benign") == "benign"
        assert _classify("Uncertain significance") is None
        assert _classify("Conflicting interpretations") is None

    def test_aligned_matches_ref_base(self):
        seq = "ATGCGT"
        v = VariantAnnotation(2, "G", "A", "Pathogenic", "", "1", "", "snv", 2, None)
        assert _aligned(v, seq) is True

    def test_aligned_rejects_mismatched_ref(self):
        seq = "ATGCGT"
        v = VariantAnnotation(2, "T", "A", "Pathogenic", "", "1", "", "snv", 2, None)
        assert _aligned(v, seq) is False

    def test_aligned_rejects_out_of_range(self):
        seq = "ATGC"
        v = VariantAnnotation(99, "A", "G", "Pathogenic", "", "1", "", "snv", 2, None)
        assert _aligned(v, seq) is False


# --- calibrate_variants with a fake, label-correlated engine -------------

class _FakeService:
    """Engine where pathogenic alt bases get a strongly negative delta and
    benign ones get a mildly positive delta — so a correct harness yields
    AUROC = 1.0."""

    def __init__(self, deltas: dict[int, float]):
        self._deltas = deltas

    async def score_mutation(self, sequence, position, alt_base):
        from models.domain import Impact, MutationScore
        delta = self._deltas[position]
        return MutationScore(
            position=position,
            reference_base=sequence[position],
            alternate_base=alt_base,
            delta_likelihood=delta,
            predicted_impact=Impact.from_delta(delta),
        )

    async def health(self):
        return {"inference_mode": "local"}


@pytest.mark.asyncio
async def test_calibrate_variants_directionality():
    seq = "ATGCGTACGT"
    variants = [
        VariantAnnotation(1, "T", "A", "Pathogenic", "", "p1", "", "snv", 2, None),
        VariantAnnotation(3, "C", "G", "Benign", "", "b1", "", "snv", 2, None),
    ]
    # pathogenic → negative delta → high pathogenicity score
    svc = _FakeService({1: -0.9, 3: 0.2})
    scored = await calibrate_variants(svc, seq, variants)
    assert len(scored) == 2
    patho = next(s for s in scored if s.label == "pathogenic")
    benign = next(s for s in scored if s.label == "benign")
    assert patho.pathogenicity_score > benign.pathogenicity_score
    labels = [1 if s.label == "pathogenic" else 0 for s in scored]
    scores = [s.pathogenicity_score for s in scored]
    assert compute_auroc(labels, scores) == 1.0


@pytest.mark.asyncio
async def test_calibrate_gene_end_to_end_with_mocked_clinvar():
    seq = "ATGCGTACGTACGT"

    def _fake_annotate(gene, sequence=None, max_variants=25, significance="pathogenic"):
        if significance == "pathogenic":
            anns = [VariantAnnotation(1, "T", "A", "Pathogenic", "c", "p1", "t", "snv", 3, None)]
        else:
            anns = [VariantAnnotation(3, "C", "G", "Benign", "c", "b1", "t", "snv", 3, None)]
        return AnnotationResult(gene=gene, total_variants_in_gene=len(anns), annotations=anns)

    svc = _FakeService({1: -0.9, 3: 0.2})
    with patch("services.calibration.annotate_variants", new_callable=AsyncMock) as mock_ann:
        mock_ann.side_effect = _fake_annotate
        report = await calibrate_gene(svc, "BRCA1", seq, max_per_class=10)

    assert isinstance(report, CalibrationReport)
    assert report.n_pathogenic == 1
    assert report.n_benign == 1
    assert report.n_scored == 2
    assert report.auroc == 1.0
    assert isinstance(report.engine_mode, str) and report.engine_mode


@pytest.mark.asyncio
async def test_calibrate_gene_no_sequence():
    svc = _FakeService({})
    report = await calibrate_gene(svc, "BRCA1", "", max_per_class=10)
    assert report.auroc is None
    assert report.n_scored == 0


@pytest.mark.asyncio
async def test_calibrate_gene_skips_unaligned():
    seq = "ATGCGTACGT"

    def _fake_annotate(gene, sequence=None, max_variants=25, significance="pathogenic"):
        if significance == "pathogenic":
            # ref base "A" does not match seq[1]="T" → skipped as unaligned
            anns = [VariantAnnotation(1, "A", "C", "Pathogenic", "c", "p1", "t", "snv", 3, None)]
        else:
            anns = [VariantAnnotation(3, "C", "G", "Benign", "c", "b1", "t", "snv", 3, None)]
        return AnnotationResult(gene=gene, total_variants_in_gene=len(anns), annotations=anns)

    svc = _FakeService({3: 0.2})
    with patch("services.calibration.annotate_variants", new_callable=AsyncMock) as mock_ann:
        mock_ann.side_effect = _fake_annotate
        report = await calibrate_gene(svc, "BRCA1", seq, max_per_class=10)

    assert report.n_skipped_unaligned == 1
    assert report.n_pathogenic == 0
    assert report.auroc is None  # only benign survived → single class


# --- endpoint ------------------------------------------------------------

def test_calibration_endpoint_mocked():
    seq = "ATGCGTACGTACGT"

    def _fake_annotate(gene, sequence=None, max_variants=25, significance="pathogenic"):
        if significance == "pathogenic":
            anns = [VariantAnnotation(1, "T", "A", "Pathogenic", "c", "p1", "t", "snv", 3, None)]
        else:
            anns = [VariantAnnotation(3, "C", "G", "Benign", "c", "b1", "t", "snv", 3, None)]
        return AnnotationResult(gene=gene, total_variants_in_gene=len(anns), annotations=anns)

    client = TestClient(app)
    with patch("services.calibration.annotate_variants", new_callable=AsyncMock) as mock_ann:
        mock_ann.side_effect = _fake_annotate
        resp = client.post("/api/calibration", json={"gene": "BRCA1", "sequence": seq})

    assert resp.status_code == 200
    body = resp.json()
    assert body["gene"] == "BRCA1"
    assert set(["auroc", "n_pathogenic", "n_benign", "n_scored", "engine_mode", "note"]).issubset(body)
    assert body["n_pathogenic"] == 1 and body["n_benign"] == 1
    assert isinstance(body["engine_mode"], str) and body["engine_mode"]
