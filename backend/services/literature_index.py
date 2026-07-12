"""Semantic (vector) search over research literature.

This is the RAG index the ``region_evidence`` module documents a seam for: it
embeds PubMed articles (title + abstract), stores them, and answers semantic
queries — "which papers are most relevant to this gene / region / question?".

Two axes of graceful degradation, matching the rest of the backend:

* **Embeddings** — hybrid (see :mod:`services.embeddings`): a real embedding API
  when a key is configured, else a deterministic local embedder.
* **Index / query backend** — MongoDB Atlas ``$vectorSearch`` when a Mongo
  connection *and* a vector index are available; otherwise an in-process cosine
  similarity scan over whatever has been indexed (kept in memory, and reloaded
  from Mongo when the durable store is up but the vector index isn't).

Nothing here ever raises for "no results": an empty index yields an empty hit
list, exactly like the retrieval services it complements.

:class:`LiteratureRagProvider` adapts this index to
``region_evidence.RegionRagProvider`` so per-region papers drop straight into
the existing coordinate-bound evidence list with ``source="literature"``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.embeddings import Embedder, cosine_similarity
from services.region_evidence import RegionEvidence, RegionQuery

logger = logging.getLogger("evo")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_text(title: str, abstract: str) -> str:
    return f"{title}\n{abstract}".strip()


def _doc_id(article: dict[str, Any]) -> str:
    """Stable id: prefer the PMID, else a content hash of title+abstract."""
    pmid = (article.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    digest = hashlib.sha1(_doc_text(article.get("title", ""), article.get("abstract", "")).encode("utf-8")).hexdigest()
    return f"doc:{digest[:16]}"


def _pubmed_url(pmid: str | None, existing: str | None) -> str | None:
    if existing:
        return existing
    pmid = (pmid or "").strip()
    if pmid and not pmid.upper().startswith("DEMO"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return None


@dataclass
class IndexResult:
    indexed: int
    persisted: bool
    backend: str  # embedding backend name


@dataclass
class SearchResult:
    hits: list[dict[str, Any]] = field(default_factory=list)
    backend: str = "memory"  # index backend that answered: "atlas" | "memory"


class LiteratureIndex:
    """Embed, store, and semantically search research literature.

    ``mongo_store`` is optional. When absent (or disabled), everything runs from
    an in-process cache — fine for a single-instance demo, lost on restart.
    """

    def __init__(self, *, embedder: Embedder, mongo_store: Any | None = None) -> None:
        self._embedder = embedder
        self._mongo = mongo_store
        # In-process cache: doc_id -> document (includes embedding). Doubles as
        # the source for in-memory cosine search when Atlas isn't available.
        self._mem: dict[str, dict[str, Any]] = {}

    @property
    def embedder_name(self) -> str:
        return self._embedder.name

    # -- Indexing -----------------------------------------------------------

    async def index_articles(
        self, articles: list[dict[str, Any]], *, gene: str | None = None
    ) -> IndexResult:
        """Embed and store a batch of articles.

        Each article is a dict with at least ``title``; ``abstract``, ``pmid``,
        ``year``, ``journal``, ``authors``, ``url``, ``gene`` are optional. The
        per-article ``gene`` wins over the batch-level ``gene`` default.
        """
        docs: list[dict[str, Any]] = []
        texts: list[str] = []
        for art in articles:
            title = (art.get("title") or "").strip()
            abstract = (art.get("abstract") or "").strip()
            text = _doc_text(title, abstract)
            if not text:
                continue
            pmid = (art.get("pmid") or "").strip() or None
            docs.append(
                {
                    "doc_id": _doc_id(art),
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract,
                    "text": text,
                    "gene": (art.get("gene") or gene or None),
                    "year": str(art.get("year") or ""),
                    "journal": art.get("journal") or "",
                    "authors": list(art.get("authors") or []),
                    "url": _pubmed_url(pmid, art.get("url")),
                    "source": art.get("source") or "pubmed",
                }
            )
            texts.append(text)

        if not docs:
            return IndexResult(indexed=0, persisted=False, backend=self._embedder.name)

        vectors = await self._embedder.embed_texts(texts)
        now = _utcnow_iso()
        for doc, vec in zip(docs, vectors):
            doc["embedding"] = vec
            doc["embedding_backend"] = self._embedder.name
            doc["embedding_dim"] = self._embedder.dim
            doc["indexed_at"] = now
            self._mem[doc["doc_id"]] = doc

        persisted = False
        if self._mongo is not None:
            persisted = await self._mongo.save_literature_docs(docs)

        return IndexResult(indexed=len(docs), persisted=persisted, backend=self._embedder.name)

    async def index_from_pubmed(
        self,
        *,
        gene: str,
        therapeutic_context: str | None = None,
        design_type: str | None = None,
        max_results: int = 5,
    ) -> tuple[IndexResult, str, int]:
        """Fetch literature from PubMed for ``gene`` and index it.

        Returns ``(index_result, query, total_available)``. A PubMed failure
        degrades to indexing zero articles (never raises).
        """
        from services.pubmed import search_literature

        result = await search_literature(
            gene=gene,
            therapeutic_context=therapeutic_context,
            design_type=design_type,
            max_results=max_results,
        )
        articles = [
            {
                "pmid": a.pmid,
                "title": a.title,
                "abstract": a.abstract,
                "year": a.year,
                "journal": a.journal,
                "authors": a.authors,
            }
            for a in result.articles
        ]
        index_result = await self.index_articles(articles, gene=gene)
        return index_result, result.query, result.total_count

    # -- Search -------------------------------------------------------------

    async def search(
        self, query: str, *, k: int = 5, gene: str | None = None
    ) -> SearchResult:
        """Return the ``k`` most semantically similar documents to ``query``.

        Tries Atlas ``$vectorSearch`` first (when Mongo is connected); if that
        is unavailable — no connection, or no vector index provisioned — falls
        back to an in-process cosine scan. Returns an empty hit list, never an
        error, when nothing has been indexed.
        """
        query = (query or "").strip()
        if not query:
            return SearchResult(hits=[], backend="memory")

        query_vector = (await self._embedder.embed_texts([query]))[0]

        # 1) Atlas vector search (returns None to signal "fall back").
        if self._mongo is not None and getattr(self._mongo, "ready", False):
            atlas_hits = await self._mongo.vector_search_literature(
                query_vector, k=k, gene=gene
            )
            if atlas_hits is not None:
                return SearchResult(
                    hits=[self._to_hit(doc, doc.get("score", 0.0)) for doc in atlas_hits],
                    backend="atlas",
                )

        # 2) In-memory cosine fallback. Prefer the in-process cache; if it is
        #    empty but a durable store exists, hydrate from it.
        pool = list(self._mem.values())
        if not pool and self._mongo is not None and getattr(self._mongo, "ready", False):
            pool = await self._mongo.list_literature_docs(gene=gene, limit=2000)

        scored: list[tuple[float, dict[str, Any]]] = []
        gene_norm = gene.strip().upper() if gene else None
        for doc in pool:
            if gene_norm:
                # Strict equality, matching the Atlas $vectorSearch filter
                # ``{"gene": gene}`` — docs with a different or missing gene are
                # excluded, so both backends return the same set.
                if (doc.get("gene") or "").upper() != gene_norm:
                    continue
            embedding = doc.get("embedding")
            if not embedding:
                continue
            scored.append((cosine_similarity(query_vector, embedding), doc))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        hits = [self._to_hit(doc, score) for score, doc in scored[:k]]
        return SearchResult(hits=hits, backend="memory")

    @staticmethod
    def _to_hit(doc: dict[str, Any], score: float) -> dict[str, Any]:
        return {
            "doc_id": doc.get("doc_id") or doc.get("_id") or "",
            "title": doc.get("title", ""),
            "abstract": doc.get("abstract", ""),
            "score": round(float(score), 6),
            "pmid": doc.get("pmid"),
            "gene": doc.get("gene"),
            "year": str(doc.get("year") or ""),
            "journal": doc.get("journal", ""),
            "url": doc.get("url"),
            "source": doc.get("source", "pubmed"),
        }


# ---------------------------------------------------------------------------
# region_evidence seam adapter
# ---------------------------------------------------------------------------


def _snippet(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class LiteratureRagProvider:
    """Adapts :class:`LiteratureIndex` to ``region_evidence.RegionRagProvider``.

    Queries the vector index with the region's label (or gene) and returns
    coordinate-bound ``RegionEvidence`` records tagged ``source="literature"``,
    so semantically-retrieved papers merge into the same evidence list the UI
    already renders. Honest by construction: URLs come straight from the indexed
    document (or None — never fabricated), and the confidence string names the
    backend that answered.
    """

    def __init__(self, index: LiteratureIndex, *, k: int = 3) -> None:
        self._index = index
        self._k = k

    async def fetch(self, query: RegionQuery) -> list[RegionEvidence]:
        text = (query.label or query.gene or "").strip()
        if not text:
            return []
        result = await self._index.search(text, k=self._k, gene=query.gene)
        return [
            RegionEvidence(
                start=query.start,
                end=query.end,
                source="literature",
                kind="paper",
                title=hit["title"],
                detail=_snippet(hit["abstract"]),
                url=hit["url"],
                identifier=hit["pmid"],
                score=hit["score"],
                confidence=f"vector search ({result.backend})",
            )
            for hit in result.hits
        ]
