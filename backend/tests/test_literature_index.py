"""Tests for services.literature_index: indexing, semantic search, and the
LiteratureRagProvider adapter that feeds region_evidence's RAG seam.

No network, no real Mongo, no real Gemini — LocalHashEmbedder + an in-memory
LiteratureIndex give deterministic, offline-safe search, and the autouse
fixture clears settings.gemini_api_key so synthesize_detail takes its
truncated-abstract fallback path (see test_evidence_synthesis.py).
"""

from __future__ import annotations

import asyncio

import pytest

from config import settings
from services.embeddings import LocalHashEmbedder
from services.literature_index import LiteratureIndex, LiteratureRagProvider
from services.region_evidence import RegionQuery


@pytest.fixture(autouse=True)
def _reset_gemini_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield


@pytest.fixture
def index() -> LiteratureIndex:
    return LiteratureIndex(embedder=LocalHashEmbedder(dim=64), mongo_store=None)


BRCA1_ARTICLE = {
    "pmid": "40000001",
    "title": "BRCA1 splicing variants alter DNA repair efficiency",
    "abstract": "We characterize BRCA1 splice-site variants and their effect on homologous recombination repair.",
    "year": "2025",
    "journal": "Nature Genetics",
    "gene": "BRCA1",
}
UNRELATED_ARTICLE = {
    "pmid": "40000002",
    "title": "Photosynthetic efficiency in engineered cyanobacteria",
    "abstract": "A study of light-harvesting complexes in modified Synechocystis strains.",
    "year": "2025",
    "journal": "Plant Cell",
    "gene": "RBCL",
}


class TestIndexAndSearch:
    @pytest.mark.asyncio
    async def test_index_then_search_finds_matching_gene(self, index: LiteratureIndex):
        await index.index_articles([BRCA1_ARTICLE, UNRELATED_ARTICLE])
        result = await index.search("BRCA1 DNA repair", k=5, gene="BRCA1")
        assert result.backend == "memory"
        assert len(result.hits) == 1
        assert result.hits[0]["pmid"] == "40000001"

    @pytest.mark.asyncio
    async def test_empty_index_returns_empty_hits(self, index: LiteratureIndex):
        result = await index.search("BRCA1", k=5, gene="BRCA1")
        assert result.hits == []

    @pytest.mark.asyncio
    async def test_gene_filter_excludes_other_genes(self, index: LiteratureIndex):
        await index.index_articles([BRCA1_ARTICLE, UNRELATED_ARTICLE])
        result = await index.search("splicing variant repair", k=5, gene="RBCL")
        assert all(hit["gene"] == "RBCL" for hit in result.hits)

    @pytest.mark.asyncio
    async def test_indexed_url_is_real_pubmed_link(self, index: LiteratureIndex):
        await index.index_articles([BRCA1_ARTICLE])
        result = await index.search("BRCA1", k=1, gene="BRCA1")
        assert result.hits[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/40000001/"


class TestLiteratureRagProvider:
    @pytest.mark.asyncio
    async def test_no_gene_or_label_returns_empty(self, index: LiteratureIndex):
        provider = LiteratureRagProvider(index)
        out = await provider.fetch(RegionQuery(start=0, end=10, sequence="A" * 10))
        assert out == []

    @pytest.mark.asyncio
    async def test_fetch_binds_coordinates_and_forces_literature_tag(self, index: LiteratureIndex):
        await index.index_articles([BRCA1_ARTICLE])
        provider = LiteratureRagProvider(index, k=1)
        query = RegionQuery(start=100, end=250, sequence="A" * 300, gene="BRCA1")
        out = await provider.fetch(query)
        assert len(out) == 1
        item = out[0]
        assert item.start == 100 and item.end == 250
        assert item.source == "literature"
        assert item.kind == "paper"
        assert item.identifier == "40000001"
        assert item.url == "https://pubmed.ncbi.nlm.nih.gov/40000001/"
        assert item.confidence == "vector search (memory)"

    @pytest.mark.asyncio
    async def test_detail_comes_from_synthesize_detail_fallback(self, index: LiteratureIndex):
        """With no Gemini key configured, detail is the deterministic truncated
        abstract, not the raw un-truncated abstract and not a hardcoded snippet."""
        await index.index_articles([BRCA1_ARTICLE])
        provider = LiteratureRagProvider(index, k=1)
        out = await provider.fetch(RegionQuery(start=0, end=10, sequence="A" * 10, gene="BRCA1"))
        assert out[0].detail == BRCA1_ARTICLE["abstract"]  # short enough to pass through verbatim

    @pytest.mark.asyncio
    async def test_no_matching_hits_returns_empty(self, index: LiteratureIndex):
        await index.index_articles([BRCA1_ARTICLE])
        provider = LiteratureRagProvider(index)
        out = await provider.fetch(RegionQuery(start=0, end=10, sequence="A" * 10, gene="TP53"))
        assert out == []
