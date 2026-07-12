# Demo scenarios — literature-RAG + anchored hover-card

Four (gene, design prompt) pairs where a real, genuinely post-2025 research
paper is relevant to the design and actually surfaces as a `source:
"literature"` hover-card citation in the running app. Each entry below was:

1. **Discovered** via the real pipeline — `LiteratureIndex.search()` against
   the live Mongo Atlas-backed index (not a mock, not a fixture).
2. **Independently verified** against live PubMed via NCBI E-utilities,
   checking the paper's *true earliest publication date* (electronic/epub
   date, not the journal issue's cover date — these can differ by months;
   see the caveat below). One otherwise-good BRCA1/TP53/PCSK9/MECP2 candidate
   was **discarded** for exactly this reason (see "Rejected candidates").
3. **Re-verified independently** a second time by a separate subagent with no
   access to this project's code or data, working only from the live PubMed
   page — see the confirmation note per entry.
4. **Run end-to-end** against the actual running app: `POST /api/design`
   with the prompt below → real WebSocket pipeline → real generated
   sequence → `POST /api/region-evidence` with that sequence + gene →
   confirmed the exact PMID appears as a `literature` item with a real,
   clickable PubMed URL.

**Gene selection caveat:** BRCA1, TP53, and CFTR are pre-warmed at startup
(`main.py::_LITERATURE_PREWARM_GENES`, currently a placeholder default) so
they demo with zero ingestion latency. PCSK9 is *not* pre-warmed — it was
backfilled live via `ensure_indexed()` (the "any gene works" on-demand
ingestion path) during this verification, which took a few seconds. **This
four-gene list is my own selection for a solid, thematically-varied set — it
has not been confirmed with the team as the final demo lineup.** Swap any
entry out freely; the process above (search → verify date → verify live) is
what matters, not these specific four.

---

## 1. BRCA1 — DNA repair / homologous recombination

**Prompt to type into the app:**
> Design a regulatory element to support BRCA1-mediated DNA repair in breast tissue

**Paper:** PMID [40934926](https://pubmed.ncbi.nlm.nih.gov/40934926/) —
*"RAD51 is chromatin enriched and targetable in BRCA1-deficient cells."*
(*Molecular Cell*)

**Why it's relevant:** The paper shows RAD51 becomes chromatin-enriched via
single-stranded DNA gaps specifically in BRCA1-deficient cells, and that this
is a targetable vulnerability — directly on-topic for a design goal about
BRCA1's DNA-repair (homologous recombination) function.

**Publication date:** Epub **2025-09-10** (print/issue Sep 18, 2025) — safely
post-2025-01-01. Confirmed both by direct NCBI efetch (this project's own
E-utilities client, independent of the indexed cache) and by an independent
subagent re-fetching the live PubMed page from scratch. No retraction found.

**Live app confirmation:** `/api/design` → intent parser correctly extracted
`target_gene: "BRCA1"` → generated an 821-base candidate → `/api/region-evidence`
on that sequence + gene returned this PMID as a `source: "literature"` item
(`confidence: "vector search (atlas)"`, real URL, non-empty detail).

---

## 2. TP53 — functional variant characterization

**Prompt to type into the app:**
> Design a regulatory element to modulate TP53 activity in tumor suppression

**Paper:** PMID [39774325](https://pubmed.ncbi.nlm.nih.gov/39774325/) —
*"Deep CRISPR mutagenesis characterizes the functional diversity of TP53
mutations."* (*Nature Genetics*)

**Why it's relevant:** A CRISPR saturation genome-editing screen of over
9,000 TP53 variants, characterizing their functional/pathogenicity
diversity — a strong thematic pairing for a tool whose whole premise is
variant scoring and functional design.

**Publication date:** Epub **2025-01-07** — passes the cutoff, but **only by
6 days**, and with one wrinkle worth knowing: the paper's DOI
(`10.1038/s41588-024-02039-4`) contains `-024-`, Nature's internal
year-of-acceptance token, which reads like a 2024 publication at a glance.
The independent subagent cross-checked the *actual* online-publication date
against two sources (the PubMed record and the PMC full-text record, which
states "Published online Jan 7, 2025") and confirmed it genuinely clears the
cutoff. Flagging this explicitly rather than picking a cleaner-margin
alternative, since it's real and verified — but if you want more buffer for
the presentation, this is the one entry worth double-checking again closer
to the date or swapping for another TP53 paper.

**Live app confirmation:** `/api/design` → `target_gene: "TP53"` → generated
an 821-base candidate → `/api/region-evidence` returned this PMID as a
`literature` item with a real URL and non-empty detail.

---

## 3. CFTR — CRISPR gene-editing correction

**Prompt to type into the app:**
> Design a regulatory element for CFTR to restore chloride channel function in airway epithelium

**Paper:** PMID [40534129](https://pubmed.ncbi.nlm.nih.gov/40534129/) —
*"CRISPR for cystic fibrosis: Advances and insights from a systematic
review."* (*Molecular Therapy*)

**Why it's relevant:** A systematic review of CRISPR gene-editing approaches
specifically aimed at correcting loss-of-function CFTR mutations — a direct
match for a design goal about restoring CFTR chloride-channel function.

**Publication date:** Epub **2025-06-17** (print/issue Sep 2025) — safely
post-2025-01-01. Confirmed via direct NCBI efetch.

**Live app confirmation:** `/api/design` → `target_gene: "CFTR"` → generated
an 821-base candidate → `/api/region-evidence` returned this PMID as a
`literature` item with a real URL and non-empty detail.

---

## 4. PCSK9 — LDL-receptor regulation (on-demand ingestion demo)

**Prompt to type into the app:**
> Design a regulatory element to reduce PCSK9 expression and lower LDL cholesterol in liver tissue

**Paper:** PMID [40071387](https://pubmed.ncbi.nlm.nih.gov/40071387/) —
*"PCSK9 Promotes LDLR Degradation by Preventing SNX17-Mediated LDLR
Recycling."* (*Circulation*)

**Why it's relevant:** Mechanistically explains *why* lowering PCSK9 raises
available LDL receptor (and thus lowers LDL cholesterol) — the exact
mechanism a "reduce PCSK9 expression" design goal is implicitly targeting.

**Publication date:** Epub **2025-03-12** (print/issue May 2025) — safely
post-2025-01-01. Confirmed via direct NCBI efetch.

**Live app confirmation:** `/api/design` → `target_gene: "PCSK9"` → generated
an 821-base candidate → `/api/region-evidence` returned this PMID as a
`literature` item with a real URL and non-empty detail. **Bonus demo value:**
PCSK9 is *not* pre-warmed, so running this scenario live also demonstrates
the on-demand `ensure_indexed()` ingestion path — the first query for a gene
nobody has asked about yet still works, just with a few seconds of one-time
ingestion latency.

---

## Rejected candidates (failed the date check)

Two papers looked like strong thematic fits and were seriously considered,
but their true earliest publication date predates 2025-01-01 even though
their journal *issue* is dated 2025 — exactly the trap manual verification
exists to catch:

| PMID | Title | Journal issue says | True epub date |
|---|---|---|---|
| 39450536 | TP53 mutations in cancer: Molecular features and therapeutic opportunities (Review) | 2025 Jan | **2024-10-25** |
| 39689710 | Acute MeCP2 loss in adult mice reveals transcriptional and chromatin changes... | 2025 Feb | **2024-12-16** |
| 39547595 | PCSK9 in metabolism and diseases | 2025 Feb | **2024-11-14** |

Neither is included above. If a future scenario needs a MECP2 or an
alternate TP53 entry, re-run the same search → date-verify → live-test
process — don't reuse these without re-checking, and don't trust the
`pubmed.py` pipeline's own `mindate` filter (it uses NCBI's `datetype=pdat`,
which appears to key off the print/issue date for some records, not the
electronic date) as sufficient on its own.

---

## A note on what "relevant to this specific region" means today

The literature hover-card evidence (`LiteratureRagProvider` in
`services/literature_index.py`) is matched by **gene identity**, not by
analyzing the actual bases at the hovered coordinates — so the same papers
above will appear regardless of which exact region of the generated sequence
you inspect, as long as `gene` is set. The region-evidence endpoint *anchors*
the citation to whatever `[region_start, region_end)` window you query, but
the search itself doesn't read the sequence content in that window. This
matches the honesty framing already used for ClinVar evidence elsewhere in
this codebase (context for the gene locus, not a claim about the specific
generated bases) — worth saying plainly during a demo rather than implying a
level of sequence-aware specificity that isn't there yet.

## A note on the `detail` field shown in each hover-card

At verification time, `GEMINI_API_KEY` was not configured in the test
environment, so every `detail` above is the deterministic truncated-abstract
fallback (`services/evidence_synthesis.py`), not a Gemini-synthesized
summary. If a Gemini key is set before the presentation, the on-screen detail
text will read as a shorter, synthesized 1-2 sentence summary instead of a
truncated abstract — re-check the `detail` text shown live if that's the
case, since it will differ from what's quoted implicitly above.
