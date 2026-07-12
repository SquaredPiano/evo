# Region → Evidence interface

This document is the contract between the **coordinate → evidence binding**
(built now, using ClinVar + regulatory motifs) and the **RAG provider** (Hayden's
per-region research-paper retrieval, wired later). The UI does not change when the
RAG is added — it renders whatever `RegionEvidence[]` the backend returns.

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
| `url`        | `str \| None`       | Real external link (PubMed / ClinVar / DOI) or `null`. **Never fabricate** — `null` when there is no stable link. |
| `identifier` | `str \| None`       | PMID / ClinVar UID / accession / motif name. |
| `score`      | `float \| None`     | Source-native strength/relevance if any. |
| `confidence` | `str \| None`       | Human label, e.g. `"ClinVar review: 3/4 stars"`, `"motif pattern match"`, `"RAG top-k"`. |

`RegionEvidence.to_dict()` returns exactly these keys — that dict IS the wire
format for both the HTTP endpoint and the WS event.

---

## 2. HTTP endpoint

`POST /api/region-evidence` — `backend/main.py`; request model
`RegionEvidenceRequest` in `backend/models/requests.py`.

Request body:

```json
{
  "sequence": "ATCG...",        // required; evidence coords are in this frame
  "gene": "BRCA1",              // optional; enables ClinVar. null → regulatory only
  "region_start": 0,            // optional, default 0
  "region_end": null,           // optional, default = len(sequence)
  "max_variants": 25,           // optional, 1..100
  "include_clinvar": true       // optional; false skips the ClinVar network call
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

`items` is `[]` when there is no evidence — an honest, non-error result.

Frontend client: `fetchRegionEvidence(...)` in `frontend/lib/api.ts`;
store action `loadRegionEvidence(sequence, gene?)` in `frontend/lib/store.ts`
(deduped by sequence). Consumed by `AnnotationTrack.tsx` +
`RegionEvidenceCard.tsx`.

---

## 3. WebSocket event

`region_evidence_ready` — emitted beside `regulatory_map_ready` from
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
  position — context for the region, not a pathogenicity claim about the
  generated sequence."* Never render a ClinVar item as "this base is pathogenic".
- **Regulatory** items are motif-derived (pattern matches), not literature; their
  `url` is always `null` and `detail` says so.
- **Never fabricate a URL.** `url = null` when no stable link exists. The UI only
  renders a link when `url` is a real `http(s)` string.

---

## 5. RAG provider — EXACTLY what to return (for Hayden)

Wire post-2025 research papers in **without touching the UI**. Implement the
`RegionRagProvider` Protocol and hand it to `attach_literature_evidence(...)`
(both in `backend/services/region_evidence.py`).

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

`fetch` may be **sync or async** — `attach_literature_evidence` awaits it if it
returns an awaitable, isolates per-region failures, and forces
`source="literature"` / `kind="paper"` so the UI badge is always truthful.

### Contract summary

1. **Input**: `RegionQuery(start, end, sequence, gene, label)`.
2. **Output**: `list[RegionEvidence]`, each carrying its own `[start, end)` span
   (candidate frame) — the region the paper actually supports.
3. **URL**: real PubMed/DOI link or `None`. Never fabricate.
4. **Merge**: append your list to the output of `assemble_region_evidence(...)`.
   Same schema, same endpoint/WS event, no UI change.

### Where to call it

Two options, both non-invasive:

- Enrich the endpoint: in `region_evidence` (main.py), after
  `assemble_region_evidence(...)`, build `RegionQuery` objects from the analyzed
  regions and `evidence += await attach_literature_evidence(regions, provider)`.
- Or enrich the WS emission in `orchestrator._emit_structure` the same way.

No frontend edits are required for either.
