# Semantic vector search over research literature

Embeds research articles (PubMed) and searches them **by meaning** rather than
keyword, so a design can surface the papers most relevant to a gene, a sequence
region, or a free-text question. It is the concrete implementation of the RAG
seam documented in `docs/region_evidence_interface.md` /
`services/region_evidence.py`.

Like the rest of the backend, it is **optional and degrades gracefully** - it
works with zero configuration and no external services, just at lower quality.

## Components

| File | Role |
| --- | --- |
| `services/embeddings.py` | Text → vector. `LocalHashEmbedder` (deterministic, offline) and `ApiEmbedder` (OpenAI-compatible). `create_embedder(settings)` picks per the hybrid policy. `cosine_similarity`. |
| `services/literature_index.py` | `LiteratureIndex` (index + search) and `LiteratureRagProvider` (region_evidence adapter). |
| `services/mongo_store.py` | Durable storage + Atlas `$vectorSearch` (`save_literature_docs`, `vector_search_literature`, `list_literature_docs`). |
| `main.py` | `POST /api/literature/index`, `POST /api/literature/search`, and the startup pre-warm task (see below). |
| `scripts/ingest_literature.py` | One-off manual ingestion CLI for a gene list - optional now that `ensure_indexed` covers ingestion on demand. |

## Two degradation axes

**Embeddings (hybrid).** If `EMBEDDING_API_KEY` (or legacy `OPENAI_API_KEY`) is
set, a real embedding model is used (`EMBEDDING_MODEL`, default
`text-embedding-3-small`). Otherwise a deterministic local feature-hashing
embedder is used - no network, same input always maps to the same vector. Both
emit L2-normalised vectors of `EMBEDDING_DIM` (default 256).

> Do **not** mix backends within one populated index - the vector spaces are
> unrelated. Pick one embedder per deployment; re-index if you switch.

**Index / query backend.** If MongoDB is connected *and* an Atlas Vector Search
index exists, queries use `$vectorSearch`. Otherwise search falls back to an
in-process cosine scan over what has been indexed (reloading from Mongo when the
durable store is up but the vector index isn't). A missing index isn't an
error - `$vectorSearch` fails, the store returns `None`, and the caller falls
back automatically.

The gene filter uses **strict equality** in both backends (Atlas
`{"gene": gene}` and the in-memory scan), so results match regardless of which
path answered.

## API

### `POST /api/literature/index`
Provide `gene` (fetch + embed PubMed articles) and/or `articles` (index supplied
records directly). At least one is required (else `422`).

```jsonc
// request
{ "gene": "BRCA1", "therapeutic_context": "breast cancer", "max_results": 5 }
// response
{ "indexed": 5, "persisted": true, "embedding_backend": "api",
  "query": "BRCA1 AND breast cancer", "total_available": 1183 }
```
`persisted` is `true` only when the docs were durably written to MongoDB.

### `POST /api/literature/search`
```jsonc
// request
{ "query": "enhancers regulating BRCA1 in neural tissue", "k": 5, "gene": "BRCA1" }
// response
{ "query": "...", "backend": "atlas", "embedding_backend": "api", "count": 5,
  "hits": [ { "doc_id": "pmid:1234", "title": "...", "abstract": "...",
              "score": 0.83, "pmid": "1234", "gene": "BRCA1",
              "url": "https://pubmed.ncbi.nlm.nih.gov/1234/", "source": "pubmed" } ] }
```
`backend` is the index path that answered (`atlas` | `memory`). An empty index
returns `count: 0` and `hits: []` - never an error.

## region → evidence integration

`LiteratureRagProvider` implements `region_evidence.RegionRagProvider`: given a
`RegionQuery`, it searches the index with the region's label/gene and returns
`RegionEvidence(source="literature", kind="paper", …)` bound to the region's
coordinates. URLs come straight from the indexed document (or `None` - never
fabricated), and `confidence` names the backend that answered.

```python
from services.literature_index import LiteratureRagProvider
from services.region_evidence import attach_literature_evidence, RegionQuery

provider = LiteratureRagProvider(literature_index, k=3)
evidence = await attach_literature_evidence(
    [RegionQuery(start=40, end=120, sequence=seq, gene="BRCA1", label="promoter")],
    provider,
)
```

## Chat retrieval integration

The design-generation pipeline's retrieval stage
(`pipeline/orchestrator.py::_emit_retrieval`, called from
`run_generation_pipeline`) previously populated its `"pubmed"` retrieval
bucket only from `services.pubmed.search_literature()` - a plain keyword
search. It now also merges in relevance-filtered `LiteratureIndex.search()`
hits, deduplicated by pmid against whatever the keyword search already found,
into that same `articles` list. This is the list the frontend's
`lib/evidence.ts` already turns into `evidence_links` for chat, and
`services/agent/graph.py`'s `RESPONDER_PROMPT` already knows how to cite -
so semantically-retrieved, real, post-2025 papers now reach chat citations
with no frontend or agent-prompt changes.

Before merging, it calls `ensure_indexed(spec.target_gene, ...)` first (same
as `LiteratureRagProvider.fetch()` does for the region-evidence path), so any
gene the user designs around gets backfilled on first use, not just
pre-warmed ones.

Relevance filtering (`_filter_relevant_literature_hits` in orchestrator.py):
an absolute floor (top hit must score ≥ 0.55) gates whether anything is cited
at all - this catches the case a purely relative cutoff can't, where every
hit in a batch is uniformly weak (an off-topic query still returns *a* best
hit, just a mediocre one). Hits that clear the floor are then kept if they
score within 70% of the top hit. Both numbers are a first pass, calibrated
against this index's real observed local-hash-embedder scores (~0.62–0.67 for
an on-topic BRCA1 query, ~0.49 for an off-topic one) - re-check them if
`EMBEDDING_API_KEY` switches the index to a different embedder, since cosine
scores from different embedders aren't on the same scale.

`run_followup_pipeline` (the edit/follow-up path) has no retrieval step at
all and so isn't part of this - only the initial design-generation retrieval
feeds chat's evidence links.

## On-demand ingestion (any gene, not just pre-indexed ones)

Previously, literature only existed in the index for genes someone had
manually run `POST /api/literature/index` (or an ingestion script) against -
ask about any other gene and the honest-empty-result path fired forever, not
because nothing was findable, but because nothing had been indexed yet.

`LiteratureIndex.ensure_indexed(gene, therapeutic_context=None, design_type=None)`
closes that gap: it checks whether any documents already exist for `gene`
(Mongo when connected and ready, else the in-process cache) and, if none are
found, backfills via `index_from_pubmed` before returning. Never raises - a
failed backfill just means the subsequent `search()` call returns its own
honest empty result, same as any other retrieval failure in this codebase.

`LiteratureRagProvider.fetch()` calls `ensure_indexed` automatically before
every `search()`, so any gene a user asks about through the region-evidence
path gets indexed on first use - no manual step required. `POST
/api/literature/index` and `scripts/ingest_literature.py` still work for
pre-populating specific genes ahead of time; they're just no longer the
*only* way literature gets in.

One consequence worth knowing: Atlas Search indexes new writes near-real-time,
not instantly, so a document upserted moments ago (e.g. by `ensure_indexed`,
in the very same request) can briefly be invisible to `$vectorSearch`.
`search()` treats an **empty** Atlas result as inconclusive and falls through
to the Mongo-hydration cosine path (a plain query, not a search index, so it
sees the write immediately) rather than returning empty outright - only a
**non-empty** Atlas result is trusted directly, to keep the common case cheap.

### Startup pre-warm

`backend/main.py` fires a non-blocking background task at app startup (inside
`_lifespan`, via `asyncio.create_task`, so it never delays the app becoming
ready) that calls `ensure_indexed` for a short list of demo genes
(`_LITERATURE_PREWARM_GENES`, currently `["BRCA1", "TP53", "CFTR"]` - a
placeholder default; confirm/adjust with the team before a live demo). This
exists purely to avoid paying first-query PubMed+embedding latency live during
a demo - `ensure_indexed` already covers the general "any gene" case on its
own.

## Provisioning the Atlas vector index

Enabling `$vectorSearch` needs a vector index named `VECTOR_INDEX_NAME`
(default `literature_vector_index`) on the `literature` collection. The backend
attempts to create it automatically on connect (best-effort; a no-op on
non-Atlas / older servers). To create it by hand in Atlas → Search → Create
Index → JSON editor:

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 256, "similarity": "cosine" },
    { "type": "filter", "path": "gene" }
  ]
}
```

`numDimensions` must equal `EMBEDDING_DIM`.

## Configuration

| Env var | Default | Meaning |
| --- | --- | --- |
| `EMBEDDING_API_KEY` | _(empty)_ | Set → API embedder; unset → local embedder. Falls back to `OPENAI_API_KEY`. |
| `EMBEDDING_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible embeddings endpoint. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model id. |
| `EMBEDDING_DIM` | `256` | Vector dimension (must match the Atlas index). |
| `VECTOR_INDEX_NAME` | `literature_vector_index` | Atlas vector index name. |

## Tests

`backend/tests/test_vector_search.py` covers the local embedder (determinism,
dimension, normalisation), cosine similarity, the hybrid factory, in-memory
index + search (ranking, gene filter, idempotent re-index, empty index), the
RAG adapter, and the API endpoints - all with MongoDB disabled, exercising the
zero-dependency fallback path.

`backend/tests/test_literature_index.py` covers `ensure_indexed` (backfills
when nothing exists, skips when a gene is already indexed via Mongo or the
in-process cache, never raises on a PubMed failure) and the Atlas-empty-falls-
through-to-hydration behavior, using a `_FakeMongo` test double - no real
network or Atlas required. `backend/tests/test_main_api.py`'s
`test_literature_prewarm_does_not_block_startup` asserts the startup pre-warm
task is genuinely non-blocking (a deliberately slow stub must not delay app
startup past a tight wall-clock bound).

`backend/tests/test_orchestrator.py` covers the chat-retrieval merge: the
relevance filter's floor/relative-cutoff logic in isolation, real merge +
pmid-dedup behavior against a fake `LiteratureIndex` double (asserting the
actual call arguments, not just that a call happened), weak matches being
excluded outright, the `result.pubmed is None` fallback path, and that
behavior is unchanged when no `literature_index` is passed at all.
