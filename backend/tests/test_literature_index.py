"""Tests for services.literature_index: indexing, semantic search, and the
LiteratureRagProvider adapter that feeds region_evidence's RAG seam.

No network, no real Mongo, no real Gemini - LocalHashEmbedder + an in-memory
LiteratureIndex give deterministic, offline-safe search, and the autouse
fixture clears settings.gemini_api_key so synthesize_detail takes its
truncated-abstract fallback path (see test_evidence_synthesis.py).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from config import settings
from services.embeddings import LocalHashEmbedder
from services.literature_index import LiteratureIndex, LiteratureRagProvider
from services.pubmed import PubMedArticle, PubMedResult
from services.region_evidence import RegionQuery


@pytest.fixture(autouse=True)
def _reset_gemini_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_real_pubmed_by_default():
    """ensure_indexed() (called from fetch() on every query) will hit real
    PubMed for any gene not already indexed. Default every test to a mocked,
    empty PubMed response so only tests that explicitly want to exercise
    backfill opt into real-looking data (via their own patch, which shadows
    this one within that test)."""
    empty_result = PubMedResult(query="", articles=[], total_count=0)
    with patch("services.pubmed.search_literature", new=AsyncMock(return_value=empty_result)):
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


class _FakeMongo:
    """Minimal test double for the mongo_store surface LiteratureIndex uses."""

    def __init__(self, *, ready: bool = True, vector_hits=None, docs=None):
        self.ready = ready
        self._vector_hits = vector_hits if vector_hits is not None else []
        self._docs = docs or []
        self.vector_search_calls = 0
        self.list_docs_calls = 0

    async def vector_search_literature(self, query_vector, *, k=5, gene=None, num_candidates=None):
        self.vector_search_calls += 1
        return self._vector_hits

    async def list_literature_docs(self, *, gene=None, limit=2000):
        self.list_docs_calls += 1
        return self._docs

    async def save_literature_docs(self, docs):
        return True


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

    @pytest.mark.asyncio
    async def test_atlas_empty_result_falls_back_to_mongo_hydration(self):
        """Atlas Search indexes new writes near-real-time, not instantly - an
        empty $vectorSearch result right after a fresh upsert (e.g. from
        ensure_indexed's on-demand backfill, same request) must not be trusted
        as "nothing exists"; it should fall through to a plain Mongo query,
        which sees the write immediately."""
        embedder = LocalHashEmbedder(dim=64)
        text = f"{BRCA1_ARTICLE['title']}\n{BRCA1_ARTICLE['abstract']}"
        vec = (await embedder.embed_texts([text]))[0]
        stored_doc = {
            "doc_id": "pmid:40000001", "pmid": "40000001", "title": BRCA1_ARTICLE["title"],
            "abstract": BRCA1_ARTICLE["abstract"], "gene": "BRCA1", "year": "2025",
            "journal": "Nature Genetics", "url": "https://pubmed.ncbi.nlm.nih.gov/40000001/",
            "source": "pubmed", "embedding": vec,
        }
        mongo = _FakeMongo(vector_hits=[], docs=[stored_doc])
        idx = LiteratureIndex(embedder=embedder, mongo_store=mongo)

        result = await idx.search("BRCA1 DNA repair", k=5, gene="BRCA1")

        assert mongo.vector_search_calls == 1
        assert mongo.list_docs_calls == 1  # fell through to hydration
        assert len(result.hits) == 1
        assert result.hits[0]["pmid"] == "40000001"
        assert result.backend == "memory"

    @pytest.mark.asyncio
    async def test_atlas_nonempty_result_is_trusted_without_hydration(self):
        """The common case stays cheap: a non-empty Atlas answer is returned
        directly, without paying for an extra Mongo hydration query."""
        mongo = _FakeMongo(vector_hits=[{
            "doc_id": "x", "title": "t", "abstract": "a", "score": 0.9,
            "pmid": "1", "gene": "BRCA1", "year": "2025", "journal": "J",
            "url": None, "source": "pubmed",
        }])
        idx = LiteratureIndex(embedder=LocalHashEmbedder(dim=64), mongo_store=mongo)
        result = await idx.search("query", k=5, gene="BRCA1")
        assert result.backend == "atlas"
        assert mongo.list_docs_calls == 0


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
        # ensure_indexed's backfill attempt (mocked to empty by the autouse
        # fixture) also means genuinely nothing gets indexed for TP53 here.

    @pytest.mark.asyncio
    async def test_fetch_calls_ensure_indexed_before_search(self, index: LiteratureIndex):
        calls: list[str | None] = []
        original_ensure_indexed = index.ensure_indexed

        async def spy(gene, *args, **kwargs):
            calls.append(gene)
            return await original_ensure_indexed(gene, *args, **kwargs)

        index.ensure_indexed = spy
        provider = LiteratureRagProvider(index)
        await provider.fetch(RegionQuery(start=0, end=10, sequence="A" * 10, gene="TP53"))
        assert calls == ["TP53"]


class TestEnsureIndexed:
    @pytest.mark.asyncio
    async def test_empty_or_none_gene_is_noop(self, index: LiteratureIndex):
        with patch("services.pubmed.search_literature", new=AsyncMock()) as mock_search:
            await index.ensure_indexed("")
            await index.ensure_indexed(None)
        mock_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_backfill_when_already_indexed_in_memory(self, index: LiteratureIndex):
        await index.index_articles([BRCA1_ARTICLE])
        with patch("services.pubmed.search_literature", new=AsyncMock()) as mock_search:
            await index.ensure_indexed("BRCA1")
        mock_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_backfill_when_already_indexed_in_mongo(self):
        mongo = _FakeMongo(docs=[{"pmid": "1", "gene": "BRCA1"}])
        idx = LiteratureIndex(embedder=LocalHashEmbedder(dim=64), mongo_store=mongo)
        with patch("services.pubmed.search_literature", new=AsyncMock()) as mock_search:
            await idx.ensure_indexed("BRCA1")
        mock_search.assert_not_called()
        assert mongo.list_docs_calls == 1

    @pytest.mark.asyncio
    async def test_backfills_when_nothing_indexed_anywhere(self, index: LiteratureIndex):
        fake_result = PubMedResult(
            query="TP53",
            articles=[
                PubMedArticle(
                    pmid="99", title="TP53 study", authors=[],
                    abstract="TP53 tumor suppressor mechanism.", year="2025", journal="Cell",
                )
            ],
            total_count=1,
        )
        with patch("services.pubmed.search_literature", new=AsyncMock(return_value=fake_result)):
            await index.ensure_indexed("TP53")

        result = await index.search("TP53", k=5, gene="TP53")
        assert len(result.hits) == 1
        assert result.hits[0]["pmid"] == "99"

    @pytest.mark.asyncio
    async def test_never_raises_when_backfill_fails(self, index: LiteratureIndex):
        with patch(
            "services.pubmed.search_literature",
            new=AsyncMock(side_effect=RuntimeError("PubMed down")),
        ):
            await index.ensure_indexed("TP53")  # must not raise

        result = await index.search("TP53", k=5, gene="TP53")
        assert result.hits == []

    @pytest.mark.asyncio
    async def test_concurrent_calls_for_same_gene_dont_duplicate_backfill(
        self, index: LiteratureIndex
    ):
        """Two overlapping ensure_indexed calls for the same never-before-seen
        gene (e.g. the startup pre-warm racing a live user query) must only
        trigger one PubMed fetch, not one each."""
        call_count = 0

        async def slow_search_literature(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return PubMedResult(
                query="TP53",
                articles=[
                    PubMedArticle(
                        pmid="1", title="t", authors=[],
                        abstract="a", year="2025", journal="J",
                    )
                ],
                total_count=1,
            )

        with patch("services.pubmed.search_literature", new=slow_search_literature):
            await asyncio.gather(
                index.ensure_indexed("TP53"), index.ensure_indexed("TP53")
            )

        assert call_count == 1
