# Semantic vector search over research literature

Embeds research articles (PubMed) and searches them **by meaning** rather than
keyword, so a design can surface the papers most relevant to a gene, a sequence
region, or a free-text question. It is the concrete implementation of the RAG
seam documented in `docs/region_evidence_interface.md` /
`services/region_evidence.py`.

Like the rest of the backend, it is **optional and degrades gracefully** — it
works with zero configuration and no external services, just at lower quality.

## Components

| File | Role |
| --- | --- |
| `services/embeddings.py` | Text → vector. `LocalHashEmbedder` (deterministic, offline) and `ApiEmbedder` (OpenAI-compatible). `create_embedder(settings)` picks per the hybrid policy. `cosine_similarity`. |
| `services/literature_index.py` | `LiteratureIndex` (index + search) and `LiteratureRagProvider` (region_evidence adapter). |
| `services/mongo_store.py` | Durable storage + Atlas `$vectorSearch` (`save_literature_docs`, `vector_search_literature`, `list_literature_docs`). |
| `main.py` | `POST /api/literature/index`, `POST /api/literature/search`. |

## Two degradation axes

**Embeddings (hybrid).** If `EMBEDDING_API_KEY` (or legacy `OPENAI_API_KEY`) is
set, a real embedding model is used (`EMBEDDING_MODEL`, default
`text-embedding-3-small`). Otherwise a deterministic local feature-hashing
embedder is used — no network, same input always maps to the same vector. Both
emit L2-normalised vectors of `EMBEDDING_DIM` (default 256).

> Do **not** mix backends within one populated index — the vector spaces are
> unrelated. Pick one embedder per deployment; re-index if you switch.

**Index / query backend.** If MongoDB is connected *and* an Atlas Vector Search
index exists, queries use `$vectorSearch`. Otherwise search falls back to an
in-process cosine scan over what has been indexed (reloading from Mongo when the
durable store is up but the vector index isn't). A missing index isn't an
error — `$vectorSearch` fails, the store returns `None`, and the caller falls
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
returns `count: 0` and `hits: []` — never an error.

## region → evidence integration

`LiteratureRagProvider` implements `region_evidence.RegionRagProvider`: given a
`RegionQuery`, it searches the index with the region's label/gene and returns
`RegionEvidence(source="literature", kind="paper", …)` bound to the region's
coordinates. URLs come straight from the indexed document (or `None` — never
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
RAG adapter, and the API endpoints — all with MongoDB disabled, exercising the
zero-dependency fallback path.
