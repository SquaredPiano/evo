# Region → Evidence interface

This document is the contract between the **coordinate → evidence binding**
(ClinVar + regulatory motifs) and the **RAG provider** (per-region research-paper
retrieval - implemented, see §5). The UI did not change when the RAG was added -
it renders whatever `RegionEvidence[]` the backend returns.

Hover a DNA region in the UI → the evidence overlapping that region is shown,
grouped by source (ClinVar / Regulatory / Paper).

---

## 1. The `RegionEvidence` schema

Backend: `backend/services/region_evidence.py` (`RegionEvidence` dataclass).
Frontend mirror: `frontend/types/sequence.ts` (`RegionEvidence` interface).

| Field        | Type                | Notes |
|--------------|---------------------|-------|
| `start`      | `int`               | 0-based, **half-open** `[start, end)`, in the candidate sequence's own frame (position 0 = first base of the sequence passed in). |
| `end`        | `int`               | Exclusive end. A point feature (e.g. a SNV) uses `end == start + 1`. |
| `source`     | `str`               | `"clinvar" \| "regulatory" \| "literature" \| ...`. Drives the UI badge. |
| `kind`       | `str`               | `"pathogenic_variant" \| "motif" \| "paper" \| ...`. |
| `title`      | `str`               | Short display title. |
| `detail`     | `str \| None`       | One-to-two sentence explanation. **Must be honest about provenance** (see §4). |
| `url`        | `str \| None`       | Real external link (PubMed / ClinVar / DOI) or `null`. **Never fabricate** - `null` when there is no stable link. |
| `identifier` | `str \| None`       | PMID / ClinVar UID / accession / motif name. |
| `score`      | `float \| None`     | Source-native strength/relevance if any. |
| `confidence` | `str \| None`       | Human label, e.g. `"ClinVar review: 3/4 stars"`, `"motif pattern match"`, `"RAG top-k"`. |

`RegionEvidence.to_dict()` returns exactly these keys - that dict IS the wire
format for both the HTTP endpoint and the WS event.

---

## 2. HTTP endpoint

`POST /api/region-evidence` - `backend/main.py`; request model
`RegionEvidenceRequest` in `backend/models/requests.py`.

Request body:

```json
{
  "sequence": "ATCG...",        // required; evidence coords are in this frame
  "gene": "BRCA1",              // optional; enables ClinVar. null → regulatory only
  "region_start": 0,            // optional, default 0
  "region_end": null,           // optional, default = len(sequence)
  "max_variants": 25,           // optional, 1..100
  "include_clinvar": true,      // optional; false skips the ClinVar network call
  "include_literature": true,   // optional; false skips the literature RAG lookup
  "session_id": null,           // optional; enables edit-history-gated literature (see §5)
  "candidate_id": 0             // optional, default 0; which candidate's edit history to read
}
```

Response body:

```json
{
  "gene": "BRCA1",
  "region_start": 0,
  "region_end": 1200,
  "items": [ /* RegionEvidence dicts, sorted by (start, source) */ ],
  "count": 7
}
```

`items` is `[]` when there is no evidence - an honest, non-error result.

Frontend client: `fetchRegionEvidence(...)` in `frontend/lib/api.ts`;
store action `loadRegionEvidence(sequence, gene?)` in `frontend/lib/store.ts`
(deduped by sequence). Consumed by `AnnotationTrack.tsx` +
`RegionEvidenceCard.tsx`.

---

## 3. WebSocket event

`region_evidence_ready` - emitted beside `regulatory_map_ready` from
`backend/pipeline/orchestrator.py::_emit_structure`. Models in
`backend/ws/events.py` (`RegionEvidenceReadyData` / `RegionEvidenceReadyEvent`).

```json
{
  "event": "region_evidence_ready",
  "data": {
    "candidate_id": 3,
    "items": [ /* RegionEvidence dicts */ ]
  }
}
```

> The WS event carries **regulatory-derived evidence only** (local, no network in
> the pipeline hot path). ClinVar and literature enrichment are fetched on demand
> via `POST /api/region-evidence`. This keeps the pipeline surgical and fast.

---

## 4. Honesty rules (apply to every source)

- **ClinVar** items are framed as *"known variant in this GENE overlapping this
  position - context for the region, not a pathogenicity claim about the
  generated sequence."* Never render a ClinVar item as "this base is pathogenic".
- **Regulatory** items are motif-derived (pattern matches), not literature; their
  `url` is always `null` and `detail` says so.
- **Never fabricate a URL.** `url = null` when no stable link exists. The UI only
  renders a link when `url` is a real `http(s)` string.

---

## 5. RAG provider - IMPLEMENTED

Post-2025 research papers are wired in, without any UI changes. The concrete
provider is `LiteratureRagProvider` in `backend/services/literature_index.py`,
which implements the `RegionRagProvider` Protocol below and is handed to
`attach_literature_evidence(...)` (both defined in
`backend/services/region_evidence.py`) from the `POST /api/region-evidence`
endpoint in `backend/main.py`.

Pipeline: `services/pubmed.py::search_literature` fetches post-2025 PubMed
articles for a gene → `services/embeddings.py` embeds them (hybrid: a real API
embedder when `EMBEDDING_API_KEY` is set, else a deterministic local
feature-hashing embedder) → `services/literature_index.py::LiteratureIndex`
stores them (MongoDB Atlas `$vectorSearch` when reachable, in-memory cosine
fallback otherwise) → `LiteratureRagProvider.fetch()` queries the index per
region, applies the shared relevance filter (below), and condenses each
surviving hit's abstract via `services/evidence_synthesis.py::synthesize_detail`
(Gemini, with a truncated-abstract fallback) into the `detail` field.

To populate the index for a gene, run from `backend/`:
```bash
python -m scripts.ingest_literature BRCA1
```

The Protocol below remains a generic seam - a different index or retrieval
strategy can implement it the same way and merge in without any UI change.

### Shared relevance filter

`services/literature_index.py::filter_relevant_hits` (with constants
`LITERATURE_ABSOLUTE_FLOOR = 0.55` and `LITERATURE_RELATIVE_CUTOFF = 0.7`) is
the **one** relevance bar both literature surfaces apply - this hover-card
path (`LiteratureRagProvider.fetch`) and the chat-retrieval path
(`pipeline/orchestrator.py::_emit_retrieval`, see `docs/vector_search.md`'s
"Chat retrieval integration"). It used to be a private copy inside
`orchestrator.py`; it moved here so the two surfaces can't silently drift to
different bars. A weak top hit means nothing in the batch is genuinely
relevant - neither surface will cite/show the "least bad" option just because
it was the closest match.

### Per-region gating (edit history, not a per-region novelty score)

Literature is bound to the regions Evo2 actually made novel, not shown
identically across the whole sequence. There is no per-region novelty score to
gate on - `CandidateScores.novelty` (`backend/models/domain.py`) is a single
whole-candidate float, not per-position - so this reads the session's own
edit/regenerate history instead, via
`services/experiment_tracker.py::novel_regions_from_versions`:

- A base edit (`POST /api/edit/base`) contributes its one-base span.
- An agent `insert_bases` tool call contributes the inserted span.
- An agent `regenerate_region` tool call contributes the regenerated span
  (using the length-adjusted `new_region_end`, not the original `end`).
- The agent's hill-climbing optimizer (`optimize_candidate`, no `scope` key -
  positions are nested per-round in `operation_details["mutations"]`)
  contributes one one-base span per round.
- `delete`, whole-candidate `transform` (codon optimization, "replace all X"),
  and `restore_sequence` (which records only a *count* of changed positions,
  not their coordinates) contribute **no** span - none has an addressable
  range in the current sequence to bind evidence to.
- Overlapping/adjacent spans are merged, so re-editing the same region twice
  doesn't produce duplicate literature lookups.

`region_evidence()` in `backend/main.py` builds **one `RegionQuery` per novel
span** (intersected with the requested `[region_start, region_end)` window),
not one blanket query over the whole sequence. A window with no novel span
inside it gets zero literature evidence - the correct, honest result, not a
fallback to generic gene-wide papers.

This requires knowing *which* session/candidate to read edit history from:
`RegionEvidenceRequest` gained `session_id` (optional) and `candidate_id`
(default `0`). **Without `session_id`, there is no known novel region, so
literature comes back empty** - today, `frontend/lib/store.ts`'s
`loadRegionEvidence(sequence, gene)` does not pass `session_id`/
`activeCandidateId` (both already exist in the store) through to
`fetchRegionEvidence`. Wiring that one call site is a small, separate frontend
change, deliberately left undone here - everything on the backend is
implemented and tested (`backend/tests/test_region_evidence.py`'s
`TestPerRegionLiteratureGating`) by calling the endpoint directly with
`session_id` set, exactly as a frontend that passes it through would.

### Protocol

```python
from services.region_evidence import RegionEvidence, RegionQuery, attach_literature_evidence

class MyRag:
    def fetch(self, query: RegionQuery) -> list[RegionEvidence]:
        # query.start, query.end : coordinate span (candidate frame, half-open)
        # query.sequence         : full candidate sequence
        # query.gene             : gene symbol or None
        # query.label            : region label/type if known
        hits = self.index.search(query.gene, query.sequence[query.start:query.end])
        return [
            RegionEvidence(
                start=query.start,          # YOU own coordinate binding: bind each
                end=query.end,              # paper to the [start, end) it supports
                source="literature",        # (forced to "literature" anyway)
                kind="paper",
                title=hit.title,
                detail=hit.snippet,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{hit.pmid}/",  # or None
                identifier=hit.pmid,
                score=hit.relevance,
                confidence="RAG top-k",
            )
            for hit in hits
        ]
```

`fetch` may be **sync or async** - `attach_literature_evidence` awaits it if it
returns an awaitable, isolates per-region failures, and forces
`source="literature"` / `kind="paper"` so the UI badge is always truthful.

### Contract summary

1. **Input**: `RegionQuery(start, end, sequence, gene, label)`.
2. **Output**: `list[RegionEvidence]`, each carrying its own `[start, end)` span
   (candidate frame) - the region the paper actually supports.
3. **URL**: real PubMed/DOI link or `None`. Never fabricate.
4. **Merge**: append your list to the output of `assemble_region_evidence(...)`.
   Same schema, same endpoint/WS event, no UI change.

### Where it's called

Wired into the HTTP endpoint only: `region_evidence()` in `backend/main.py`
builds one `RegionQuery` per novel span (see above) after
`assemble_region_evidence(...)` and merges in
`await attach_literature_evidence(literature_queries, literature_rag_provider)`
- a list, not a single query, so `attach_literature_evidence`'s existing
per-region iteration does the fetching. Gated by
`RegionEvidenceRequest.include_literature` (default `True`) *and* by there
being at least one novel span to query.

Deliberately **not** added to the WS emission (`orchestrator._emit_structure`,
which emits `region_evidence_ready`) - that path stays regulatory-only by
design (local, no network, keeps the pipeline hot path fast; see §3 above).
Literature stays on-demand via the HTTP endpoint. No frontend edits were
required.
