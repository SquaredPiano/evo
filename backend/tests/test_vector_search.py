"""Tests for semantic (vector) search over research literature.

Covers the deterministic local embedder, cosine similarity, the hybrid embedder
factory, the LiteratureIndex in-memory search path, the region_evidence RAG
adapter, and the API endpoints. Everything runs with MongoDB disabled, so the
suite exercises the in-memory fallback — the path that must work with zero
external services (the honest default for a demo / CI).
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

import main
from main import app
from models.responses import LiteratureHit
from services.embeddings import (
    ApiEmbedder,
    LocalHashEmbedder,
    cosine_similarity,
    create_embedder,
)
from services.literature_index import LiteratureIndex, LiteratureRagProvider
from services.region_evidence import RegionEvidence, RegionQuery


# Three articles with clearly distinct vocabulary, so lexical ranking is stable.
BRCA1_ARTICLE = {
    "pmid": "1001",
    "title": "BRCA1 and hereditary breast cancer risk",
    "abstract": "BRCA1 is a tumor suppressor gene; pathogenic variants sharply "
    "increase hereditary breast and ovarian cancer risk in carriers.",
    "gene": "BRCA1",
}
CFTR_ARTICLE = {
    "pmid": "1002",
    "title": "CFTR mutations in cystic fibrosis",
    "abstract": "The CFTR chloride channel gene causes cystic fibrosis when "
    "mutated, disrupting epithelial ion transport in the lungs.",
    "gene": "CFTR",
}
PLANT_ARTICLE = {
    "pmid": "1003",
    "title": "Carbon fixation in C4 plants",
    "abstract": "Photosynthetic carbon fixation pathways in maize and sugarcane "
    "leaves concentrate carbon dioxide around rubisco.",
    "gene": None,
}


# ---------------------------------------------------------------------------
# 1. Local deterministic embedder
# ---------------------------------------------------------------------------


class TestLocalHashEmbedder:
    @pytest.mark.asyncio
    async def test_deterministic_same_input_same_vector(self):
        emb = LocalHashEmbedder(dim=128)
        v1 = (await emb.embed_texts(["BRCA1 tumor suppressor"]))[0]
        v2 = (await emb.embed_texts(["BRCA1 tumor suppressor"]))[0]
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_vector_has_configured_dim(self):
        emb = LocalHashEmbedder(dim=64)
        vec = (await emb.embed_texts(["hello world"]))[0]
        assert len(vec) == 64

    @pytest.mark.asyncio
    async def test_nonempty_vector_is_l2_normalized(self):
        emb = LocalHashEmbedder(dim=256)
        vec = (await emb.embed_texts(["a moderately long sentence about genes"]))[0]
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_empty_text_is_zero_vector(self):
        emb = LocalHashEmbedder(dim=32)
        vec = (await emb.embed_texts(["   "]))[0]
        assert vec == [0.0] * 32

    @pytest.mark.asyncio
    async def test_different_texts_differ(self):
        emb = LocalHashEmbedder(dim=256)
        v1 = (await emb.embed_texts(["breast cancer"]))[0]
        v2 = (await emb.embed_texts(["cystic fibrosis"]))[0]
        assert v1 != v2

    def test_zero_dim_rejected(self):
        with pytest.raises(ValueError):
            LocalHashEmbedder(dim=0)


# ---------------------------------------------------------------------------
# 2. Cosine similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors_is_one(self):
        v = [0.6, 0.8]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-12

    def test_orthogonal_vectors_is_zero(self):
        assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-12

    def test_opposite_vectors_is_minus_one(self):
        assert abs(cosine_similarity([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-12

    def test_zero_vector_is_zero_not_nan(self):
        result = cosine_similarity([0.0, 0.0], [1.0, 1.0])
        assert result == 0.0 and not math.isnan(result)

    def test_mismatched_shapes_is_zero(self):
        assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# 3. Hybrid embedder factory
# ---------------------------------------------------------------------------


class _FakeSettings:
    def __init__(self, **kw):
        self.embedding_dim = kw.get("embedding_dim", 256)
        self.embedding_api_key = kw.get("embedding_api_key", "")
        self.openai_api_key = kw.get("openai_api_key", "")
        self.embedding_base_url = kw.get("embedding_base_url", "https://api.openai.com/v1")
        self.embedding_model = kw.get("embedding_model", "text-embedding-3-small")


class TestCreateEmbedder:
    def test_no_key_selects_local(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        emb = create_embedder(_FakeSettings())
        assert isinstance(emb, LocalHashEmbedder)
        assert emb.name == "local-hash"

    def test_api_key_selects_api_embedder(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        emb = create_embedder(_FakeSettings(embedding_api_key="sk-test", embedding_dim=128))
        assert isinstance(emb, ApiEmbedder)
        assert emb.name == "api" and emb.dim == 128

    def test_legacy_openai_key_selects_api_embedder(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
        emb = create_embedder(_FakeSettings(openai_api_key="sk-legacy"))
        assert isinstance(emb, ApiEmbedder)


# ---------------------------------------------------------------------------
# 4. LiteratureIndex — in-memory index + search
# ---------------------------------------------------------------------------


def _fresh_index() -> LiteratureIndex:
    return LiteratureIndex(embedder=LocalHashEmbedder(dim=256), mongo_store=None)


class TestLiteratureIndexInMemory:
    @pytest.mark.asyncio
    async def test_index_reports_count_and_no_persistence(self):
        idx = _fresh_index()
        result = await idx.index_articles([BRCA1_ARTICLE, CFTR_ARTICLE, PLANT_ARTICLE])
        assert result.indexed == 3
        assert result.persisted is False  # no mongo_store
        assert result.backend == "local-hash"

    @pytest.mark.asyncio
    async def test_search_ranks_topical_match_first(self):
        idx = _fresh_index()
        await idx.index_articles([BRCA1_ARTICLE, CFTR_ARTICLE, PLANT_ARTICLE])
        result = await idx.search(
            "BRCA1 breast cancer tumor suppressor risk", k=3
        )
        assert result.backend == "memory"
        assert result.hits, "expected at least one hit"
        assert result.hits[0]["pmid"] == "1001"  # the BRCA1 paper
        # Scores are sorted descending.
        scores = [h["score"] for h in result.hits]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_gene_filter_restricts_results(self):
        idx = _fresh_index()
        await idx.index_articles([BRCA1_ARTICLE, CFTR_ARTICLE, PLANT_ARTICLE])
        result = await idx.search("gene mutation disease", k=5, gene="CFTR")
        assert result.hits
        assert all(h["gene"] == "CFTR" for h in result.hits)

    @pytest.mark.asyncio
    async def test_k_limits_result_count(self):
        idx = _fresh_index()
        await idx.index_articles([BRCA1_ARTICLE, CFTR_ARTICLE, PLANT_ARTICLE])
        result = await idx.search("gene", k=1)
        assert len(result.hits) <= 1

    @pytest.mark.asyncio
    async def test_search_empty_index_returns_no_hits(self):
        idx = _fresh_index()
        result = await idx.search("anything at all", k=5)
        assert result.hits == []
        assert result.backend == "memory"

    @pytest.mark.asyncio
    async def test_blank_query_returns_no_hits(self):
        idx = _fresh_index()
        await idx.index_articles([BRCA1_ARTICLE])
        result = await idx.search("   ", k=5)
        assert result.hits == []

    @pytest.mark.asyncio
    async def test_reindex_same_doc_is_idempotent(self):
        idx = _fresh_index()
        await idx.index_articles([BRCA1_ARTICLE])
        await idx.index_articles([BRCA1_ARTICLE])  # same pmid → same doc_id
        result = await idx.search("BRCA1 cancer", k=10)
        assert len(result.hits) == 1

    @pytest.mark.asyncio
    async def test_article_without_title_is_skipped(self):
        idx = _fresh_index()
        result = await idx.index_articles([{"title": "", "abstract": ""}])
        assert result.indexed == 0


# ---------------------------------------------------------------------------
# 5. region_evidence RAG adapter
# ---------------------------------------------------------------------------


class TestLiteratureRagProvider:
    @pytest.mark.asyncio
    async def test_fetch_returns_literature_region_evidence(self):
        idx = _fresh_index()
        await idx.index_articles([BRCA1_ARTICLE, CFTR_ARTICLE])
        provider = LiteratureRagProvider(idx, k=2)
        query = RegionQuery(start=10, end=40, sequence="ACGT" * 20, gene="BRCA1", label="BRCA1 breast cancer")
        evidence = await provider.fetch(query)

        assert evidence, "expected literature evidence"
        for item in evidence:
            assert isinstance(item, RegionEvidence)
            assert item.source == "literature"
            assert item.kind == "paper"
            assert item.start == 10 and item.end == 40  # bound to the region
            assert item.confidence.startswith("vector search")
        # Gene-scoped query should surface the BRCA1 paper.
        assert any(item.identifier == "1001" for item in evidence)

    @pytest.mark.asyncio
    async def test_fetch_empty_region_query_returns_nothing(self):
        idx = _fresh_index()
        await idx.index_articles([BRCA1_ARTICLE])
        provider = LiteratureRagProvider(idx)
        query = RegionQuery(start=0, end=5, sequence="ACGTA", gene=None, label=None)
        assert await provider.fetch(query) == []


# ---------------------------------------------------------------------------
# 6. API endpoints (Mongo disabled → in-memory path)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    """A client whose literature index uses the deterministic local embedder.

    Swaps the module-level singleton for an isolated, hermetic index so these
    tests never depend on an embedding key being unset in the environment and
    never make a network call. Restored afterwards.
    """
    original = main.literature_index
    main.literature_index = LiteratureIndex(
        embedder=LocalHashEmbedder(dim=256), mongo_store=main.mongo_store
    )
    try:
        yield TestClient(app)
    finally:
        main.literature_index = original


class TestLiteratureAPI:
    def test_index_direct_articles(self, client):
        res = client.post(
            "/api/literature/index",
            json={"articles": [BRCA1_ARTICLE, CFTR_ARTICLE]},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["indexed"] == 2
        assert body["persisted"] is False  # Mongo disabled
        assert body["embedding_backend"] == "local-hash"

    def test_search_after_index_returns_ranked_hits(self, client):
        client.post(
            "/api/literature/index",
            json={"articles": [BRCA1_ARTICLE, CFTR_ARTICLE, PLANT_ARTICLE]},
        )
        res = client.post(
            "/api/literature/search",
            json={"query": "cystic fibrosis CFTR chloride channel lungs", "k": 2},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["backend"] == "memory"
        assert body["embedding_backend"] == "local-hash"
        assert body["count"] >= 1
        assert body["hits"][0]["pmid"] == "1002"  # CFTR paper
        # Response validates against the LiteratureHit contract.
        LiteratureHit(**body["hits"][0])

    def test_search_with_gene_filter(self, client):
        client.post(
            "/api/literature/index",
            json={"articles": [BRCA1_ARTICLE, CFTR_ARTICLE]},
        )
        res = client.post(
            "/api/literature/search",
            json={"query": "gene mutation disease", "gene": "BRCA1", "k": 5},
        )
        assert res.status_code == 200
        hits = res.json()["hits"]
        assert hits and all(h["gene"] == "BRCA1" for h in hits)

    def test_search_empty_index_is_ok(self, client):
        res = client.post(
            "/api/literature/search",
            json={"query": "no documents indexed here yet zzz", "gene": "NOPE_GENE"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 0
        assert body["hits"] == []

    def test_search_requires_query(self, client):
        res = client.post("/api/literature/search", json={"k": 5})
        assert res.status_code == 422

    def test_search_rejects_empty_query(self, client):
        res = client.post("/api/literature/search", json={"query": ""})
        assert res.status_code == 422

    def test_index_requires_gene_or_articles(self, client):
        res = client.post("/api/literature/index", json={})
        assert res.status_code == 422

    def test_health_detail_reports_embedding(self, client):
        res = client.get("/api/health/detail")
        assert res.status_code == 200
        body = res.json()
        assert body["embedding_backend"] == "local-hash"
        assert body["embedding_dim"] == 256
        assert body["vector_index"] == "literature_vector_index"
