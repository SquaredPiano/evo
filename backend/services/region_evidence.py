"""Region → evidence binding.

Binds *coordinates* in a candidate sequence to the research/evidence that
supports (or contextualises) them. This is the layer that lets the UI turn
"hover a DNA region" into "here is the evidence for that region".

It is deliberately **source-agnostic**: every piece of evidence, whether it
comes from ClinVar, the local regulatory-motif scanner, or a future RAG index
of research papers, is normalised into a single :class:`RegionEvidence` record
carrying its own 0-based, half-open coordinates in the candidate's frame.

Sources wired in TODAY (all three already exist in the codebase):

* **ClinVar** — via :mod:`services.variant_annotation`. Known variants for the
  *gene* are parsed from HGVS titles into positions and overlaid on these
  coordinates. Honesty note: this is *context about the gene locus*, NOT a
  claim that the generated base is pathogenic. That framing is encoded in the
  ``detail`` field of every ClinVar record.
* **Regulatory** — via :func:`services.regulatory_viz.build_regulatory_map`.
  Each detected motif becomes a ``source="regulatory"`` record. These are
  motif-derived (pattern matches), not literature-linked, so ``url`` is None.
* **Literature** — via :class:`services.literature_index.LiteratureRagProvider`,
  a concrete :class:`RegionRagProvider` (see below) that vector-searches
  post-2025 PubMed papers indexed in :class:`services.literature_index.LiteratureIndex`
  and Gemini-condenses each hit's abstract into an honest ``detail`` (see
  :func:`services.evidence_synthesis.synthesize_detail`). Wired into
  ``POST /api/region-evidence`` in ``backend/main.py`` via
  :func:`attach_literature_evidence`. Populate the index for a gene with
  ``python -m scripts.ingest_literature <GENE>`` (run from ``backend/``).

:func:`attach_literature_evidence` and :class:`RegionRagProvider` below remain
a generic seam — any other ``RegionRagProvider`` implementation (a different
index, a different retrieval strategy) drops in the same way, with no UI
change, since every source normalises into the same :class:`RegionEvidence`
record with ``source="literature"``.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Protocol, Sequence, runtime_checkable

from services.regulatory_viz import build_regulatory_map
from services.variant_annotation import annotate_variants

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalised evidence record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegionEvidence:
    """A single piece of evidence bound to a coordinate span.

    Coordinates are **0-based, half-open** ``[start, end)`` in the candidate
    sequence's own frame (i.e. position 0 == first base of the sequence the
    caller passed in). A point feature (e.g. a single-nucleotide variant) uses
    ``end == start + 1``.
    """

    start: int
    end: int
    source: str            # "clinvar" | "regulatory" | "literature" | ...
    kind: str              # "pathogenic_variant" | "motif" | "paper" | ...
    title: str
    detail: str | None = None
    url: str | None = None          # real external link, or None. Never fabricate.
    identifier: str | None = None   # PMID / ClinVar UID / accession / motif name
    score: float | None = None      # source-native confidence/strength if any
    confidence: str | None = None   # human label: "review: 3/4 stars", "motif match", ...

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable dict. Field names match the WS/HTTP contract."""
        return asdict(self)


# ---------------------------------------------------------------------------
# ClinVar → RegionEvidence
# ---------------------------------------------------------------------------

def _clinvar_variation_url(uid: str) -> str | None:
    uid = (uid or "").strip()
    if not uid or uid.upper().startswith("DEMO"):
        return None
    return f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{uid}/"


def _stars_label(stars: int) -> str:
    return f"ClinVar review: {stars}/4 stars"


async def _clinvar_evidence(
    gene: str,
    sequence: str,
    region_start: int,
    region_end: int,
    max_variants: int,
    significance: str,
) -> list[RegionEvidence]:
    """Known gene variants overlapping [region_start, region_end)."""
    result = await annotate_variants(
        gene=gene,
        sequence=sequence,
        max_variants=max_variants,
        significance=significance,
    )

    out: list[RegionEvidence] = []
    for ann in result.annotations:
        # annotate_variants returns positions in the FULL-sequence frame.
        if not (region_start <= ann.position < region_end):
            continue

        change = (
            f"{ann.ref_base}>{ann.alt_base}"
            if ann.ref_base and ann.alt_base
            else ann.variation_type or "variant"
        )
        # HONESTY: this is a known variant at this locus in the reference gene,
        # NOT a statement that the generated base here is pathogenic.
        detail = (
            f"Known ClinVar variant in {gene} ({change}) overlapping this "
            f"position — context for the region, not a pathogenicity claim "
            f"about the generated sequence."
        )
        if ann.condition:
            detail += f" Reported condition: {ann.condition}."

        out.append(
            RegionEvidence(
                start=ann.position,
                end=ann.position + 1,
                source="clinvar",
                kind="pathogenic_variant",
                title=ann.variant_title or f"ClinVar {ann.variant_id}",
                detail=detail,
                url=_clinvar_variation_url(ann.variant_id),
                identifier=ann.variant_id or None,
                score=None,
                confidence=_stars_label(ann.review_stars),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Regulatory motifs → RegionEvidence
# ---------------------------------------------------------------------------

# Human-readable descriptions for the motifs regulatory_viz scans for.
_MOTIF_DESCRIPTIONS: dict[str, str] = {
    "TATA_box": "Core promoter element; positions the transcription start site.",
    "CAAT_box": "Upstream promoter element; modulates transcription efficiency.",
    "GC_box": "Sp1-family binding site; common in housekeeping promoters.",
    "polyA_signal": "Polyadenylation signal; directs 3' cleavage and poly-A tailing.",
    "CpG": "CpG dinucleotide; methylation / CpG-island context.",
}


def _regulatory_evidence(
    regulatory_map: dict[str, object],
    region_start: int,
    region_end: int,
) -> list[RegionEvidence]:
    """Convert a regulatory map's motif features to RegionEvidence.

    Pure/local — no network. Safe to call inside the pipeline. Features are
    kept when they OVERLAP [region_start, region_end).
    """
    features = regulatory_map.get("features")
    if not isinstance(features, list):
        return []

    out: list[RegionEvidence] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        try:
            start = int(feat["start"])
            end = int(feat["end"])
        except (KeyError, TypeError, ValueError):
            continue
        # overlap test for half-open ranges
        if end <= region_start or start >= region_end:
            continue
        name = str(feat.get("name", "motif"))
        score = feat.get("score")
        out.append(
            RegionEvidence(
                start=start,
                end=end,
                source="regulatory",
                kind="motif",
                title=name.replace("_", " "),
                detail=_MOTIF_DESCRIPTIONS.get(
                    name, "Sequence motif detected by pattern scan."
                )
                + " Motif-derived (pattern match), not a literature citation.",
                url=None,
                identifier=name,
                score=float(score) if isinstance(score, (int, float)) else None,
                confidence="motif pattern match",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Public assembly API
# ---------------------------------------------------------------------------

async def assemble_region_evidence(
    sequence: str,
    gene: str | None = None,
    region_start: int = 0,
    region_end: int | None = None,
    max_variants: int = 25,
    significance: str = "pathogenic",
    include_clinvar: bool = True,
    regulatory_map: dict[str, object] | None = None,
) -> list[RegionEvidence]:
    """Assemble coordinate-bound evidence for a sequence from existing sources.

    Args:
        sequence: The candidate DNA sequence (evidence coordinates are in ITS frame).
        gene: Gene symbol for ClinVar context (e.g. "BRCA1"). If falsy, ClinVar
            is skipped and only regulatory evidence is returned (honest: no gene,
            no gene-scoped literature/variants).
        region_start / region_end: Restrict to [start, end); defaults to the
            whole sequence. Items are kept when they overlap the window.
        max_variants: Max ClinVar variants to fetch.
        significance: ClinVar significance filter (default "pathogenic").
        include_clinvar: Set False to skip the network fetch entirely (tests,
            offline, or when only local regulatory evidence is wanted).
        regulatory_map: Pre-computed map from ``build_regulatory_map`` to reuse
            (the pipeline already builds one). Built on demand if None.

    Returns:
        A flat list of RegionEvidence, sorted by (start, source). Empty list is
        a valid, honest result — never raises for "no evidence".
    """
    if region_end is None:
        region_end = len(sequence)
    region_start = max(0, region_start)
    region_end = min(len(sequence), region_end)
    if region_start >= region_end:
        return []

    evidence: list[RegionEvidence] = []

    # Regulatory (local, always available).
    if regulatory_map is None:
        regulatory_map = build_regulatory_map(sequence)
    try:
        evidence.extend(_regulatory_evidence(regulatory_map, region_start, region_end))
    except Exception:  # pragma: no cover - defensive; regulatory is local
        logger.warning("regulatory evidence assembly failed", exc_info=True)

    # ClinVar (network; gene-scoped). Failures degrade to no ClinVar evidence.
    if include_clinvar and gene:
        try:
            evidence.extend(
                await _clinvar_evidence(
                    gene=gene,
                    sequence=sequence,
                    region_start=region_start,
                    region_end=region_end,
                    max_variants=max_variants,
                    significance=significance,
                )
            )
        except Exception:
            logger.warning("ClinVar evidence assembly failed for %s", gene, exc_info=True)

    evidence.sort(key=lambda e: (e.start, e.source))
    return evidence


# ---------------------------------------------------------------------------
# LITERATURE / RAG EXTENSION SEAM
# ---------------------------------------------------------------------------
#
# A RAG over post-2025 research papers, indexed per region, plugs in HERE
# without touching the UI or the assembly above. Implemented today by
# :class:`services.literature_index.LiteratureRagProvider` (wired into
# ``POST /api/region-evidence`` in ``backend/main.py``) — this stays a generic
# Protocol so a different index/strategy can be swapped in the same way.
#
# Contract for the provider:
#   - Input : the candidate sequence + gene context + a coordinate span.
#   - Output: zero or more RegionEvidence with source="literature",
#             kind="paper", url=<PubMed/DOI URL or None>, identifier=<PMID/DOI>.
#   - The provider owns coordinate binding: each returned RegionEvidence must
#     carry the [start, end) span (in the candidate's frame) the paper supports.
#   - Never fabricate a URL. If the paper has no stable link, return url=None.
#
# The provider may be sync or async; ``attach_literature_evidence`` awaits it if
# it returns an awaitable.

@dataclass(frozen=True)
class RegionQuery:
    """One region handed to the RAG provider for evidence lookup."""
    start: int
    end: int
    sequence: str
    gene: str | None = None
    label: str | None = None   # e.g. the SequenceRegion.type / label, if known


@runtime_checkable
class RegionRagProvider(Protocol):
    """Implement this to feed per-region research papers into the same list.

    Concrete implementation: :class:`services.literature_index.LiteratureRagProvider`.

    Example (a from-scratch implementation, for reference):

        class MyRag:
            def fetch(self, query: RegionQuery) -> list[RegionEvidence]:
                hits = self.index.search(query.gene, query.sequence[query.start:query.end])
                return [
                    RegionEvidence(
                        start=query.start, end=query.end,
                        source="literature", kind="paper",
                        title=hit.title, detail=hit.snippet,
                        url=f"https://pubmed.ncbi.nlm.nih.gov/{hit.pmid}/",
                        identifier=hit.pmid, score=hit.relevance,
                        confidence="RAG top-k",
                    )
                    for hit in hits
                ]
    """

    def fetch(self, query: RegionQuery) -> "list[RegionEvidence] | object":
        ...


async def attach_literature_evidence(
    regions: Sequence[RegionQuery],
    provider: RegionRagProvider,
) -> list[RegionEvidence]:
    """Seam: collect literature RegionEvidence for each region via a RAG provider.

    Normalises provider output, forces source/kind so the UI badges it as a
    paper, and tolerates sync or async providers. It does NOT itself query any
    index — pass a concrete :class:`RegionRagProvider`, e.g.
    ``LiteratureRagProvider(literature_index)`` from
    :mod:`services.literature_index` (see ``backend/main.py``).

    Returns a flat, coordinate-bound list ready to be merged with the output of
    :func:`assemble_region_evidence`.
    """
    import inspect

    collected: list[RegionEvidence] = []
    for query in regions:
        try:
            result = provider.fetch(query)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            logger.warning("RAG provider failed for region %s-%s", query.start, query.end, exc_info=True)
            continue
        for item in result or []:
            if not isinstance(item, RegionEvidence):
                continue
            # Force provenance so the UI badge is always truthful.
            collected.append(
                RegionEvidence(
                    start=item.start,
                    end=item.end,
                    source="literature",
                    kind=item.kind or "paper",
                    title=item.title,
                    detail=item.detail,
                    url=item.url,
                    identifier=item.identifier,
                    score=item.score,
                    confidence=item.confidence,
                )
            )
    return collected
