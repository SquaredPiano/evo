#!/usr/bin/env python3
"""Populate the literature vector index for one or more genes via PubMed.

Fetches post-2025 PubMed articles (services.pubmed's default date filter),
embeds them, and upserts them into the literature index — the same index
/api/region-evidence's RAG seam (services.literature_index.LiteratureRagProvider)
searches at request time. Uses the exact same embedder/Mongo-store construction
as backend/main.py, so what this script writes is what the running app reads.

Run from backend/:
    source .venv/bin/activate
    python -m scripts.ingest_literature BRCA1
    python -m scripts.ingest_literature BRCA1 TP53 --max-results 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from services.embeddings import create_embedder
from services.literature_index import LiteratureIndex
from services.mongo_store import create_mongo_store


async def ingest(genes: list[str], max_results: int) -> None:
    embedder = create_embedder(settings)
    mongo_store = create_mongo_store(settings)
    connected = await mongo_store.connect()
    print(f"Embedder: {embedder.name} (dim={embedder.dim})")
    if connected:
        print("MongoDB Atlas: connected — articles persist for every process, not just this run.")
    else:
        print(
            "MongoDB Atlas: unreachable — indexing in this script's in-process cache only. "
            "It will be searchable here but gone on exit; the running backend won't see it "
            "until Atlas is reachable. Not a crash, just an honest limitation."
        )

    index = LiteratureIndex(embedder=embedder, mongo_store=mongo_store)
    try:
        for gene in genes:
            result, query, total_available = await index.index_from_pubmed(
                gene=gene, max_results=max_results
            )
            print(
                f"  {gene}: indexed {result.indexed} article(s) "
                f"(persisted={result.persisted}, query={query!r}, "
                f"total available on PubMed={total_available})"
            )
    finally:
        await mongo_store.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest post-2025 PubMed literature into the semantic search index"
    )
    parser.add_argument("genes", nargs="+", help="Gene symbols to fetch and index, e.g. BRCA1 TP53")
    parser.add_argument(
        "--max-results", type=int, default=5, help="Max PubMed articles per gene (default 5)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    asyncio.run(ingest(args.genes, args.max_results))


if __name__ == "__main__":
    main()
