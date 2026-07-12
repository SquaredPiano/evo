"""Tests for region → evidence binding (services.region_evidence).

Covers: assembly from existing sources, coordinate filtering, the honest empty
case, the RAG extension seam, and the /api/region-evidence contract. ClinVar is
mocked so tests never hit the network.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from main import app
from services.variant_annotation import AnnotationResult, VariantAnnotation
from services.region_evidence import (
    RegionEvidence,
    RegionQuery,
    assemble_region_evidence,
    attach_literature_evidence,
    _regulatory_evidence,
)


def _mk_annotation(position: int, ref="C", alt="A") -> VariantAnnotation:
    return VariantAnnotation(
        position=position,
        ref_base=ref,
        alt_base=alt,
        clinical_significance="pathogenic",
        condition="Hereditary breast cancer",
        variant_id="12345",
        variant_title=f"NM_007294.4(BRCA1):c.{position}{ref}>{alt}",
        variation_type="single nucleotide variant",
        review_stars=3,
        allele_frequency=None,
    )


# ---------------------------------------------------------------------------
# RegionEvidence record
# ---------------------------------------------------------------------------

class TestRegionEvidenceRecord:
    def test_to_dict_roundtrip(self):
        ev = RegionEvidence(
            start=5, end=6, source="clinvar", kind="pathogenic_variant",
            title="t", detail="d", url="http://x", identifier="1", score=0.9,
            confidence="review: 3/4 stars",
        )
        d = ev.to_dict()
        assert d["start"] == 5 and d["end"] == 6
        assert d["source"] == "clinvar"
        assert set(d.keys()) == {
            "start", "end", "source", "kind", "title", "detail",
            "url", "identifier", "score", "confidence",
        }


# ---------------------------------------------------------------------------
# Regulatory conversion (local, no network)
# ---------------------------------------------------------------------------

class TestRegulatoryEvidence:
    def test_motif_becomes_evidence(self):
        reg_map = {"features": [{"name": "TATA_box", "start": 10, "end": 16, "score": 0.6}]}
        out = _regulatory_evidence(reg_map, 0, 100)
        assert len(out) == 1
        assert out[0].source == "regulatory"
        assert out[0].kind == "motif"
        assert out[0].start == 10 and out[0].end == 16
        assert out[0].url is None  # motif-derived, not literature

    def test_overlap_filtering(self):
        reg_map = {"features": [
            {"name": "TATA_box", "start": 10, "end": 16, "score": 0.6},
            {"name": "GC_box", "start": 50, "end": 56, "score": 0.7},
        ]}
        out = _regulatory_evidence(reg_map, 0, 20)  # only first overlaps
        assert [e.identifier for e in out] == ["TATA_box"]

    def test_malformed_features_ignored(self):
        reg_map = {"features": ["not a dict", {"start": "x"}, {}]}
        assert _regulatory_evidence(reg_map, 0, 100) == []

    def test_no_features_key(self):
        assert _regulatory_evidence({}, 0, 100) == []


# ---------------------------------------------------------------------------
# Full assembly + coordinate filtering + honesty
# ---------------------------------------------------------------------------

class TestAssembly:
    @pytest.mark.asyncio
    async def test_regulatory_only_when_no_gene(self):
        seq = "TATAAA" + "G" * 40 + "GGGCGG"
        out = await assemble_region_evidence(seq, gene=None)
        assert all(e.source == "regulatory" for e in out)
        assert any(e.identifier == "TATA_box" for e in out)

    @pytest.mark.asyncio
    async def test_clinvar_merged_and_coordinate_filtered(self):
        seq = "TATAAA" + "A" * 100
        annotations = [_mk_annotation(3), _mk_annotation(80)]
        mock_result = AnnotationResult(
            gene="BRCA1", total_variants_in_gene=2, annotations=annotations,
        )
        with patch(
            "services.region_evidence.annotate_variants",
            new=AsyncMock(return_value=mock_result),
        ):
            # window [0, 50) keeps only the variant at position 3
            out = await assemble_region_evidence(
                seq, gene="BRCA1", region_start=0, region_end=50,
            )
        clinvar = [e for e in out if e.source == "clinvar"]
        assert len(clinvar) == 1
        assert clinvar[0].start == 3 and clinvar[0].end == 4
        # HONESTY: framed as gene context, not a per-base pathogenicity claim
        assert "not a pathogenicity claim" in (clinvar[0].detail or "")
        assert clinvar[0].url == "https://www.ncbi.nlm.nih.gov/clinvar/variation/12345/"

    @pytest.mark.asyncio
    async def test_clinvar_failure_degrades_gracefully(self):
        seq = "TATAAA" + "A" * 40
        with patch(
            "services.region_evidence.annotate_variants",
            new=AsyncMock(side_effect=RuntimeError("network down")),
        ):
            out = await assemble_region_evidence(seq, gene="BRCA1")
        # Regulatory still present, ClinVar silently dropped — no crash.
        assert all(e.source == "regulatory" for e in out)

    @pytest.mark.asyncio
    async def test_honest_empty_case(self):
        # No motifs, no gene → empty list, no crash.
        seq = "AAAAAAAAAAAAAAAAAAAA"
        out = await assemble_region_evidence(seq, gene=None)
        assert out == []

    @pytest.mark.asyncio
    async def test_empty_window_returns_empty(self):
        out = await assemble_region_evidence("TATAAA" * 5, region_start=10, region_end=10)
        assert out == []

    @pytest.mark.asyncio
    async def test_sorted_by_start(self):
        seq = "TATAAA" + "A" * 20 + "GGGCGG"
        out = await assemble_region_evidence(seq, gene=None)
        starts = [e.start for e in out]
        assert starts == sorted(starts)


# ---------------------------------------------------------------------------
# RAG extension seam
# ---------------------------------------------------------------------------

class TestLiteratureSeam:
    @pytest.mark.asyncio
    async def test_sync_provider_normalised_to_literature(self):
        class FakeRag:
            def fetch(self, query: RegionQuery):
                return [RegionEvidence(
                    start=query.start, end=query.end,
                    source="wrong", kind="paper", title="A 2026 paper",
                    url="https://pubmed.ncbi.nlm.nih.gov/99999999/",
                    identifier="99999999",
                )]

        regions = [RegionQuery(start=0, end=10, sequence="ACGTACGTAC", gene="BRCA1")]
        out = await attach_literature_evidence(regions, FakeRag())
        assert len(out) == 1
        assert out[0].source == "literature"  # forced, even though provider said "wrong"
        assert out[0].url.startswith("https://pubmed")

    @pytest.mark.asyncio
    async def test_async_provider_supported(self):
        class AsyncRag:
            async def fetch(self, query: RegionQuery):
                return [RegionEvidence(
                    start=query.start, end=query.end,
                    source="literature", kind="paper", title="async paper",
                )]

        out = await attach_literature_evidence(
            [RegionQuery(start=2, end=5, sequence="ACGTACGT")], AsyncRag()
        )
        assert out and out[0].title == "async paper"

    @pytest.mark.asyncio
    async def test_provider_failure_isolated(self):
        class BoomRag:
            def fetch(self, query: RegionQuery):
                raise ValueError("boom")

        out = await attach_literature_evidence(
            [RegionQuery(start=0, end=5, sequence="ACGTA")], BoomRag()
        )
        assert out == []


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------

class TestEndpoint:
    def test_region_evidence_endpoint_regulatory_only(self):
        client = TestClient(app)
        seq = "TATAAA" + "G" * 40 + "GGGCGG"
        resp = client.post(
            "/api/region-evidence",
            json={"sequence": seq, "include_clinvar": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == len(body["items"])
        assert body["region_start"] == 0
        assert body["region_end"] == len(seq)
        assert all(item["source"] == "regulatory" for item in body["items"])
        assert all("start" in item and "end" in item for item in body["items"])

    def test_region_evidence_endpoint_honest_empty(self):
        client = TestClient(app)
        resp = client.post(
            "/api/region-evidence",
            json={"sequence": "A" * 30, "include_clinvar": False},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []
